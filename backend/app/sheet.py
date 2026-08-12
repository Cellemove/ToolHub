"""Live product presets from the reference Google Sheet.

Access paths, in priority order:

1. Workload Identity Federation (deployed on Vercel, keyless): Vercel's runtime
   injects ``VERCEL_OIDC_TOKEN``; with ``GOOGLE_WIF_AUDIENCE`` set, it is
   exchanged at Google STS for a federated token, then for a token as the
   service account named by ``GOOGLE_IMPERSONATE_SERVICE_ACCOUNT``.
2. Keyless impersonation (local dev): ``GOOGLE_IMPERSONATE_SERVICE_ACCOUNT``
   alone — local ADC (``gcloud auth application-default login``) mints
   short-lived tokens as that account via the IAM Credentials API.
3. Service-account key: set ``GOOGLE_APPLICATION_CREDENTIALS`` to a key JSON.
   Auth is a locally-signed JWT against the Sheets API v4.
4. Public CSV export: used when nothing is configured; works only when the
   sheet is link-shared as Viewer.

Whichever path, share the sheet with the service account's email as Viewer.

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
from pydantic import BaseModel, Field

DEFAULT_SHEET_ID = "1-OEZQk_HvpfcGEfc1HWyrymxLNEI6mALgapLtZiPIRU"
DEFAULT_SHEET_GID = "1196565987"
CSV_URL = "https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"  # rw: presets read + row append


class Product(BaseModel):
    name: str = Field(min_length=1)
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
        "no_write_access": f"Adding rows needs write access — share the sheet with {email} "
        "as Editor (it currently has Viewer).",
        "bad_credentials": "GOOGLE_APPLICATION_CREDENTIALS does not point to a valid service-account key.",
        "impersonation_failed": f"Could not impersonate {email} — check ADC "
        "(gcloud auth application-default login) and the serviceAccountTokenCreator binding.",
        "wif_failed": f"Workload Identity Federation failed — check GOOGLE_WIF_AUDIENCE, "
        f"the provider's attribute condition, and the workloadIdentityUser binding on {email}.",
        "oidc_token_missing": "No Vercel OIDC token on this request — enable OpenID Connect "
        "Federation in the Vercel project (Settings → Security), then redeploy.",
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
                target_scopes=[SHEETS_SCOPE],
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


async def _wif_token(oidc: str | None) -> str:
    """SA token via Workload Identity Federation from Vercel's OIDC token — keyless."""
    oidc = oidc or os.getenv("VERCEL_OIDC_TOKEN")
    if not oidc:
        raise SheetUnavailable("oidc_token_missing")
    audience = os.environ["GOOGLE_WIF_AUDIENCE"]
    target = os.environ["GOOGLE_IMPERSONATE_SERVICE_ACCOUNT"]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            sts = await client.post(
                "https://sts.googleapis.com/v1/token",
                json={
                    "grantType": "urn:ietf:params:oauth:grant-type:token-exchange",
                    "audience": audience,
                    "scope": "https://www.googleapis.com/auth/cloud-platform",
                    "requestedTokenType": "urn:ietf:params:oauth:token-type:access_token",
                    "subjectToken": oidc,
                    "subjectTokenType": "urn:ietf:params:oauth:token-type:jwt",
                },
            )
            sts.raise_for_status()
            gen = await client.post(
                "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
                f"{target}:generateAccessToken",
                headers={"Authorization": f"Bearer {sts.json()['access_token']}"},
                json={"scope": [SHEETS_SCOPE]},
            )
            gen.raise_for_status()
            return str(gen.json()["accessToken"])
    except httpx.HTTPStatusError as exc:
        raise SheetUnavailable("wif_failed") from exc


def _api_token() -> str:
    target = os.getenv("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT")
    if target:
        return _impersonation_token(target)
    return _key_file_token(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])


async def _bearer_token(oidc: str | None) -> str:
    # On Vercel (VERCEL=1) WIF is the only viable path; locally fall through to ADC
    # even when GOOGLE_WIF_AUDIENCE is present in the shared .env.
    if os.getenv("GOOGLE_WIF_AUDIENCE") and (oidc or os.getenv("VERCEL_OIDC_TOKEN") or os.getenv("VERCEL")):
        return await _wif_token(oidc)
    return _api_token()


async def _resolve_title(client: httpx.AsyncClient, headers: dict[str, str], sid: str, gid: str) -> str:
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
    return title


