"""
forecaster.py — 50-week weekly spend forecasting.
Uses Holt-Winters Exponential Smoothing (additive, seasonal period = 4 weeks).
Falls back to linear regression when data is sparse.
Applies India-specific seasonality multipliers.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Tuple
from statsmodels.tsa.holtwinters import ExponentialSmoothing


# ── India Seasonality ─────────────────────────────────────────────────────────

def seasonal_multiplier(dt: datetime) -> float:
    """Adjusts predicted spend for Indian seasonal patterns."""
    m = dt.month
    w = (dt.day - 1) // 7 + 1  # 1-indexed week of month

    month_mult = {
        10: 1.20,  # Diwali / Navratri
        11: 1.15,  # Post-Diwali, Christmas lead-up
        12: 1.15,  # Year-end / Christmas / New Year
        1:  1.10,  # New Year
        8:  1.08,  # Independence Day / Raksha Bandhan
        9:  1.08,  # Ganesh Chaturthi / Onam
        4:  1.05,  # Ugadi / Gudi Padwa / financial year-end
    }.get(m, 1.0)

    # First week of month = salary credited = higher spend
    week_mult = 1.08 if w == 1 else (0.95 if w >= 4 else 1.0)

    return month_mult * week_mult


# ── Confidence Bands ──────────────────────────────────────────────────────────

def confidence_band(base: float, std: float, week_ahead: int, z: float = 1.28) -> Tuple[float, float]:
    """80% confidence interval, widening with forecast horizon."""
    uncertainty = 1.0 + (week_ahead - 1) * 0.012
    margin = std * z * uncertainty
    return max(0.0, base - margin), base + margin


# ── Core Forecast ─────────────────────────────────────────────────────────────

def forecast_50_weeks(df_weekly: pd.DataFrame, weeks_ahead: int = 50) -> pd.DataFrame:
    """
    Input:  df_weekly with columns ['week', 'total']  (historical weekly spend)
    Output: DataFrame with historical + 50-week forecast rows.

    Columns in output:
        week_label, week_start, predicted, lower, upper, is_forecast,
        week_number (negative = historical, positive = future)
    """

    values = df_weekly["total"].values.astype(float)
    n_hist = len(values)

    # ── Choose model ──────────────────────────────────────────────────────────
    if n_hist >= 12:
        # Holt-Winters with additive trend + additive seasonality (period = 4 weeks)
        try:
            model = ExponentialSmoothing(
                values,
                trend="add",
                seasonal="add",
                seasonal_periods=4,
                initialization_method="estimated"
            ).fit(optimized=True, use_brute=True)
            fitted   = model.fittedvalues
            forecast = model.forecast(weeks_ahead)
        except Exception:
            forecast = _linear_forecast(values, weeks_ahead)
            fitted   = values.copy()
    elif n_hist >= 4:
        # Simple Holt (trend only, no seasonality)
        try:
            model = ExponentialSmoothing(
                values, trend="add", initialization_method="estimated"
            ).fit(optimized=True)
            fitted   = model.fittedvalues
            forecast = model.forecast(weeks_ahead)
        except Exception:
            forecast = _linear_forecast(values, weeks_ahead)
            fitted   = values.copy()
    else:
        # Not enough data — use mean projection
        mean = values.mean() if len(values) > 0 else 0
        fitted   = values.copy()
        forecast = np.full(weeks_ahead, mean)

    # Rolling std for confidence bands
    std = float(pd.Series(values).rolling(4, min_periods=1).std().iloc[-1] or np.std(values))

    rows = []

    # ── Historical rows ───────────────────────────────────────────────────────
    for i, (week_str, actual) in enumerate(zip(df_weekly["week"], values)):
        try:
            # week_str like "2024-W03"
            year, wk = week_str.split("-W")
            dt = datetime.strptime(f"{year}-W{wk}-1", "%Y-W%W-%w")
        except Exception:
            dt = datetime.now() - timedelta(weeks=(n_hist - i))
        rows.append({
            "week_label":  dt.strftime("%-d %b '%y"),
            "week_start":  dt,
            "predicted":   float(actual),
            "lower":       float(actual),
            "upper":       float(actual),
            "is_forecast": False,
            "week_number": i - n_hist,  # negative
        })

    # ── Forecast rows ─────────────────────────────────────────────────────────
    now = datetime.now()
    # Align to start of current week (Monday)
    week_start = now - timedelta(days=now.weekday())

    for w in range(1, weeks_ahead + 1):
        dt    = week_start + timedelta(weeks=w)
        raw   = max(0.0, float(forecast[w - 1]))
        adj   = raw * seasonal_multiplier(dt)
        lo, hi = confidence_band(adj, std, w)
        rows.append({
            "week_label":  dt.strftime("%-d %b '%y"),
            "week_start":  dt,
            "predicted":   adj,
            "lower":       lo,
            "upper":       hi,
            "is_forecast": True,
            "week_number": w,
        })

    return pd.DataFrame(rows)


def _linear_forecast(values: np.ndarray, n: int) -> np.ndarray:
    x = np.arange(len(values), dtype=float)
    coeffs = np.polyfit(x, values, 1)
    future_x = np.arange(len(values), len(values) + n, dtype=float)
    return np.clip(np.polyval(coeffs, future_x), 0, None)


# ── Category Forecasts ────────────────────────────────────────────────────────

def forecast_by_category(df_all: pd.DataFrame, weeks_ahead: int = 50) -> dict:
    """Run separate 50-week forecasts for each category."""
    results = {}
    if df_all.empty or "category" not in df_all.columns:
        return results

    for cat in df_all["category"].unique():
        cat_df = df_all[df_all["category"] == cat].copy()
        if len(cat_df) < 3:
            continue
        cat_df["week"] = cat_df["date"].dt.strftime("%Y-W%W")
        weekly = cat_df.groupby("week")["amount"].sum().reset_index()
        weekly.columns = ["week", "total"]
        try:
            results[cat] = forecast_50_weeks(weekly, weeks_ahead)
        except Exception:
            pass
    return results


# ── Summary Metrics ───────────────────────────────────────────────────────────

def forecast_summary(fc_df: pd.DataFrame) -> dict:
    future = fc_df[fc_df["is_forecast"]]
    past   = fc_df[~fc_df["is_forecast"]]
    return {
        "avg_weekly":      float(past["predicted"].mean()) if not past.empty else 0,
        "total_50_weeks":  float(future["predicted"].sum()),
        "next_4_weeks":    float(future.head(4)["predicted"].sum()),
        "next_12_weeks":   float(future.head(12)["predicted"].sum()),
        "peak_week":       future.loc[future["predicted"].idxmax()] if not future.empty else None,
        "lowest_week":     future.loc[future["predicted"].idxmin()] if not future.empty else None,
        "trend":           _trend(past["predicted"].values if not past.empty else np.array([])),
    }


def _trend(values: np.ndarray) -> str:
    if len(values) < 4:
        return "stable"
    x = np.arange(len(values), dtype=float)
    slope = np.polyfit(x, values, 1)[0]
    mean  = values.mean() or 1
    if slope > mean * 0.03:
        return "increasing"
    if slope < -mean * 0.03:
        return "decreasing"
    return "stable"
