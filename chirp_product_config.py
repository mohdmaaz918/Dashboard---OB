"""
Chirp-specific product configuration.

This isolates the US/Chirp demo from UK FCA product economics while preserving
the shared categorisation and scoring framework.
"""

from __future__ import annotations

from typing import Dict, Tuple

# Tier anchors (USD) for scheduled daily cost — see resolve_chirp_scheduled_daily_rate.
CHIRP_PRICING_ANCHORS: Tuple[int, ...] = (300, 400, 500, 600, 700, 800, 900, 1000)

# Daily cost as a decimal (e.g. 1.8017% per day → 0.018017). Source: published rate card.
CHIRP_PRICING_SCHEDULE: Dict[str, Dict[int, float]] = {
    "biweekly": {
        300: 0.018017,
        400: 0.015463,
        500: 0.013548,
        600: 0.012329,
        700: 0.011313,
        800: 0.010453,
        900: 0.009717,
        1000: 0.009078,
    },
    "monthly": {
        300: 0.016850,
        400: 0.014462,
        500: 0.012672,
        600: 0.011533,
        700: 0.010583,
        800: 0.009780,
        900: 0.009091,
        1000: 0.008494,
    },
}

CHIRP_PRODUCT_CONFIG: Dict = {
    "min_loan_amount": 300,
    "max_loan_amount": 1000,
    "available_terms": [3, 4, 5, 6],
    # Chirp-specific economics used for affordability/offer sizing.
    # No total_cost_cap: interest accrues as principal × (daily_rate × 30.4) × term only.
    "daily_interest_rate": 0.001,
    "min_disposable_buffer": 50,
    "max_repayment_to_disposable": 1.0,
    "expense_shock_buffer": 1.1,
}


def resolve_chirp_scheduled_daily_rate(
    principal: float,
    cadence: str,
) -> Tuple[float, int, float]:
    """
    Pick the scheduled daily rate from the loan amount and product line.

    Uses the **largest tier anchor that is still <= principal** (e.g. $650 → $600 row).
    Amounts below the smallest anchor use the **$300** tier rate.

    Returns:
        (daily_rate_decimal, anchor_used, simple_annual_pct)
        where simple_annual_pct is 365 × daily rate × 100 (matches “simple per-annum” column).
    """
    key = (cadence or "monthly").lower().replace(" ", "").replace("-", "")
    if key == "biweekly":
        sched_key = "biweekly"
    else:
        sched_key = "monthly"

    sched = CHIRP_PRICING_SCHEDULE[sched_key]
    chosen = CHIRP_PRICING_ANCHORS[0]
    for a in CHIRP_PRICING_ANCHORS:
        if float(principal) + 1e-9 >= float(a):
            chosen = a
    daily = float(sched[chosen])
    simple_annual_pct = daily * 365.0 * 100.0
    return daily, int(chosen), simple_annual_pct


def build_chirp_product_config(daily_interest_rate: float) -> Dict:
    """Base Chirp limits with a chosen daily rate (no total interest cap unless added to config)."""
    cfg = dict(CHIRP_PRODUCT_CONFIG)
    cfg["daily_interest_rate"] = daily_interest_rate
    return cfg
