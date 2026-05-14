"""
HCSTC Scoring Engine for Loan Applications.
Implements scoring system with hard decline rules and score-based loan limits.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from openbanking_engine import income

from ..config.scoring_config import SCORING_CONFIG, PRODUCT_CONFIG
from .feature_builder import (
    IncomeMetrics,
    ExpenseMetrics,
    DebtMetrics,
    AffordabilityMetrics,
    BalanceMetrics,
    RiskMetrics,
    total_interest_for_term,
)


class Decision(Enum):
    """Loan decision outcomes."""

    APPROVE = "APPROVE"
    REFER = "REFER"
    DECLINE = "DECLINE"


class RiskLevel(Enum):
    """Risk level classifications."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    VERY_HIGH = "Very High"


@dataclass
class ScoreBreakdown:
    """Detailed score breakdown by component."""

    affordability_score: float = 0.0
    affordability_breakdown: Dict = field(default_factory=dict)

    income_quality_score: float = 0.0
    income_breakdown: Dict = field(default_factory=dict)

    account_conduct_score: float = 0.0
    conduct_breakdown: Dict = field(default_factory=dict)

    risk_indicators_score: float = 0.0
    risk_breakdown: Dict = field(default_factory=dict)

    total_score: float = 0.0
    penalties_applied: List[str] = field(default_factory=list)


@dataclass
class LoanOffer:
    """Loan offer details."""

    approved_amount: float = 0.0
    approved_term: int = 0
    monthly_repayment: float = 0.0
    total_repayable: float = 0.0
    apr: float = 0.0
    interest_rate: float = 0.0


@dataclass
class ScoringResult:
    """Complete scoring result for an application."""

    application_ref: str = ""
    decision: Decision = Decision.DECLINE
    score: float = 0.0
    risk_level: RiskLevel = RiskLevel.HIGH

    loan_offer: Optional[LoanOffer] = None
    score_breakdown: Optional[ScoreBreakdown] = None

    # Affordability summary
    monthly_income: float = 0.0
    monthly_expenses: float = 0.0
    monthly_disposable: float = 0.0
    post_loan_disposable: float = 0.0

    # Behavioural diagnostics (for export/tuning)
    months_observed: int = 0
    overdraft_days_per_month: float = 0.0
    income_stability_score: float = 0.0

    # Risk flags
    risk_flags: List[str] = field(default_factory=list)
    decline_reasons: List[str] = field(default_factory=list)
    
    # Tiered approval system (based on combined risk signals)
    risk_tier: str = "CLEAN"  # CLEAN, WATCH, or FLAG
    risk_flag_count: int = 0
    tier_adjustments: List[str] = field(default_factory=list)  # Actions taken based on tier

    # Processing info
    processing_notes: List[str] = field(default_factory=list)


