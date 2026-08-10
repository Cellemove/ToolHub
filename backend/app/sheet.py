"""Live product presets from the reference Google Sheet.

Access paths, in priority order:

1. Keyless impersonation (private sheet, no key files): set
   ``GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`` to the service account email. Local
   ADC (``gcloud auth application-default login``) mints short-lived tokens as
   that account via the IAM Credentials API. Share the sheet with the service
   account's email as Viewer.
2. Service-account key: set ``GOOGLE_APPLICATION_CREDENTIALS`` to a key JSON.
   Auth is a locally-signed JWT against the Sheets API v4.
3. Public CSV export: used when neither is configured; works only when the
   sheet is link-shared as Viewer.

Column layout mirrors the xlsx: name, PSP, VAT, other fees, min margin,
target margin, COGS, price (A..H).
"""

import csv
import io
import json
import os
from typing import Any
from urllib.parse import quote

import google.auth
import httpx
from google.auth import impersonated_credentials
from google.auth import jwt as google_jwt
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from pydantic import BaseModel

DEFAULT_SHEET_ID = "1-OEZQk_HvpfcGEfc1HWyrymxLNEI6mALgapLtZiPIRU"
DEFAULT_SHEET_GID = "1196565987"
CSV_URL = "https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


class Product(BaseModel):
    name: str
    psp_fee: float
    vat: float
    other_fees: float
    min_margin: float
    target_margin: float
    cogs: float
    selling_price: float


class SheetUnavailable(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def unavailable_hint(reason: str) -> str:
    email = service_account_email() or "the service account"
    hints = {
        "no_access": f"Share the sheet with {email} as Viewer to enable presets.",
        "bad_credentials": "GOOGLE_APPLICATION_CREDENTIALS does not point to a valid service-account key.",
        "impersonation_failed": f"Could not impersonate {email} — check ADC "
        "(gcloud auth application-default login) and the serviceAccountTokenCreator binding.",
        "private": "Configure service-account access (private sheet), "
        "or share the sheet as 'Anyone with the link — Viewer'.",
        "gid_not_found": "No tab with that gid — check ROAS_SHEET_GID against the tab's URL.",
        "not_found": "Spreadsheet not found — check ROAS_SHEET_ID.",
        "unreachable": "Google is unreachable from the backend.",
    }
    return hints.get(reason, "Google Sheet unavailable.")


def service_account_email() -> str | None:
    impersonated = os.getenv("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT")
    if impersonated:
        return impersonated
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            email = json.load(f).get("client_email")
        return str(email) if email else None
    except (OSError, ValueError):
        return None


def _num(raw: str) -> float | None:
    """Parse a sheet number: '0.07', '0,07', '7%', '1 234,5' → float."""
    s = raw.strip().replace(" ", "").replace(" ", "")
    if not s:
        return None
    is_pct = s.endswith("%")
    s = s.rstrip("%")
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return v / 100 if is_pct else v


def _pct(raw: str) -> float | None:
    """Percent cell as a fraction; bare values >= 1 mean someone typed 7 for 7% (or 1 for 1%)."""
    v = _num(raw)
    if v is None:
        return None
    return v / 100 if v >= 1 else v


def _from_rows(rows: list[list[str]]) -> list[Product]:
    """Usable preset rows: named, with positive price and COGS. First wins on duplicate names."""
    out: list[Product] = []
    seen: set[str] = set()
    for raw_row in rows:
        row = raw_row + [""] * (8 - len(raw_row))  # API rows are jagged
        name = row[0].strip()
        cogs, price = _num(row[6]), _num(row[7])
        if not name or name in seen or not price or price <= 0 or not cogs or cogs <= 0:
            continue
        pcts = [_pct(row[i]) for i in range(1, 6)]
        if any(p is not None and p >= 1 for p in pcts):  # a 100%+ fee/margin row is garbage
            continue
        psp, vat, other, m_min, m_target = pcts
        seen.add(name)
        out.append(
            Product(
                name=name,
                psp_fee=psp or 0.0,
                vat=vat or 0.0,
                other_fees=other or 0.0,
                min_margin=m_min if m_min is not None else 0.15,
                target_margin=m_target if m_target is not None else 0.20,
                cogs=cogs,
                selling_price=price,
            )
        )
    return out


def parse_products(csv_text: str) -> list[Product]:
    return _from_rows(list(csv.reader(io.StringIO(csv_text)))[1:])


def parse_values(values: list[list[Any]]) -> list[Product]:
    """Sheets API v4 values (UNFORMATTED_VALUE): cells are numbers/strings, rows jagged."""
    return _from_rows([["" if c is None else str(c) for c in row] for row in values[1:]])


_jwt: google_jwt.Credentials | None = None
_imp: impersonated_credentials.Credentials | None = None


def _impersonation_token(target: str) -> str:
    """Short-lived token minted as the service account via ADC — no key file."""
    global _imp
    try:
        if _imp is None:
            source, _ = google.auth.default()
            _imp = impersonated_credentials.Credentials(  # type: ignore[no-untyped-call]
                source_credentials=source,
                target_principal=target,
                target_scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
            )
        if not _imp.valid:
            _imp.refresh(Request())  # type: ignore[no-untyped-call]
    except GoogleAuthError as exc:
        raise SheetUnavailable("impersonation_failed") from exc
    return str(_imp.token)


def _key_file_token(path: str) -> str:
    """Self-signed JWT bearer token from a service-account key (cached, auto-renewed)."""
    global _jwt
    if _jwt is None:
        try:
            sa = service_account.Credentials.from_service_account_file(path)  # type: ignore[no-untyped-call]
            _jwt = google_jwt.Credentials.from_signing_credentials(  # type: ignore[no-untyped-call]
                sa, audience="https://sheets.googleapis.com/"
            )
        except (OSError, ValueError) as exc:
            raise SheetUnavailable("bad_credentials") from exc
    if not _jwt.valid:
        _jwt.refresh(None)  # self-signed JWT: the transport request is unused
    token = _jwt.token
    return token.decode() if isinstance(token, bytes) else str(token)


def _api_token() -> str:
    target = os.getenv("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT")
    if target:
        return _impersonation_token(target)
    return _key_file_token(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])


