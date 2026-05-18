"""
Chirp-only wrapper around the openbanking_engine scoring pipeline.

Duplicates the orchestration in openbanking_engine.run_open_banking_scoring so we can
also return ScoringResult for dashboard DataFrames — without modifying UK app code.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

from openbanking_engine import (
    MetricsCalculator,
    ScoringEngine,
    TransactionCategorizer,
)
from openbanking_engine.scoring.scoring_engine import ScoringResult

from chirp_product_config import CHIRP_PRODUCT_CONFIG

# Initialised once at import time — avoids re-loading patterns on every request
_categorizer = TransactionCategorizer()


def _chirp_label_match_method(match_method: str) -> str:
    """Engine labels match_method as plaid_*; Chirp data is mapped synthetically, not live Plaid."""
    if not match_method:
        return match_method
    s = str(match_method)
    s = re.sub(r"(?i)plaid_strict", "chirp_mapped_strict", s)
    s = re.sub(r"(?i)plaid_", "chirp_", s)
    s = re.sub(r"(?i)plaid", "chirp", s)
    return s


def run_chirp_scoring_pipeline(
    transactions: List[Dict],
    requested_amount: float,
    requested_term: int,
    days_covered: int = 90,
    product_config: Optional[Dict] = None,
    *,
    lookback_months: int = 3,
) -> Tuple[Dict, ScoringResult]:
    """
    Same behaviour as openbanking_engine.run_open_banking_scoring, plus ScoringResult.

    `days_covered` is accepted for API parity; the core engine currently uses
    transaction-derived lookbacks (same as run_open_banking_scoring).

    `lookback_months` controls income/expense windowing in MetricsCalculator (1–12 typical).
    """
    del days_covered  # unused, matches public API of run_open_banking_scoring

    cfg = product_config if product_config is not None else CHIRP_PRODUCT_CONFIG
    lb = max(1, min(12, int(lookback_months)))

    categorized = _categorizer.categorize_transactions_batch(transactions)
    category_summary = _categorizer.get_category_summary(categorized)

    accounts: List[Dict] = []
    calculator = MetricsCalculator(
        lookback_months=lb,
        transactions=transactions,
        product_config=cfg,
    )
    metrics = calculator.calculate_all_metrics(
        category_summary=category_summary,
        transactions=transactions,
        accounts=accounts,
        loan_amount=requested_amount,
        loan_term=requested_term,
        categorized_transactions=categorized,
    )

    categorized_list = []
    for txn, category_match in categorized:
        categorized_list.append(
            {
                "date": txn.get("date"),
                "amount": txn.get("amount"),
                "description": txn.get("description"),
                "category": category_match.category,
                "subcategory": category_match.subcategory,
                "confidence": category_match.confidence,
                "match_method": _chirp_label_match_method(category_match.match_method),
                "weight": category_match.weight,
                "is_stable": category_match.is_stable,
                "is_housing": category_match.is_housing,
                "risk_level": category_match.risk_level,
            }
        )

    scoring_engine = ScoringEngine(product_config=cfg)
    scoring_result = scoring_engine.score_application(
        metrics=metrics,
        requested_amount=requested_amount,
        requested_term=requested_term,
    )

    result = {
        "lookback_months": lb,
        "decision": scoring_result.decision.value,
        "score": scoring_result.score,
        "max_approved_amount": scoring_result.loan_offer.approved_amount
        if scoring_result.loan_offer
        else 0,
        "max_approved_term": scoring_result.loan_offer.approved_term
        if scoring_result.loan_offer
        else 0,
        "decline_reasons": scoring_result.decline_reasons,
        "referral_reasons": scoring_result.risk_flags,
        "risk_level": scoring_result.risk_level.value,
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

    return result, scoring_result


def scoring_result_to_row(
    result: ScoringResult,
    application_ref: str,
) -> Dict:
    """One ScoringResult -> row dict aligned with hcstc_batch_processor.results_to_dataframe."""
    default_offer = {
        "approved_amount": 0,
        "approved_term": 0,
        "monthly_repayment": 0,
        "total_repayable": 0,
    }
    if result.loan_offer:
        offer_data = {
            "approved_amount": result.loan_offer.approved_amount,
            "approved_term": result.loan_offer.approved_term,
            "monthly_repayment": result.loan_offer.monthly_repayment,
            "total_repayable": result.loan_offer.total_repayable,
        }
    else:
        offer_data = default_offer

    row: Dict = {
        "Application Ref": application_ref,
        "Decision": result.decision.value,
        "Score": result.score,
        "Risk Level": result.risk_level.value,
        "Approved Amount": offer_data["approved_amount"],
        "Approved Term": offer_data["approved_term"],
        "Monthly Repayment": offer_data["monthly_repayment"],
        "Total Repayable": offer_data["total_repayable"],
        "Monthly Income": round(result.monthly_income, 2),
        "Monthly Expenses": round(result.monthly_expenses, 2),
        "Monthly Disposable": round(result.monthly_disposable, 2),
        "Post-Loan Disposable": round(result.post_loan_disposable, 2),
        "Months Observed": getattr(result, "months_observed", None),
        "Overdraft Days per Month": getattr(result, "overdraft_days_per_month", None),
        "Income Stability Score": getattr(result, "income_stability_score", None),
        "Risk Flags": "; ".join(result.risk_flags) if result.risk_flags else "",
        "Decline Reasons": "; ".join(result.decline_reasons) if result.decline_reasons else "",
        "Refer Reasons": "; ".join(result.processing_notes) if result.processing_notes else "",
    }

    if result.score_breakdown:
        row["Affordability Score"] = result.score_breakdown.affordability_score
        row["Income Quality Score"] = result.score_breakdown.income_quality_score
        row["Account Conduct Score"] = result.score_breakdown.account_conduct_score
        row["Risk Indicators Score"] = result.score_breakdown.risk_indicators_score

    return row


def rows_to_dataframe(rows: List[Dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)
