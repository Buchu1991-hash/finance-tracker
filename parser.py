"""
parser.py — Parses financial emails into structured transaction/bill records.
Handles all major Indian banks + CC bill lifecycle (generated → reminder → paid).
"""

import re
import hashlib
from datetime import datetime
from typing import Optional, Dict, List
from dateutil import parser as dateparser


# ── Amount Extraction ─────────────────────────────────────────────────────────

AMOUNT_PATTERNS = [
    re.compile(r"(?:INR|Rs\.?|₹)\s*([0-9,]+(?:\.[0-9]{1,2})?)", re.I),
    re.compile(r"([0-9,]+(?:\.[0-9]{2})?)\s*(?:INR|Rs\.?|₹)", re.I),
    re.compile(r"(?:amount|total)[:\s]+(?:INR|Rs\.?|₹)?\s*([0-9,]+(?:\.[0-9]{2})?)", re.I),
    re.compile(r"(?:debit(?:ed)?|paid?|spent?)[:\s]+(?:INR|Rs\.?|₹)?\s*([0-9,]+(?:\.[0-9]{2})?)", re.I),
]

def extract_amount(text: str) -> Optional[float]:
    for p in AMOUNT_PATTERNS:
        m = p.search(text)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


# ── Transaction Type ──────────────────────────────────────────────────────────

DEBIT_WORDS  = ["debited", "debit", "spent", "payment", "paid", "purchase",
                "withdrawn", "pos ", "upi debit", "neft sent", "imps sent",
                "auto debit", "emi", "bill payment", "charged"]
CREDIT_WORDS = ["credited", "credit", "received", "deposited", "salary",
                "refund", "cashback", "reward", "reversed", "neft credit",
                "imps credit", "upi credit", "transferred to your"]

def get_type(text: str) -> str:
    t = text.lower()
    if any(w in t for w in CREDIT_WORDS):
        return "CREDIT"
    return "DEBIT"


# ── Merchant Extraction ───────────────────────────────────────────────────────

MERCHANT_PATTERNS = [
    re.compile(r"\bat\s+([A-Z][A-Za-z0-9\s&'*\-\.]{2,30}?)(?:\s+on|\s+via|\.|$)"),
    re.compile(r"\bto\s+([A-Z][A-Za-z0-9\s&'*\-\.]{2,30}?)(?:\s+on|\s+via|\.|$)"),
    re.compile(r"\bfor\s+([A-Z][A-Za-z0-9\s&'*\-\.]{2,25}?)(?:\s+on|\s+via|\.|$)"),
    re.compile(r"VPA\s+[\w.\-@]+\s+\(([^)]+)\)"),
    re.compile(r"merchant[:\s]+([A-Za-z0-9\s&'*\-\.]{2,25})", re.I),
]

MERCHANT_MAP = {
    "SWGY": "Swiggy", "ZOMATO": "Zomato", "BLINKIT": "Blinkit",
    "BIGBASKET": "BigBasket", "ZEPTO": "Zepto", "DUNZO": "Dunzo",
    "AMZN": "Amazon", "AMAZON": "Amazon", "FLIPKART": "Flipkart",
    "UBER": "Uber", "OLA": "Ola", "RAPIDO": "Rapido",
    "NETFLIX": "Netflix", "SPOTIFY": "Spotify",
    "HOTSTAR": "Disney+ Hotstar", "PRIME": "Amazon Prime",
    "BESCOM": "BESCOM (Electricity)", "AIRTEL": "Airtel",
    "JIO": "Jio", "ACT": "ACT Fibernet", "BSNL": "BSNL",
    "GPAY": "Google Pay", "PHONEPE": "PhonePe", "PAYTM": "Paytm",
    "IRCTC": "IRCTC", "MMT": "MakeMyTrip", "GOIBIBO": "Goibibo",
    "MYNTRA": "Myntra", "AJIO": "Ajio", "NYKAA": "Nykaa",
    "APOLLO": "Apollo Pharmacy", "MEDPLUS": "MedPlus",
}

def extract_merchant(text: str, subject: str = "") -> str:
    # Try subject first (often cleaner)
    if subject and len(subject) < 50:
        for key, val in MERCHANT_MAP.items():
            if key in subject.upper():
                return val

    for p in MERCHANT_PATTERNS:
        m = p.search(text)
        if m:
            raw = m.group(1).strip().upper()
            return MERCHANT_MAP.get(raw, m.group(1).strip().title())

    # Map check on full text
    for key, val in MERCHANT_MAP.items():
        if key in text.upper():
            return val
    return "Unknown"


# ── Bank Detection ────────────────────────────────────────────────────────────

def detect_bank(sender: str, text: str) -> str:
    s = (sender + text).upper()
    for bank in ["HDFC", "ICICI", "SBI", "AXIS", "KOTAK", "YES BANK",
                 "BOB", "PNB", "INDUSIND", "CANARA", "IDFC", "RBL",
                 "FEDERAL", "CITIBANK", "AMEX"]:
        if bank in s:
            return bank.title()
    return "Bank"


