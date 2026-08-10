"""ToolHub API — tools registry (Supabase-backed) and the ROAS calculator."""

import logging
import os

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .roas import compute
from .sheet import Product, SheetUnavailable, fetch_products, unavailable_hint

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
        url="https://invoice2-0-tau.vercel.app",
    ),
    Tool(
        slug="adfactory",
        name="AdFactory",
        description="Research-to-script ad pipeline — avatar deep dives, angles and ready ad scripts.",
        icon="ads",
        status="live",
        sort=4,
        url="https://cellumove-ad-factory.vercel.app",
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


@app.get("/api/roas/products", response_model=list[Product])
async def roas_products() -> list[Product]:
    """Product presets from the reference Google Sheet (live source of truth)."""
    try:
        return await fetch_products()
    except SheetUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Google Sheet unavailable ({exc.reason}). {unavailable_hint(exc.reason)}",
        ) from exc


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
