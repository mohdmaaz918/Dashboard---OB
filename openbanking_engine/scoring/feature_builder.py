"""
Financial Metrics Calculator for HCSTC Loan Scoring.
Calculates income, expense, debt, affordability, and risk metrics.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import statistics
import logging
from unicodedata import category

from openbanking_engine.categorisation.engine import CategoryMatch

from ..config.scoring_config import PRODUCT_CONFIG

# Initialize logger for this module
logger = logging.getLogger(__name__)


def total_interest_for_term(
    principal: float,
    monthly_rate: float,
    term_months: int,
    product_config: Dict,
) -> float:
    """
    Simple interest accrual: principal × monthly_rate × term.

    If ``product_config`` includes ``total_cost_cap`` (multiplier of principal, e.g. 1.0 = 100%),
    interest is capped at ``principal * total_cost_cap``. If the key is omitted or ``None``,
    there is no cap (Chirp US demo).
    """
    uncapped = principal * monthly_rate * term_months
    cap_mult = product_config.get("total_cost_cap")
    if cap_mult is None:
        return uncapped
    return min(uncapped, principal * float(cap_mult))


# NOTE: Debug logging should be configured at the application level, not here
# To enable debug logging, configure it in your application's entry point:
#   logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


@dataclass
class IncomeMetrics:
    """Income-related metrics."""

    total_income: float = 0.0
    monthly_income: float = 0.0
    monthly_stable_income: float = 0.0  # Salary + Benefits + Pension
    monthly_gig_income: float = 0.0
    effective_monthly_income: float = 0.0  # Stable + (Gig * 1.0)
    income_stability_score: float = 0.0  # 0-100
    income_regularity_score: float = 0.0  # 0-100
    has_verifiable_income: bool = False
    income_sources: List[str] = field(default_factory=list)
    monthly_income_breakdown: Dict = field(default_factory=dict)
    
    # NEW: Income trend analysis
    income_trend: str = "stable"  # "increasing", "stable", "decreasing"
    income_trend_pct: float = 0.0  # Percentage change


@dataclass
class ExpenseMetrics:
    """Expense-related metrics."""

    monthly_housing: float = 0.0  # Rent OR Mortgage
    monthly_council_tax: float = 0.0
    monthly_utilities: float = 0.0
    monthly_transport: float = 0.0
    monthly_groceries: float = 0.0
    monthly_communications: float = 0.0
    monthly_insurance: float = 0.0
    monthly_childcare: float = 0.0

    # Split totals
    monthly_essential_total: float = 0.0
    monthly_discretionary_total: float = 0.0
    monthly_total_spend: float = 0.0

    # Optional: current month-to-date spend trend (not included in the base averages)
    mtd_total_spend: float = 0.0
    mtd_spend_vs_3m_avg_ratio: float = 0.0
    mtd_spend_flag: str = ""

    essential_breakdown: Dict = field(default_factory=dict)


@dataclass
class DebtMetrics:
    """Debt-related metrics."""

    monthly_debt_payments: float = 0.0
    monthly_hcstc_payments: float = 0.0
    active_hcstc_count: int = 0
    active_hcstc_count_90d: int = 0  # Count in last 90 days
    monthly_bnpl_payments: float = 0.0
    monthly_credit_card_payments: float = 0.0
    monthly_other_loan_payments: float = 0.0
    total_debt_commitments: float = 0.0
    debt_breakdown: Dict = field(default_factory=dict)


@dataclass
class AffordabilityMetrics:
    """Affordability-related metrics."""

    debt_to_income_ratio: float = 0.0  # Target < 50%
    essential_ratio: float = 0.0  # Target < 70%
    monthly_disposable: float = 0.0
    disposable_ratio: float = 0.0  # Target > 15%

    # Loan-specific
    proposed_repayment: float = 0.0
    post_loan_disposable: float = 0.0
    repayment_to_disposable_ratio: float = 0.0
    is_affordable: bool = False
    max_affordable_amount: float = 0.0


@dataclass
class BalanceMetrics:
    """Account balance metrics."""

    average_balance: float = 0.0
    minimum_balance: float = 0.0
    maximum_balance: float = 0.0

    # Raw counts (over the observed window)
    days_in_overdraft: int = 0
    overdraft_frequency: int = 0  # Number of times balance went from >=0 to <0

    # Normalised (per observed month)
    months_observed: int = 0
    overdraft_days_per_month: float = 0.0
    overdraft_events_per_month: float = 0.0

    end_of_month_average: float = 0.0


@dataclass
class RiskMetrics:
    """Risk indicator metrics."""

    gambling_total: float = 0.0
    gambling_percentage: float = 0.0
    gambling_frequency: int = 0
    failed_payments_count: int = 0
    failed_payments_count_45d: int = 0  # Count in last 45 days
    debt_collection_activity: int = 0
    debt_collection_distinct: int = 0
    bank_charges_count: int = 0
    bank_charges_count_90d: int = 0  # Count in last 90 days
    new_credit_providers_90d: int = 0  # Distinct credit providers in last 90 days
    savings_activity: float = 0.0
    has_gambling_concern: bool = False
    has_failed_payment_concern: bool = False
    has_debt_collection_concern: bool = False
    has_bank_charges_concern: bool = False  # For mandatory referral
    has_new_credit_burst: bool = False  # For mandatory referral
    
    # Savings behavior score (positive indicator)
    savings_behavior_score: float = 0.0  # 0-3 points for regular savers
    
    # Combined Risk Signals (for tiered approval system)
    # Individual flags
    flag_low_income_stability: bool = False  # income_stability_score < 50
    flag_low_debt_management: bool = False   # monthly_debt_payments < 200
    flag_low_credit_activity: bool = False   # new_credit_providers_90d < 10
    flag_no_savings: bool = False            # savings_activity < 5
    
    # Combined signal
    risk_flag_count: int = 0  # Count of flags (0-4)
    risk_tier: str = "CLEAN"  # CLEAN (0-1 flags), WATCH (2 flags), FLAG (3+ flags)


class MetricsCalculator:
    """Calculates financial metrics from categorized transactions."""

    PARTIAL_MONTH_DAY_CUTOFF = 15

    def __init__(
        self,
        lookback_months: int = 3,
        months_of_data: Optional[int] = None,
        transactions: Optional[List[Dict]] = None,
        product_config: Optional[Dict] = None,
    ):
        """
        Initialize the metrics calculator.

        Args:
            lookback_months: Number of months to look back for income/expense calculations (default 3).
                           This determines the window for calculating monthly averages.
            months_of_data: Number of months of transaction data (optional).
                           If not provided, will be calculated from transactions.
            transactions: Transaction list to calculate months from (optional).
                         Used when months_of_data is not provided.
        """
        self.lookback_months = lookback_months

        # If months_of_data is explicitly provided, use it
        if months_of_data is not None:
            self.months_of_data = months_of_data
        # Otherwise, try to calculate from transactions
        elif transactions is not None:
            self.months_of_data = self._calculate_months_of_data(transactions)
        # Fallback to default of 3 for backward compatibility
        else:
            self.months_of_data = 3

        self.product_config = product_config or PRODUCT_CONFIG

    def _calculate_months_of_data(self, transactions: List[Dict]) -> int:
        """
        Calculate the number of unique months covered by INCOME transactions.

        This method finds the earliest and latest INCOME transaction dates and calculates
        the number of unique calendar months between them (inclusive).

        Uses income transactions only (negative amounts) to determine the actual
        income period, excluding historical expenses or other non-income transactions.

        For example:
        - Income from March 1 to March 31: 1 month
        - Income from March 1 to May 31: 3 months (March, April, May)
        - Income from Jan 15 to Dec 20: 12 months

        Args:
            transactions: List of transaction dictionaries with 'date' and 'amount' fields

        Returns:
            Number of unique months (minimum 1)
        """
        if not transactions:
            return 3  # Default fallback

        # Extract valid dates from INCOME transactions only (negative amounts)
        income_dates = []
        for txn in transactions:
            # Filter for income transactions (negative amounts)
            # Note: In PLAID format, income is represented as negative amounts,
            # expenses as positive amounts. This is the convention used throughout
            # the transaction data.
            amount = txn.get("amount", 0)
            if amount >= 0:  # Skip expenses (positive) and zero amounts
                continue

            date_str = txn.get("date", "")
            if not date_str:
                continue

            try:
                # Parse date string (format: YYYY-MM-DD)
                date = datetime.strptime(date_str, "%Y-%m-%d")
                income_dates.append(date)
            except (ValueError, TypeError):
                # Skip invalid dates
                continue

        if not income_dates:
            return 3  # Default fallback if no valid income dates

        # Find earliest and latest INCOME dates
        earliest = min(income_dates)
        latest = max(income_dates)

        # Calculate number of unique months
        # Using year*12 + month to count unique calendar months
        earliest_month = earliest.year * 12 + earliest.month
        latest_month = latest.year * 12 + latest.month

        # Add 1 because both start and end months are included
        months = latest_month - earliest_month + 1

        # Return at least 1 month
        return max(1, months)

    def _filter_recent_transactions(
        self, transactions: List[Dict], months: int
    ) -> List[Dict]:
        """
        Filter transactions to only include the last N *complete* calendar months.

        Important: This intentionally EXCLUDES the current (possibly partial) month.
        Example: If the most recent transaction is on 2025-12-14 and months=3,
        this returns all transactions dated in Sep/Oct/Nov 2025 only.

        This prevents overstating expenses (and sometimes income) by accidentally
        including a partial month but still dividing totals by N months.

        Args:
            transactions: Full transaction list
            months: Number of complete calendar months to include

        Returns:
            Filtered transaction list for the last N complete calendar months
        """
        if not transactions:
            return []

        # Find most recent transaction date
        recent_date = None
        for txn in transactions:
            date_str = txn.get("date", "")
            if date_str:
                try:
                    d = datetime.strptime(date_str, "%Y-%m-%d")
                    if recent_date is None or d > recent_date:
                        recent_date = d
                except ValueError:
                    continue

        if recent_date is None:
            return transactions

        # End boundary = first day of the current month (exclude current partial month)
        end_boundary = recent_date.replace(day=1)

        # Start boundary = first day of the month 'months' back from end_boundary
        # (e.g. if end_boundary is 2025-12-01 and months=3 -> start_boundary 2025-09-01)
        y, mth = end_boundary.year, end_boundary.month
        mth -= months
        while mth <= 0:
            mth += 12
            y -= 1
        start_boundary = end_boundary.replace(year=y, month=mth, day=1)

        filtered: List[Dict] = []
        for txn in transactions:
            date_str = txn.get("date", "")
            if not date_str:
                continue
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue

            if start_boundary <= d < end_boundary:
                filtered.append(txn)

        return filtered

    def _filter_last_complete_calendar_months(
        self, transactions: List[Dict], months: int
    ) -> List[Dict]:
        """
        Return transactions from the last N COMPLETE calendar months that have expenses,
        excluding the current (partial) month.

        This ensures we only count months with actual expenses within the recent lookback period.

        Example:  Latest txn is 2025-05-25, lookback=3
        - Exclude May (partial month)
        - Take up to 3 complete months before May that have expenses:  April, March, (Feb if it has expenses)
        """
        if not transactions:
            return []

        # Find the most recent transaction date
        max_date = None
        for txn in transactions:
            date_str = txn.get("date")
            if not date_str:
                continue
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                if max_date is None or dt > max_date:
                    max_date = dt
            except ValueError:
                continue

        if max_date is None:
            return []

        # Treat the latest month as partial only when the latest observed
        # transaction lands early in the month.
        anchor_month = (max_date.year, max_date.month)
        exclude_anchor_month = max_date.day < self.PARTIAL_MONTH_DAY_CUTOFF

        # Calculate the earliest allowed month (lookback period)
        # We want to include up to 'months' complete months before the anchor
        # Example: anchor=(2025, 5), months=3 -> earliest=(2025, 2)
        # That gives us Feb, March, April (3 months, excluding May)
        y, m = anchor_month

        # Go back 'months' from the anchor
        for _ in range(months):
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        earliest_allowed = (y, m)

        # Find all months with EXPENSE transactions within the valid range
        expense_months = set()
        for txn in transactions:
            amount = txn.get("amount", 0)
            # Skip income (negative amounts)
            if amount <= 0:
                continue

            date_str = txn.get("date")
            if not date_str:
                continue
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                txn_month = (dt.year, dt.month)

                # Skip anchor month only when it looks partial.
                if exclude_anchor_month and txn_month == anchor_month:
                    continue
                if txn_month < earliest_allowed:
                    continue

                expense_months.add(txn_month)
            except ValueError:
                continue

        if not expense_months:
            return []

        # Sort months in descending order and take up to 'months' of them
        selected_months = sorted(expense_months, reverse=True)[:months]
        selected_months_set = set(selected_months)

        # Filter transactions to selected months
        filtered = []
        for txn in transactions:
            date_str = txn.get("date")
            if not date_str:
                continue
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                if (dt.year, dt.month) in selected_months_set:
                    filtered.append(txn)
            except ValueError:
                continue

        return filtered

    def _filter_last_n_income_months(
        self, categorized_transactions: List[Tuple[Dict, "CategoryMatch"]], months: int
    ) -> List[Dict]:
        """
        Return INCOME transactions from the most recent N COMPLETE calendar months that contain income.

        This excludes the current (partial) month to match the expense filtering logic.

        Args:
            categorized_transactions:  List of (txn, CategoryMatch)
            months: number of income months to include

        Returns:
            List of transaction dicts (income only) within the selected months
        """
        if not categorized_transactions or months <= 0:
            return []
        # Find the most recent transaction date to determine the anchor month
        max_date = None
        for txn, match in categorized_transactions:
            date_str = txn.get("date")
            if not date_str:
                continue
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                if max_date is None or dt > max_date:
                    max_date = dt
            except ValueError:
                continue
        if max_date is None:
            return []

        # See _filter_last_complete_calendar_months for why this is conditional.
        anchor_month = (max_date.year, max_date.month)
        exclude_anchor_month = max_date.day < self.PARTIAL_MONTH_DAY_CUTOFF

        income_months = set()

        # 1) Identify which calendar months contain income (excluding anchor month)
        for txn, match in categorized_transactions:
            try:
                if getattr(match, "category", None) != "income":
                    continue
                amt = txn.get("amount", 0)
                # In your convention:  income = negative amounts
                if amt is None or float(amt) >= 0:
                    continue

                date_str = txn.get("date")
                if not date_str:
                    continue
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                txn_month = (dt.year, dt.month)
                if exclude_anchor_month and txn_month == anchor_month:
                    continue

                income_months.add(txn_month)
            except Exception:
                continue

        if not income_months:
            return []

        # 2) Take the most recent N income months
        selected_months = sorted(income_months, reverse=True)[:months]
        selected_months = set(selected_months)

        # 3) Return only income transactions that fall in those months
        filtered_income_txns: List[Dict] = []
        for txn, match in categorized_transactions:
            try:
                if getattr(match, "category", None) != "income":
                    continue
                amt = txn.get("amount", 0)
                if amt is None or float(amt) >= 0:
                    continue

                date_str = txn.get("date")
                if not date_str:
                    continue
                dt = datetime.strptime(date_str, "%Y-%m-%d")

                if (dt.year, dt.month) in selected_months:
                    filtered_income_txns.append(txn)
            except Exception:
                continue

        logger.debug(
            "[INCOME FILTER DEBUG] Anchor month (excluded): %s, Found %d income months: %s, selected %d months, returning %d transactions",
            anchor_month,
            len(income_months),
            sorted(income_months, reverse=True),
            months,
            len(filtered_income_txns),
        )

        return filtered_income_txns

    def _filter_month_to_date_transactions(
        self, transactions: List[Dict]
    ) -> List[Dict]:
        """
        Filter transactions to the current month-to-date based on the most recent transaction date.

        This is used ONLY for the optional MTD spend trend flag (not for the main monthly averages).
        """
        if not transactions:
            return []

        recent_date = None
        for txn in transactions:
            date_str = txn.get("date", "")
            if date_str:
                try:
                    d = datetime.strptime(date_str, "%Y-%m-%d")
                    if recent_date is None or d > recent_date:
                        recent_date = d
                except ValueError:
                    continue

        if recent_date is None:
            return []

        start_of_month = recent_date.replace(day=1)

        filtered: List[Dict] = []
        for txn in transactions:
            date_str = txn.get("date", "")
            if not date_str:
                continue
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue

            if start_of_month <= d <= recent_date:
                filtered.append(txn)

        return filtered

    def _get_transaction_id(self, txn: Dict) -> Tuple:
        # Use fields that actually exist consistently in your pipeline.
        # Your engine uses txn["name"] as the primary description field.
        desc = txn.get("name") or txn.get("description") or ""
        merchant = txn.get("merchant_name") or ""
        return (txn.get("date"), txn.get("amount"), desc, merchant)

    def _build_filtered_category_summary(
        self,
        categorized_transactions: List[Tuple[Dict, CategoryMatch]],
        recent_transactions: List[Dict],
    ) -> Dict:
        """
        Build a category summary from only the recent transactions.

        This is used to calculate accurate income and expense totals from the filtered
        time period without including old sporadic transactions.

        Args:
        categorized_transactions: Full list of (transaction, CategoryMatch) tuples
        recent_transactions:  Filtered list of recent transactions

        Returns:
            Category summary dict with totals from recent transactions only
        """
        # Create set of recent transaction IDs for fast lookup
        recent_txn_ids = set()
        for txn in recent_transactions:
            recent_txn_ids.add(self._get_transaction_id(txn))

        # Helper: recurring-like check (local, minimal)
        def _normalize_desc(s: str) -> str:
            s = (s or "").strip().lower()
            cleaned = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in s)
            return " ".join(cleaned.split())

        def _is_recurring_like_local(
            txn: Dict, amount_tolerance: float = 0.25, min_similar: int = 2
        ) -> bool:
            # We only care about cadence of same-ish description + amount
            this_norm = _normalize_desc(txn.get("name", ""))
            if not this_norm:
                return False

            this_amt = abs(float(txn.get("amount", 0) or 0))
            if this_amt <= 0:
                return False

            this_id = self._get_transaction_id(txn)
            dates = []
            for t in recent_transactions:
                if self._get_transaction_id(t) == this_id:
                    continue

                a = float(t.get("amount", 0) or 0)
                if abs(a) <= 0:
                    continue
                other_norm = _normalize_desc(t.get("name", ""))
                if other_norm != this_norm:
                    continue

                # similar amount band
                if abs(abs(a) - this_amt) / this_amt > amount_tolerance:
                    continue

                ds = t.get("date")
                if not ds:
                    continue
                try:
                    dates.append(datetime.strptime(ds, "%Y-%m-%d"))
                except ValueError:
                    continue

            if len(dates) < min_similar:
                return False

            dates_sorted = sorted(dates)
            intervals = [
                (dates_sorted[i] - dates_sorted[i - 1]).days
                for i in range(1, len(dates_sorted))
            ]
            if not intervals:
                return False

            avg = sum(intervals) / len(intervals)
            return (5 <= avg <= 9) or (11 <= avg <= 17) or (25 <= avg <= 35)

        # Initialize summary structure
        summary = {
            "income": {
                "salary": {"total": 0.0, "count": 0},
                "benefits": {"total": 0.0, "count": 0},
                "pension": {"total": 0.0, "count": 0},
                "gig_economy": {"total": 0.0, "count": 0},
                "loans": {"total": 0.0, "count": 0},
                "other": {"total": 0.0, "count": 0},
                "account_transfer": {"total": 0.0, "count": 0},
            },
            "essential": {
                "rent": {"total": 0.0, "count": 0},
                "mortgage": {"total": 0.0, "count": 0},
                "council_tax": {"total": 0.0, "count": 0},
                "utilities": {"total": 0.0, "count": 0},
                "communications": {"total": 0.0, "count": 0},
                "insurance": {"total": 0.0, "count": 0},
                "transport": {"total": 0.0, "count": 0},
                "groceries": {"total": 0.0, "count": 0},
                "childcare": {"total": 0.0, "count": 0},
            },
            "expense": {
                "other": {"total": 0.0, "count": 0},
                "food_dining": {"total": 0.0, "count": 0},
                "discretionary": {"total": 0.0, "count": 0},  # NEW
                "unpaid": {"total": 0.0, "count": 0},
                "unauthorised_overdraft": {"total": 0.0, "count": 0},
                "gambling": {"total": 0.0, "count": 0},
                "account_transfer": {"total": 0.0, "count": 0},
            },
            "debt": {
                "hcstc_payday": {
                    "total": 0.0,
                    "count": 0,
                    "lenders": set(),
                    "lenders_90d": set(),
                },
                "other_loans": {"total": 0.0, "count": 0},
                "credit_cards": {"total": 0.0, "count": 0},
                "bnpl": {"total": 0.0, "count": 0},
                "catalogue": {"total": 0.0, "count": 0},
            },
        }

        transfer_income_supplement = 0.0

        # Filter categorized transactions and rebuild summary
        for txn, match in categorized_transactions:
            # Check if this transaction is in the recent set
            if self._get_transaction_id(txn) not in recent_txn_ids:
                continue

            amount = abs(txn.get("amount", 0))
            category = match.category
            subcategory = match.subcategory

            # Track income and ALL expense categories in filtered summary
            if category in [
                "income",
                "essential",
                "expense",
                "debt",
            ] and subcategory in summary.get(category, {}):
                # For income, apply weight; for expenses, use full amount
                if category == "income":
                    summary[category][subcategory]["total"] += amount * match.weight
                    # DEBUG: Log weighted income
                    if match.weight < 1.0:
                        logger.debug(
                            "[INCOME WEIGHTING] Txn:  %s, Amount: £%.2f, Weight: %.2f, Weighted: £%.2f, Category: %s/%s",
                            txn.get("date"),
                            amount,
                            match.weight,
                            amount * match.weight,
                            category,
                            subcategory,
                        )
                    summary[category][subcategory]["count"] += 1
                # EXCLUDE expense/account_transfer from affordability (internal transfers out)
                elif category == "expense" and subcategory == "account_transfer":
                    # Skip - don't count internal transfers out as expenses
                    pass
                # EXCLUDE transfer/internal from affordability (internal transfers)
                elif category == "transfer" and subcategory == "internal":
                    # Skip - don't count internal transfers as expenses
                    pass
                else:
                    summary[category][subcategory]["total"] += amount
                    summary[category][subcategory]["count"] += 1

            if category == "transfer" and subcategory == "internal":
                raw_amt = float(txn.get("amount", 0) or 0)
                if raw_amt < 0:
                    if _is_recurring_like_local(txn):
                        transfer_income_supplement += abs(raw_amt) * 0.5

        core_income_total = (
            summary["income"]["salary"]["total"]
            + summary["income"]["benefits"]["total"]
            + summary["income"]["pension"]["total"]
            + summary["income"]["gig_economy"]["total"]
        )

        cap = core_income_total * 0.40  # 20% cap
        applied = min(transfer_income_supplement, cap)

        summary["income"]["other"]["total"] += applied
        if applied > 0:
            summary["income"]["other"]["count"] += 1

        return summary

    def calculate_all_metrics(
        self,
        category_summary: Dict,
        transactions: List[Dict],
        accounts: List[Dict],
        loan_amount: float = 500,
        loan_term: int = 4,
        categorized_transactions: Optional[List[Tuple[Dict, "CategoryMatch"]]] = None,
    ) -> Dict:
        """
        Calculate all metrics from categorized transactions.

        This method applies different time windows for different metric types:
        - Income/Expense metrics: Use recent transactions (last N months) for accurate monthly averages
        - Risk metrics: Use full transaction history to capture all historical risk patterns

        Args:
            category_summary: Summary from TransactionCategorizer (based on full history)
            transactions: Raw transaction list (full history)
            accounts: Account information list
            loan_amount: Requested loan amount
            loan_term: Requested loan term in months
            categorized_transactions: Optional list of (transaction, CategoryMatch) tuples
                                     Used to rebuild category summary for filtered period

        Returns:
            Dictionary containing all metric objects
        """
        # Filter transactions to last N months for income/expense calculations
        recent_transactions = self._filter_recent_transactions(
            transactions, self.lookback_months
        )

        # Month-to-date transactions for the optional trend flag (NOT used in averages)
        mtd_transactions = self._filter_month_to_date_transactions(transactions)

        # Build filtered category summaries separately:
        # - expenses: last N COMPLETE calendar months (avoids partial-month inflation)
        # - income: most recent N months that actually contain income (avoids dropping partial-month salary)
        if categorized_transactions is not None:
            expense_transactions = self._filter_last_complete_calendar_months(
                transactions, self.lookback_months
            )

            income_transactions = self._filter_last_n_income_months(
                categorized_transactions, self.lookback_months
            )

            filtered_category_summary_expense = self._build_filtered_category_summary(
                categorized_transactions, expense_transactions
            )
            filtered_category_summary_income = self._build_filtered_category_summary(
                categorized_transactions, income_transactions
            )

            # Optional MTD category summary (for trend flag logic later)
            mtd_category_summary = self._build_filtered_category_summary(
                categorized_transactions, mtd_transactions
            )
        else:
            # Fallback: no categorized txns provided
            expense_transactions = recent_transactions
            income_transactions = recent_transactions
            filtered_category_summary_expense = category_summary
            filtered_category_summary_income = category_summary
            mtd_category_summary = None

        # Calculate income and expenses using their own windows
        income_metrics = self.calculate_income_metrics(
            filtered_category_summary_income, income_transactions
        )

        expense_metrics = self.calculate_expense_metrics(
            filtered_category_summary_expense,
            expense_transactions,
            mtd_category_summary=mtd_category_summary,
            mtd_transactions=mtd_transactions,
        )

        # Calculate debt metrics using the same filtered period as expenses
        # This ensures consistent time basis for affordability calculations
        # (Monthly debt must be calculated over the same period as monthly expenses)
        filtered_category_summary_debt = (
            self._build_filtered_category_summary(
                categorized_transactions, expense_transactions
            )
            if categorized_transactions is not None
            else filtered_category_summary_expense
        )

        # Calculate debt payments from filtered period
        debt_metrics = self.calculate_debt_metrics(filtered_category_summary_debt)

        # However, HCSTC lender counts should come from FULL history for risk assessment
        # Override the lender counts with full history data
        full_debt_data = category_summary.get("debt", {})
        full_hcstc_data = full_debt_data.get("hcstc_payday", {})
        full_lenders = full_hcstc_data.get("lenders", set())
        full_lenders_90d = full_hcstc_data.get("lenders_90d", set())

        # Convert sets to length (lenders are always stored as sets in the category summary)
        debt_metrics.active_hcstc_count = (
            len(full_lenders) if isinstance(full_lenders, set) else full_lenders
        )
        debt_metrics.active_hcstc_count_90d = (
            len(full_lenders_90d)
            if isinstance(full_lenders_90d, set)
            else full_lenders_90d
        )
        balance_metrics = self.calculate_balance_metrics(transactions, accounts)
        risk_metrics = self.calculate_risk_metrics(
            category_summary, income_metrics, categorized_transactions=categorized_transactions
        )

        affordability_metrics = self.calculate_affordability_metrics(
            income_metrics=income_metrics,
            expense_metrics=expense_metrics,
            debt_metrics=debt_metrics,
            loan_amount=loan_amount,
            loan_term=loan_term,
        )

        # Calculate combined risk flags for tiered approval system
        # These flags are based on analysis showing combined weak signals create strong signals
        flag_low_income_stability = (
            income_metrics.income_stability_score is not None 
            and income_metrics.income_stability_score < 50
        )
        flag_low_debt_management = (
            debt_metrics.monthly_debt_payments is not None
            and debt_metrics.monthly_debt_payments < 200
        )
        flag_low_credit_activity = (
            risk_metrics.new_credit_providers_90d is not None
            and risk_metrics.new_credit_providers_90d < 10
        )
        flag_no_savings = (
            risk_metrics.savings_activity is not None
            and risk_metrics.savings_activity < 5
        )
        
        # Count total flags
        risk_flag_count = sum([
            flag_low_income_stability,
            flag_low_debt_management,
            flag_low_credit_activity,
            flag_no_savings
        ])
        
        # Determine risk tier
        if risk_flag_count >= 3:
            risk_tier = "FLAG"  # High risk - approve with conditions
        elif risk_flag_count == 2:
            risk_tier = "WATCH"  # Elevated risk - monitor closely
        else:
            risk_tier = "CLEAN"  # Normal risk - standard approval
        
        # Update risk_metrics with the flag information
        risk_metrics.flag_low_income_stability = flag_low_income_stability
        risk_metrics.flag_low_debt_management = flag_low_debt_management
        risk_metrics.flag_low_credit_activity = flag_low_credit_activity
        risk_metrics.flag_no_savings = flag_no_savings
        risk_metrics.risk_flag_count = risk_flag_count
        risk_metrics.risk_tier = risk_tier

        return {
            "income": income_metrics,
            "expenses": expense_metrics,
            "debt": debt_metrics,
            "affordability": affordability_metrics,
            "balance": balance_metrics,
            "risk": risk_metrics,
            "mtd_category_summary": mtd_category_summary,
            "mtd_transactions": mtd_transactions,
        }

    def _count_unique_income_months(self, transactions: List[Dict]) -> int:
        """
        Count unique calendar months that contain INCOME transactions.

        This prevents dividing by months that have no income, which would
        artificially deflate monthly income averages.

        Note: In PLAID format, income transactions have NEGATIVE amounts
        (money coming in), while expense transactions have POSITIVE amounts
        (money going out). This is the opposite of typical accounting convention.

        Returns:
            Number of unique months with income (minimum 1)
        """
        income_months = set()

        for txn in transactions:
            amount = txn.get("amount", 0)
            if amount >= 0:  # Not income (in PLAID format: negative = credit/income)
                continue

            date_str = txn.get("date", "")
            if not date_str:
                continue

            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
                income_months.add((date.year, date.month))
            except (ValueError, TypeError):
                continue

        return max(1, len(income_months))

    def _count_unique_months(self, transactions: List[Dict]) -> int:
        """
        Count unique calendar months in transaction list.

        Returns:
            Number of unique months (minimum 1)
        """
        months = set()

        for txn in transactions:
            date_str = txn.get("date", "")
            if not date_str:
                continue

            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
                months.add((date.year, date.month))
            except (ValueError, TypeError):
                continue

        return max(1, len(months))

    def calculate_income_metrics(
        self, category_summary: Dict, transactions: List[Dict]
    ) -> IncomeMetrics:
        """
        Calculate income-related metrics from recent transactions.

        Args:
            category_summary: Category summary (should be from filtered transactions)
            transactions: Recent transactions list (for stability/regularity calculation)

        Returns:
            IncomeMetrics with monthly income averages
        """
        income_data = category_summary.get("income", {})

        # Calculate totals (these are already from filtered transactions)
        salary_total = income_data.get("salary", {}).get("total", 0)
        benefits_total = income_data.get("benefits", {}).get("total", 0)
        pension_total = income_data.get("pension", {}).get("total", 0)
        gig_total = income_data.get("gig_economy", {}).get("total", 0)
        other_total = income_data.get("other", {}).get("total", 0)
        account_transfer_total = income_data.get("account_transfer", {}).get("total", 0)

        total_income = abs(
            salary_total
            + benefits_total
            + pension_total
            + gig_total
            + other_total
            + account_transfer_total
        )

        # **ADD VALIDATION LOGGING**
        salary_count = income_data.get("salary", {}).get("count", 0)
        benefits_count = income_data.get("benefits", {}).get("count", 0)
        pension_count = income_data.get("pension", {}).get("count", 0)
        gig_count = income_data.get("gig_economy", {}).get("count", 0)
        other_count = income_data.get("other", {}).get("count", 0)
        account_transfer_count = income_data.get("account_transfer", {}).get("count", 0)

        logger.debug(
            "[INCOME VALIDATION]\n"
            "Salary: £%.2f (%d txns)\n"
            "Benefits: £%.2f (%d txns)\n"
            "Pension: £%.2f (%d txns)\n"
            "Gig Economy: £%.2f (%d txns)\n"
            "Other: £%.2f (%d txns)\n"
            "Account Transfer: £%.2f (%d txns)\n"
            "Total: £%.2f",
            salary_total,
            salary_count,
            benefits_total,
            benefits_count,
            pension_total,
            pension_count,
            gig_total,
            gig_count,
            other_total,
            other_count,
            account_transfer_total,
            account_transfer_count,
            total_income,  # Use the already calculated total_income
        )

        # **CRITICAL FIX**: Count months in FILTERED transactions, not total history
        actual_months = self._count_unique_income_months(transactions)

        logger.debug(
            "[INCOME VALIDATION] Using %d months for averaging (lookback=%d, total_history=%d)",
            actual_months,
            self.lookback_months,
            self.months_of_data,
        )

        # Monthly calculations - divide by ACTUAL months in recent period
        monthly_stable = (salary_total + benefits_total + pension_total) / actual_months
        monthly_gig = gig_total / actual_months
        monthly_other = other_total / actual_months
        monthly_income = total_income / actual_months
        monthly_account_transfer = account_transfer_total / actual_months

        # Effective income (gig weighted at 100%, other at 100%)
        effective_monthly = abs(
            monthly_stable
            + (monthly_gig * 1.0)
            + monthly_other
            + monthly_account_transfer
        )

        # Income stability score
        stability_score = self._calculate_income_stability(transactions)

        # Income regularity score
        regularity_score = self._calculate_income_regularity(transactions)

        # Determine income sources
        income_sources = []
        if salary_total > 0:
            income_sources.append("Salary")
        if benefits_total > 0:
            income_sources.append("Benefits")
        if pension_total > 0:
            income_sources.append("Pension")
        if gig_total > 0:
            income_sources.append("Gig Economy")

        # Verifiable income check
        has_verifiable = salary_total > 0 or benefits_total > 0 or pension_total > 0

        # NEW: Calculate income trend
        income_trend, income_trend_pct = self._calculate_income_trend(transactions)

        return IncomeMetrics(
            total_income=total_income,
            monthly_income=monthly_income,
            monthly_stable_income=monthly_stable,
            monthly_gig_income=monthly_gig,
            effective_monthly_income=effective_monthly,
            income_stability_score=stability_score,
            income_regularity_score=regularity_score,
            has_verifiable_income=has_verifiable,
            income_sources=income_sources,
            monthly_income_breakdown={
                "salary": salary_total / actual_months,
                "benefits": benefits_total / actual_months,
                "pension": pension_total / actual_months,
                "gig_economy": monthly_gig,
                "other": monthly_other,
                "account_transfer": account_transfer_total / actual_months,
            },
            income_trend=income_trend,
            income_trend_pct=income_trend_pct,
        )

    def _calculate_income_stability(self, transactions: List[Dict]) -> float:
        """
        Calculate income stability score based on standard deviation.

        Score = 100 - (StdDev / Mean * 100)
        """
        # Group income by month
        monthly_income = defaultdict(float)

        for txn in transactions:
            amount = txn.get("amount", 0)
            if amount >= 0:  # Not income
                continue

            date_str = txn.get("date", "")
            if not date_str:
                continue

            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
                month_key = date.strftime("%Y-%m")
                monthly_income[month_key] += abs(amount)
            except (ValueError, TypeError):
                continue

        if len(monthly_income) < 2:
            return 50.0  # Default if insufficient data

        values = list(monthly_income.values())
        mean_income = statistics.mean(values)

        if mean_income == 0:
            return 0.0

        std_dev = statistics.stdev(values) if len(values) > 1 else 0
        coefficient_of_variation = (std_dev / mean_income) * 100

        # Score calculation: 100 - CV, clamped to 0-100
        stability_score = max(0, min(100, 100 - coefficient_of_variation))

        return round(stability_score, 1)

    def _calculate_income_regularity(self, transactions: List[Dict]) -> float:
        """
        Calculate income regularity based on payment day consistency.

        Higher score = more consistent payment days
        """
        # Find income transactions and their days
        income_days = []

        for txn in transactions:
            amount = txn.get("amount", 0)
            if amount >= 0:  # Not income
                continue

            # Only consider larger payments (likely salary/benefits)
            if abs(amount) < 100:
                continue

            date_str = txn.get("date", "")
            if not date_str:
                continue

            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
                income_days.append(date.day)
            except (ValueError, TypeError):
                continue

        if len(income_days) < 2:
            return 50.0  # Default if insufficient data

        # Calculate standard deviation of payment days
        std_dev = statistics.stdev(income_days) if len(income_days) > 1 else 0

        # Score: Lower std_dev = higher score
        # Max regularity if std_dev <= 2 days
        if std_dev <= 2:
            return 100.0
        elif std_dev <= 5:
            return 80.0
        elif std_dev <= 10:
            return 60.0
        elif std_dev <= 15:
            return 40.0
        else:
            return 20.0

    def _calculate_income_trend(self, transactions: List[Dict]) -> Tuple[str, float]:
        """
        Calculate income trend by comparing recent vs older income.
        
        Returns:
            Tuple of (trend_label, trend_percentage)
            trend_label: "increasing", "stable", or "decreasing"
            trend_percentage: Percentage change (positive = increasing)
        """
        from collections import defaultdict
        
        # Group income by month
        monthly_income = defaultdict(float)
        
        for txn in transactions:
            amount = txn.get("amount", 0)
            if amount >= 0:  # Not income
                continue
            
            date_str = txn.get("date", "")
            if not date_str:
                continue
            
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
                month_key = date.strftime("%Y-%m")
                monthly_income[month_key] += abs(amount)
            except (ValueError, TypeError):
                continue
        
        if len(monthly_income) < 3:
            return "stable", 0.0  # Insufficient data
        
        # Sort months chronologically
        sorted_months = sorted(monthly_income.keys())
        monthly_values = [monthly_income[m] for m in sorted_months]
        
        # Compare recent 2 months vs older months
        recent_avg = sum(monthly_values[-2:]) / 2 if len(monthly_values) >= 2 else monthly_values[-1]
        older_avg = sum(monthly_values[:-2]) / max(1, len(monthly_values) - 2)
        
        if older_avg == 0:
            return "stable", 0.0
        
        change_pct = (recent_avg - older_avg) / older_avg * 100
        
        if change_pct > 10:
            return "increasing", round(change_pct, 1)
        elif change_pct < -10:
            return "decreasing", round(change_pct, 1)
        else:
            return "stable", round(change_pct, 1)

    def _validate_category_summary(self, category_summary: Dict, label: str = ""):
        """
        Debug helper to validate category summary structure.

        Call this after building filtered_category_summary to ensure
        transferred income is properly included.
        """
        logger.debug("[CATEGORY SUMMARY VALIDATION - %s]", label)

        for category in ["income", "essential", "expense", "debt"]:
            cat_data = category_summary.get(category, {})
            logger.debug("\n%s:", category.upper())

            for subcategory, data in cat_data.items():
                if isinstance(data, dict):
                    total = data.get("total", 0)
                    count = data.get("count", 0)
                    if total > 0 or count > 0:
                        logger.debug("  %s: £%.2f (%d txns)", subcategory, total, count)

    def calculate_expense_metrics(
        self,
        category_summary: Dict,
        transactions: Optional[List[Dict]] = None,
        mtd_category_summary: Optional[Dict] = None,
        mtd_transactions: Optional[List[Dict]] = None,
    ) -> ExpenseMetrics:
        """
        Calculate expense-related metrics from recent transactions.

        Args:
            category_summary: Category summary (should be from filtered transactions)
            transactions: Recent transactions list (for calculating actual months)

        Returns:
            ExpenseMetrics with monthly expense averages
        """
        essential_data = category_summary.get("essential", {})
        debt_data = category_summary.get("debt", {})
        expense_data = category_summary.get("expense", {})

        # Calculate actual months in the filtered period
        # Count unique months in the filtered transactions to handle edge cases
        # where the filter may return fewer months than expected
        if transactions:
            actual_months = self._count_unique_months(transactions)
        else:
            actual_months = self.lookback_months

        # Get monthly averages based on actual months in filtered period
        rent = essential_data.get("rent", {}).get("total", 0) / actual_months
        mortgage = essential_data.get("mortgage", {}).get("total", 0) / actual_months
        council_tax = (
            essential_data.get("council_tax", {}).get("total", 0) / actual_months
        )
        utilities = essential_data.get("utilities", {}).get("total", 0) / actual_months
        transport = essential_data.get("transport", {}).get("total", 0) / actual_months
        groceries = essential_data.get("groceries", {}).get("total", 0) / actual_months
        communications = (
            essential_data.get("communications", {}).get("total", 0) / actual_months
        )
        insurance = essential_data.get("insurance", {}).get("total", 0) / actual_months
        childcare = essential_data.get("childcare", {}).get("total", 0) / actual_months

        # Add other expenses that aren't in "essential" category
        other_expenses = expense_data.get("other", {}).get("total", 0) / actual_months
        food_dining = (
            expense_data.get("food_dining", {}).get("total", 0) / actual_months
        )
        discretionary = (
            expense_data.get("discretionary", {}).get("total", 0) / actual_months
        )
        account_transfer_expenses = (
            expense_data.get("account_transfer", {}).get("total", 0) / actual_months
        )

        # New expense subcategories
        unpaid = expense_data.get("unpaid", {}).get("total", 0) / actual_months
        unauthorised_overdraft = (
            expense_data.get("unauthorised_overdraft", {}).get("total", 0)
            / actual_months
        )
        gambling = expense_data.get("gambling", {}).get("total", 0) / actual_months

        # Housing is rent OR mortgage (not both)
        housing = max(rent, mortgage)

        # Essential costs (fixed/necessary spend)
        # Include unpaid + unauthorised_overdraft as essential-like spend
        essential_total = (
            housing
            + council_tax
            + utilities
            + transport
            + groceries
            + communications
            + insurance
            + childcare
            + other_expenses
            + food_dining
            + account_transfer_expenses
            + unpaid
            + unauthorised_overdraft
        )

        # Discretionary costs (separate bucket)
        # Include gambling as discretionary-like spend
        discretionary_total = discretionary + gambling

        # Total spend used for affordability
        monthly_total_spend = essential_total + discretionary_total

        # DEBUG: Log expense breakdown
        logger.debug(
            "[EXPENSE FILTER DEBUG]\n"
            "Other: £%.2f\n"
            "Food Dining: £%.2f\n"
            "Discretionary: £%.2f\n"
            "Account Transfer: £%.2f\n"
            "Gambling: £%.2f\n"
            "Essential Total: £%.2f\n"
            "Discretionary Total: £%.2f\n"
            "Months: %d",
            other_expenses * actual_months,
            food_dining * actual_months,
            discretionary * actual_months,
            account_transfer_expenses * actual_months,
            gambling * actual_months,
            essential_total * actual_months,
            discretionary_total * actual_months,
            actual_months,
        )

        # --- Optional month-to-date (MTD) spend trend flag (NOT part of the averages) ---
        mtd_total_spend = 0.0
        mtd_ratio = 0.0
        mtd_flag = ""

        try:
            # Baseline: average monthly spend over the lookback window (3 complete months)
            discretionary_total_period = 0.0
            for sub, data in category_summary.get("expense", {}).items():
                discretionary_total_period += abs(float(data.get("total", 0.0)))

            monthly_discretionary = discretionary_total_period / max(
                self.lookback_months, 1
            )
            baseline_monthly_spend = essential_total + monthly_discretionary

            if mtd_category_summary:
                # MTD spend uses the same "spend" basket, excluding debt/transfers
                for cat in ("essential", "expense", "risk"):
                    for sub, data in mtd_category_summary.get(cat, {}).items():
                        mtd_total_spend += abs(float(data.get("total", 0.0)))

                if baseline_monthly_spend > 0:
                    mtd_ratio = mtd_total_spend / baseline_monthly_spend

                # Simple, explainable flag
                if mtd_ratio >= 1.25:
                    mtd_flag = "MTD spending running HIGH vs 3-month average"
                elif mtd_ratio <= 0.75 and mtd_total_spend > 0:
                    mtd_flag = "MTD spending running LOW vs 3-month average"
        except Exception:
            # Never fail expense metrics because of the optional trend flag
            mtd_total_spend = 0.0
            mtd_ratio = 0.0
            mtd_flag = ""

        return ExpenseMetrics(
            monthly_housing=housing,
            monthly_council_tax=council_tax,
            monthly_utilities=utilities,
            monthly_transport=transport,
            monthly_groceries=groceries,
            monthly_communications=communications,
            monthly_insurance=insurance,
            monthly_childcare=childcare,
            monthly_essential_total=essential_total,
            monthly_discretionary_total=discretionary_total,
            monthly_total_spend=monthly_total_spend,
            mtd_total_spend=mtd_total_spend,
            mtd_spend_vs_3m_avg_ratio=mtd_ratio,
            mtd_spend_flag=mtd_flag,
            essential_breakdown={
                "housing": housing,
                "council_tax": council_tax,
                "utilities": utilities,
                "transport": transport,
                "groceries": groceries,
                "communications": communications,
                "insurance": insurance,
                "childcare": childcare,
                "other_expenses": other_expenses,
                "food_dining": food_dining,
                "unpaid": unpaid,
                "unauthorised_overdraft": unauthorised_overdraft,
                "discretionary": discretionary,
                "gambling": gambling,
            },
        )

    def calculate_debt_metrics(self, category_summary: Dict) -> DebtMetrics:
        """Calculate debt-related metrics."""
        debt_data = category_summary.get("debt", {})

        # Get monthly averages using the same lookback period as expenses
        # This ensures consistent time basis for affordability calculations
        hcstc = debt_data.get("hcstc_payday", {}).get("total", 0) / self.lookback_months
        other_loans = (
            debt_data.get("other_loans", {}).get("total", 0) / self.lookback_months
        )
        credit_cards = (
            debt_data.get("credit_cards", {}).get("total", 0) / self.lookback_months
        )
        bnpl = debt_data.get("bnpl", {}).get("total", 0) / self.lookback_months
        catalogue = (
            debt_data.get("catalogue", {}).get("total", 0) / self.lookback_months
        )

        # Active HCSTC lender count (all time and 90 days)
        # Handle both set and int types for backward compatibility
        lenders = debt_data.get("hcstc_payday", {}).get("lenders", set())
        lenders_90d = debt_data.get("hcstc_payday", {}).get("lenders_90d", set())

        # Convert sets to length (lenders are stored as sets in the filtered category summary)
        active_hcstc_count = len(lenders) if isinstance(lenders, set) else lenders
        active_hcstc_count_90d = (
            len(lenders_90d) if isinstance(lenders_90d, set) else lenders_90d
        )

        # Total debt commitments
        total_debt = hcstc + other_loans + credit_cards + bnpl + catalogue

        # DEBUG: Log debt breakdown
        logger.debug(
            "[DEBT FILTER DEBUG]\n"
            "HCSTC: £%.2f (monthly)\n"
            "BNPL: £%.2f (monthly)\n"
            "Credit Cards: £%.2f (monthly)\n"
            "Other Loans: £%.2f (monthly)\n"
            "Total Debt: £%.2f (monthly)",
            hcstc,
            bnpl,
            credit_cards,
            other_loans + catalogue,
            total_debt,
        )

        return DebtMetrics(
            monthly_debt_payments=total_debt,
            monthly_hcstc_payments=hcstc,
            active_hcstc_count=active_hcstc_count,
            active_hcstc_count_90d=active_hcstc_count_90d,
            monthly_bnpl_payments=bnpl,
            monthly_credit_card_payments=credit_cards,
            monthly_other_loan_payments=other_loans + catalogue,
            total_debt_commitments=total_debt,
            debt_breakdown={
                "hcstc": hcstc,
                "other_loans": other_loans,
                "credit_cards": credit_cards,
                "bnpl": bnpl,
                "catalogue": catalogue,
            },
        )

    def calculate_affordability_metrics(
        self,
        income_metrics: IncomeMetrics,
        expense_metrics: ExpenseMetrics,
        debt_metrics: DebtMetrics,
        loan_amount: float,
        loan_term: int,
    ) -> AffordabilityMetrics:
        """Calculate affordability metrics."""

        effective_income = income_metrics.effective_monthly_income or 0.0
        total_spend = expense_metrics.monthly_total_spend or 0.0
        debt_payments = debt_metrics.monthly_debt_payments or 0.0

        # Apply expense shock buffer for income/expenses resilience assessment
        # This buffer (default 10%) accounts for potential increases in expenses
        # or temporary reductions in income, improving the robustness of
        # affordability calculations and reducing default risk.
        expense_buffer = self.product_config.get("expense_shock_buffer", 1.1)
        essential_costs = expense_metrics.monthly_essential_total or 0.0
        discretionary_costs = expense_metrics.monthly_discretionary_total or 0.0
        buffered_expenses = (essential_costs * expense_buffer) + discretionary_costs

        # Debt-to-Income Ratio
        if effective_income > 0:
            dti_ratio = (debt_payments / effective_income) * 100
        else:
            dti_ratio = 100.0

        # Essential Ratio (using buffered expenses)
        if effective_income > 0:
            essential_ratio = (buffered_expenses / effective_income) * 100
        else:
            essential_ratio = 100.0

        print(
            f"[DEBUG] effective_income={effective_income}, buffered_expenses={buffered_expenses}, debt_payments={debt_payments}"
        )

        monthly_disposable = effective_income - buffered_expenses - debt_payments

        # Disposable Ratio
        if effective_income > 0:
            disposable_ratio = (monthly_disposable / effective_income) * 100
        else:
            disposable_ratio = 0.0

        # Calculate proposed loan repayment
        # Monthly payment with FCA price cap (0.8% per day)
        daily_rate = self.product_config["daily_interest_rate"]
        days_per_month = 30.4  # Average days per month
        monthly_rate = daily_rate * days_per_month

        total_interest = total_interest_for_term(
            loan_amount, monthly_rate, loan_term, self.product_config
        )

        total_repayable = loan_amount + total_interest
        proposed_repayment = total_repayable / loan_term

        # Post-loan disposable
        post_loan_disposable = monthly_disposable - proposed_repayment

        print(
            f"[AFFORDABILITY] "
            f"Income £{effective_income:.2f} | "
            f"Expenses £{expense_metrics.monthly_total_spend:.2f} | "
            f"Debt £{debt_payments:.2f} | "
            f"Repayment £{proposed_repayment:.2f} | "
            f"Post-loan £{post_loan_disposable:.2f}"
        )

        # Repayment-to-disposable ratio (MI / reporting ONLY)
        if monthly_disposable > 0:
            repayment_to_disp = (proposed_repayment / monthly_disposable) * 100
        else:
            repayment_to_disp = 100.0

        # Minimum disposable buffer (single source of truth)
        min_buffer = self.product_config["min_disposable_buffer"]

        # Affordability decision
        # NOTE: repayment_to_disp is NOT used here
        is_affordable = post_loan_disposable >= min_buffer

        # Calculate max affordable amount
        max_affordable = self._calculate_max_affordable_amount(
            monthly_disposable=monthly_disposable,
            min_buffer=min_buffer,
            max_term=loan_term,
        )

        return AffordabilityMetrics(
            debt_to_income_ratio=round(dti_ratio, 1),
            essential_ratio=round(essential_ratio, 1),
            monthly_disposable=round(monthly_disposable, 2),
            disposable_ratio=round(disposable_ratio, 1),
            proposed_repayment=round(proposed_repayment, 2),
            post_loan_disposable=round(post_loan_disposable, 2),
            repayment_to_disposable_ratio=round(repayment_to_disp, 1),
            is_affordable=is_affordable,
            max_affordable_amount=round(max_affordable, 2),
        )

    def _calculate_max_affordable_amount(
        self, monthly_disposable: float, min_buffer: float, max_term: int
    ) -> float:
        """Calculate maximum affordable loan amount."""
        # Max monthly payment = disposable - buffer
        monthly_disposable = monthly_disposable or 0.0
        max_monthly_payment = monthly_disposable - min_buffer

        if max_monthly_payment <= 0:
            return 0.0

        # Calculate max loan amount
        daily_rate = self.product_config["daily_interest_rate"]
        days_per_month = 30.4
        monthly_rate = daily_rate * days_per_month

        # Solve for principal: payment = (principal + principal * rate * term) / term
        # payment * term = principal * (1 + rate * term)
        # principal = payment * term / (1 + rate * term)
        total_payments = max_monthly_payment * max_term
        interest_factor = 1 + (monthly_rate * max_term)

        # Cap interest at 100%
        interest_factor = min(interest_factor, 2.0)  # Max 100% interest = factor of 2

        max_amount = total_payments / interest_factor

        # Cap at product maximum
        return min(max_amount, self.product_config["max_loan_amount"])

    def calculate_balance_metrics(
            self, transactions: List[Dict], accounts: List[Dict]
    ) -> BalanceMetrics:
        """Calculate account balance metrics."""

        # Always define months_observed up front (avoid UnboundLocalError)
        months_observed = int(getattr(self, "months_of_data", 0) or 1)
        months_observed = max(1, months_observed)

        # Try to get balance from accounts
        balances = []
        for account in accounts:
            account_balances = account.get("balances", {})
            current = account_balances.get("current", 0) or 0.0
            available = account_balances.get("available", 0) or 0.0
            balances.append(max(current, available))

        # Calculate daily balances from transactions
        daily_balances = self._calculate_daily_balances(transactions, accounts)

        if daily_balances:
            avg_balance = statistics.mean(daily_balances)
            min_balance = min(daily_balances)
            max_balance = max(daily_balances)
            days_negative = sum(1 for b in daily_balances if b < 0)

            # Count times balance went from positive to negative
            overdraft_count = 0
            for i in range(1, len(daily_balances)):
                if daily_balances[i - 1] >= 0 and daily_balances[i] < 0:
                    overdraft_count += 1
        else:
            avg_balance = sum(balances) / len(balances) if balances else 0.0
            min_balance = min(balances) if balances else 0.0
            max_balance = max(balances) if balances else 0.0
            days_negative = 0
            overdraft_count = 0

        # Normalise behavioural counts to a per-month rate (prevents history-length bias)
        overdraft_days_per_month = float(days_negative) / float(months_observed)
        overdraft_events_per_month = float(overdraft_count) / float(months_observed)

        return BalanceMetrics(
            average_balance=round(avg_balance, 2),
            minimum_balance=round(min_balance, 2),
            maximum_balance=round(max_balance, 2),
            days_in_overdraft=days_negative,
            overdraft_frequency=overdraft_count,
            months_observed=months_observed,
            overdraft_days_per_month=round(overdraft_days_per_month, 2),
            overdraft_events_per_month=round(overdraft_events_per_month, 2),
            end_of_month_average=round(avg_balance, 2),  # Simplified
        )

    def _calculate_daily_balances(
            self, transactions: List[Dict], accounts: List[Dict]
    ) -> List[float]:
        """Calculate estimated daily balances from transactions."""
        # Get starting balance from accounts
        starting_balance = 0.0
        for account in accounts:
            balances = account.get("balances", {})
            starting_balance += balances.get("current", 0) or 0.0

        # Sort transactions by date
        sorted_txns = sorted(
            transactions,
            key=lambda x: x.get("date", "9999-99-99"),
            reverse=True,  # Most recent first
        )

        if not sorted_txns:
            return [starting_balance]

        # Work backwards from current balance
        daily_balances = defaultdict(float)
        current_balance = starting_balance

        for txn in sorted_txns:
            date_str = txn.get("date", "")
            amount = txn.get("amount", 0) or 0.0

            if not date_str:
                continue

            daily_balances[date_str] = current_balance

            # Reverse the transaction to get previous balance.
            # PLAID: negative = credit (money in), positive = debit (money out).
            # Working backwards, undo the txn by adding the amount.
            current_balance = current_balance + float(amount)

        return list(daily_balances.values()) if daily_balances else [starting_balance]

    def calculate_risk_metrics(
            self,
            category_summary: Dict,
            income_metrics: IncomeMetrics,
            categorized_transactions: Optional[List[Tuple[Dict, "CategoryMatch"]]] = None,
    ) -> RiskMetrics:

        """Calculate risk indicator metrics."""
        risk_data = category_summary.get("risk", {})
        positive_data = category_summary.get("positive", {})

        # Gambling metrics
        gambling_total = risk_data.get("gambling", {}).get("total", 0)
        gambling_count = risk_data.get("gambling", {}).get("count", 0)

        total_income = income_metrics.total_income or 0.0
        if total_income > 0:
            gambling_pct = (gambling_total / total_income) * 100
        else:
            gambling_pct = 0.0

        # Failed payments (all time and 45 days)
        failed_count = 0

        try:
            if categorized_transactions:
                for txn, match in categorized_transactions:
                    if getattr(match, "category", None) != "expense":
                        continue
                    if getattr(match, "subcategory", None) not in ("unpaid", "unauthorised_overdraft"):
                        continue
                    failed_count += 1
        except Exception:
            failed_count = 0

        # --- Calculate last-45-days failed payments from categorised transactions ---
        failed_count_45d = 0

        try:
            if categorized_transactions:
                # Anchor to most recent txn date (stable across machines / run dates)
                anchor_date = None
                for txn, _m in categorized_transactions:
                    ds = txn.get("date")
                    if not ds:
                        continue
                    try:
                        d = datetime.strptime(ds, "%Y-%m-%d")
                    except ValueError:
                        continue
                    if anchor_date is None or d > anchor_date:
                        anchor_date = d

                if anchor_date is not None:
                    cutoff = anchor_date - timedelta(days=45)

                    for txn, match in categorized_transactions:
                        # Count failed-payment signals coming from expense categories
                        if getattr(match, "category", None) != "expense":
                            continue
                        if getattr(match, "subcategory", None) not in ("unpaid", "unauthorised_overdraft"):
                            continue

                        ds = txn.get("date")
                        if not ds:
                            continue
                        try:
                            d = datetime.strptime(ds, "%Y-%m-%d")
                        except ValueError:
                            continue

                        if d >= cutoff:
                            failed_count_45d += 1
        except Exception:
            failed_count_45d = 0

        # Bank charges proxy (all time and 90 days): unpaid + unauthorised_overdraft
        bank_charges_count = 0
        bank_charges_count_90d = 0

        try:
            if categorized_transactions:
                anchor_date = None
                for txn, _m in categorized_transactions:
                    ds = txn.get("date")
                    if not ds:
                        continue
                    try:
                        d = datetime.strptime(ds, "%Y-%m-%d")
                    except ValueError:
                        continue
                    if anchor_date is None or d > anchor_date:
                        anchor_date = d

                cutoff = (anchor_date - timedelta(days=90)) if anchor_date else None

                for txn, match in categorized_transactions:
                    if getattr(match, "category", None) != "expense":
                        continue
                    if getattr(match, "subcategory", None) not in {"unpaid", "unauthorised_overdraft"}:
                        continue

                    bank_charges_count += 1

                    if cutoff is not None:
                        ds = txn.get("date")
                        if not ds:
                            continue
                        try:
                            d = datetime.strptime(ds, "%Y-%m-%d")
                        except ValueError:
                            continue
                        if d >= cutoff:
                            bank_charges_count_90d += 1

        except Exception:
            bank_charges_count = 0
            bank_charges_count_90d = 0

        # Debt collection
        dca_count = risk_data.get("debt_collection", {}).get("count", 0)
        dca_distinct = risk_data.get("debt_collection", {}).get("distinct_dcas", 0)

        # New credit providers in last 90 days
        debt_data = category_summary.get("debt", {})
        new_credit_providers_90d = debt_data.get("hcstc_payday", {}).get(
            "new_credit_providers_90d", 0
        )

        # Savings activity
        savings_total = positive_data.get("savings", {}).get("total", 0)

        # Concern flags
        has_gambling_concern = gambling_pct > 5 or gambling_count > 5
        has_failed_payment_concern = failed_count >= 3
        has_dca_concern = dca_distinct >= 2
        has_bank_charges_concern = (
            bank_charges_count_90d > 2
        )  # Allow 1-2 bank charges without referral
        has_new_credit_burst = (
            new_credit_providers_90d >= 5
        )  # Allow up to 4 new credit providers without referral

        # NEW: Calculate savings behavior score (positive indicator)
        # Regular savers demonstrate financial discipline
        if savings_total > 100:
            savings_behavior_score = 3.0  # Regular saver
        elif savings_total > 0:
            savings_behavior_score = 1.5  # Some savings
        else:
            savings_behavior_score = 0.0  # No detected savings

        logger.debug(
            "[RISK DEBUG] failed_payments_count=%s | failed_payments_count_45d=%s",
            failed_count,
            failed_count_45d,
        )

        return RiskMetrics(
            gambling_total=round(gambling_total, 2),
            gambling_percentage=round(gambling_pct, 1),
            gambling_frequency=gambling_count,
            failed_payments_count=failed_count,
            failed_payments_count_45d=failed_count_45d,
            debt_collection_activity=dca_count,
            debt_collection_distinct=dca_distinct,
            bank_charges_count=bank_charges_count,
            bank_charges_count_90d=bank_charges_count_90d,
            new_credit_providers_90d=new_credit_providers_90d,
            savings_activity=round(savings_total, 2),
            has_gambling_concern=has_gambling_concern,
            has_failed_payment_concern=has_failed_payment_concern,
            has_debt_collection_concern=has_dca_concern,
            has_bank_charges_concern=has_bank_charges_concern,
            has_new_credit_burst=has_new_credit_burst,
            savings_behavior_score=savings_behavior_score,
        )