async def _fetch_via_api(sid: str, gid: str) -> list[Product]:
    headers = {"Authorization": f"Bearer {_api_token()}"}
    async with httpx.AsyncClient(timeout=10) as client:
        meta = await client.get(
            f"{API_BASE}/{sid}",
            params={"fields": "sheets(properties(sheetId,title))"},
            headers=headers,
        )
        if meta.status_code in (401, 403):
            raise SheetUnavailable("no_access")
        if meta.status_code == 404:
            raise SheetUnavailable("not_found")
        meta.raise_for_status()
        title: str | None = next(
            (
                s["properties"]["title"]
                for s in meta.json().get("sheets", [])
                if str(s["properties"]["sheetId"]) == gid
            ),
            None,
        )
        if title is None:
            raise SheetUnavailable("gid_not_found")
        escaped = title.replace("'", "''")
        value_range = quote(f"'{escaped}'!A:H", safe="")
        vals = await client.get(
            f"{API_BASE}/{sid}/values/{value_range}",
            params={"valueRenderOption": "UNFORMATTED_VALUE"},
            headers=headers,
        )
        vals.raise_for_status()
        return parse_values(vals.json().get("values", []))


async def _fetch_via_csv(sid: str, gid: str) -> list[Product]:
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        r = await client.get(CSV_URL.format(sid=sid, gid=gid))
    if r.status_code in (401, 403) or "text/html" in r.headers.get("content-type", ""):
        raise SheetUnavailable("private")
    if r.status_code != 200:
        raise SheetUnavailable(f"http_{r.status_code}")
    return parse_products(r.text)


async def fetch_products() -> list[Product]:
    sid = os.getenv("ROAS_SHEET_ID", DEFAULT_SHEET_ID)
    gid = os.getenv("ROAS_SHEET_GID", DEFAULT_SHEET_GID)
    try:
        if os.getenv("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT") or os.getenv(
            "GOOGLE_APPLICATION_CREDENTIALS"
        ):
            return await _fetch_via_api(sid, gid)
        return await _fetch_via_csv(sid, gid)
    except httpx.HTTPError as exc:
        raise SheetUnavailable("unreachable") from exc
