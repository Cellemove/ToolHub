"""Registered offers per market/product/bundle — data for the market overview.

Stored in Supabase (``roas_offers``). Reads use the anon key (RLS allows
select only); registering an offer needs ``SUPABASE_SERVICE_KEY`` so writes
never ride on a public-writable policy.
"""

import os

import httpx
from pydantic import BaseModel, Field, field_validator

from .roas import compute

TABLE_URL = "{base}/rest/v1/roas_offers"
SUPPORTED_MARKETS = ("UK", "USA", "CANADA", "PT", "PL", "GR", "FR", "DE", "ES", "MX", "CZ")
SUPPORTED_CURRENCIES = ("USD", "EUR", "GBP", "CHF", "CAD", "AUD", "SEK", "AED", "PLN", "MXN", "CZK")


class OfferKey(BaseModel):
    market: str = Field(min_length=1, max_length=8)
    product: str = Field(min_length=1, max_length=120)
    bundle: str = Field(min_length=1, max_length=40)

    @field_validator("market", mode="before")
    @classmethod
    def normalize_market(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().upper()
        normalized = "USA" if normalized == "US" else normalized
        if normalized not in SUPPORTED_MARKETS:
            raise ValueError(f"market must be one of: {', '.join(SUPPORTED_MARKETS)}")
        return normalized

    @field_validator("product", "bundle", mode="before")
    @classmethod
    def trim_names(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class OfferIn(OfferKey):
    currency: str = Field(min_length=3, max_length=3)
    selling_price: float = Field(gt=0)
    cogs_usd: float = Field(ge=0)
    psp_fee: float = Field(ge=0, lt=1)
    vat: float = Field(ge=0, lt=1)
    other_fees: float = Field(ge=0, lt=1)
    min_margin: float = Field(ge=0, lt=1)
    target_margin: float = Field(ge=0, lt=1)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().upper()
        if normalized not in SUPPORTED_CURRENCIES:
            raise ValueError(f"currency must be one of: {', '.join(SUPPORTED_CURRENCIES)}")
        return normalized


class Offer(OfferIn):
    status: str = Field(default="active", pattern="^active$")


class OfferMetrics(Offer):
    roas_breakeven: float | None
    roas_at_min_margin: float | None
    roas_at_target_margin: float | None
    breakeven_cpa: float | None
    warning: str | None


class OffersUnavailable(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


OFFER_HINTS = {
    "supabase_not_configured": "Set SUPABASE_URL and SUPABASE_ANON_KEY on the backend.",
    "table_missing": "Run supabase/migrations/004_roas_offers.sql in the Supabase SQL editor.",
    "no_service_key": "Registering offers needs SUPABASE_SERVICE_KEY (service_role) on the backend.",
    "unreachable": "Supabase is unreachable from the backend.",
    "write_failed": "Supabase rejected the active-offer update.",
}


def enrich(offer: Offer, usd_rate: float | None = None) -> OfferMetrics:
    """Attach metrics. ``usd_rate`` is units of ``offer.currency`` per USD.

    COGS is always USD; a non-USD selling price converts via ``usd_rate``
    before the math. Without a rate, metrics are unknown, not wrong.
    """
    if offer.currency == "USD":
        price_usd = offer.selling_price
    elif usd_rate and usd_rate > 0:
        price_usd = offer.selling_price / usd_rate
    else:
        return OfferMetrics(
            **offer.model_dump(),
            roas_breakeven=None,
            roas_at_min_margin=None,
            roas_at_target_margin=None,
            breakeven_cpa=None,
            warning="fx_unavailable",
        )
    result = compute(
        price=price_usd,
        cogs=offer.cogs_usd,
        psp_fee=offer.psp_fee,
        vat=offer.vat,
        other_fees=offer.other_fees,
        min_margin=offer.min_margin,
        target_margin=offer.target_margin,
    )
    return OfferMetrics(
        **offer.model_dump(),
        roas_breakeven=result.roas_breakeven,
        roas_at_min_margin=result.roas_at_min_margin,
        roas_at_target_margin=result.roas_at_target_margin,
        breakeven_cpa=result.breakeven_cpa,
        warning=None if result.roas_breakeven is not None else "not_profitable",
    )


def _base_and_key() -> tuple[str, str]:
    base, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_ANON_KEY")
    if not base or not key:
        raise OffersUnavailable("supabase_not_configured")
    return base, key


async def fetch_offers() -> list[Offer]:
    base, key = _base_and_key()
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                TABLE_URL.format(base=base),
                params={"select": "*", "order": "market,product,bundle"},
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
    except httpx.HTTPError as exc:
        raise OffersUnavailable("unreachable") from exc
    if r.status_code == 404:
        raise OffersUnavailable("table_missing")
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise OffersUnavailable("unreachable") from exc
    return [Offer(**row) for row in r.json()]


async def upsert_offer(offer: OfferIn) -> None:
    base, _ = _base_and_key()
    service_key = os.getenv("SUPABASE_SERVICE_KEY")
    if not service_key:
        raise OffersUnavailable("no_service_key")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(
                TABLE_URL.format(base=base),
                params={"on_conflict": "market,product,bundle"},
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                    "Prefer": "resolution=merge-duplicates,return=minimal",
                },
                json=offer.model_dump(),
            )
    except httpx.HTTPError as exc:
        raise OffersUnavailable("unreachable") from exc
    if r.status_code == 404:
        raise OffersUnavailable("table_missing")
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise OffersUnavailable("write_failed") from exc


async def delete_offer(offer: OfferKey) -> bool:
    """Delete exactly one active market/product/bundle slot."""
    base, _ = _base_and_key()
    service_key = os.getenv("SUPABASE_SERVICE_KEY")
    if not service_key:
        raise OffersUnavailable("no_service_key")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.delete(
                TABLE_URL.format(base=base),
                params={
                    "market": f"eq.{offer.market}",
                    "product": f"eq.{offer.product}",
                    "bundle": f"eq.{offer.bundle}",
                },
                headers={
                    "apikey": service_key,
                    "Authorization": f"Bearer {service_key}",
                    "Prefer": "return=representation",
                },
            )
    except httpx.HTTPError as exc:
        raise OffersUnavailable("unreachable") from exc
    if r.status_code == 404:
        raise OffersUnavailable("table_missing")
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise OffersUnavailable("write_failed") from exc
    return bool(r.json())
