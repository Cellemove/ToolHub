"""Checks against actual rows of 'References/ROAS BE calculation.xlsx'."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.roas import compute

client = TestClient(app)


def test_sheet_row_2_legging_uk_sleeve() -> None:
    # H=53.55, G=13.8, psp=0.07, tva=0, autres=0.01, min=0.15, cible=0.20
    r = compute(53.55, 13.8, 0.07, 0.0, 0.01, 0.15, 0.20)
    assert r.multiplier == pytest.approx(3.880434783, abs=1e-6)
    assert r.roas_breakeven == pytest.approx(1.509896803, abs=1e-6)
    assert r.roas_at_target_margin == pytest.approx(2.163111973, abs=1e-6)
    assert round(r.roas_at_min_margin or 0, 2) == 1.95  # sheet range "1,95 - 2,16"
    assert round(r.roas_at_target_margin or 0, 2) == 2.16


def test_sheet_row_6_two_uk() -> None:
    r = compute(47.9, 17.97, 0.07, 0.0, 0.01, 0.15, 0.20)
    assert r.roas_breakeven == pytest.approx(1.835389685, abs=1e-6)
    assert r.roas_at_target_margin == pytest.approx(2.899866812, abs=1e-6)


def test_breakeven_cpa_is_contribution() -> None:
    r = compute(100.0, 30.0, 0.05, 0.0, 0.0, 0.15, 0.20)
    assert r.breakeven_cpa == pytest.approx(100.0 * 0.95 - 30.0)
    assert r.roas_breakeven == pytest.approx(100.0 / (100.0 * 0.95 - 30.0))


def test_unachievable_margin_returns_none_not_negative() -> None:
    # price*(1-fees-target) < cogs -> target ROAS undefined (sheet shows #DIV/0! or nonsense)
    r = compute(10.0, 2.0, 0.05, 0.20, 0.05, 0.60, 0.75)
    assert r.roas_at_target_margin is None
    assert r.roas_at_min_margin is None
    assert r.roas_breakeven is not None


def test_cannot_break_even_at_all() -> None:
    r = compute(10.0, 12.0, 0.07, 0.0, 0.01, 0.15, 0.20)
    assert r.roas_breakeven is None
    assert r.breakeven_cpa is None
    assert r.multiplier is not None


def test_zero_cogs_no_multiplier_but_valid_roas() -> None:
    r = compute(50.0, 0.0, 0.07, 0.0, 0.01, 0.15, 0.20)
    assert r.multiplier is None
    assert r.roas_breakeven == pytest.approx(1 / 0.92)


def test_api_endpoint_matches_sheet() -> None:
    resp = client.post(
        "/api/roas/breakeven",
        json={
            "selling_price": 53.55,
            "cogs": 13.8,
            "psp_fee": 0.07,
            "vat": 0.0,
            "other_fees": 0.01,
            "min_margin": 0.15,
            "target_margin": 0.20,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["roas_breakeven"] == pytest.approx(1.509896803, abs=1e-6)
    assert body["warning"] is None


def test_api_warning_when_unprofitable() -> None:
    resp = client.post("/api/roas/breakeven", json={"selling_price": 10, "cogs": 12})
    assert resp.status_code == 200
    assert "cannot break even" in resp.json()["warning"]


def test_api_validation_rejects_bad_input() -> None:
    assert client.post("/api/roas/breakeven", json={"selling_price": 0, "cogs": 1}).status_code == 422
    assert client.post("/api/roas/breakeven", json={"selling_price": 10, "cogs": 1, "vat": 1.5}).status_code == 422


def test_tools_fallback_available() -> None:
    resp = client.get("/api/tools")
    assert resp.status_code == 200
    tools = {t["slug"]: t for t in resp.json()}
    assert tools["roas-breakeven"]["url"] is None  # internal tool routes by slug
    for slug in ("recast", "invoice-checker", "adfactory", "forklane"):
        assert tools[slug]["url"].startswith("https://")