# ── Account Last 4 ────────────────────────────────────────────────────────────

ACCOUNT_RE = [
    re.compile(r"[Aa]/[Cc]\s*[Xx*]{2,}(\d{4})"),
    re.compile(r"[Cc]ard\s*[Xx*]{2,}(\d{4})"),
    re.compile(r"[Xx*]{4,}(\d{4})"),
    re.compile(r"ending\s+(?:in\s+)?(\d{4})", re.I),
]

def extract_account(text: str) -> str:
    for p in ACCOUNT_RE:
        m = p.search(text)
        if m:
            return m.group(1)
    return ""


# ── Balance ───────────────────────────────────────────────────────────────────

BALANCE_RE = re.compile(
    r"(?:Avl|Avail(?:able)?)\s*(?:Bal|Balance)[:\s]*(?:INR|Rs\.?|₹)?\s*([0-9,]+(?:\.[0-9]{2})?)", re.I
)

def extract_balance(text: str) -> Optional[float]:
    m = BALANCE_RE.search(text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


# ── Date ──────────────────────────────────────────────────────────────────────

def extract_date_ts(date_str: str, fallback_ms: int = None) -> int:
    try:
        dt = dateparser.parse(date_str, fuzzy=True)
        if dt:
            return int(dt.timestamp() * 1000)
    except Exception:
        pass
    return fallback_ms or int(datetime.now().timestamp() * 1000)


# ── Category ─────────────────────────────────────────────────────────────────

CATEGORY_MAP = [
    ("Food & Dining",     ["swiggy","zomato","food","restaurant","cafe","hotel","pizza","kfc",
                           "mcdonalds","burger","dunkin","starbucks","barbeque","dominos"]),
    ("Groceries",         ["bigbasket","blinkit","zepto","grofer","dmart","supermarket",
                           "grocery","fresh","vegetables","meesho"]),
    ("Transport",         ["uber","ola","rapido","metro","bmtc","petrol","fuel",
                           "indian oil","hp gas","namma metro","irctc","bus","cab"]),
    ("Shopping",          ["amazon","flipkart","myntra","ajio","nykaa","snapdeal",
                           "shopping","retail","store","mall","meesho"]),
    ("Utilities & Bills", ["bescom","electricity","airtel","jio","bsnl","act","internet",
                           "broadband","gas","recharge","dth","water","bill"]),
    ("Entertainment",     ["netflix","spotify","hotstar","prime","zee5","sony","bookmyshow",
                           "movie","theatre","concert","game","youtube"]),
    ("Health & Medical",  ["pharmacy","apollo","medplus","hospital","clinic","lab",
                           "doctor","medicine","health","wellness","max hospital"]),
    ("Education",         ["course","udemy","coursera","book","school","college","university",
                           "byju","unacademy","tuition","coaching"]),
    ("Travel",            ["makemytrip","goibibo","cleartrip","airline","indigo","airasia",
                           "spicejet","oyo","treebo","flight","hotel booking"]),
    ("Investments",       ["mutual fund","zerodha","groww","kuvera","sip","stock","nse","bse"]),
    ("Salary / Income",   ["salary","stipend","credited by employer"]),
    ("Transfers",         ["transfer","neft","imps","upi transfer","sent to"]),
]

def categorize(merchant: str, body: str) -> str:
    text = (merchant + " " + body).lower()
    for category, keywords in CATEGORY_MAP:
        if any(kw in text for kw in keywords):
            return category
    return "Other"


# ── CC Bill Lifecycle ─────────────────────────────────────────────────────────

CC_BILL_GENERATED = [
    re.compile(r"statement\s+(?:generated|ready|available)", re.I),
    re.compile(r"total\s+(?:amount\s+)?due[:\s]+(?:INR|Rs\.?|₹)?\s*[0-9,]+", re.I),
    re.compile(r"e-?statement", re.I),
    re.compile(r"monthly\s+statement", re.I),
    re.compile(r"credit\s+card\s+bill\s+(?:is\s+)?(?:generated|ready|due)", re.I),
]
CC_REMINDER_KEYWORDS = [
    "payment reminder", "bill reminder", "pay your credit card",
    "pay your cc bill", "minimum amount due", "avoid late fee",
    "last date to pay", "action required: pay", "pay before",
    "due date is approaching", "outstanding amount", "please pay"
]
CC_PAYMENT_CONFIRMED = [
    re.compile(r"payment\s+(?:of\s+)?(?:INR|Rs\.?|₹)?\s*[0-9,]+.*?(?:received|successful|confirmed|processed)", re.I),
    re.compile(r"thank\s+you.*?payment", re.I),
    re.compile(r"cc\s+bill\s+payment.*?successful", re.I),
    re.compile(r"credit\s+card\s+payment\s+(?:successful|confirmed|received)", re.I),
]
CC_REMINDER_SUBJECTS = [
    "payment reminder", "bill reminder", "due date", "minimum due",
    "outstanding", "pay now", "action required"
]

def classify_cc_message(subject: str, body: str) -> str:
    """Returns: BILL_GENERATED | REMINDER | PAYMENT_CONFIRMED | REGULAR"""
    combined = (subject + " " + body).lower()
    subj_low = subject.lower()

    # Payment confirmed — most specific first
    if any(p.search(combined) for p in CC_PAYMENT_CONFIRMED):
        if any(w in combined for w in ["credit card", "cc bill", "card payment", "card dues"]):
            return "PAYMENT_CONFIRMED"

    # Reminder
    if any(kw in combined for kw in CC_REMINDER_KEYWORDS):
        return "REMINDER"
    if any(kw in subj_low for kw in CC_REMINDER_SUBJECTS):
        return "REMINDER"

    # Bill generated
    if any(p.search(combined) for p in CC_BILL_GENERATED):
        return "BILL_GENERATED"

    return "REGULAR"


def extract_cc_total_due(text: str) -> Optional[float]:
    patterns = [
        re.compile(r"total\s+(?:amount\s+)?due[:\s]+(?:INR|Rs\.?|₹)?\s*([0-9,]+(?:\.[0-9]{2})?)", re.I),
        re.compile(r"outstanding\s+(?:balance|amount)[:\s]+(?:INR|Rs\.?|₹)?\s*([0-9,]+(?:\.[0-9]{2})?)", re.I),
        re.compile(r"current\s+(?:balance|dues?)[:\s]+(?:INR|Rs\.?|₹)?\s*([0-9,]+(?:\.[0-9]{2})?)", re.I),
    ]
    for p in patterns:
        m = p.search(text)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return extract_amount(text)


def extract_due_date_ts(text: str) -> Optional[int]:
    patterns = [
        re.compile(r"due\s+(?:date|by)[:\s]+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", re.I),
        re.compile(r"pay\s+by[:\s]+(\d{1,2}\s+\w+\s*,?\s*\d{4})", re.I),
        re.compile(r"pay\s+before\s+(\d{1,2}\s+\w+\s*,?\s*\d{4})", re.I),
        re.compile(r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4}).*?due", re.I),
    ]
    for p in patterns:
        m = p.search(text)
        if m:
            try:
                dt = dateparser.parse(m.group(1), fuzzy=True)
                if dt:
                    return int(dt.timestamp() * 1000)
            except Exception:
                pass
    return None