async def _fetch_via_api(sid: str, gid: str, oidc: str | None) -> list[Product]:
    headers = {"Authorization": f"Bearer {await _bearer_token(oidc)}"}
    async with httpx.AsyncClient(timeout=10) as client:
        title = await _resolve_title(client, headers, sid, gid)
        escaped = title.replace("'", "''")
        value_range = quote(f"'{escaped}'!A:H", safe="")
        vals = await client.get(
            f"{API_BASE}/{sid}/values/{value_range}",
            params={"valueRenderOption": "UNFORMATTED_VALUE"},
            headers=headers,
        )
        vals.raise_for_status()
        return parse_values(vals.json().get("values", []))


def _safe_cell(s: str) -> str:
    """Neutralize formula/DDE triggers in user text (OWASP CSV-injection guidance).

    A leading apostrophe makes Sheets store the value as literal text under
    USER_ENTERED — the apostrophe itself is an input marker, not cell content.
    """
    return "'" + s if s and s[0] in ("=", "+", "-", "@", "\t", "\r") else s


def next_free_row(values: list[list[Any]]) -> int:
    """1-based index of the first row whose A..H cells are all empty.

    Only A:H matters — far rows carry stray I:L formulas in the reference sheet,
    and unnamed rows with data in B..H must not be overwritten.
    """
    last = 0
    for i, row in enumerate(values, start=1):
        if any(str(c).strip() for c in row[:8] if c is not None):
            last = i
    return last + 1


def row_formulas(r: int) -> list[str]:
    """Columns I..L exactly as the reference sheet computes them per row.

    Function arguments use ';' — the sheet's locale is French (comma decimals),
    where ',' as an argument separator is a parse error. Google Sheets accepts
    ';' in dot-decimal locales too, so this is the safe separator either way.
    """
    return [
        f"=H{r}/G{r}",
        f"=(H{r})/(H{r}*(1-B{r}-C{r}-D{r})-G{r})",
        f"=H{r} / (H{r} * (1 -B{r}-C{r}-D{r} - F{r}) - G{r})",
        f'=ROUND(H{r} / (H{r} * (1 -B{r} -C{r}-D{r} - E{r}) - G{r}); 2) & " - " & '
        f'ROUND(H{r} / (H{r} * (1 -B{r}-C{r}-D{r} - F{r}) - G{r}); 2)',
    ]


async def append_product(product: Product, oidc_token: str | None = None) -> int:
    """Write the offer as a new sheet row (inputs A..H + formula columns I..L)."""
    sid = os.getenv("ROAS_SHEET_ID", DEFAULT_SHEET_ID)
    gid = os.getenv("ROAS_SHEET_GID", DEFAULT_SHEET_GID)
    headers = {"Authorization": f"Bearer {await _bearer_token(oidc_token)}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            title = await _resolve_title(client, headers, sid, gid)
            escaped = title.replace("'", "''")
            read_range = quote(f"'{escaped}'!A1:H", safe="")
            got = await client.get(f"{API_BASE}/{sid}/values/{read_range}", headers=headers)
            got.raise_for_status()
            row = next_free_row(got.json().get("values", []))
            write_range = quote(f"'{escaped}'!A{row}:L{row}", safe="")
            update = await client.put(
                f"{API_BASE}/{sid}/values/{write_range}",
                params={"valueInputOption": "USER_ENTERED"},
                headers=headers,
                json={
                    "range": f"'{title}'!A{row}:L{row}",
                    "values": [
                        [
                            _safe_cell(product.name),
                            product.psp_fee,
                            product.vat,
                            product.other_fees,
                            product.min_margin,
                            product.target_margin,
                            product.cogs,
                            product.selling_price,
                            *row_formulas(row),
                        ]
                    ],
                },
            )
            if update.status_code in (401, 403):
                raise SheetUnavailable("no_write_access")
            update.raise_for_status()
            return row
    except httpx.HTTPError as exc:
        raise SheetUnavailable("unreachable") from exc


async def _fetch_via_csv(sid: str, gid: str) -> list[Product]:
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        r = await client.get(CSV_URL.format(sid=sid, gid=gid))
    if r.status_code in (401, 403) or "text/html" in r.headers.get("content-type", ""):
        raise SheetUnavailable("private")
    if r.status_code != 200:
        raise SheetUnavailable(f"http_{r.status_code}")
    return parse_products(r.text)


async def fetch_products(oidc_token: str | None = None) -> list[Product]:
    sid = os.getenv("ROAS_SHEET_ID", DEFAULT_SHEET_ID)
    gid = os.getenv("ROAS_SHEET_GID", DEFAULT_SHEET_GID)
    try:
        if os.getenv("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT") or os.getenv(
            "GOOGLE_APPLICATION_CREDENTIALS"
        ):
            return await _fetch_via_api(sid, gid, oidc_token)
        return await _fetch_via_csv(sid, gid)
    except httpx.HTTPError as exc:
        raise SheetUnavailable("unreachable") from exc
