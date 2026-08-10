"""Break-even / target ROAS math.

Mirrors ``References/ROAS BE calculation.xlsx``:

    multiplier   = price / cogs
    ROAS(margin) = price / (price * (1 - fees - margin) - cogs)
    ROAS BE      = ROAS(0)
    range        = ROAS(min_margin) .. ROAS(target_margin)

``fees`` is the sum of the percentage fees (PSP + VAT + other), expressed
as fractions of the selling price. A ROAS is ``None`` when the denominator
is <= 0, i.e. the margin is not achievable at any ad spend.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RoasResult:
    """All figures the spreadsheet derives for one product row."""

    multiplier: float | None
    contribution: float
    roas_breakeven: float | None
    roas_at_min_margin: float | None
    roas_at_target_margin: float | None
    breakeven_cpa: float | None
    target_cpa: float | None


def roas_at(price: float, cogs: float, fees: float, margin: float = 0.0) -> float | None:
    """ROAS needed to keep ``margin`` (fraction of revenue) after fees and COGS."""
    denominator = price * (1.0 - fees - margin) - cogs
    return price / denominator if denominator > 0 else None


def compute(
    price: float,
    cogs: float,
    psp_fee: float,
    vat: float,
    other_fees: float,
    min_margin: float,
    target_margin: float,
) -> RoasResult:
    """Compute every output of the spreadsheet for one product."""
    fees = psp_fee + vat + other_fees
    contribution = price * (1.0 - fees) - cogs
    target_cpa = price * (1.0 - fees - target_margin) - cogs
    return RoasResult(
        multiplier=price / cogs if cogs > 0 else None,
        contribution=contribution,
        roas_breakeven=roas_at(price, cogs, fees),
        roas_at_min_margin=roas_at(price, cogs, fees, min_margin),
        roas_at_target_margin=roas_at(price, cogs, fees, target_margin),
        breakeven_cpa=contribution if contribution > 0 else None,
        target_cpa=target_cpa if target_cpa > 0 else None,
    )
