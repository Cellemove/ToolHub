"""ToolHub API — tools registry (Supabase-backed) and the ROAS calculator."""

import logging
import os
import time

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .offers import (
    OFFER_HINTS,
    OfferIn,
    OfferKey,
    OfferMetrics,
    OffersUnavailable,
    delete_offer,
    enrich,
    fetch_offers,
    upsert_offer,
)
from .roas import compute
from .sheet import (
    Product,
    SheetUnavailable,
    append_product,
    fetch_products,
    unavailable_hint,
)

log = logging.getLogger("toolhub")

app = FastAPI(title="ToolHub API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Tool(BaseModel):
    slug: str
    name: str
    description: str = ""
    icon: str = "tool"
    status: str = "live"
    sort: int = 0
    url: str | None = None  # external tools open this link; internal tools route by slug


FALLBACK_TOOLS = [
    Tool(
        slug="roas-breakeven",
        name="ROAS Calculator",
        description="Break-even and target ROAS from price, COGS, fees and margin goals. Multi-currency.",
        icon="chart",
        status="live",
        sort=1,
    ),
    Tool(
        slug="recast",
        name="Recast",
        description="File converter — drop a file, pick a format, download the result.",
        icon="convert",
        status="live",
        sort=2,
        url="https://file-converter-app-iota.vercel.app",
    ),
    Tool(
        slug="invoice-checker",
        name="Invoice Checker",
        description="Reconciles invoice files against live Shopify orders — prices, quantities and SKUs.",
        icon="invoice",
        status="live",
        sort=3,
        url="https://invoice-checker-2.vercel.app/",
    ),
    Tool(
        slug="adfactory",
        name="AdFactory",
        description="Research-to-script ad pipeline — avatar deep dives, angles and ready ad scripts.",
        icon="ads",
        status="live",
        sort=4,
        url="https://ad-factory-zeta.vercel.app/",
    ),
    Tool(
        slug="forklane",
        name="Forklane",
        description="Controlled Shopify checkout and cart experiments — variants, lift and confidence.",
        icon="experiment",
        status="live",
        sort=5,
        url="https://forklane.vercel.app/",
    ),
    Tool(
        slug="cellucall",
        name="CelluCall",
        description="Call-center workspace — delivered-order call lists from Shopify, synced live.",
        icon="call",
        status="live",
        sort=6,
        url="https://cellu-call.vercel.app",
    ),
    Tool(
        slug="teardown",
        name="Teardown",
        description="Winning-ad deconstruction — Gemini watches the ad and returns a frame-by-frame script plus the 14-part workbook.",
        icon="teardown",
        status="live",
        sort=7,
        url="https://teardown-gamma.vercel.app",
    ),
]


class RoasRequest(BaseModel):
    """Percentages are fractions of the selling price (0.07 = 7%)."""

    selling_price: float = Field(gt=0)
    cogs: float = Field(ge=0)
    psp_fee: float = Field(default=0.0, ge=0, lt=1)
    vat: float = Field(default=0.0, ge=0, lt=1)
    other_fees: float = Field(default=0.0, ge=0, lt=1)
    min_margin: float = Field(default=0.15, ge=0, lt=1)
    target_margin: float = Field(default=0.20, ge=0, lt=1)


class RoasResponse(BaseModel):
    multiplier: float | None
    contribution: float
    roas_breakeven: float | None
    roas_at_min_margin: float | None
    roas_at_target_margin: float | None
    breakeven_cpa: float | None
    target_cpa: float | None
    warning: str | None


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/tools", response_model=list[Tool])
async def tools() -> list[Tool]:
    """Tool registry from Supabase; static fallback when unconfigured/unreachable."""
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_ANON_KEY")
    if url and key:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(
                    f"{url}/rest/v1/tools",
                    params={"select": "slug,name,description,icon,status,sort,url", "order": "sort"},
                    headers={"apikey": key, "Authorization": f"Bearer {key}"},
                )
                r.raise_for_status()
                return [Tool(**row) for row in r.json()]
        except httpx.HTTPError:
            log.warning("Supabase unreachable, serving fallback tool list")
    return FALLBACK_TOOLS


CURRENCIES = ("EUR", "USD", "GBP", "CHF", "CAD", "AUD", "SEK", "AED", "PLN", "MXN", "CZK")
FX_URL = "https://open.er-api.com/v6/latest/USD"
FX_TTL_SECONDS = 12 * 3600

_fx_cache: tuple[float, dict[str, float]] | None = None


class FxResponse(BaseModel):
    base: str
    rates: dict[str, float]


async def get_fx_rates() -> dict[str, float] | None:
    """Cached USD-based rates; stale beats missing; None when nothing is available."""
    global _fx_cache
    if _fx_cache and time.monotonic() - _fx_cache[0] < FX_TTL_SECONDS:
        return _fx_cache[1]
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(FX_URL)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError:
        return _fx_cache[1] if _fx_cache else None
    rates = {c: float(data["rates"][c]) for c in CURRENCIES if c in data.get("rates", {})}
    if len(rates) < len(CURRENCIES):
        log.warning("FX feed missing currencies: %s", set(CURRENCIES) - set(rates))
    _fx_cache = (time.monotonic(), rates)
    return rates


@app.get("/api/fx", response_model=FxResponse)
async def fx_rates() -> FxResponse:
    """USD-based exchange rates for the supported currencies (cached ~12h)."""
    rates = await get_fx_rates()
    if rates is None:
        raise HTTPException(status_code=503, detail="FX rates unavailable.")
    return FxResponse(base="USD", rates=rates)


@app.get("/api/roas/offers", response_model=list[OfferMetrics])
async def roas_offers() -> list[OfferMetrics]:
    """Registered offers with computed break-even metrics (market overview)."""
    try:
        offers = await fetch_offers()
    except OffersUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Offers unavailable ({exc.reason}). {OFFER_HINTS.get(exc.reason, '')}",
        ) from exc
    return [enrich(o) for o in offers]


