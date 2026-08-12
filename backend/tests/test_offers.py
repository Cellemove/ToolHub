"""Metric enrichment for the market overview."""

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.offers import Offer, enrich

client = TestClient(main_module.app)


def offer(**overrides: object) -> Offer:
    base: dict[str, object] = {
        "market": "UK",
        "product": "Legging V1",
        "bundle": "x2",
        "currency": "USD",
        "selling_price": 47.90,
        "cogs_usd": 17.97,
        "psp_fee": 0.07,
        "vat": 0.0,
        "other_fees": 0.01,
        "min_margin": 0.15,
        "target_margin": 0.20,
    }
    base.update(overrides)
    return Offer(**base)  # type: ignore[arg-type]


def test_usd_offer_ignores_rate() -> None:
    m = enrich(offer(currency="USD"), usd_rate=None)
    # same numbers as the sheet row "2 UK": BE 1.8354
    assert m.roas_breakeven == pytest.approx(1.835389685, abs=1e-6)
    assert m.warning is None


def test_market_currency_is_ignored_for_accounting() -> None:
    m = enrich(offer(), usd_rate=0.75)
    expected = 47.90 / (47.90 * 0.92 - 17.97)
    assert m.roas_breakeven == pytest.approx(expected)
    assert m.currency == "USD"


def test_missing_fx_does_not_block_usd_metrics() -> None:
    m = enrich(offer(), usd_rate=None)
    assert m.roas_breakeven is not None
    assert m.warning is None


def test_unprofitable_offer_flagged() -> None:
    m = enrich(offer(currency="USD", selling_price=10.0, cogs_usd=12.0), usd_rate=None)
    assert m.roas_breakeven is None
    assert m.warning == "not_profitable"


def test_offer_identity_is_normalized() -> None:
    normalized = offer(market=" uk ", product=" VLegging V1 ", bundle=" x2 ", currency=" usd ")
    assert normalized.market == "UK"
    assert normalized.product == "VLegging V1"
    assert normalized.bundle == "x2"
    assert normalized.currency == "USD"


def test_non_usd_accounting_currency_is_rejected() -> None:
    with pytest.raises(ValueError, match="currency must be USD"):
        offer(currency="GBP")


def test_us_market_alias_becomes_usa() -> None:
    assert offer(market="US").market == "USA"


def test_unknown_market_is_rejected() -> None:
    with pytest.raises(ValueError, match="market must be one of"):
        offer(market="NL")


def test_remove_offer_endpoint_deletes_exact_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_delete(key: object) -> bool:
        assert getattr(key, "market") == "UK"
        assert getattr(key, "product") == "VLegging V1"
        assert getattr(key, "bundle") == "2 Leggings + Sleeve"
        return True

    monkeypatch.setattr(main_module, "delete_offer", fake_delete)
    response = client.request(
        "DELETE",
        "/api/roas/offers",
        json={"market": "UK", "product": "VLegging V1", "bundle": "2 Leggings + Sleeve"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "removed"}


def test_remove_offer_endpoint_returns_404_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_delete(_key: object) -> bool:
        return False

    monkeypatch.setattr(main_module, "delete_offer", fake_delete)
    response = client.request(
        "DELETE",
        "/api/roas/offers",
        json={"market": "UK", "product": "VLegging V1", "bundle": "Missing"},
    )
    assert response.status_code == 404
