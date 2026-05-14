"""
Scoring Module for HCSTC Loan Applications.

Contains feature aggregation from categorised transactions and scoring logic.
"""

# Import from feature_builder (metrics_calculator)
from .feature_builder import (
    IncomeMetrics,
    ExpenseMetrics,
    DebtMetrics,
    AffordabilityMetrics,
    BalanceMetrics,
    RiskMetrics,
    MetricsCalculator,
)

# Import from scoring_engine
from .scoring_engine import (
    Decision,
    RiskLevel,
    ScoreBreakdown,
    LoanOffer,
    ScoringResult,
    ScoringEngine,
)

__all__ = [
    # Feature builder exports
    "IncomeMetrics",
    "ExpenseMetrics",
    "DebtMetrics",
    "AffordabilityMetrics",
    "BalanceMetrics",
    "RiskMetrics",
    "MetricsCalculator",
    # Scoring engine exports
    "Decision",
    "RiskLevel",
    "ScoreBreakdown",
    "LoanOffer",
    "ScoringResult",
    "ScoringEngine",
]
