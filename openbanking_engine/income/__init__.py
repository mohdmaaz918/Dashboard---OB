"""
Income Detection Module for HCSTC Scoring Engine.

Detects income through recurring patterns, payroll keywords, and behavioral analysis.
"""

from .income_detector import IncomeDetector, RecurringIncomeSource

__all__ = [
    "IncomeDetector",
    "RecurringIncomeSource",
]