@app.post("/api/roas/offers", status_code=201)
async def register_offer(offer: OfferIn) -> dict[str, str]:
    """Upsert the active offer for (market, product, bundle)."""
    try:
        await upsert_offer(offer)
    except OffersUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot register ({exc.reason}). {OFFER_HINTS.get(exc.reason, '')}",
        ) from exc
    return {"status": "registered"}


@app.delete("/api/roas/offers")
async def remove_roas_offer(offer: OfferKey) -> dict[str, str]:
    """Remove exactly one active market/product/bundle configuration."""
    try:
        deleted = await delete_offer(offer)
    except OffersUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot remove ({exc.reason}). {OFFER_HINTS.get(exc.reason, '')}",
        ) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Active offer not found.")
    return {"status": "removed"}


@app.get("/api/roas/products", response_model=list[Product])
async def roas_products(request: Request) -> list[Product]:
    """Product presets from the reference Google Sheet (live source of truth)."""
    # Vercel delivers its OIDC token as a request header. Passed per-request, never
    # stored globally: a forged value can only fail Google's checks for that request.
    try:
        return await fetch_products(oidc_token=request.headers.get("x-vercel-oidc-token"))
    except SheetUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Google Sheet unavailable ({exc.reason}). {unavailable_hint(exc.reason)}",
        ) from exc


@app.post("/api/roas/products", status_code=201)
async def add_roas_product(product: Product, request: Request) -> dict[str, int]:
    """Append the offer as a new row on the reference sheet (needs Editor access)."""
    try:
        row = await append_product(
            product, oidc_token=request.headers.get("x-vercel-oidc-token")
        )
    except SheetUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Google Sheet unavailable ({exc.reason}). {unavailable_hint(exc.reason)}",
        ) from exc
    return {"row": row}


@app.post("/api/roas/breakeven", response_model=RoasResponse)
def roas_breakeven(req: RoasRequest) -> RoasResponse:
    result = compute(
        price=req.selling_price,
        cogs=req.cogs,
        psp_fee=req.psp_fee,
        vat=req.vat,
        other_fees=req.other_fees,
        min_margin=req.min_margin,
        target_margin=req.target_margin,
    )
    warning: str | None = None
    if result.roas_breakeven is None:
        warning = "Fees + COGS meet or exceed revenue — this product cannot break even at any ROAS."
    elif result.roas_at_target_margin is None:
        warning = "Target margin is not achievable at this price — lower the margin, fees or COGS."
    return RoasResponse(
        multiplier=result.multiplier,
        contribution=result.contribution,
        roas_breakeven=result.roas_breakeven,
        roas_at_min_margin=result.roas_at_min_margin,
        roas_at_target_margin=result.roas_at_target_margin,
        breakeven_cpa=result.breakeven_cpa,
        target_cpa=result.target_cpa,
        warning=warning,
    )