# ── Main Parse Function ───────────────────────────────────────────────────────

def parse_email(email: dict) -> Optional[dict]:
    """
    Parse a raw email dict into a structured record.
    Returns one of:
      { "type": "TRANSACTION", ... }
      { "type": "CC_BILL", ... }
      { "type": "CC_PAYMENT", ... }
      None  (if not financial or is a REMINDER)
    """
    subject  = email.get("subject", "")
    sender   = email.get("sender",  "")
    body     = email.get("body",    "")
    combined = email.get("combined", f"{subject}\n{body}")
    date_str = email.get("date",    "")
    h        = email.get("hash",    hashlib.sha256(combined[:300].encode()).hexdigest())
    ts       = extract_date_ts(date_str)

    cc_type = classify_cc_message(subject, body)

    # ── Reminders: skip entirely ──────────────────────────────────────────────
    if cc_type == "REMINDER":
        return None

    # ── CC Bill Generated ─────────────────────────────────────────────────────
    if cc_type == "BILL_GENERATED":
        total = extract_cc_total_due(combined)
        if not total:
            return None
        bank = detect_bank(sender, combined)
        card = extract_account(combined)
        due_ts = extract_due_date_ts(combined)
        return {
            "type":     "CC_BILL",
            "bank":     bank,
            "card":     card,
            "amount":   total,
            "due_ts":   due_ts,
            "name":     f"{bank} Credit Card XX{card}" if card else f"{bank} Credit Card",
            "hash":     h,
            "ts":       ts,
        }

    # ── CC Payment Confirmed ──────────────────────────────────────────────────
    if cc_type == "PAYMENT_CONFIRMED":
        amount = extract_amount(combined)
        if not amount:
            return None
        bank = detect_bank(sender, combined)
        return {
            "type":     "CC_PAYMENT",
            "amount":   amount,
            "bank":     bank,
            "merchant": f"{bank} CC Payment",
            "category": "Utilities & Bills",
            "hash":     h,
            "ts":       ts,
            "raw":      combined[:300],
        }

    # ── Regular Transaction ───────────────────────────────────────────────────
    amount = extract_amount(combined)
    if not amount:
        return None

    tx_type  = get_type(combined)
    merchant = extract_merchant(combined, subject)
    category = categorize(merchant, combined)
    bank     = detect_bank(sender, combined)
    account  = extract_account(combined)
    balance  = extract_balance(combined)

    return {
        "type":         "TRANSACTION",
        "amount":       amount,
        "tx_type":      tx_type,
        "merchant":     merchant,
        "category":     category,
        "bank":         bank,
        "account_last4": account,
        "balance":      balance,
        "source":       "EMAIL",
        "hash":         h,
        "ts":           ts,
        "raw":          combined[:300],
    }
