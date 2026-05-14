"""
OpenBanking Engine - Professional HCSTC Loan Scoring System.

A modular, well-organized system for categorizing transactions and scoring
loan applications based on UK consumer banking data.

Main Components:
    - patterns: Transaction categorization patterns
    - config: Scoring configuration and product parameters
    - income: Income detection logic
    - categorisation: Transaction categorization engine
    - scoring: Metrics calculation and scoring engine
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime

# Core categorisation components
from .categorisation.engine import (
    TransactionCategorizer,
    CategoryMatch,
    HCSTC_LENDER_CANONICAL_NAMES,
    HCSTC_LENDER_PATTERNS_SORTED,
)

# Income detection
from .income.income_detector import (
    IncomeDetector,
    RecurringIncomeSource,
)

# Scoring components
from .scoring.feature_builder import (
    MetricsCalculator,
    IncomeMetrics,
    ExpenseMetrics,
    DebtMetrics,
    AffordabilityMetrics,
    BalanceMetrics,
    RiskMetrics,
)

from .scoring.scoring_engine import (
    ScoringEngine,
    Decision,
    RiskLevel,
    ScoreBreakdown,
    ScoringResult,
)

# Configuration
from .config.scoring_config import (
    SCORING_CONFIG,
    PRODUCT_CONFIG,
)

from .patterns.transaction_patterns import (
    INCOME_PATTERNS,
    TRANSFER_PATTERNS,
    DEBT_PATTERNS,
    ESSENTIAL_PATTERNS,
    RISK_PATTERNS,
    POSITIVE_PATTERNS,
)


__version__ = "1.0.0"
__all__ = [
    # Categorisation
    "TransactionCategorizer",
    "CategoryMatch",
    "HCSTC_LENDER_CANONICAL_NAMES",
    "HCSTC_LENDER_PATTERNS_SORTED",
    # Income detection
    "IncomeDetector",
    "RecurringIncomeSource",
    # Scoring
    "MetricsCalculator",
    "IncomeMetrics",
    "ExpenseMetrics",
    "DebtMetrics",
    "AffordabilityMetrics",
    "BalanceMetrics",
    "RiskMetrics",
    "ScoringEngine",
    "Decision",
    "RiskLevel",
    "ScoreBreakdown",
    "ScoringResult",
    # Configuration
    "SCORING_CONFIG",
    "PRODUCT_CONFIG",
    # Patterns
    "INCOME_PATTERNS",
    "TRANSFER_PATTERNS",
    "DEBT_PATTERNS",
    "ESSENTIAL_PATTERNS",
    "RISK_PATTERNS",
    "POSITIVE_PATTERNS",
    # Main function
    "run_open_banking_scoring",
]


def run_open_banking_scoring(
    transactions: List[Dict],
    requested_amount: float,
    requested_term: int,
    days_covered: int = 90,
) -> Dict:
    """
    Main entry point for open banking scoring.
    
    This function orchestrates the complete scoring pipeline:
    1. Categorize all transactions
    2. Calculate financial metrics
    3. Score the loan application
    4. Return decision and recommendations
    
    Args:
        transactions: List of transaction dictionaries with keys:
            - date: Transaction date (string or datetime)
            - amount: Transaction amount (negative=credit, positive=debit)
            - description: Transaction description
            - merchant_name: (Optional) Merchant name
            - plaid_category: (Optional) PLAID detailed category
            - plaid_category_primary: (Optional) PLAID primary category
        requested_amount: Loan amount requested
        requested_term: Loan term in months
        days_covered: Number of days covered by transactions (default 90)
        
    Returns:
        Dictionary containing:
            - decision: "APPROVE", "REFER", or "DECLINE"
            - score: Numerical score (0-175)
            - max_approved_amount: Maximum amount that can be approved
            - max_approved_term: Maximum term that can be approved
            - decline_reasons: List of decline reasons (if declined)
            - referral_reasons: List of referral reasons (if referred)
            - metrics: Financial metrics breakdown
            - score_breakdown: Detailed score breakdown
            - categorized_transactions: List of categorized transactions
    
    Example:
        >>> transactions = [
        ...     {
        ...         "date": "2025-01-15",
        ...         "amount": -2500.0,
        ...         "description": "SALARY FROM ACME LTD",
        ...         "merchant_name": "ACME Ltd",
        ...         "plaid_category": "INCOME_WAGES",
        ...         "plaid_category_primary": "INCOME"
        ...     },
        ...     {
        ...         "date": "2025-01-16",
        ...         "amount": 850.0,
        ...         "description": "RENT TO LANDLORD",
        ...         "merchant_name": "Property Management",
        ...         "plaid_category": "RENT_AND_UTILITIES_RENT",
        ...         "plaid_category_primary": "RENT_AND_UTILITIES"
        ...     }
        ... ]
        >>> result = run_open_banking_scoring(
        ...     transactions=transactions,
        ...     requested_amount=500,
        ...     requested_term=3
        ... )
        >>> print(result["decision"])
        APPROVE
    """
    # Step 1: Categorize transactions
    categorizer = TransactionCategorizer()
    categorized = categorizer.categorize_transactions(transactions)
    category_summary = categorizer.get_category_summary(categorized)
    
    # Step 2: Calculate metrics
    # Prepare accounts list (empty if not provided)
    accounts = []
    
    # Create calculator with automatic month calculation from transactions
    # Use lookback_months=3 (default) for income/expense calculations
    calculator = MetricsCalculator(lookback_months=3, transactions=transactions)
    metrics = calculator.calculate_all_metrics(
        category_summary=category_summary,
        transactions=transactions,
        accounts=accounts,
        loan_amount=requested_amount,
        loan_term=requested_term,
        categorized_transactions=categorized
    )
    
    # Build categorized transaction list for response
    categorized_list = []
    for txn, category_match in categorized:
        categorized_txn = {
            "date": txn.get("date"),
            "amount": txn.get("amount"),
            "description": txn.get("description"),
            "category": category_match.category,
            "subcategory": category_match.subcategory,
            "confidence": category_match.confidence,
            "match_method": category_match.match_method,
            "weight": category_match.weight,
            "is_stable": category_match.is_stable,
            "is_housing": category_match.is_housing,
            "risk_level": category_match.risk_level,
        }
        categorized_list.append(categorized_txn)
    
    # Step 3: Score the application
    scoring_engine = ScoringEngine()
    scoring_result = scoring_engine.score_application(
        metrics=metrics,
        requested_amount=requested_amount,
        requested_term=requested_term
    )
    
    # Step 4: Build response
    result = {
        "decision": scoring_result.decision.value,
        "score": scoring_result.score,
        "max_approved_amount": scoring_result.loan_offer.approved_amount if scoring_result.loan_offer else 0,
        "max_approved_term": scoring_result.loan_offer.approved_term if scoring_result.loan_offer else 0,
        "decline_reasons": scoring_result.decline_reasons,
        "referral_reasons": scoring_result.risk_flags,  # risk_flags contains referral reasons
        "metrics": {
            "income": {
                "total_income": metrics["income"].total_income,
                "monthly_income": metrics["income"].monthly_income,
                "monthly_stable_income": metrics["income"].monthly_stable_income,
                "monthly_gig_income": metrics["income"].monthly_gig_income,
                "effective_monthly_income": metrics["income"].effective_monthly_income,
                "income_stability_score": metrics["income"].income_stability_score,
                "income_regularity_score": metrics["income"].income_regularity_score,
                "has_verifiable_income": metrics["income"].has_verifiable_income,
                "income_sources": metrics["income"].income_sources,
                "monthly_income_breakdown": metrics["income"].monthly_income_breakdown,
            },
            "expense": {
                "monthly_housing": metrics["expenses"].monthly_housing,
                "monthly_council_tax": metrics["expenses"].monthly_council_tax,
                "monthly_utilities": metrics["expenses"].monthly_utilities,
                "monthly_transport": metrics["expenses"].monthly_transport,
                "monthly_groceries": metrics["expenses"].monthly_groceries,
                "monthly_communications": metrics["expenses"].monthly_communications,
                "monthly_insurance": metrics["expenses"].monthly_insurance,
                "monthly_childcare": metrics["expenses"].monthly_childcare,
                "monthly_essential_total": metrics["expenses"].monthly_essential_total,
                "essential_breakdown": metrics["expenses"].essential_breakdown,
            },
            "debt": {
                "monthly_debt_payments": metrics["debt"].monthly_debt_payments,
                "monthly_hcstc_payments": metrics["debt"].monthly_hcstc_payments,
                "active_hcstc_count": metrics["debt"].active_hcstc_count,
                "active_hcstc_count_90d": metrics["debt"].active_hcstc_count_90d,
                "monthly_bnpl_payments": metrics["debt"].monthly_bnpl_payments,
                "monthly_credit_card_payments": metrics["debt"].monthly_credit_card_payments,
                "monthly_other_loan_payments": metrics["debt"].monthly_other_loan_payments,
                "total_debt_commitments": metrics["debt"].total_debt_commitments,
                "debt_breakdown": metrics["debt"].debt_breakdown,
            },
            "affordability": {
                "monthly_disposable": metrics["affordability"].monthly_disposable,
                "debt_to_income_ratio": metrics["affordability"].debt_to_income_ratio,
                "essential_ratio": metrics["affordability"].essential_ratio,
                "disposable_ratio": metrics["affordability"].disposable_ratio,
                "post_loan_disposable": metrics["affordability"].post_loan_disposable,
                "proposed_repayment": metrics["affordability"].proposed_repayment,
                "repayment_to_disposable_ratio": metrics["affordability"].repayment_to_disposable_ratio,
                "is_affordable": metrics["affordability"].is_affordable,
                "max_affordable_amount": metrics["affordability"].max_affordable_amount,
            },
            "balance": {
                "average_balance": metrics["balance"].average_balance,
                "minimum_balance": metrics["balance"].minimum_balance,
                "maximum_balance": metrics["balance"].maximum_balance,
                "days_in_overdraft": metrics["balance"].days_in_overdraft,
                "overdraft_frequency": metrics["balance"].overdraft_frequency,
                "end_of_month_average": metrics["balance"].end_of_month_average,
            },
            "risk": {
                "gambling_total": metrics["risk"].gambling_total,
                "gambling_percentage": metrics["risk"].gambling_percentage,
                "gambling_frequency": metrics["risk"].gambling_frequency,
                "bank_charges_count": metrics["risk"].bank_charges_count,
                "bank_charges_count_90d": metrics["risk"].bank_charges_count_90d,
                "failed_payments_count": metrics["risk"].failed_payments_count,
                "failed_payments_count_45d": metrics["risk"].failed_payments_count_45d,
                "debt_collection_activity": metrics["risk"].debt_collection_activity,
                "debt_collection_distinct": metrics["risk"].debt_collection_distinct,
                "new_credit_providers_90d": metrics["risk"].new_credit_providers_90d,
                "savings_activity": metrics["risk"].savings_activity,
            },
        },
        "score_breakdown": {
            "affordability_score": scoring_result.score_breakdown.affordability_score,
            "affordability_breakdown": scoring_result.score_breakdown.affordability_breakdown,
            "income_quality_score": scoring_result.score_breakdown.income_quality_score,
            "income_breakdown": scoring_result.score_breakdown.income_breakdown,
            "account_conduct_score": scoring_result.score_breakdown.account_conduct_score,
            "conduct_breakdown": scoring_result.score_breakdown.conduct_breakdown,
            "risk_indicators_score": scoring_result.score_breakdown.risk_indicators_score,
            "risk_breakdown": scoring_result.score_breakdown.risk_breakdown,
        },
        "categorized_transactions": categorized_list,
    }
    
    return result
