"""
Scoring configuration for HCSTC Loan Scoring.
Contains scoring weights, thresholds, and decision rules.
"""

# Scoring Configuration
# Maximum possible score is 100
SCORING_CONFIG = {
    # Score ranges and decisions
    # RECALIBRATED: Lowered approval threshold from 70 to 60 based on backtest
    # At threshold 60: 64.8% approval, 4.17% default rate, 87.1% full repayment
    "score_ranges": {
        "approve": {"min": 60, "max": 100, "decision": "APPROVE"},
        "refer": {"min": 40, "max": 59, "decision": "REFER"},
        "decline": {"min": 0, "max": 39, "decision": "DECLINE"},
    },

    # Scoring weights (total = 100)
    # RECALIBRATED based on outcome data analysis - see EFFECTIVENESS_IMPROVEMENTS.md
    "weights": {
        "income_quality": {
            "total": 35,  # INCREASED from 25 - income stability is strongest predictor
            "income_stability": 20,  # INCREASED from 12 - highest outcome correlation (+0.62)
            "income_regularity": 8,
            "income_verification": 5,
            "credit_history_bonus": 2,  # NEW - reward for managed existing debt
        },
        "affordability": {
            "total": 30,  # DECREASED from 45 - disposable income has low predictive power
            "dti_ratio": 12,  # DECREASED from 18
            "disposable_income": 8,  # DECREASED from 15 - near-zero outcome correlation
            "post_loan_affordability": 10,  # DECREASED from 12
        },
        "account_conduct": {
            "total": 25,  # INCREASED from 20
            "failed_payments": 10,  # INCREASED from 8
            "overdraft_usage": 8,  # INCREASED from 7
            "balance_management": 7,  # INCREASED from 5
        },
        "risk_indicators": {
            "total": 10,
            "gambling_activity": 5,
            "hcstc_history": 5,
        },
    },
    
    # Thresholds for scoring
    # RECALIBRATED based on outcome data analysis - see EFFECTIVENESS_IMPROVEMENTS.md
    "thresholds": {
        "dti_ratio": [
            {"max": 30, "points": 12},  # Reduced from 18 - max now 12
            {"max": 40, "points": 10},
            {"max": 50, "points": 8},
            {"max": 60, "points": 5},
            {"max": 70, "points": 2},
            {"max": 100, "points": 0},
        ],

        "disposable_income": [
            {"min": 300, "points": 8},  # Reduced from 15 - max now 8 (low predictor)
            {"min": 200, "points": 6},
            {"min": 100, "points": 4},
            {"min": 50, "points": 2},
            {"min": 0, "points": 0},
        ],

        "income_stability": [
            # INCREASED points - strongest predictor (+0.62 effect)
            # Thresholds aligned with outcome medians (never paid: 58.65, fully repaid: 71.70)
            {"min": 80, "points": 20},  # Excellent stability (max increased from 12 to 20)
            {"min": 70, "points": 16},  # Good (above median for fully repaid)
            {"min": 60, "points": 12},  # Average (between outcome medians)
            {"min": 50, "points": 6},   # Below average
            {"min": 0, "points": 0},    # Poor
        ],

        "gambling_percentage": [
            {"max": 0, "points": 5},
            {"max": 2, "points": 3},
            {"max": 5, "points": 0},
            {"max": 10, "points": -3},
            {"max": 100, "points": -5},
        ],

        # NEW: Credit history bonus thresholds
        # Rewards customers who demonstrate ability to manage existing debt
        "credit_history_bonus": [
            {"min": 200, "points": 2},   # Manages substantial monthly debt payments
            {"min": 100, "points": 1.5}, # Manages moderate debt
            {"min": 50, "points": 1},    # Some credit history
            {"min": 0, "points": 0},     # Thin file - unknown risk
        ],
    },
    
    # Rule configurations - easily toggle between DECLINE and REFER
    "rules": {
        "min_monthly_income": {
            "threshold": 1500,
            "action": "REFER",  # Change to "REFER" to make it a soft rule
            "description": "Minimum monthly income required"
        },
        "no_verifiable_income": {
            "threshold": 300,
            "action": "REFER",
            "description": "No verifiable income source and income below threshold"
        },
        "max_active_hcstc_lenders": {
            "threshold": 20,  # 21+ triggers - effectively disabled for most applications
            # Data shows more HCSTC lenders correlates with BETTER outcomes in this population
            "action": "REFER",
            "lookback_days": 90,
            "description": "Maximum active HCSTC lenders in lookback period"
        },
        "max_gambling_percentage": {
            "threshold": 15,
            "action": "REFER",  # Change to "DECLINE" to make it harder
            "description": "Maximum percentage of income spent on gambling"
        },
        "min_post_loan_disposable": {
            "threshold": -1000,  # Effectively disabled - backtest doesn't apply this
            # Score already accounts for affordability through disposable income points
            "action": "REFER",
            "description": "Minimum disposable income after loan payment"
        },
        "max_failed_payments": {
            "threshold": 5,  # 5+ in 45 days triggers - RAISED to match backtest
            "action": "REFER",
            "lookback_days": 45,
            "description": "Maximum failed payments in lookback period"
        },
        "new_credit_burst": {
            "threshold": 100,  # Effectively disabled - backtest doesn't apply this rule
            "lookback_days": 90,
            "action": "REFER",
            "description": "Excessive new credit providers within recent lookback period"
        },
        "max_dca_count": {
            "threshold":  4,  # 4+ triggers action
            "action": "REFER",  # Change to "REFER" for case-by-case review
            "description": "Maximum distinct debt collection agencies"
        },
        "max_dti_with_new_loan": {
            "threshold": 100,  # RAISED - only trigger for truly unsustainable DTI
            "action": "REFER",
            "description": "Maximum debt-to-income ratio including new loan"
        },
    },

    # Backwards-compatibility alias (some code expects this key)
    "hard_decline_rules": {},

    
    # Loan amount determination by score (thresholds scaled by 1.75x)
    "score_based_limits": [
        {"min_score": 75, "max_amount": 1500, "max_term": 6},
        {"min_score": 65, "max_amount": 1200, "max_term": 6},
        {"min_score": 55, "max_amount": 800,  "max_term": 5},
        {"min_score": 45, "max_amount": 500,  "max_term": 4},
        {"min_score": 35, "max_amount": 300,  "max_term": 3},
        {"min_score": 0,  "max_amount": 0,    "max_term": 0},
    ],

    
    # Mandatory referral rules (not automatic declines)
    "mandatory_referral_rules": {
        "bank_charges_lookback_days": 90,  # Check for bank charges in last 3 months
        "bank_charges_threshold": 2,  # 3+ bank charges triggers referral
        "new_credit_lookback_days": 90,  # Check for new credit providers in last 3 months
        "new_credit_threshold": 5,  # 5+ new credit providers triggers referral
    },
}

# Product Parameters
PRODUCT_CONFIG = {
    "min_loan_amount": 200,
    "max_loan_amount": 1500,
    "available_terms": [3, 4, 5, 6],  # months
    "daily_interest_rate": 0.008,  # 0.8% per day (FCA cap)
    "total_cost_cap": 1.0,  # 100% total cost cap
    "min_disposable_buffer": 50,  # Minimum £50 post-loan disposable
    "max_repayment_to_disposable": 1.0,  # Not included in scoring, just a product rule
    "expense_shock_buffer": 1.1,  # 10% buffer on expenses for resilience assessment
}
