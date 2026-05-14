"""
Transaction Categorizer for HCSTC Loan Scoring.
Categorizes UK consumer banking transactions for affordability assessment.
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta

from openbanking_engine import patterns

try:
    from rapidfuzz import fuzz as _fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    _fuzz = None
    RAPIDFUZZ_AVAILABLE = False



from ..patterns.transaction_patterns import (
    INCOME_PATTERNS,
    TRANSFER_PATTERNS,
    DEBT_PATTERNS,
    ESSENTIAL_PATTERNS,
    RISK_PATTERNS,
    EXPENSE_PATTERNS,
    POSITIVE_PATTERNS,
)

from ..income.income_detector import IncomeDetector


# HCSTC Lender Canonical Name Mappings
# Maps variations of lender names to a single canonical identifier
HCSTC_LENDER_CANONICAL_NAMES = {
    "LENDING STREAM": "LENDING_STREAM",
    "LENDINGSTREAM": "LENDING_STREAM",
    "DRAFTY": "DRAFTY",
    "MR LENDER": "MR_LENDER",
    "MRLENDER": "MR_LENDER",
    "MONEYBOAT": "MONEYBOAT",
    "CREDITSPRING": "CREDITSPRING",
    "CASHFLOAT": "CASHFLOAT",
    "QUIDMARKET": "QUIDMARKET",
    "QUID MARKET": "QUIDMARKET",
    "LOANS 2 GO": "LOANS_2_GO",
    "LOANS2GO": "LOANS_2_GO",
    "CASHASAP": "CASHASAP",
    "POLAR CREDIT": "POLAR_CREDIT",
    "118 118 MONEY": "118_118_MONEY",
    "118118 MONEY": "118_118_MONEY",
    "118118MONEY": "118_118_MONEY",
    "THE MONEY PLATFORM": "THE_MONEY_PLATFORM",
    "MONEY PLATFORM": "THE_MONEY_PLATFORM",
    "FAST LOAN UK": "FAST_LOAN_UK",
    "FASTLOAN": "FAST_LOAN_UK",
    "CONDUIT": "CONDUIT",
    "SALAD MONEY": "SALAD_MONEY",
    "FAIR FINANCE": "FAIR_FINANCE",
    "SAVVY LOAN PRODUCTS LIMITED": "SAVVY_LOAN_PRODUCTS_LIMITED",
    "LIKELY LOANS": "LIKELY_LOANS",

}

# Pre-computed sorted patterns (longest first) for efficient matching
# This avoids sorting on every call to _normalize_hcstc_lender
HCSTC_LENDER_PATTERNS_SORTED = sorted(
    HCSTC_LENDER_CANONICAL_NAMES.items(),
    key=lambda x: len(x[0]),
    reverse=True
)


@dataclass
class CategoryMatch:
    """Result of transaction categorization."""
    category: str
    subcategory: str
    confidence: float
    description: str
    match_method: str  # 'keyword', 'regex', 'fuzzy', 'plaid'
    risk_level: Optional[str] = None
    weight: float = 1.0
    is_stable: bool = False
    is_housing: bool = False
    debug_rationale: Optional[str] = None  # Optional debug information


class TransactionCategorizer:
    """Categorizes transactions for HCSTC loan scoring."""

    # Minimum confidence threshold for fuzzy matching
    FUZZY_THRESHOLD = 80

    # Transfer promotion thresholds (in pounds)
    # Minimum amount for company suffix to trigger promotion
    COMPANY_SUFFIX_MIN_AMOUNT = 200.0
    # Minimum amount for Faster Payment prefix to trigger promotion
    FASTER_PAYMENT_MIN_AMOUNT = 200.0
    # Minimum amount for large named payment promotion
    LARGE_PAYMENT_MIN_AMOUNT = 500.0

    # Salary detection keywords (used to identify legitimate salary payments)
    SALARY_KEYWORDS = [
        "SALARY", "WAGES", "PAYROLL", "NET PAY", "WAGE",
        "PAYSLIP", "EMPLOYER", "EMPLOYERS",
        "BGC", "BANK GIRO CREDIT", "CHEQUERS CONTRACT",
        "CONTRACT PAY", "MONTHLY PAY", "WEEKLY PAY"
    ]

    # Keywords that indicate internal transfers (not income)
    TRANSFER_EXCLUSION_KEYWORDS = ["OWN ACCOUNT", "INTERNAL", "SELF TRANSFER"]

    # Known expense services that should not be treated as income
    # These are payment processors, BNPL services, and lenders that might
    # have keywords like "PAY" or "PAYMENT" but are expenses, not income
    # Stored as set for O(1) lookup performance
    KNOWN_EXPENSE_SERVICES = {
        # Payment processors
        "PAYPAL", "STRIPE", "SQUARE", "WORLDPAY", "SAGEPAY",
        # BNPL services (already in debt patterns but listed for clarity)
        "CLEARPAY", "KLARNA", "ZILCH", "LAYBUY", "MONZO FLEX",
        # HCSTC Lenders (already in debt patterns but listed for clarity)
        "LENDING STREAM", "LENDINGSTREAM", "MONEYBOAT", "DRAFTY",
        "CASHFLOAT", "QUIDMARKET", "MR LENDER", "MRLENDER",
        "SAVVY LOAN PRODUCTS LIMITED", "LIKELY LOANS",
        # Additional loan providers
        "LENDABLE", "ZOPA", "TOTALSA", "AQUA", "HSBC LOANS",
        "VISA DIRECT PAYMENT", "BARCLAYS CASHBACK",
        "BAMBOO", "BAMBOO LTD",
        "FERNOVO", "OAKBROOK", "OAKBROOK FINANCE", "OAKBROOK FINANCE LIMITED",
        "CREDIT UNION", "CREDIT UNION PAYMENT", "CU ",

    }

    def __init__(self, debug_mode: bool = False):
        """Initialize the categorizer with pattern dictionaries.

        Args:
            debug_mode: If True, emit detailed rationale for categorization decisions
        """
        self.income_patterns = INCOME_PATTERNS
        self.transfer_patterns = TRANSFER_PATTERNS
        self.debt_patterns = DEBT_PATTERNS
        self.essential_patterns = ESSENTIAL_PATTERNS
        self.risk_patterns = RISK_PATTERNS
        self.expense_patterns = EXPENSE_PATTERNS
        self.positive_patterns = POSITIVE_PATTERNS
        self.income_detector = IncomeDetector()
        self.debug_mode = debug_mode

    def categorize_transaction(
        self,
        description: str,
        amount: float,
        merchant_name: Optional[str] = None,
        plaid_category: Optional[str] = None,
        plaid_category_primary: Optional[str] = None
    ) -> CategoryMatch:
        """
        Categorize a single transaction.

        Args:
            description: Transaction description/name
            amount: Transaction amount (negative = credit, positive = debit)
            merchant_name: Optional merchant name from PLAID
            plaid_category: Optional PLAID category (personal_finance_category.detailed)
            plaid_category_primary: Optional PLAID primary category (personal_finance_category.primary)

        Returns:
            CategoryMatch with categorization result
        """
        # Normalize text for matching
        text = self._normalize_text(description)
        merchant_text = self._normalize_text(merchant_name) if merchant_name else ""
        combined_text = f"{text} {merchant_text}".strip()

        # Determine if income or expense based on PLAID amount convention.
        # In PLAID format: Negative amounts = credits (money IN to account),
        # Positive amounts = debits (money OUT of account).
        # This is the opposite of typical accounting where negative = outflow.
        is_credit = amount < 0

        if is_credit:
            return self._categorize_income(combined_text, text, amount, plaid_category, plaid_category_primary)
        else:
            return self._categorize_expense(combined_text, text, plaid_category)

    def _normalize_text(self, text: Optional[str]) -> str:
        """Normalize text for matching."""
        if not text:
            return ""
        # Convert to uppercase for matching
        return text.upper().strip()

    def _build_debug_rationale(self, match_type: str, details: str = "") -> Optional[str]:
        """Build debug rationale string if debug mode is enabled.

        Args:
            match_type: Type of match (e.g., 'plaid_detailed', 'keyword', 'transfer_pairing')
            details: Additional details about the match

        Returns:
            Debug rationale string if debug_mode is True, None otherwise
        """
        if not self.debug_mode:
            return None

        if details:
            return f"{match_type}: {details}"
        return match_type

    def _find_transfer_pair(
        self,
        transactions: List[Dict],
        current_idx: int,
        amount: float,
        description: str,
        date_str: str
    ) -> Optional[Dict]:
        """Find potential transfer pair for this transaction (debit/credit matching).

        Args:
            transactions: Full list of transactions
            current_idx: Index of current transaction
            amount: Transaction amount
            description: Transaction description
            date_str: Transaction date string (YYYY-MM-DD)

        Returns:
            Matching transaction dict if found, None otherwise
        """
        if not transactions or not date_str:
            return None

        try:
            from datetime import datetime, timedelta
            current_date = datetime.strptime(date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            return None

        # Normalize description for comparison
        norm_desc = self._normalize_text(description)
        if len(norm_desc) < 3:  # Too short to match reliably
            return None

        # Look for opposite-signed transaction within 1-2 days
        for i, txn in enumerate(transactions):
            if i == current_idx:
                continue

            txn_amount = txn.get("amount", 0)
            # Look for opposite sign
            if (amount < 0 and txn_amount >= 0) or (amount >= 0 and txn_amount < 0):
                # Check amount similarity (within 5-10%)
                abs_amount = abs(amount)
                abs_txn_amount = abs(txn_amount)
                if abs_amount == 0:
                    continue

                amount_diff = abs(abs_amount - abs_txn_amount) / abs_amount
                if amount_diff > 0.10:  # More than 10% different
                    continue

                # Check date proximity (within 1-2 days)
                txn_date_str = txn.get("date", "")
                if not txn_date_str:
                    continue

                try:
                    txn_date = datetime.strptime(txn_date_str, "%Y-%m-%d")
                    days_diff = abs((current_date - txn_date).days)
                    if days_diff > 2:
                        continue
                except (ValueError, TypeError):
                    continue

                # Check description overlap
                txn_desc = self._normalize_text(txn.get("name", ""))
                if len(txn_desc) < 3:
                    continue

                # Simple overlap check: find common words
                desc_words = set(norm_desc.split())
                txn_words = set(txn_desc.split())
                if not desc_words or not txn_words:
                    continue

                common_words = desc_words.intersection(txn_words)
                # Require at least 30% overlap
                overlap_ratio = len(common_words) / min(len(desc_words), len(txn_words))
                if overlap_ratio >= 0.30:
                    return txn

        return None

    def _normalize_hcstc_lender(self, merchant_name: str) -> Optional[str]:
        """
        Normalize HCSTC lender name to canonical form.

        Args:
            merchant_name: Raw merchant/transaction name

        Returns:
            Canonical lender name if recognized, None otherwise
        """
        if not merchant_name:
            return None

        upper_name = merchant_name.upper()

        # Use pre-sorted patterns (longest first) to ensure most specific match
        # This prevents "LENDING" from matching "MR LENDER" before "LENDING STREAM"
        for pattern, canonical in HCSTC_LENDER_PATTERNS_SORTED:
            if pattern in upper_name:
                return canonical

        return None

    def _should_promote_transfer_to_income(
        self,
        description: str,
        amount: float,
        plaid_category: Optional[str],
        plaid_category_primary: Optional[str]
    ) -> Tuple[bool, float, str]:
        """
        Determine if a TRANSFER_IN should be promoted to income.

        This rescues legitimate salary/wages that Plaid mislabeled as transfers.

        Returns:
            (should_promote, confidence, reason)
        """
        if amount >= 0:  # Not a credit
            return (False, 0.0, "not_credit")

        desc_upper = description.upper()

        # EXCLUSIONS: These are real transfers or loan proceeds, do NOT promote
        exclusion_keywords = [
            "OWN ACCOUNT", "INTERNAL", "SELF TRANSFER",
            "FROM SAVINGS", "TO SAVINGS", "MOVED FROM", "MOVED TO",
            "POT", "VAULT", "ROUND UP", "ISA TRANSFER"
        ]
        if any(kw in desc_upper for kw in exclusion_keywords):
            return (False, 0.0, "excluded_internal_transfer")

        # EXCLUSION: Loan-related descriptions should not be promoted to income
        loan_exclusion_keywords = [
            "LOAN DISBURSEMENT", "LOAN ADVANCE", "LOAN PAYOUT",
            "PERSONAL LOAN", "PAYDAY LOAN", "SHORT TERM LOAN",
        ]
        if any(kw in desc_upper for kw in loan_exclusion_keywords):
            return (False, 0.0, "excluded_loan_disbursement")

        # EXCLUSION: Known HCSTC/loan lenders should not be promoted
        if self.income_detector._looks_like_loan_disbursement(description, plaid_category):
            return (False, 0.0, "excluded_loan_lender")

        # STRONG SIGNALS: Promote with high confidence

        # 1. Gig economy payouts (check FIRST - more specific than "WEEKLY PAY")
        gig_keywords = [
            "UBER", "DELIVEROO", "JUST EAT", "STRIPE PAYOUT",
            "PAYPAL PAYOUT", "SHOPIFY PAYMENTS"
        ]
        if any(kw in desc_upper for kw in gig_keywords):
            return (True, 0.85, "transfer_promoted_gig_payout")

        # 2. Explicit payroll keywords
        payroll_keywords = [
            "SALARY", "WAGES", "PAYROLL", "NET PAY", "WAGE",
            "PAYSLIP", "EMPLOYER", "MONTHLY PAY", "WEEKLY PAY",
            "BGC", "BANK GIRO CREDIT", "BACS CREDIT"
        ]
        if any(kw in desc_upper for kw in payroll_keywords):
            return (True, 0.95, "transfer_promoted_payroll_keyword")

        # 3. Company suffix (LTD, LIMITED, PLC, etc.) + meaningful amount
        if re.search(r'\b(LTD|LIMITED|PLC|LLP|INC|CORP)\b', desc_upper):
            if abs(amount) >= self.COMPANY_SUFFIX_MIN_AMOUNT:
                return (True, 0.90, "transfer_promoted_company_suffix")

        # 4. Faster Payment (FP-) prefix - common for salary
        if desc_upper.startswith("FP-") or " FP-" in desc_upper:
            if abs(amount) >= self.FASTER_PAYMENT_MIN_AMOUNT:
                return (True, 0.88, "transfer_promoted_faster_payment")

        # 5. Benefits keywords
        benefit_keywords = [
            "UNIVERSAL CREDIT", "DWP", "CHILD BENEFIT",
            "PIP", "DLA", "ESA", "JSA", "HMRC"
        ]
        if any(kw in desc_upper for kw in benefit_keywords):
            return (True, 0.92, "transfer_promoted_benefits")

        # 6. Large one-off payment from named entity (not generic "PAYMENT")
        if abs(amount) >= self.LARGE_PAYMENT_MIN_AMOUNT:
            # Check if description has specific words (not just "PAYMENT" or "TRANSFER")
            generic_words = ["PAYMENT", "TRANSFER", "CREDIT", "DEBIT", "TFR"]
            words = desc_upper.split()
            specific_words = [w for w in words if w not in generic_words and len(w) > 3]

            if len(specific_words) >= 2:  # Has meaningful identifier
                return (True, 0.75, "transfer_promoted_large_named_payment")

        # DEFAULT: Do not promote
        return (False, 0.0, "transfer_not_promoted")

    def _looks_like_employer_name(self, description: str) -> bool:
        """
        Check if description looks like an employer name.

        Returns True if description contains:
        - Company suffix (LTD, LIMITED, PLC, etc.)
        - Multiple words (not just "PAYMENT" or "TRANSFER")
        - Proper capitalization pattern
        """
        if not description:
            return False

        desc_upper = description.upper()

        # Check for company suffix
        if not re.search(r'\b(LTD|LIMITED|PLC|LLP|INC|CORP|CORPORATION)\b', desc_upper):
            return False

        # Check for generic words that indicate it's NOT an employer
        generic_only = ["PAYMENT", "TRANSFER", "CREDIT", "DEBIT", "FROM", "TO"]
        words = [w for w in desc_upper.split() if len(w) > 2]
        specific_words = [w for w in words if w not in generic_only]

        # Need at least 2 specific words + company suffix
        return len(specific_words) >= 2


    def _check_strict_plaid_categories(
        self,
        plaid_category_detailed: Optional[str]
    ) -> Optional[CategoryMatch]:

        if not plaid_category_detailed:
            return None

        detailed_upper = str(plaid_category_detailed).strip().upper()

        # Check specific TRANSFER_IN categories BEFORE generic TRANSFER_IN
        # This ensures more specific matches take precedence

        # Loan disbursements are NOT income (weight=0.0)
        if detailed_upper == "TRANSFER_IN_CASH_ADVANCES_AND_LOANS":
            return CategoryMatch(
                category="income",
                subcategory="loans",
                confidence=0.98,
                description="Loan Payments/Disbursements",
                match_method="plaid_strict",
                weight=0.0,
                is_stable=False
            )

        # === TRANSFER IN → HOLDING CATEGORY (NOT INCOME BY DEFAULT) ===
        # Plaid often labels true income (e.g., salary via Faster Payments) as TRANSFER_IN.
        # We therefore treat TRANSFER_IN as a holding state and allow the IncomeDetector
        # to reclassify it into income where appropriate.
        # EXCEPT: Explicit account transfers should remain as transfers
        if detailed_upper.startswith("TRANSFER_IN"):
            # Both account transfers and generic TRANSFER_IN use category="transfer"
            # so they enter the fallback/promotion path. This allows strong income
            # signals (DWP, salary keywords, etc.) to override Plaid's label.
            if "ACCOUNT_TRANSFER" in detailed_upper:
                return CategoryMatch(
                    category="transfer",
                    subcategory="account_transfer",
                    confidence=0.98,
                    description="Account Transfer In",
                    match_method="plaid_strict",
                    weight=0.75,
                    is_stable=False
                )
            return CategoryMatch(
                category="transfer",
                subcategory="in",
                confidence=0.98,
                description="Plaid Transfer In",
                match_method="plaid_strict",
                weight=0.75,
                is_stable=False
            )

        # === TRANSFER OUT → HANDLE ACCOUNT TRANSFERS SPECIALLY ===
        if detailed_upper.startswith("TRANSFER_OUT"):
            # Explicit account transfers should be categorized as transfers, not expenses
            if "ACCOUNT_TRANSFER" in detailed_upper:
                return CategoryMatch(
                    category="expense",
                    subcategory="account_transfer",
                    confidence=0.98,
                    description="Account Transfer Out",
                    match_method="plaid_strict",
                    weight=0.75,
                    is_stable=False
                )
            # Other TRANSFER_OUT (e.g., payments) are expenses
            return CategoryMatch(
                category="expense",
                subcategory="other",
                confidence=0.98,
                description="Plaid Transfer Out",
                match_method="plaid_strict",
                weight=0.75,
                is_stable=False
            )

        # === EXPENSE SUBCATEGORIES → STRICT PLAID MAPPINGS ===
        # These take precedence over keyword matching to ensure PLAID categorization is preserved
        if "BANK_FEES_INSUFFICIENT_FUNDS" in detailed_upper:
            return CategoryMatch(
                category="expense",
                subcategory="unpaid",
                confidence=0.98,
                description="Unpaid/Returned/NSF Fees",
                match_method="plaid_strict",
                weight=1.0,
                is_stable=False
            )

        if "BANK_FEES_OVERDRAFT" in detailed_upper:
            return CategoryMatch(
                category="expense",
                subcategory="unauthorised_overdraft",
                confidence=0.98,
                description="Overdraft Fees",
                match_method="plaid_strict",
                weight=1.0,
                is_stable=False
            )

        if "ENTERTAINMENT_CASINOS_AND_GAMBLING" in detailed_upper:
            return CategoryMatch(
                category="expense",
                subcategory="gambling",
                confidence=0.98,
                description="Gambling",
                match_method="plaid_strict",
                weight=1.0,
                is_stable=False
            )

        return None

    def _categorize_income(
        self,
        combined_text: str,
        description: str,
        amount: float,
        plaid_category: Optional[str],
        plaid_category_primary: Optional[str] = None
    ) -> CategoryMatch:
        """Categorize an income transaction (credit)."""

        # STEP 0A: Check strict PLAID categories FIRST (before any other logic)
        # BUT:  Ignore TRANSFER_OUT categories when amount is negative (Plaid error)
        plaid_detailed_upper = (plaid_category or "").upper()
        if "TRANSFER_OUT" in plaid_detailed_upper:
            # Skip Plaid's strict categorization - it's wrong for negative amounts
            strict_match = None
        else:
            strict_match = self._check_strict_plaid_categories(plaid_category)

        # IMPORTANT:
        # - Some Plaid TRANSFER_IN entries are genuine income (e.g. salary via Faster Payments)
        # - Treat TRANSFER_IN as a holding category and allow IncomeDetector to reclassify it
        # - EXCEPT: Explicit account transfers (TRANSFER_IN_ACCOUNT_TRANSFER) should remain as transfers
        transfer_fallback = None
        if strict_match:
            if strict_match.category != "transfer":
                return strict_match
            # All TRANSFER_IN variants (including account_transfer) enter the
            # fallback path so promotion logic can rescue salary/benefits/gig signals.
            transfer_fallback = strict_match


        # STEP 0B: TRANSFER PROMOTION (runs before known-expense check, aligned with batch path)
        # Check if this TRANSFER_IN should be promoted to income
        if transfer_fallback is not None:
            should_promote, confidence, reason = self._should_promote_transfer_to_income(
                description=description,
                amount=amount,
                plaid_category=plaid_category,
                plaid_category_primary=plaid_category_primary
            )

            if should_promote:
                # Determine subcategory from reason
                if "payroll" in reason or "faster_payment" in reason or "company_suffix" in reason:
                    subcategory = "salary"
                    desc = "Salary & Wages"
                elif "benefits" in reason:
                    subcategory = "benefits"
                    desc = "Benefits & Government"
                elif "gig_payout" in reason:
                    subcategory = "gig_economy"
                    desc = "Gig Economy Income"
                else:
                    subcategory = "other"
                    desc = "Other Income"

                return CategoryMatch(
                    category="income",
                    subcategory=subcategory,
                    confidence=confidence,
                    description=desc,
                    match_method=reason,
                    weight=1.0,
                    is_stable=(subcategory in ["salary", "benefits"]),
                    debug_rationale=self._build_debug_rationale("transfer_promotion", reason)
                )

        # STEP 0C: Known expense services should not be treated as income
        # EXCEPT when it's a payout (gig economy income)
        matched_service = None
        for service in self.KNOWN_EXPENSE_SERVICES:
            if service in combined_text:
                matched_service = service
                break
        if matched_service:
            # Allow STRIPE PAYOUT, PAYPAL PAYOUT, SHOPIFY PAYMENTS to pass through
            if "PAYOUT" in combined_text or "DISBURSEMENT" in combined_text:
                pass
            elif plaid_category_primary:
                plaid_primary_upper = plaid_category_primary.upper()

                if "LOAN_PAYMENTS" in plaid_primary_upper:
                    return CategoryMatch(
                        category="income",
                        subcategory="loans",
                        confidence=0.95,
                        description="Loan Payments/Disbursements",
                        match_method="plaid",
                        weight=0.0,
                        is_stable=False
                    )

                if "TRANSFER" in plaid_primary_upper:
                    return CategoryMatch(
                        category="transfer",
                        subcategory="internal",
                        confidence=0.90,
                        description="Plaid Transfer",
                        match_method="plaid",
                        weight=0.0,
                        is_stable=False
                    )

                return CategoryMatch(
                    category="income",
                    subcategory="other",
                    confidence=0.50,
                    description="Other Income",
                    match_method="known_service_exclusion",
                    weight=1.0,
                    is_stable=False
                )
            else:
                return CategoryMatch(
                    category="income",
                    subcategory="other",
                    confidence=0.50,
                    description="Other Income",
                    match_method="known_service_exclusion",
                    weight=1.0,
                    is_stable=False
                )


        # STEP 1: Check PLAID categories for high-confidence loan/transfer indicators
        # BEFORE applying keyword-based income detection
        # This preserves PLAID's accurate categorization of loan payments and transfers
        if plaid_category or plaid_category_primary:
            plaid_cat_upper = (plaid_category or "").upper()
            plaid_primary_upper = (plaid_category_primary or "").upper()

            # Check for LOAN_PAYMENTS category - these are loan disbursements/refunds, NOT income
            # CRITICAL: This must be checked BEFORE keyword-based income detection to prevent
            # loan disbursements from being miscategorized as salary/income
            if "LOAN_PAYMENTS" in plaid_primary_upper or "LOAN_PAYMENTS" in plaid_cat_upper:
                return CategoryMatch(
                    category="income",
                    subcategory="loans",
                    confidence=0.95,
                    description="Loan Payments/Disbursements",
                    match_method="plaid",
                    weight=0.0,  # Not counted as income
                    is_stable=False
                )

            # Check for TRANSFER_IN with CASH_ADVANCES or LOANS
            # These are loan disbursements, should be categorized as income > loans with weight=0.0
            if "CASH_ADVANCES" in plaid_cat_upper or "ADVANCES" in plaid_cat_upper or "LOANS" in plaid_cat_upper:
                # This is likely a cash advance or loan disbursement
                return CategoryMatch(
                    category="income",
                    subcategory="loans",
                    confidence=0.95,
                    description="Loan Payments/Disbursements",
                    match_method="plaid",
                    weight=0.0,
                    is_stable=False
                )

            # Credit union handling (incoming loan proceeds vs outgoing repayments)
            desc_upper = (description or "").upper()
            if "CREDIT UNION" in desc_upper or "CU " in desc_upper:
                if amount < 0:
                    # incoming: treat as loan proceeds (NOT income)
                    return CategoryMatch(
                        category="income",
                        subcategory="loans",
                        confidence=0.90,
                        description="Credit Union Loan Proceeds",
                        match_method="keyword_credit_union",
                        weight=0.0,
                        is_stable=False
                    )
                else:
                    # outgoing: treat as debt repayment
                    return CategoryMatch(
                        category="debt",
                        subcategory="other_loans",
                        confidence=0.90,
                        description="Credit Union Loan Repayment",
                        match_method="keyword_credit_union",
                        weight=1.0,
                        is_stable=False
                    )

        # STEP 2: SIMPLIFIED - Check PLAID INCOME_WAGES first (Pragmatic Fix)
        # Use simplified income detector (PLAID-first only, no behavioral)
        is_income, confidence, reason = self.income_detector.is_likely_income(
            description=description,
            amount=amount,
            plaid_category_primary=plaid_category_primary,
            plaid_category_detailed=plaid_category
        )

        # If the income detector explicitly identified this as a loan disbursement,
        # return immediately (don't fall through to keyword matching where gig patterns fire)
        if not is_income and reason == "loan_disbursement":
            return CategoryMatch(
                category="income",
                subcategory="loans",
                confidence=0.90,
                description="Loan Disbursements/Refunds (Not Income)",
                match_method="income_detector_loan",
                weight=0.0,
                is_stable=False
            )

        # If PLAID identifies as income with high confidence, trust it
        if is_income and confidence >= 0.85:
            # Determine subcategory based on reason
            if "wages" in reason or "salary" in reason:
                return CategoryMatch(
                    category="income",
                    subcategory="salary",
                    confidence=confidence,
                    description="Salary & Wages",
                    match_method=f"plaid_{reason}",
                    weight=1.0,
                    is_stable=True,
                    debug_rationale=self._build_debug_rationale("income_detection", reason)
                )
            elif "interest" in reason:
                return CategoryMatch(
                    category="income",
                    subcategory="interest",
                    confidence=confidence,
                    description="Interest Income",
                    match_method=f"plaid_{reason}",
                    weight=1.0,
                    is_stable=True,
                    debug_rationale=self._build_debug_rationale("income_detection", reason)
                )
            elif "gig" in reason:
                return CategoryMatch(
                    category="income",
                    subcategory="gig_economy",
                    confidence=confidence,
                    description="Gig Economy Income",
                    match_method=f"plaid_{reason}",
                    weight=1.0,
                    is_stable=False,
                    debug_rationale=self._build_debug_rationale("income_detection", reason)
                )
            else:
                # Generic PLAID income - check if it matches specific patterns
                gig_match = self._check_gig_economy_patterns(combined_text)
                if gig_match:
                    return gig_match
                # Not gig economy, return as other income with lower weight
                return CategoryMatch(
                    category="income",
                    subcategory="other",
                    confidence=0.7,
                    description="Other Income",
                    match_method=f"plaid_{reason}",
                    # Weight 0.5 for unverifiable income (vs 1.0 for stable salary)
                    # This reflects that non-salary income is less reliable for affordability
                    weight=1.0,
                    is_stable=False,
                    debug_rationale=self._build_debug_rationale("income_detection", reason)
                )

        # STEP 3: Check income patterns (keyword matching ONLY)
        # No PLAID guessing or behavioral detection
        for subcategory, patterns in self.income_patterns.items():
            match = self._match_patterns(combined_text, patterns)
            if match:
                match_method, match_confidence = match

                return CategoryMatch(
                    category="income",
                    subcategory=subcategory,
                    confidence=match_confidence,
                    description=patterns.get("description", subcategory),
                    match_method=match_method,
                    weight=patterns.get("weight", 1.0),
                    is_stable=patterns.get("is_stable", False),
                    debug_rationale=self._build_debug_rationale("keyword_pattern_match", f"income/{subcategory}")
                )

        # STEP 4: Check for transfers (only if NOT identified as income above)
        if self._is_plaid_transfer(plaid_category_primary, plaid_category, description):
            return CategoryMatch(
                category="transfer",
                subcategory="internal",
                confidence=0.95,
                description="Internal Transfer",
                match_method="plaid",
                weight=0.0,
                is_stable=False
            )

        # Check if it's a transfer based on keywords (fallback)
        if self._is_transfer(combined_text):
            return CategoryMatch(
                category="transfer",
                subcategory="internal",
                confidence=0.90,
                description="Internal Transfer",
                match_method="keyword",
                weight=0.0,
                is_stable=False
            )

        # If we have a transfer fallback (e.g., Plaid TRANSFER_IN), keep it aside.
        # We still run income detection below (promotion/recurrence/keywords).
        # Only return transfer_fallback at the VERY end if nothing identifies income.
        pass

        # STEP 5: Unknown income (default with low weight)
        return CategoryMatch(
            category="income",
            subcategory="other",
            confidence=0.5,
            description="Other Income",
            match_method="default",
            weight=1.0,
            is_stable=False
        )

    def _check_credit_card_or_catalogue_debt(
        self,
        combined_text: str
    ) -> Optional[CategoryMatch]:
        """
        Check if transaction matches credit card or catalogue debt patterns.

        Helper method to avoid code duplication when checking for debt patterns
        before categorizing as groceries.

        Args:
            combined_text: Combined description and merchant text (normalized)

        Returns:
            CategoryMatch if debt pattern found, None otherwise
        """
        for subcategory, patterns in self.debt_patterns.items():
            if subcategory in ["credit_cards", "catalogue"]:
                match = self._match_patterns(combined_text, patterns)
                if match:
                    # This is a credit card or catalogue payment, not groceries
                    return CategoryMatch(
                        category="debt",
                        subcategory=subcategory,
                        confidence=match[1],
                        description=patterns.get("description", subcategory),
                        match_method=match[0],
                        risk_level=patterns.get("risk_level", "medium")
                    )
        return None

    def _categorize_expense(
        self,
        combined_text: str,
        description: str,
        plaid_category: Optional[str]
    ) -> CategoryMatch:
        """Categorize an expense transaction (debit)."""

        # STEP 1: Check strict PLAID categories FIRST
        strict_match = self._check_strict_plaid_categories(plaid_category)
        if strict_match:
            return strict_match


        # Fallback to keyword/regex transfer detection
        # IMPORTANT: do NOT treat "standing order" alone as a transfer (rent/bills are often standing orders)
        if self._is_transfer(combined_text) and not re.search(r"(?i)\bstanding\s*order\b", combined_text):
            return CategoryMatch(
                category="transfer",
                subcategory="internal",
                confidence=0.90,
                description="Internal Transfer",
                match_method="keyword",
                weight=0.0,
                is_stable=False
            )

        # STEP 2: Check risk patterns (highest priority)
        for subcategory, patterns in self.risk_patterns.items():
            match = self._match_patterns(combined_text, patterns)
            if match:
                return CategoryMatch(
                    category="risk",
                    subcategory=subcategory,
                    confidence=match[1],
                    description=patterns.get("description", subcategory),
                    match_method=match[0],
                    risk_level=patterns.get("risk_level", "medium")
                )

        # STEP 3: Check expense patterns (after risk patterns)
        for subcategory, patterns in self.expense_patterns.items():
            match = self._match_patterns(combined_text, patterns)
            if match:
                return CategoryMatch(
                    category="expense",
                    subcategory=subcategory,
                    confidence=match[1],
                    description=patterns.get("description", subcategory),
                    match_method=match[0]
                )

        # SIMPLIFIED: Let keyword patterns drive categorization naturally
        # No PLAID defaults that override keyword matching (Pragmatic Fix)

        # Special case: If description contains BANK or CREDIT CARD indicators, check debt first
        # This handles "SAINSBURYS BANK" vs "SAINSBURYS" distinction
        # NOTE: bare "CARD" was removed -- it matched every "CARD PAYMENT TO ..." debit card purchase
        if any(indicator in combined_text for indicator in ["BANK", "CREDIT CARD", "BARCLAYCARD"]):
            # Check debt patterns first for financial institutions
            for subcategory, patterns in self.debt_patterns.items():
                match = self._match_patterns(combined_text, patterns)
                if match:
                    return CategoryMatch(
                        category="debt",
                        subcategory=subcategory,
                        confidence=match[1],
                        description=patterns.get("description", subcategory),
                        match_method=match[0],
                        risk_level=patterns.get("risk_level", "medium")
                    )

        # Check essential patterns BEFORE debt patterns (for non-bank transactions)
        # This prevents grocery stores from being miscategorized as credit card/catalogue debt
        for subcategory, patterns in self.essential_patterns.items():
            match = self._match_patterns(combined_text, patterns)
            if match:
                return CategoryMatch(
                    category="essential",
                    subcategory=subcategory,
                    confidence=match[1],
                    description=patterns.get("description", subcategory),
                    match_method=match[0],
                    is_housing=patterns.get("is_housing", False)
                )

        # Check debt patterns AFTER essential patterns
        for subcategory, patterns in self.debt_patterns.items():
            match = self._match_patterns(combined_text, patterns)
            if match:
                return CategoryMatch(
                    category="debt",
                    subcategory=subcategory,
                    confidence=match[1],
                    description=patterns.get("description", subcategory),
                    match_method=match[0],
                    risk_level=patterns.get("risk_level", "medium")
                )

        # IMPORTANT: Use PLAID category fallback BEFORE checking positive patterns
        # This prevents "positive" keyword collisions (e.g., CHIP vs Chipotle)
        # This preserves high-confidence PLAID categorizations (e.g., gambling, restaurants)
        # Only fall back to generic expense/other if PLAID also doesn't have a match
        if plaid_category:
            plaid_match = self._match_plaid_category(plaid_category, is_income=False)
            if plaid_match:
                return plaid_match

        # Check positive patterns
        for subcategory, patterns in self.positive_patterns.items():
            match = self._match_patterns(combined_text, patterns)
            if match:
                return CategoryMatch(
                    category="positive",
                    subcategory=subcategory,
                    confidence=match[1],
                    description=patterns.get("description", subcategory),
                    match_method=match[0]
                )


        # Unknown expense (only reached if no patterns matched AND no PLAID category)
        return CategoryMatch(
            category="expense",
            subcategory="other",
            confidence=0.3,
            description="Other Expense",
            match_method="default"
        )

    def _check_gig_economy_patterns(self, combined_text: str) -> Optional[CategoryMatch]:
        """
        Check if transaction matches gig economy patterns.

        Helper method to avoid duplicate gig economy checking logic.

        Args:
            combined_text: Combined description and merchant text (normalized)

        Returns:
            CategoryMatch if gig economy pattern found, None otherwise
        """
        for subcategory, patterns in self.income_patterns.items():
            if subcategory == "gig_economy":
                match = self._match_patterns(combined_text, patterns)
                if match:
                    return CategoryMatch(
                        category="income",
                        subcategory=subcategory,
                        confidence=match[1],
                        description=patterns.get("description", subcategory),
                        match_method=match[0],
                        weight=patterns.get("weight", 1.0),
                        is_stable=patterns.get("is_stable", False)
                    )
        return None

    def _is_transfer(self, text: str) -> bool:
        """Check if transaction is an internal transfer."""
        patterns = self.transfer_patterns

        # Check keywords
        for keyword in patterns.get("keywords", []):
            if keyword.upper() in text:
                return True

        # Check regex patterns
        for pattern in patterns.get("regex_patterns", []):
            if re.search(pattern, text):
                return True

        return False

    def _contains_salary_keywords(self, text: str) -> bool:
        """
        Check if transaction description contains salary/income-related keywords.

        This is used to identify legitimate salary payments that PLAID may have
        miscategorized as transfers (e.g., BANK GIRO CREDIT, FP- prefix payments).

        Args:
            text: Transaction description text (should be uppercase)

        Returns:
            True if salary keywords are found, False otherwise
        """
        if not text:
            return False

        # Check for salary keywords
        for keyword in self.SALARY_KEYWORDS:
            if keyword in text:
                return True

        # Check for FP- prefix (Faster Payments for salary)
        if text.startswith("FP-") or " FP-" in text:
            return True

        # Check for patterns like "COMPANY NAME LTD" or "COMPANY NAME LIMITED"
        # These often indicate employer payments
        if re.search(r'\b(LTD|LIMITED|PLC)\b', text):
            # But only if it doesn't contain obvious transfer keywords
            if not any(kw in text for kw in self.TRANSFER_EXCLUSION_KEYWORDS):
                return True

        return False

    def _is_plaid_transfer(
        self,
        plaid_category_primary: Optional[str],
        plaid_category_detailed: Optional[str],
        description: Optional[str] = None
    ) -> bool:
        """
        Check if transaction is a transfer based on Plaid categories.

        Args:
            plaid_category_primary: The primary Plaid category (e.g., "TRANSFER_IN")
            plaid_category_detailed: The detailed Plaid category (e.g., "TRANSFER_IN_ACCOUNT_TRANSFER")
            description: Optional transaction description to check for salary keywords

        Returns:
            True if the transaction is identified as a transfer, False otherwise
        """
        if not plaid_category_primary and not plaid_category_detailed:
            return False

        # Check primary category for transfer indicators
        if plaid_category_primary:
            primary_upper = plaid_category_primary.upper()
            if "TRANSFER_IN" in primary_upper or "TRANSFER_OUT" in primary_upper:
                # Before marking as transfer, check if description contains salary keywords
                # This catches legitimate salary payments that PLAID miscategorized
                if description and self._contains_salary_keywords(description.upper()):
                    return False  # Not a transfer - it's likely salary
                return True

        # Check detailed category for transfer indicators
        if plaid_category_detailed:
            detailed_upper = plaid_category_detailed.upper()
            # Look for transfer-related keywords in detailed category
            if "TRANSFER" in detailed_upper:
                # Before marking as transfer, check if description contains salary keywords
                if description and self._contains_salary_keywords(description.upper()):
                    return False  # Not a transfer - it's likely salary
                return True

        return False

    def _match_patterns(
        self,
        text: str,
        patterns: Dict
    ) -> Optional[Tuple[str, float]]:
        """
        Match text against pattern dictionary.

        Returns:
            Tuple of (match_method, confidence) or None if no match
        """
        # Check keyword matches first (fastest)
        for keyword in patterns.get("keywords", []):
            if keyword.upper() in text:
                return ("keyword", 0.95)

        # Check regex patterns
        for pattern in patterns.get("regex_patterns", []):
            if re.search(pattern, text, re.IGNORECASE):
                return ("regex", 0.90)

        # Try fuzzy matching if available
        if RAPIDFUZZ_AVAILABLE and _fuzz is not None:
            for keyword in patterns.get("keywords", []):
                score = _fuzz.token_set_ratio(keyword.upper(), text)
                if score >= self.FUZZY_THRESHOLD:
                    return ("fuzzy", score / 100.0)
        return None

    def _match_plaid_category(
        self,
        plaid_category: str,
        is_income: bool
    ) -> Optional[CategoryMatch]:
        """Map PLAID category to our categories."""
        if not plaid_category:
            return None

        plaid_upper = plaid_category.upper()

        # Check specific expense categories BEFORE generic patterns
        # This ensures more specific PLAID categories are matched first
        if not is_income:
            # PLAID expense category mappings (specific before generic)
            if "BANK_FEES_INSUFFICIENT_FUNDS" in plaid_upper or "INSUFFICIENT_FUNDS" in plaid_upper:
                return CategoryMatch(
                    category="expense",
                    subcategory="unpaid",
                    confidence=0.90,
                    description="Unpaid/Returned/NSF Fees",
                    match_method="plaid"
                )
            if "BANK_FEES_OVERDRAFT" in plaid_upper:
                return CategoryMatch(
                    category="expense",
                    subcategory="unauthorised_overdraft",
                    confidence=0.90,
                    description="Overdraft Fees",
                    match_method="plaid"
                )
            if "ENTERTAINMENT_CASINOS_AND_GAMBLING" in plaid_upper or ("CASINOS" in plaid_upper and "GAMBLING" in plaid_upper):
                return CategoryMatch(
                    category="expense",
                    subcategory="gambling",
                    confidence=0.85,
                    description="Gambling",
                    match_method="plaid"
                )
            if "GAMBLING" in plaid_upper or "CASINO" in plaid_upper:
                return CategoryMatch(
                    category="expense",
                    subcategory="gambling",
                    confidence=0.85,
                    description="Gambling",
                    match_method="plaid"
                )

        # Discretionary spending (PLAID detailed categories) - checked after specific patterns
        if not is_income and any(x in plaid_upper for x in [
        "GENERAL_MERCHANDISE",
            "ENTERTAINMENT",
            "SUBSCRIPTIONS",
            "PERSONAL_CARE"
        ]):
            return CategoryMatch(
                category="expense",
                subcategory="discretionary",
                confidence=0.90,
                description="Discretionary Spending",
                match_method="plaid",
                weight=1.0,
                is_stable=False
            )


        # Income categories
        if is_income:
            if "SALARY" in plaid_upper or "PAYROLL" in plaid_upper:
                return CategoryMatch(
                    category="income",
                    subcategory="salary",
                    confidence=0.85,
                    description="Salary & Wages",
                    match_method="plaid",
                    weight=1.0,
                    is_stable=True
                )
            if "GOVERNMENT" in plaid_upper or "BENEFIT" in plaid_upper:
                return CategoryMatch(
                    category="income",
                    subcategory="benefits",
                    confidence=0.85,
                    description="Benefits & Government",
                    match_method="plaid",
                    weight=1.0,
                    is_stable=True
                )
            if "PENSION" in plaid_upper or "RETIREMENT" in plaid_upper:
                return CategoryMatch(
                    category="income",
                    subcategory="pension",
                    confidence=0.85,
                    description="Pension Income",
                    match_method="plaid",
                    weight=1.0,
                    is_stable=True
                )

        # Expense categories
        else:
            if "RENT" in plaid_upper:
                return CategoryMatch(
                    category="essential",
                    subcategory="rent",
                    confidence=0.85,
                    description="Rent",
                    match_method="plaid",
                    is_housing=True
                )
            if "MORTGAGE" in plaid_upper:
                return CategoryMatch(
                    category="essential",
                    subcategory="mortgage",
                    confidence=0.85,
                    description="Mortgage",
                    match_method="plaid",
                    is_housing=True
                )
            if "UTILITY" in plaid_upper or "UTILITIES" in plaid_upper:
                return CategoryMatch(
                    category="essential",
                    subcategory="utilities",
                    confidence=0.85,
                    description="Utilities",
                    match_method="plaid"
                )
            if "GROCERY" in plaid_upper or "GROCERIES" in plaid_upper:
                return CategoryMatch(
                    category="essential",
                    subcategory="groceries",
                    confidence=0.85,
                    description="Groceries",
                    match_method="plaid"
                )
            # Food and dining categories
            if "RESTAURANT" in plaid_upper or "FOOD_AND_DRINK" in plaid_upper or "DINING" in plaid_upper:
                return CategoryMatch(
                    category="expense",
                    subcategory="food_dining",
                    confidence=0.85,
                    description="Food & Dining",
                    match_method="plaid"
                )
            if "LOAN" in plaid_upper:
                return CategoryMatch(
                    category="debt",
                    subcategory="other_loans",
                    confidence=0.80,
                    description="Loan Payment",
                    match_method="plaid",
                    risk_level="medium"
                )

        return None

    def categorize_transactions(
        self,
        transactions: List[Dict]
    ) -> List[Tuple[Dict, CategoryMatch]]:
        """
        Categorize a list of transactions.

        Args:
            transactions: List of transaction dictionaries

        Returns:
            List of tuples (transaction, category_match)
        """
        results = []

        for i, txn in enumerate(transactions):
            txn["_batch_index"] = i

            description = txn.get("name", "")
            amount = txn.get("amount", 0)
            merchant_name = txn.get("merchant_name")
            plaid_category = (
                txn.get("personal_finance_category.detailed")
                or txn.get("plaid_category_detailed")
            )

            plaid_category_primary = (
                txn.get("personal_finance_category.primary")
                or txn.get("plaid_category_primary")
            )

            # Handle nested PLAID category if present
            if "personal_finance_category" in txn:
                pfc = txn.get("personal_finance_category", {})
                if isinstance(pfc, dict):
                    if not plaid_category:
                        plaid_category = pfc.get("detailed")
                    if not plaid_category_primary:
                        plaid_category_primary = pfc.get("primary")

            category_match = self.categorize_transaction(
                description=description,
                amount=amount,
                merchant_name=merchant_name,
                plaid_category=plaid_category,
                plaid_category_primary=plaid_category_primary
            )

            results.append((txn, category_match))

        return results

    def categorize_transactions_batch(
        self,
        transactions: List[Dict]
    ) -> List[Tuple[Dict, CategoryMatch]]:
        """
        Categorize a list of transactions with optimized batch processing.

        This method is more efficient than categorize_transactions() for large
        transaction lists because it performs recurring pattern detection once
        for the entire batch, rather than potentially analyzing patterns for
        each individual transaction.

        Performance Benefits:
        - Single pass for recurring income detection (O(n²) once vs. potentially per-transaction)
        - Cached pattern lookup for individual categorizations (O(1) per transaction)
        - Dramatically faster for large transaction sets (100+ transactions)

        Args:
            transactions: List of transaction dictionaries with:
                - 'name': Transaction description
                - 'amount': Amount (negative for credits, positive for debits)
                - 'date': Transaction date (YYYY-MM-DD)
                - 'merchant_name': Optional merchant name
                - 'personal_finance_category': Optional PLAID category (dict or flat fields)

        Returns:
            List of tuples (transaction, category_match)

        Example:
            >>> categorizer = TransactionCategorizer()
            >>> transactions = [
            ...     {"name": "ACME LTD SALARY", "amount": -2500, "date": "2024-01-25"},
            ...     {"name": "TESCO", "amount": 45.50, "date": "2024-01-26"},
            ... ]
            >>> results = categorizer.categorize_transactions_batch(transactions)
            >>> for txn, match in results:
            ...     print(f"{txn['name']}: {match.category}/{match.subcategory}")
        """
        # Step 1: Analyze batch for recurring income patterns
        # This populates the income detector's cache with recurring sources
        self.income_detector.analyze_batch(transactions)
        self._current_batch_transactions = transactions


        try:
            # Step 2: Categorize each transaction using cached patterns
            results = []

            for idx, txn in enumerate(transactions):
                txn["_batch_index"] = idx

                description = txn.get("name", "")
                amount = txn.get("amount", 0)

                merchant_name = txn.get("merchant_name")
                plaid_category = (
                    txn.get("personal_finance_category.detailed")
                    or txn.get("plaid_category_detailed")
                )

                plaid_category_primary = (
                    txn.get("personal_finance_category.primary")
                    or txn.get("plaid_category_primary")
                )


                # Handle nested PLAID category if present
                if "personal_finance_category" in txn:
                    pfc = txn.get("personal_finance_category", {})
                    if isinstance(pfc, dict):
                        if not plaid_category:
                            plaid_category = pfc.get("detailed")
                        if not plaid_category_primary:
                            plaid_category_primary = pfc.get("primary")

                # Use optimized batch categorization
                category_match = self._categorize_transaction_from_batch(
                    description=description,
                    amount=amount,
                    transaction_index=idx,
                    merchant_name=merchant_name,
                    plaid_category=plaid_category,
                    plaid_category_primary=plaid_category_primary
                )

                results.append((txn, category_match))

            return results

        except Exception:
            # Only clean up on error; normal cleanup deferred to get_category_summary
            # or explicit cleanup_batch() call so recurring logic remains available
            self.income_detector.clear_batch_cache()
            self._current_batch_transactions = None
            raise


    def _categorize_transaction_from_batch(
        self,
        description: str,
        amount: float,
        transaction_index: int,
        merchant_name: Optional[str] = None,
        plaid_category: Optional[str] = None,
        plaid_category_primary: Optional[str] = None
    ) -> CategoryMatch:
        """
        Categorize a single transaction using cached batch patterns.

        Internal method used by categorize_transactions_batch(). Uses the
        income detector's cached recurring patterns for efficient categorization.

        Args:
            description: Transaction description/name
            amount: Transaction amount (negative = credit, positive = debit)
            transaction_index: Index in the batch (for pattern lookup)
            merchant_name: Optional merchant name from PLAID
            plaid_category: Optional PLAID category (personal_finance_category.detailed)
            plaid_category_primary: Optional PLAID primary category

        Returns:
            CategoryMatch with categorization result
        """
        # Normalize text for matching
        text = self._normalize_text(description)
        merchant_text = self._normalize_text(merchant_name) if merchant_name else ""
        combined_text = f"{text} {merchant_text}".strip()

        # Determine if income or expense
        is_credit = amount < 0

        if is_credit:
            return self._categorize_income_from_batch(
                combined_text,
                text,
                amount,
                transaction_index,
                plaid_category,
                plaid_category_primary
            )
        else:
            return self._categorize_expense(combined_text, text, plaid_category)

    def _categorize_income_from_batch(
        self,
        combined_text: str,
        description: str,
        amount: float,
        transaction_index: int,
        plaid_category: Optional[str],
        plaid_category_primary: Optional[str] = None
    ) -> CategoryMatch:
        """
        Categorize an income transaction using cached batch patterns.

        Internal method that uses the optimized is_likely_income_from_batch()
        which leverages pre-computed recurring patterns.
        """

        plaid_detailed_upper = (plaid_category or "").upper()
        plaid_primary_upper = (plaid_category_primary or "").upper()

        # STEP 0A: Check strict PLAID categories FIRST (before any other logic)
        # BUT:  Ignore TRANSFER_OUT categories when amount is negative (Plaid error)
        plaid_detailed_upper = (plaid_category or "").upper()
        if "TRANSFER_OUT" in plaid_detailed_upper:
            # Skip Plaid's strict categorization - it's wrong for negative amounts
            strict_match = None
        else:
            strict_match = self._check_strict_plaid_categories(plaid_category)

        # IMPORTANT:  TRANSFER_IN_ACCOUNT_TRANSFER is now categorized as income.
        # Other TRANSFER_IN types are treated as holding categories for potential promotion.
        transfer_fallback = None
        if strict_match:
            if strict_match.category != "transfer":
                return strict_match
            transfer_fallback = strict_match


        # **STEP 0B: AGGRESSIVE TRANSFER PROMOTION** (MOVED UP - MUST RUN FIRST)
        # Check if this TRANSFER_IN should be promoted to income
        if transfer_fallback is not None:
            should_promote, confidence, reason = self._should_promote_transfer_to_income(
                description=description,
                amount=amount,
                plaid_category=plaid_category,
                plaid_category_primary=plaid_category_primary
            )

            if should_promote:
                # Determine subcategory from reason
                if "payroll" in reason or "faster_payment" in reason or "company_suffix" in reason:
                    subcategory = "salary"
                    desc = "Salary & Wages"
                elif "benefits" in reason:
                    subcategory = "benefits"
                    desc = "Benefits & Government"
                elif "gig_payout" in reason:
                    subcategory = "gig_economy"
                    desc = "Gig Economy Income"
                else:
                    subcategory = "other"
                    desc = "Other Income"

                return CategoryMatch(
                    category="income",
                    subcategory=subcategory,
                    confidence=confidence,
                    description=desc,
                    match_method=reason,
                    weight=1.0,
                    is_stable=(subcategory in ["salary", "benefits"]),
                    debug_rationale=self._build_debug_rationale("transfer_promotion", reason)
                )

        # **STEP 0C: Known Expense Service Check** (MOVED DOWN - RUNS AFTER PROMOTION)
        # Only check this AFTER we've tried to promote transfers to income
        for service in self.KNOWN_EXPENSE_SERVICES:
            if service in combined_text:
                plaid_cat_for_checks = f"{plaid_detailed_upper} {plaid_primary_upper}"

                if "TRANSFER" in plaid_cat_for_checks:
                    return CategoryMatch(
                        category="transfer",
                        subcategory="internal",
                        confidence=0.90,
                        description="Internal Transfer",
                        match_method="plaid",
                        weight=0.0,
                        is_stable=False
                    )

                if "LOAN_PAYMENTS" in plaid_cat_for_checks:
                    return CategoryMatch(
                        category="income",
                        subcategory="loans",
                        confidence=0.95,
                        description="Loan Payments/Disbursements",
                        match_method="plaid",
                        weight=0.0,
                        is_stable=False
                    )
                return CategoryMatch(
                    category="income",
                    subcategory="other",
                    confidence=0.5,
                    description="Other Income",
                    match_method="known_service_exclusion",
                    weight=1.0,
                    is_stable=False
                )

        # STEP 1: Check PLAID categories for loan/transfer indicators (same as non-batch)
        if plaid_category or plaid_category_primary:
            plaid_cat_upper = (plaid_category or "").upper()
            plaid_primary_upper = (plaid_category_primary or "").upper()

            # Check for LOAN_PAYMENTS category - these are loan disbursements/refunds, NOT income
            if "LOAN_PAYMENTS" in plaid_primary_upper or "LOAN_PAYMENTS" in plaid_cat_upper:
                return CategoryMatch(
                    category="income",
                    subcategory="loans",
                    confidence=0.95,
                    description="Loan Payments/Disbursements",
                    match_method="plaid",
                    weight=0.0,
                    is_stable=False
                )

            if "CASH_ADVANCES" in plaid_cat_upper or "ADVANCES" in plaid_cat_upper or "LOANS" in plaid_cat_upper:
                return CategoryMatch(
                    category="income",
                    subcategory="loans",
                    confidence=0.95,
                    description="Loan Payments/Disbursements",
                    match_method="plaid",
                    weight=0.0,
                    is_stable=False
                )
            # Loan proceeds sent as TRANSFER_IN (common for credit unions & some lenders)
            desc_upper = (description or "").upper()
            plaid_checks = f"{(plaid_category or '').upper()} {(plaid_category_primary or '').upper()}"

            if amount < 0 and "TRANSFER" in plaid_checks and any(x in desc_upper for x in [
                "BAMBOO",
                "BAMBOO LTD",
                "FERNOVO",
                "OAKBROOK",
                "OAKBROOK FINANCE",
                "OAKBROOK FINANCE LIMITED",
                "LENDING STREAM",
                "LENDINGSTREAM",
                "DRAFTY",
                "MR LENDER",
                "MRLENDER",
                "MONEYBOAT",
                "CREDITSPRING",
                "CASHFLOAT",
                "QUIDMARKET",
                "QUID MARKET",
                "LOANS 2 GO",
                "LOANS2GO",
                "POLAR CREDIT",
                "118 118 MONEY",
                "CASHASAP",
                "CREDIT UNION",
                "CREDIT U",
            ]):
                return CategoryMatch(
                    category="income",
                    subcategory="loans",
                    confidence=0.95,
                    description="Loan Proceeds (Transfer In)",
                    match_method="keyword_loan_proceeds",
                    weight=0.0,
                    is_stable=False
                )


            # Credit union handling (incoming loan proceeds vs outgoing repayments)
            desc_upper = (description or "").upper()
            if "CREDIT UNION" in desc_upper or "CREDIT U" in desc_upper:
                if amount < 0:
                    # incoming: treat as loan proceeds (NOT income)
                    return CategoryMatch(
                        category="income",
                        subcategory="loans",
                        confidence=0.90,
                        description="Credit Union Loan Proceeds",
                        match_method="keyword_credit_union",
                        weight=0.0,
                        is_stable=False
                    )
                else:
                    # outgoing: treat as debt repayment
                    return CategoryMatch(
                        category="debt",
                        subcategory="other_loans",
                        confidence=0.90,
                        description="Credit Union Loan Repayment",
                        match_method="keyword_credit_union",
                        weight=1.0,
                        is_stable=False
                    )

        # SIMPLIFIED: Use same logic as non-batch (Pragmatic Fix)
        # Just delegate to simplified income detector
        is_income, confidence, reason = self.income_detector.is_likely_income(
            description=description,
            amount=amount,
            plaid_category_primary=plaid_category_primary,
            plaid_category_detailed=plaid_category,
            all_transactions=getattr(self, "_current_batch_transactions", None),
            current_txn_index=transaction_index
        )

        # If the income detector explicitly identified this as a loan disbursement,
        # return immediately (don't fall through to keyword matching where gig patterns fire)
        if not is_income and reason == "loan_disbursement":
            return CategoryMatch(
                category="income",
                subcategory="loans",
                confidence=0.90,
                description="Loan Disbursements/Refunds (Not Income)",
                match_method="income_detector_loan",
                weight=0.0,
                is_stable=False
            )

        # If PLAID identifies as income with high confidence, trust it
        if is_income and confidence >= 0.85:
            # Determine subcategory based on reason
            if "wages" in reason or "salary" in reason:
                return CategoryMatch(
                    category="income",
                    subcategory="salary",
                    confidence=confidence,
                    description="Salary & Wages",
                    match_method=f"batch_plaid_{reason}",
                    weight=1.0,
                    is_stable=True
                )
            else:
                # Generic PLAID income - check if it matches specific patterns
                gig_match = self._check_gig_economy_patterns(combined_text)
                if gig_match:
                    gig_match.match_method = f"batch_{gig_match.match_method}"
                    return gig_match
                # Not gig economy, return as other income with lower weight
                return CategoryMatch(
                    category="income",
                    subcategory="other",
                    confidence=0.7,
                    description="Other Income",
                    match_method=f"batch_plaid_{reason}",
                    weight=1.0,  # Lower weight for uncertain income
                    is_stable=False
                )

        # Check income patterns (keyword matching ONLY)
        for subcategory, patterns in self.income_patterns.items():
            match = self._match_patterns(combined_text, patterns)
            if match:
                match_method, match_confidence = match

                return CategoryMatch(
                    category="income",
                    subcategory=subcategory,
                    confidence=match_confidence,
                    description=patterns.get("description", subcategory),
                    match_method=match_method,
                    weight=patterns.get("weight", 1.0),
                    is_stable=patterns.get("is_stable", False)
                )

        # STEP 4: Check for transfers (only if NOT identified as income above)
        if self._is_plaid_transfer(plaid_category_primary, plaid_category, description):
            return CategoryMatch(
                category="transfer",
                subcategory="internal",
                confidence=0.95,
                description="Internal Transfer",
                match_method="plaid",
                weight=0.0,
                is_stable=False
            )

        # Check if it's a transfer based on keywords (fallback)
        if self._is_transfer(combined_text):
            return CategoryMatch(
                category="transfer",
                subcategory="internal",
                confidence=0.9,
                description="Internal Transfer",
                match_method="keyword",
                weight=0.0,
                is_stable=False
            )

        # If Plaid told us TRANSFER_IN and nothing else promoted it to income, keep it as transfer
        if transfer_fallback:
            return transfer_fallback

        # Unknown income (default with low weight)
        return CategoryMatch(
            category="income",
            subcategory="other",
            confidence=0.5,
            description="Other Income",
            match_method="default",
            weight=1.0,
            is_stable=False
        )

    def cleanup_batch(self) -> None:
        """Explicitly clean up batch context and caches.

        Call this after you are done with both categorize_transactions_batch()
        and get_category_summary() to free memory.
        """
        self.income_detector.clear_batch_cache()
        self._current_batch_transactions = None

    def get_category_summary(
        self,
        categorized_transactions: List[Tuple[Dict, CategoryMatch]]
    ) -> Dict:
        """
        Generate a summary of categorized transactions.

        Returns:
            Dictionary with category totals and counts
        """
        # Get most recent transaction date to calculate lookback periods
        recent_date = None
        for txn, _ in categorized_transactions:
            txn_date_str = txn.get("date", "")
            if txn_date_str:
                try:
                    txn_date = datetime.strptime(txn_date_str, "%Y-%m-%d")
                    if recent_date is None or txn_date > recent_date:
                        recent_date = txn_date
                except ValueError:
                    continue

        if recent_date is None:
            recent_date = datetime.now()

        hcstc_cutoff = recent_date - timedelta(days=90)
        failed_payment_cutoff = recent_date - timedelta(days=45)
        bank_charges_cutoff = recent_date - timedelta(days=90)
        new_credit_cutoff = recent_date - timedelta(days=90)

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
            "debt": {
                "hcstc_payday": {
                    "total": 0.0,
                    "count": 0,
                    "lenders": set(),
                    "lenders_90d": set(),
                    "credit_providers_90d": set(),
                },
                "other_loans": {"total": 0.0, "count": 0, "providers_90d": set()},
                "credit_cards": {"total": 0.0, "count": 0, "providers_90d": set()},
                "bnpl": {"total": 0.0, "count": 0, "providers_90d": set()},
                "catalogue": {"total": 0.0, "count": 0, "providers_90d": set()},
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
                "discretionary": {"total": 0.0, "count": 0},
                "food_dining": {"total": 0.0, "count": 0},
                "unpaid": {"total": 0.0, "count": 0},
                "unauthorised_overdraft": {"total": 0.0, "count": 0},
                "gambling": {"total": 0.0, "count": 0},
                "other": {"total": 0.0, "count": 0},
                "account_transfer": {"total": 0.0, "count": 0},
            },


            "risk": {
                "gambling": {"total": 0.0, "count": 0},
                "failed_payments": {"total": 0.0, "count": 0, "count_45d": 0},
                "debt_collection": {"total": 0.0, "count": 0, "dcas": set()},
                "bank_charges": {"total": 0.0, "count": 0, "count_90d": 0},
            },
            "positive": {
                "savings": {"total": 0.0, "count": 0},
            },
            "transfer": {
                "internal": {"total": 0.0, "count": 0},
                "external": {"total": 0.0, "count": 0},
            },
            "other": {"total": 0.0, "count": 0},
        }

        for txn, match in categorized_transactions:
            amount = abs(txn.get("amount", 0))
            category = match.category
            subcategory = match.subcategory

            txn_date = None
            txn_date_str = txn.get("date", "")
            if txn_date_str:
                try:
                    txn_date = datetime.strptime(txn_date_str, "%Y-%m-%d")
                except ValueError:
                    pass

            # --- BANK CHARGES roll-up (all-time + 90d) ---
            # NOTE: your categoriser is using unpaid/unauthorised_overdraft as bank-charge signals
            # (so RiskMetrics must align to that reality).
            if category == "expense" and subcategory in ("unpaid", "unauthorised_overdraft"):
                summary["risk"]["bank_charges"]["total"] += amount
                summary["risk"]["bank_charges"]["count"] += 1
                if txn_date and txn_date >= bank_charges_cutoff:
                    summary["risk"]["bank_charges"]["count_90d"] += 1

            # If you *also* ever emit explicit risk/bank_charges matches, keep this too:
            if category == "risk" and subcategory == "bank_charges":
                summary["risk"]["bank_charges"]["total"] += amount
                summary["risk"]["bank_charges"]["count"] += 1
                if txn_date and txn_date >= bank_charges_cutoff:
                    summary["risk"]["bank_charges"]["count_90d"] += 1

            if category in summary and subcategory in summary.get(category, {}):
                if category == "income":
                    summary[category][subcategory]["total"] += (amount * match.weight)
                    summary[category][subcategory]["count"] += 1

                elif category == "expense" and subcategory == "other":
                    # PARTIAL INCLUSION: NON-recurring expense/other counted at 50%
                    raw_amt = txn.get("amount", 0)
                    txns = getattr(self, "_current_batch_transactions", None)
                    idx = txn.get("_batch_index")

                    is_rec = False
                    if txns is not None and idx is not None:
                        is_rec = self.income_detector.is_recurring_like(
                            description=txn.get("name", ""),
                            amount=raw_amt,
                            all_transactions=txns,
                            current_txn_index=idx
                        )
                    if is_rec:
                        # recurring commitments (Netflix etc) count at 100%
                        summary[category][subcategory]["total"] += amount
                    else:
                        # one-offs / noise discounted
                        summary[category][subcategory]["total"] += (amount * 0.5)
                    summary[category][subcategory]["count"] += 1

                else:
                    # All other categories and subcategories (including new expense subcategories)
                    summary[category][subcategory]["total"] += amount
                    summary[category][subcategory]["count"] += 1

                    # Track distinct credit providers within lookback (used for new_credit_providers_90d)
                    if category == "debt":
                        provider_name = txn.get("name", "").strip().upper()
                        if provider_name and txn_date and txn_date >= new_credit_cutoff:
                            # Global 'new credit providers' set (90d) — counts any credit provider observed
                            summary["debt"]["hcstc_payday"]["credit_providers_90d"].add(provider_name)

                            # Also keep per-product provider sets where configured
                            if isinstance(summary["debt"].get(subcategory), dict) and "providers_90d" in summary["debt"][subcategory]:
                                summary["debt"][subcategory]["providers_90d"].add(provider_name)


                    # Track HCSTC lenders for risk assessment
                    if category == "debt" and subcategory == "hcstc_payday":
                        # Extract lender name from transaction
                        lender_name = txn.get("name", "").strip().upper()
                        if lender_name:
                            summary["debt"]["hcstc_payday"]["lenders"].add(lender_name)

                            # Also track lenders in last 90 days
                            if txn_date and txn_date >= hcstc_cutoff:
                                summary["debt"]["hcstc_payday"]["lenders_90d"].add(lender_name)

                    # --- NEW CREDIT PROVIDERS (90d) tracking ---
                    if category == "debt":
                        provider_name = txn.get("name", "").strip().upper()
                        if provider_name and txn_date and txn_date >= new_credit_cutoff:
                            if subcategory == "hcstc_payday":
                                summary["debt"]["hcstc_payday"]["credit_providers_90d"].add(provider_name)
                            elif subcategory in ("other_loans", "credit_cards", "bnpl", "catalogue"):
                                summary["debt"][subcategory]["providers_90d"].add(provider_name)


            elif category == "transfer":
                if subcategory in summary["transfer"]:
                    summary["transfer"][subcategory]["total"] += amount
                    summary["transfer"][subcategory]["count"] += 1
                else:
                    if "other" not in summary["transfer"]:
                        summary["transfer"]["other"] = {"total": 0.0, "count": 0}
                    summary["transfer"]["other"]["total"] += amount
                    summary["transfer"]["other"]["count"] += 1

                # ✅ ADDITION: 50% income inclusion for recurring internal transfer credits
                raw_amt = txn.get("amount", 0)
                if subcategory == "internal" and raw_amt < 0:
                    txns = getattr(self, "_current_batch_transactions", None)
                    idx = txn.get("_batch_index")
                    if txns is not None and idx is not None:
                        if self.income_detector.is_recurring_like(
                            description=txn.get("name", ""),
                            amount=raw_amt,
                            all_transactions=txns,
                            current_txn_index=idx
                        ):
                            summary["income"]["other"]["total"] += (amount * 0.5)
                            summary["income"]["other"]["count"] += 1
            else:
                summary["other"]["total"] += amount
                summary["other"]["count"] += 1

        # Derived metrics (keep both set + numeric count for downstream compatibility)
        summary["debt"]["hcstc_payday"]["new_credit_providers_90d"] = len(
            summary["debt"]["hcstc_payday"].get("credit_providers_90d", set())
        )

        # --- Compute new_credit_providers_90d as a single numeric metric ---
        providers_90d_union = set()

        providers_90d_union |= set(summary["debt"]["hcstc_payday"].get("credit_providers_90d", set()))
        providers_90d_union |= set(summary["debt"]["other_loans"].get("providers_90d", set()))
        providers_90d_union |= set(summary["debt"]["credit_cards"].get("providers_90d", set()))
        providers_90d_union |= set(summary["debt"]["bnpl"].get("providers_90d", set()))
        providers_90d_union |= set(summary["debt"]["catalogue"].get("providers_90d", set()))

        summary["debt"]["hcstc_payday"]["new_credit_providers_90d"] = len(providers_90d_union)

        # Clean up batch context now that summary is complete
        self.cleanup_batch()

        return summary