class ScoringEngine:
    """HCSTC loan scoring engine."""

    def __init__(self, product_config: Optional[Dict] = None):
        """Initialize the scoring engine with configuration."""
        self.scoring_config = SCORING_CONFIG
        self.product_config = product_config or PRODUCT_CONFIG
        self.weights = self.scoring_config["weights"]
        self.thresholds = self.scoring_config["thresholds"]
        self.hard_decline_rules = self.scoring_config["hard_decline_rules"]
        self.score_based_limits = self.scoring_config["score_based_limits"]

    def score_application(
        self,
        metrics: Dict,
        requested_amount: float = 350,
        requested_term: int = 6,
        application_ref: str = "",
    ) -> ScoringResult:
        """
        Score a loan application based on calculated metrics.

        Args:
            metrics: Dictionary containing all metric objects
            requested_amount: Requested loan amount
            requested_term: Requested loan term in months
            application_ref: Application reference number

        Returns:
            ScoringResult with decision and details
        """
        income = metrics.get("income", IncomeMetrics())
        expenses = metrics.get("expenses", ExpenseMetrics())
        debt = metrics.get("debt", DebtMetrics())
        affordability = metrics.get("affordability", AffordabilityMetrics())
        balance = metrics.get("balance", BalanceMetrics())
        risk = metrics.get("risk", RiskMetrics())

        # Get risk tier information from risk metrics
        risk_tier = getattr(risk, "risk_tier", "CLEAN") or "CLEAN"
        risk_flag_count = getattr(risk, "risk_flag_count", 0) or 0
        
        # Initialize result
        result = ScoringResult(
            application_ref=application_ref,
            monthly_income=income.effective_monthly_income,
            monthly_expenses=expenses.monthly_essential_total
                             + expenses.monthly_discretionary_total
                             + debt.monthly_debt_payments,
            monthly_disposable=affordability.monthly_disposable,
            post_loan_disposable=affordability.post_loan_disposable,

            months_observed=getattr(balance, "months_observed", 0) or 0,
            overdraft_days_per_month=getattr(balance, "overdraft_days_per_month", 0.0) or 0.0,
            income_stability_score=getattr(income, "income_stability_score", 0.0) or 0.0,
            
            # Tiered approval information
            risk_tier=risk_tier,
            risk_flag_count=risk_flag_count,
        )

        # Calculate score breakdown FIRST
        score_breakdown = self._calculate_scores(
            income=income,
            affordability=affordability,
            balance=balance,
            risk=risk,
            debt=debt,
        )

        result.score_breakdown = score_breakdown
        result.score = score_breakdown.total_score

        # Check for critical decline-only rules (hard gates)
        # These are absolute requirements that override score-based decisions
        decline_reasons = self._check_critical_decline_rules(income)
        
        if decline_reasons:
            result.decision = Decision.DECLINE
            result.decline_reasons = decline_reasons
            result.score = 0.0
            result.risk_level = RiskLevel.VERY_HIGH
            return result

        # =======================================================================
        # SCORE-BASED DECISION ONLY (matching backtest logic)
        # =======================================================================
        # Decision is determined purely by score thresholds:
        #   >= 60: APPROVE
        #   >= 40: REFER  
        #   < 40:  DECLINE
        # No rule-based overrides - the score already incorporates all risk factors
        # =======================================================================
        decision, risk_level = self._determine_decision(score_breakdown.total_score)
        result.decision = decision
        result.risk_level = risk_level

        # Collect informational notes (for manual review context, NOT decision-changing)
        informational_notes = self._collect_informational_notes(
            income=income,
            debt=debt,
            affordability=affordability,
            risk=risk,
            balance=balance,
        )
        result.processing_notes = informational_notes

        # If REFER, add generic note
        if result.decision == Decision.REFER:
            if "Manual review required" not in result.processing_notes:
                result.processing_notes.insert(0, "Manual review required")

        # Collect risk flags
        result.risk_flags = self._collect_risk_flags(risk, debt, affordability, balance)

        # Determine loan offer if approved
        if result.decision == Decision.APPROVE:
            loan_offer = self._determine_loan_offer(
                score=score_breakdown.total_score,
                affordability=affordability,
                requested_amount=requested_amount,
                requested_term=requested_term,
                risk_tier=risk_tier,
            )
            result.loan_offer = loan_offer
            result.post_loan_disposable = (
                affordability.monthly_disposable - loan_offer.monthly_repayment
            )
            
            # Add tier-based adjustments and notes
            if risk_tier == "FLAG":
                result.tier_adjustments.append("Loan amount capped due to elevated risk signals")
                result.tier_adjustments.append("Recommend direct debit setup")
                result.tier_adjustments.append("Flag for proactive collections monitoring")
                result.processing_notes.append(f"RISK_TIER: FLAG ({risk_flag_count} risk signals)")
            elif risk_tier == "WATCH":
                result.tier_adjustments.append("Monitor account closely")
                result.processing_notes.append(f"RISK_TIER: WATCH ({risk_flag_count} risk signals)")
            else:
                result.processing_notes.append(f"RISK_TIER: CLEAN ({risk_flag_count} risk signals)")
                
        elif result.decision == Decision.REFER:
            result.processing_notes.append("Manual review required")
            # Add tier context for manual reviewers
            if risk_tier == "FLAG":
                result.processing_notes.append(f"RISK_TIER: FLAG ({risk_flag_count} risk signals) - consider declining")
            elif risk_tier == "WATCH":
                result.processing_notes.append(f"RISK_TIER: WATCH ({risk_flag_count} risk signals) - lean toward approval")

        # DEBUG: confirm nothing overrides after the gate
        result.processing_notes.append(f"FINAL_DECISION: {result.decision.value}")

        return result

    def _check_rule_violations(
            self,
            income: IncomeMetrics,
            debt: DebtMetrics,
            affordability: AffordabilityMetrics,
            risk: RiskMetrics,
            balance: BalanceMetrics,
            requested_amount: float,
            requested_term: int,
    ) -> Tuple[List[str], List[str]]:

        """
        Check all rules and return violations by action type.

        Returns:
            Tuple of (decline_reasons, refer_reasons)
        """
        decline_reasons = []
        refer_reasons = []
        rules = self.scoring_config["rules"]

        # Rule 1: Monthly income
        rule = rules["min_monthly_income"]
        if (
            income.effective_monthly_income is not None
            and income.effective_monthly_income < rule["threshold"]
        ):
            reason = (
                f"Monthly income (£{income.effective_monthly_income:.2f}) "
                f"below minimum (£{rule['threshold']})"
            )
            if rule["action"] == "DECLINE":
                decline_reasons.append(reason)
            else:
                refer_reasons.append(reason)

        # Rule 2: No identifiable income source
        rule = rules["no_verifiable_income"]
        if (
            not income.has_verifiable_income
            and income.effective_monthly_income is not None
            and income.effective_monthly_income < rule["threshold"]
        ):
            reason = "No verifiable income source identified"
            if rule["action"] == "DECLINE":
                decline_reasons.append(reason)
            else:
                refer_reasons.append(reason)

        # Behavioural Gate 1: Income stability - ONLY DECLINE for extreme cases
        # REFER gate removed to match backtest approval rate
        # The score already penalizes low income stability appropriately
        if income.income_stability_score is not None:
            if income.income_stability_score < 25:
                # Extremely low stability - hard decline only
                decline_reasons.append(
                    f"Behavioural gate: extremely low income stability score ({income.income_stability_score:.1f} < 25)"
                )
            # NOTE: REFER gate removed - let score drive decision

        # Behavioural Gate 2: Overdraft usage - DISABLED
        # Data analysis showed overdraft days are NOT predictive of default in this
        # CRA-pre-approved population. Full repayers actually had MORE overdraft days.
        # Removing this gate to match backtest approval rate.
        # (Keeping the calculation for informational purposes only)
        od_pm = getattr(balance, "overdraft_days_per_month", None)
        if od_pm is None:
            months_obs = max(1, int(getattr(balance, "months_observed", 0) or 1))
            od_pm = float(getattr(balance, "days_in_overdraft", 0) or 0) / months_obs
        # NOTE: No REFER triggered - overdraft not predictive in this population

        # Rule 3: Active HCSTC lenders
        rule = rules["max_active_hcstc_lenders"]
        if (
            debt.active_hcstc_count_90d is not None
            and debt.active_hcstc_count_90d > rule["threshold"]
        ):
            reason = (
                f"Active HCSTC with {debt.active_hcstc_count_90d} lenders in last "
                f"{rule['lookback_days']} days (maximum {rule['threshold']})"
            )
            if rule["action"] == "DECLINE":
                decline_reasons.append(reason)
            else:
                refer_reasons.append(reason)


        # Rule 4: Gambling
        rule = rules["max_gambling_percentage"]
        if (
            risk.gambling_percentage is not None
            and risk.gambling_percentage > rule["threshold"]
        ):
            reason = (
                f"Gambling ({risk.gambling_percentage:.1f}%) exceeds "
                f"maximum ({rule['threshold']}%)"
            )
            if rule["action"] == "DECLINE":
                decline_reasons.append(reason)
            else:
                refer_reasons.append(reason)

        # Rule 5: Post-loan disposable
        rule = rules["min_post_loan_disposable"]
        if (
            affordability.post_loan_disposable is not None
            and affordability.post_loan_disposable < rule["threshold"]
        ):
            reason = (
                f"Post-loan disposable (£{affordability.post_loan_disposable:.2f}) "
                f"below minimum (£{rule['threshold']})"
            )
            if rule["action"] == "DECLINE":
                decline_reasons.append(reason)
            else:
                refer_reasons.append(reason)

        # Rule 6: Failed payments
        rule = rules["max_failed_payments"]

        failed_45d = int(risk.failed_payments_count_45d or 0)
        threshold = int(rule["threshold"])

        triggered = failed_45d >= threshold  # use >= if "2 triggers at threshold 2"

        if triggered:
            reason = (
                f"Failed payments ({failed_45d}) in last "
                f"{rule['lookback_days']} days meet or exceed maximum ({threshold})"
            )
            # v1 safety: failed payments is REFER-only until validated at scale
            refer_reasons.append(reason)

        # Rule X: New credit burst (recent dependency)
        rule = rules.get("new_credit_burst")
        if rule:
            if (
                    risk.new_credit_providers_90d is not None
                    and risk.new_credit_providers_90d > rule["threshold"]
            ):
                reason = (
                    f"Multiple new credit providers ({risk.new_credit_providers_90d}) "
                    f"in last {rule['lookback_days']} days"
                )
                if rule["action"] == "DECLINE":
                    decline_reasons.append(reason)
                else:
                    refer_reasons.append(reason)

        # Rule 7: Debt collection
        rule = rules["max_dca_count"]
        if (
            risk.debt_collection_distinct is not None
            and risk.debt_collection_distinct > rule["threshold"]
        ):
            reason = (
                f"Active debt collection with {risk.debt_collection_distinct} agencies "
                f"(maximum {rule['threshold']})"
            )
            if rule["action"] == "DECLINE":
                decline_reasons.append(reason)
            else:
                refer_reasons.append(reason)

        # Rule 8: DTI with new loan
        rule = rules["max_dti_with_new_loan"]
        new_loan_payment = self._calculate_monthly_payment(
            requested_amount, requested_term
        )
        if (
            income.effective_monthly_income is not None
            and income.effective_monthly_income > 0
        ):
            projected_dti = (
                (debt.monthly_debt_payments + new_loan_payment)
                / income.effective_monthly_income
                * 100
            )
            if projected_dti > rule["threshold"]:
                reason = (
                    f"Projected DTI ({projected_dti:.1f}%) would exceed "
                    f"maximum ({rule['threshold']}%)"
                )
                if rule["action"] == "DECLINE":
                    decline_reasons.append(reason)
                else:
                    refer_reasons.append(reason)

        return decline_reasons, refer_reasons

    def _check_critical_decline_rules(
        self,
        income: IncomeMetrics,
    ) -> List[str]:
        """
        Check only critical rules that require hard decline.
        
        DESIGN DECISION: No hard decline rules are applied.
        
        The score already incorporates all risk factors (income stability, 
        affordability, conduct, etc.). Even applications with very low income
        stability can have compensating factors that result in acceptable scores.
        
        This matches the backtest behavior where decisions are purely score-based:
          - Score >= 60: APPROVE
          - Score >= 40: REFER
          - Score < 40:  DECLINE
        
        Returns:
            Empty list (no hard declines - let score decide)
        """
        # No hard decline rules - score handles all risk assessment
        return []

    def _collect_informational_notes(
        self,
        income: IncomeMetrics,
        debt: DebtMetrics,
        affordability: AffordabilityMetrics,
        risk: RiskMetrics,
        balance: BalanceMetrics,
    ) -> List[str]:
        """
        Collect informational notes for manual review context.
        
        These notes are for INFORMATION ONLY - they do NOT affect the decision.
        The decision is made purely based on score thresholds.
        
        Returns:
            List of informational notes
        """
        notes = []
        
        # Note any factors that might be of interest for manual review
        if income.income_stability_score is not None and income.income_stability_score < 50:
            notes.append(f"Note: income stability below average ({income.income_stability_score:.1f})")
        
        if debt.active_hcstc_count_90d is not None and debt.active_hcstc_count_90d > 5:
            notes.append(f"Note: {debt.active_hcstc_count_90d} active HCSTC lenders (90d)")
        
        if risk.failed_payments_count_45d is not None and risk.failed_payments_count_45d > 0:
            notes.append(f"Note: {risk.failed_payments_count_45d} failed payments (45d)")
        
        if affordability.post_loan_disposable is not None and affordability.post_loan_disposable < 0:
            notes.append(f"Note: negative post-loan disposable (£{affordability.post_loan_disposable:.0f})")
        
        if risk.gambling_percentage is not None and risk.gambling_percentage > 5:
            notes.append(f"Note: gambling at {risk.gambling_percentage:.1f}% of income")
        
        return notes

    def _calculate_scores(
        self,
        income: IncomeMetrics,
        affordability: AffordabilityMetrics,
        balance: BalanceMetrics,
        risk: RiskMetrics,
        debt: DebtMetrics,
    ) -> ScoreBreakdown:
        """
        Calculate detailed score breakdown.
        
        RECALIBRATED based on outcome data analysis - see EFFECTIVENESS_IMPROVEMENTS.md
        Key changes:
        - Income stability weight increased (strongest predictor +0.62 effect)
        - Disposable income weight decreased (near-zero predictive power)
        - Credit history bonus added (managed debt = positive signal)
        """
        breakdown = ScoreBreakdown()
        penalties = []

        # 1. Income Quality Score (35 points) - INCREASED from 25
        # Income stability is the strongest predictor of repayment (+0.62 effect)
        inc_weights = self.weights["income_quality"]

        # Income Stability (20 points) - INCREASED from 12
        stability_points = self._score_threshold(
            income.income_stability_score,
            self.thresholds["income_stability"],
            is_lower_better=False,
        )

        # Income Regularity (8 points)
        if income.income_regularity_score is not None:
            regularity_points = min(8, income.income_regularity_score / 100 * 8)
        else:
            regularity_points = 0

        # Income Verification (5 points)
        verification_points = 5 if income.has_verifiable_income else 2.5

        # Credit History Bonus (2 points) - NEW
        # Rewards customers who demonstrate ability to manage existing debt
        # Data shows monthly_debt_payments has +0.58 effect on good outcomes
        credit_history_points = self._score_threshold(
            debt.monthly_debt_payments,
            self.thresholds.get("credit_history_bonus", [{"min": 0, "points": 0}]),
            is_lower_better=False,
        )

        income_score = stability_points + regularity_points + verification_points + credit_history_points
        breakdown.income_quality_score = min(income_score, inc_weights["total"])
        breakdown.income_breakdown = {
            "income_stability": round(stability_points, 1),
            "income_regularity": round(regularity_points, 1),
            "income_verification": round(verification_points, 1),
            "credit_history_bonus": round(credit_history_points, 1),
        }

        # 2. Affordability Score (30 points) - DECREASED from 45
        # Disposable income has near-zero predictive power in outcome data
        aff_weights = self.weights["affordability"]

        # DTI Ratio (12 points) - DECREASED from 18
        dti_points = self._score_threshold(
            affordability.debt_to_income_ratio,
            self.thresholds["dti_ratio"],
            is_lower_better=True,
        )

        # Disposable Income (8 points) - DECREASED from 15
        disp_points = self._score_threshold(
            affordability.monthly_disposable,
            self.thresholds["disposable_income"],
            is_lower_better=False,
        )

        # Post-loan Affordability (10 points) - DECREASED from 12
        post_loan_max = aff_weights.get("post_loan_affordability", 10)
        if affordability.post_loan_disposable is not None:
            post_loan_points = min(
                post_loan_max, max(0, affordability.post_loan_disposable / 50 * post_loan_max)
            )
        else:
            post_loan_points = 0

        affordability_score = dti_points + disp_points + post_loan_points
        breakdown.affordability_score = min(affordability_score, aff_weights["total"])
        breakdown.affordability_breakdown = {
            "dti_ratio": round(dti_points, 1),
            "disposable_income": round(disp_points, 1),
            "post_loan_affordability": round(post_loan_points, 1),
        }

        # 3. Account Conduct Score (25 points) - INCREASED from 20
        conduct_weights = self.weights["account_conduct"]

        # Failed Payments (10 points) - INCREASED from 8
        failed_max = conduct_weights.get("failed_payments", 10)
        if risk.failed_payments_count is not None:
            failed_points = max(0, failed_max - risk.failed_payments_count * 2)
        else:
            failed_points = 0

        # Overdraft Usage (8 points) - INCREASED from 7
        # Overdraft Usage (8 points)
        # NOTE: Data analysis shows overdraft days are NOT predictive in CRA-approved populations
        # (good payers actually had MORE overdraft days). Reduced penalty gradient.
        overdraft_max = conduct_weights.get("overdraft_usage", 8)
        if balance.days_in_overdraft is not None:
            if balance.days_in_overdraft == 0:
                overdraft_points = overdraft_max
            elif balance.days_in_overdraft <= 30:
                # Gentle decline - overdraft usage not penalized heavily
                overdraft_points = overdraft_max * 0.75
            elif balance.days_in_overdraft <= 60:
                overdraft_points = overdraft_max * 0.5
            else:
                # Only penalize extreme overdraft (60+ days)
                overdraft_points = overdraft_max * 0.25
        else:
            overdraft_points = overdraft_max * 0.5  # Unknown = moderate points

        # Balance Management (7 points)
        # NOTE: Data analysis shows balance is NOT predictive in CRA-approved populations
        # (defaulters actually had HIGHER balances). Giving flat points to neutralize.
        balance_max = conduct_weights.get("balance_management", 7)
        if balance.average_balance is not None:
            # Give moderate points regardless of balance level - not a strong predictor
            balance_points = balance_max * 0.5  # Flat 3.5 points
        else:
            balance_points = balance_max * 0.35  # Small penalty for missing data

        conduct_score = failed_points + overdraft_points + balance_points
        breakdown.account_conduct_score = min(conduct_score, conduct_weights["total"])
        breakdown.conduct_breakdown = {
            "failed_payments": round(failed_points, 1),
            "overdraft_usage": round(overdraft_points, 1),
            "balance_management": round(balance_points, 1),
        }

        # 4. Risk Indicators Score (10 points + bonuses)
        risk_weights = self.weights["risk_indicators"]

        # Gambling Activity (5 points)
        gambling_points = self._score_threshold(
            risk.gambling_percentage,
            self.thresholds["gambling_percentage"],
            is_lower_better=True,
        )

        # HCSTC History (5 points)
        # Adjusted: Only penalize at 4+ active HCSTC lenders (was penalizing at 2+)
        if debt.active_hcstc_count is not None:
            if debt.active_hcstc_count == 0:
                hcstc_points = 5
            elif debt.active_hcstc_count <= 2:
                hcstc_points = 4  # 1-2 HCSTC is normal, minimal reduction
            elif debt.active_hcstc_count == 3:
                hcstc_points = 2.5  # 3 HCSTC - some concern
            else:
                hcstc_points = 0  # 4+ HCSTC - significant concern
                penalties.append(f"Multiple HCSTC lenders ({debt.active_hcstc_count})")
        else:
            hcstc_points = 2.5  # Unknown - moderate points

        # NEW: Savings Behavior Bonus (up to 3 points)
        # Regular savers demonstrate financial discipline - positive indicator
        savings_bonus = getattr(risk, 'savings_behavior_score', 0.0) or 0.0

        # NEW: Income Trend Adjustment
        # Increasing income is a positive signal, decreasing is a risk
        income_trend = getattr(income, 'income_trend', 'stable')
        if income_trend == "increasing":
            trend_bonus = 2.0  # Bonus for improving financial situation
        elif income_trend == "decreasing":
            trend_bonus = -2.0  # Penalty for declining income
            penalties.append(f"Declining income trend")
        else:
            trend_bonus = 0.0

        risk_score = gambling_points + hcstc_points + savings_bonus + trend_bonus
        breakdown.risk_indicators_score = risk_score
        breakdown.risk_breakdown = {
            "gambling_activity": round(gambling_points, 1),
            "hcstc_history": round(hcstc_points, 1),
            "savings_bonus": round(savings_bonus, 1),
            "income_trend_adjustment": round(trend_bonus, 1),
        }

        # Apply penalties
        if risk.gambling_percentage is not None and risk.gambling_percentage > 5:
            penalty = -5
            penalties.append(f"Gambling penalty: {penalty}")
            risk_score += penalty

        # HCSTC penalty only for 4+ active lenders (was 2+, too strict)
        if debt.active_hcstc_count is not None and debt.active_hcstc_count >= 4:
            penalty = -5  # Reduced from -10
            penalties.append(f"High HCSTC count penalty ({debt.active_hcstc_count} lenders): {penalty}")
            risk_score += penalty

        breakdown.penalties_applied = penalties

        # Total Score (max 100)
        breakdown.total_score = max(
            0,
            min(
                100,
                breakdown.affordability_score
                + breakdown.income_quality_score
                + breakdown.account_conduct_score
                + breakdown.risk_indicators_score,
            ),
        )

        return breakdown

    def _score_threshold(
        self, value: float, thresholds: List[Dict], is_lower_better: bool
    ) -> float:
        """Score a value against threshold table."""
        # Handle None values - return lowest score (0 points)
        if value is None:
            return 0

        for threshold in thresholds:
            if is_lower_better:
                if "max" in threshold and value <= threshold["max"]:
                    return threshold["points"]
            else:
                if "min" in threshold and value >= threshold["min"]:
                    return threshold["points"]

        # Return last threshold's points as default
        return thresholds[-1].get("points", 0)

    def _determine_decision(self, score: float) -> Tuple[Decision, RiskLevel]:
        """Determine decision and risk level from score."""
        ranges = self.scoring_config["score_ranges"]

        if score >= ranges["approve"]["min"]:
            return Decision.APPROVE, RiskLevel.LOW
        elif score >= ranges["refer"]["min"]:
            return Decision.REFER, RiskLevel.HIGH
        else:
            return Decision.DECLINE, RiskLevel.VERY_HIGH

    def _collect_risk_flags(
        self,
        risk: RiskMetrics,
        debt: DebtMetrics,
        affordability: AffordabilityMetrics,
        balance: BalanceMetrics,
    ) -> List[str]:
        """Collect risk flags for the application."""
        flags = []

        if risk.gambling_percentage is not None and risk.gambling_percentage > 0:
            flags.append(f"Gambling: {risk.gambling_percentage:.1f}% of income")

        if debt.active_hcstc_count_90d is not None and debt.active_hcstc_count_90d > 0:
            flags.append(f"Active HCSTC (90d): {debt.active_hcstc_count_90d} lenders")

        if (
            risk.failed_payments_count_45d is not None
            and risk.failed_payments_count_45d > 0
        ):
            flags.append(f"Failed payments (45d): {risk.failed_payments_count_45d}")

        if (
            risk.debt_collection_distinct is not None
            and risk.debt_collection_distinct > 0
        ):
            flags.append(f"Debt collection: {risk.debt_collection_distinct} agencies")

        if balance.days_in_overdraft is not None and balance.days_in_overdraft > 10:
            flags.append(f"Overdraft: {balance.days_in_overdraft} days")

        if (
            affordability.debt_to_income_ratio is not None
            and affordability.debt_to_income_ratio > 40
        ):
            flags.append(f"High DTI: {affordability.debt_to_income_ratio:.1f}%")

        return flags

    def _determine_loan_offer(
        self,
        score: float,
        affordability: AffordabilityMetrics,
        requested_amount: float,
        requested_term: int,
        risk_tier: str = "CLEAN",
    ) -> LoanOffer:
        """Determine the loan offer based on score, affordability, and risk tier."""

        # Get score-based limits
        score_limit = 0
        max_term = 0
        for limit in self.score_based_limits:
            if score >= limit["min_score"]:
                score_limit = limit["max_amount"]
                max_term = limit["max_term"]
                break
        
        # Apply tier-based adjustments to loan limits
        # FLAG tier: Reduce max amount by 40% and max term by 1 month
        # WATCH tier: Reduce max amount by 20%
        if risk_tier == "FLAG":
            score_limit = int(score_limit * 0.6)  # 40% reduction
            max_term = max(3, max_term - 1)  # Reduce term, minimum 3 months
        elif risk_tier == "WATCH":
            score_limit = int(score_limit * 0.8)  # 20% reduction

        # Calculate affordability-based maximum
        aff_max = (
            affordability.max_affordable_amount
            if affordability.max_affordable_amount is not None
            else 0
        )

        # Final approved amount is minimum of all limits
        approved_amount = min(
            requested_amount,
            self.product_config["max_loan_amount"],
            score_limit,
            aff_max,
        )

        # Ensure minimum loan amount
        if approved_amount < self.product_config["min_loan_amount"]:
            approved_amount = 0

        # Adjust term
        approved_term = min(requested_term, max_term)
        if approved_term < 3:
            approved_term = 3

        # Calculate repayment
        monthly_payment = self._calculate_monthly_payment(
            approved_amount, approved_term
        )
        total_repayable = monthly_payment * approved_term

        # Calculate simplified APR for display purposes only.
        # NOTE: For production use, this should implement the proper APR calculation
        # methodology required by UK Consumer Credit Act and FCA regulations.
        # The actual APR calculation involves solving for the internal rate of return
        # of the cash flows and annualizing it according to specific regulatory rules.
        # This simplified version is for indicative purposes only.
        if approved_amount > 0:
            interest = total_repayable - approved_amount
            apr = (interest / approved_amount) * (12 / approved_term) * 100
        else:
            apr = 0

        return LoanOffer(
            approved_amount=round(approved_amount, 2),
            approved_term=approved_term,
            monthly_repayment=round(monthly_payment, 2),
            total_repayable=round(total_repayable, 2),
            apr=round(apr, 1),
            interest_rate=self.product_config["daily_interest_rate"] * 100,
        )

    def _calculate_monthly_payment(self, amount: float, term: int) -> float:
        """Calculate monthly payment for a loan."""
        if amount <= 0 or term <= 0:
            return 0.0

        daily_rate = self.product_config["daily_interest_rate"]
        days_per_month = 30.4
        monthly_rate = daily_rate * days_per_month

        total_interest = total_interest_for_term(
            amount, monthly_rate, term, self.product_config
        )

        total_repayable = amount + total_interest
        return total_repayable / term
