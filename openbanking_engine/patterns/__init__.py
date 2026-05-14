"""
Transaction Pattern Definitions for HCSTC Scoring Engine.

Contains all keyword and regex patterns for categorizing transactions into:
- Income types (salary, benefits, pension, gig economy, loans)
- Transfer patterns (internal transfers)
- Debt categories (HCSTC, loans, credit cards, BNPL, catalogue)
- Essential expenses (rent, mortgage, utilities, transport, etc.)
- Risk indicators (gambling, bank charges, failed payments, debt collection)
- Positive indicators (savings activity)
"""

from .transaction_patterns import (
    INCOME_PATTERNS,
    TRANSFER_PATTERNS,
    DEBT_PATTERNS,
    ESSENTIAL_PATTERNS,
    RISK_PATTERNS,
    POSITIVE_PATTERNS,
)

__all__ = [
    "INCOME_PATTERNS",
    "TRANSFER_PATTERNS",
    "DEBT_PATTERNS",
    "ESSENTIAL_PATTERNS",
    "RISK_PATTERNS",
    "POSITIVE_PATTERNS",
]
