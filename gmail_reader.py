"""
gmail_reader.py — Reads Gmail using OAuth2.
Works with Streamlit's session state for token management.
"""

import os
import json
import base64
import hashlib
import re
from email import message_from_bytes
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
import streamlit as st

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"   # out-of-band (works without a live redirect URL)


# ── OAuth Flow ────────────────────────────────────────────────────────────────

def get_auth_url(client_secret_json: dict) -> tuple:
    """Returns (auth_url, flow) for the OAuth consent page."""
    flow = Flow.from_client_config(
        client_secret_json,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    return auth_url, flow


def exchange_code(flow: Flow, code: str) -> Credentials:
    """Exchange the auth code for credentials."""
    flow.fetch_token(code=code)
    return flow.credentials


def creds_to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }


def dict_to_creds(d: dict) -> Credentials:
    return Credentials(
        token=d["token"],
        refresh_token=d.get("refresh_token"),
        token_uri=d["token_uri"],
        client_id=d["client_id"],
        client_secret=d["client_secret"],
        scopes=d["scopes"],
    )


def refresh_if_needed(creds: Credentials) -> Credentials:
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


# ── Gmail API ─────────────────────────────────────────────────────────────────

def build_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


FINANCIAL_QUERY = (
    "(subject:transaction OR subject:debited OR subject:credited OR "
    "subject:payment OR subject:order OR subject:bill OR subject:statement OR "
    "subject:receipt OR subject:invoice OR subject:EMI OR subject:recharge) "
    "newer_than:90d"
)


def fetch_emails(creds: Credentials, max_results: int = 200) -> List[Dict]:
    """Fetch and parse financial emails. Returns list of raw email dicts."""
    service = build_service(creds)
    results = []
    page_token = None

    while len(results) < max_results:
        kwargs = {
            "userId": "me",
            "q": FINANCIAL_QUERY,
            "maxResults": min(50, max_results - len(results)),
        }
        if page_token:
            kwargs["pageToken"] = page_token

        response = service.users().messages().list(**kwargs).execute()
        messages = response.get("messages", [])
        if not messages:
            break

        for msg_ref in messages:
            try:
                msg = service.users().messages().get(
                    userId="me", id=msg_ref["id"], format="full"
                ).execute()
                parsed = _parse_message(msg)
                if parsed:
                    results.append(parsed)
            except Exception:
                pass

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return results


def _parse_message(msg: dict) -> Optional[Dict]:
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    subject = headers.get("subject", "")
    sender  = headers.get("from", "")
    date_str = headers.get("date", "")
    msg_id  = msg.get("id", "")

    body_text = _extract_body(msg)
    combined  = f"{subject}\n{body_text}"

    return {
        "id":      msg_id,
        "subject": subject,
        "sender":  sender,
        "date":    date_str,
        "body":    body_text,
        "combined": combined,
        "hash":    hashlib.sha256(combined[:500].encode()).hexdigest()
    }


def _extract_body(msg: dict) -> str:
    payload = msg.get("payload", {})

    def decode_data(data: str) -> str:
        try:
            fixed = data.replace("-", "+").replace("_", "/")
            decoded = base64.b64decode(fixed + "==").decode("utf-8", errors="replace")
            return decoded
        except Exception:
            return ""

    def find_part(payload, mime_type: str) -> str:
        if payload.get("mimeType") == mime_type:
            data = payload.get("body", {}).get("data", "")
            return decode_data(data) if data else ""
        for part in payload.get("parts", []):
            result = find_part(part, mime_type)
            if result:
                return result
        return ""

    plain = find_part(payload, "text/plain")
    if plain.strip():
        return plain[:2000]

    html = find_part(payload, "text/html")
    if html:
        soup = BeautifulSoup(html, "lxml")
        return soup.get_text(separator=" ", strip=True)[:2000]

    return ""
