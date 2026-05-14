"""
Behavioral Income Detection Module for HCSTC Loan Scoring.

Detects income through recurring patterns, payroll keywords, and behavioral analysis.
This module helps identify legitimate salary payments that PLAID may have miscategorized
as TRANSFER_IN by analyzing transaction patterns and descriptions.
"""

import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class RecurringIncomeSource:
    """Represents a detected recurring income source."""
    description_pattern: str
    amount_avg: float
    amount_std_dev: float
    frequency_days: float  # Average days between payments
    occurrence_count: int
    transaction_indices: List[int]  # Indices in original transaction list
    confidence: float  # 0.0 to 1.0
    source_type: str  # 'salary', 'benefits', 'pension', 'unknown'
    day_of_month_consistent: bool = False  # Whether payment day is consistent (±3 days)


class IncomeDetector:
    """Detects income through layered logic: exclusions → PLAID → TRANSFER_IN promotion → recurring patterns → keywords."""

    PAYROLL_KEYWORDS = [
        "SALARY", "WAGES", "PAYROLL", "NET PAY", "WAGE",
        "PAYSLIP", "EMPLOYER", "EMPLOYERS",
        "BGC", "BANK GIRO CREDIT", "CONTRACT PAY", "MONTHLY PAY", "WEEKLY PAY",
        "EMPLOYMENT", "PAYCHECK",
        # Payroll providers and systems
        "ADP", "PAYFIT", "SAGE PAYROLL", "XERO PAYRUN", "WORKDAY",
        "BARCLAYS PAYMENTS", "HSBC PAYROLL"
        # NOTE: BACS CREDIT, FASTER PAYMENT, FP- removed -- they are payment method
        # identifiers used for all types of credits, not just salary.
        # Transfer promotion in the engine handles FP-/BACS with amount thresholds.
    ]

    BENEFIT_KEYWORDS = [
        "UNIVERSAL CREDIT", " UC ", "DWP", "HMRC",
        "CHILD BENEFIT", "PIP", "DLA", "ESA", "JSA",
        "PENSION CREDIT", "HOUSING BENEFIT",
        "TAX CREDIT", "WORKING TAX", "CHILD TAX",
        "CARERS ALLOWANCE", "ATTENDANCE ALLOWANCE",
        "BEREAVEMENT", "MATERNITY ALLOWANCE",
        # Additional benefit and tax refund keywords (additive)
        "HMRC REFUND", "TAX REFUND", "HMRC TAX REFUND"
    ]

    PENSION_KEYWORDS = [
        "PENSION", "ANNUITY", "STATE PENSION", "RETIREMENT",
        # Provider names require "PENSION" suffix to avoid substring false positives
        # e.g. bare "NEST" would match "NESTLE", bare "AVIVA" matches insurer
        "NEST PENSION", "AVIVA PENSION", "LEGAL AND GENERAL PENSION",
        "SCOTTISH WIDOWS PENSION", "STANDARD LIFE PENSION", "PRUDENTIAL PENSION",
        "ROYAL LONDON PENSION", "AEGON PENSION"
    ]

    EXCLUSION_KEYWORDS = [
        "OWN ACCOUNT", "INTERNAL", "SELF TRANSFER",
        "FROM SAVINGS", "FROM CURRENT", "MOVED FROM",
        "MOVED TO", "BETWEEN ACCOUNTS", "INTERNAL TFR",
        "ISA TRANSFER", "SAVINGS TRANSFER",
        # Additional neobank and internal transfer keywords (additive)
        "POT", "VAULT", "ROUND UP", "MOVE MONEY", "INTERNAL MOVE"
    ]

    LOAN_KEYWORDS = [
        "LENDING STREAM", "LENDINGSTREAM", "DRAFTY",
        "MR LENDER", "MRLENDER", "MONEYBOAT", "CREDITSPRING",
        "CASHFLOAT", "QUIDMARKET", "QUID MARKET", "LOANS 2 GO", "LOANS2GO",
        "LOAN DISBURSEMENT", "LOAN ADVANCE",
        "PAYDAY LOAN", "SHORT TERM LOAN",
        "POLAR CREDIT", "118 118 MONEY", "CASHASAP",
        "BAMBOO", "BAMBOO LTD",
        "FERNOVO",
        "OAKBROOK", "OAKBROOK FINANCE", "OAKBROOK FINANCE LIMITED",
        "CREDIT UNION", "CU "

    ]
    
    # Additional gig economy platforms (additive)
    GIG_KEYWORDS = [
        "UBER", "UBER EATS", "DELIVEROO", "JUST EAT", "AMAZON FLEX",
        "EVRI", "DPD", "YODEL", "ROYAL MAIL",
        "SHOPIFY PAYMENTS", "STRIPE PAYOUT", "PAYPAL PAYOUT"
    ]
    
    # Interest income keywords (additive)
    INTEREST_KEYWORDS = [
        "INTEREST", "GROSS INTEREST", "GROSS INT", "BANK INTEREST", "SAVINGS INTEREST"
    ]

    LARGE_PAYMENT_THRESHOLD = 500.0

    LONG_NUMBER_THRESHOLD = 8
    LONG_ID_THRESHOLD = 12

    WEEKLY_MIN_DAYS = 5
    WEEKLY_MAX_DAYS = 9
    FORTNIGHTLY_MIN_DAYS = 11
    FORTNIGHTLY_MAX_DAYS = 17
    MONTHLY_MIN_DAYS = 25
    MONTHLY_MAX_DAYS = 35
    QUARTERLY_MIN_DAYS = 80
    QUARTERLY_MAX_DAYS = 100

    SALARY_TIGHT_VARIANCE = 0.05
    SALARY_LOOSE_VARIANCE = 0.30

    def __init__(self, min_amount: float = 50.0, min_occurrences: int = 3):
        self.min_amount = min_amount
        self.min_occurrences = min_occurrences
        self._cached_recurring_sources: List[RecurringIncomeSource] = []
        self._transaction_index_map: Dict[int, RecurringIncomeSource] = {}
        self._cache_valid = False

    # ----------------------------
    # Normalization + keyword tests
    # ----------------------------
    def _normalize_description(self, description: str) -> str:
        if not description:
            return ""

        desc = str(description).upper().strip()

        desc = re.sub(r'^(FP-|FASTER PAYMENTS?|BGC|BACS)\s*', '', desc)

        desc = re.sub(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', '', desc)
        desc = re.sub(r'\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b', '', desc)

        desc = re.sub(r'\bREF\s*\d+\b', '', desc)
        desc = re.sub(rf'\b\d{{{self.LONG_NUMBER_THRESHOLD},}}\b', '', desc)
        desc = re.sub(rf'\b[A-Z0-9]{{{self.LONG_ID_THRESHOLD},}}\b', '', desc)

        desc = re.sub(r'\bLIMITED\b', 'LTD', desc)
        desc = re.sub(r'\bCORPORATION\b', 'CORP', desc)

        desc = re.sub(r'\s+(SALARY|WAGES?|PAYMENT|PAYROLL|PAY)$', '', desc)
        desc = ' '.join(desc.split())
        return desc

    def matches_payroll_patterns(self, description: str) -> bool:
        if not description:
            return False
        d = description.upper()
        return any(k in d for k in self.PAYROLL_KEYWORDS)

    def matches_benefit_patterns(self, description: str) -> bool:
        if not description:
            return False
        d = description.upper()
        if any(k in d for k in self.BENEFIT_KEYWORDS):
            return True
        return bool(re.search(r"\bUC\b", d))

    def _matches_pension_patterns(self, description: str) -> bool:
        if not description:
            return False
        d = description.upper()
        return any(k in d for k in self.PENSION_KEYWORDS)
    
    def _matches_gig_patterns(self, description: str) -> bool:
        """Check if description matches gig economy patterns (additive)."""
        if not description:
            return False
        d = description.upper()
        return any(k in d for k in self.GIG_KEYWORDS)
    
    def _matches_interest_patterns(self, description: str) -> bool:
        """Check if description matches interest income patterns (additive)."""
        if not description:
            return False
        d = description.upper()
        return any(k in d for k in self.INTEREST_KEYWORDS)

    def _looks_like_internal_transfer(self, description: str) -> bool:
        d = (description or "").upper()
        return any(k in d for k in self.EXCLUSION_KEYWORDS)

    def _looks_like_loan_disbursement(self, description: str, plaid_category_detailed: Optional[str]) -> bool:
        d = (description or "").upper()
        if any(k in d for k in self.LOAN_KEYWORDS):
            return True
        # If PLAID explicitly says transfer-in cash advances / loans, treat as NOT income
        if (plaid_category_detailed or "").upper() == "TRANSFER_IN_CASH_ADVANCES_AND_LOANS":
            return True
        return False

    # ----------------------------
    # Recurring detection
    # ----------------------------
    def find_recurring_income_sources(self, transactions: List[Dict]) -> List[RecurringIncomeSource]:
        income_candidates = []
        for idx, txn in enumerate(transactions):
            amount = txn.get("amount", 0)
            if amount < 0 and abs(amount) >= self.min_amount:
                income_candidates.append((idx, txn))

        if len(income_candidates) < self.min_occurrences:
            return []

        description_groups = defaultdict(list)
        for idx, txn in income_candidates:
            normalized_desc = self._normalize_description(txn.get("name", ""))
            if not normalized_desc:
                continue
            description_groups[normalized_desc].append((idx, txn))

        recurring_sources: List[RecurringIncomeSource] = []

        for desc_pattern, group in description_groups.items():
            if len(group) < self.min_occurrences:
                continue

            amounts = []
            dates = []
            indices = []

            for idx, txn in group:
                a = abs(txn.get("amount", 0))
                ds = txn.get("date", "")
                if not ds:
                    continue
                try:
                    dt = datetime.strptime(ds, "%Y-%m-%d")
                except ValueError:
                    continue
                amounts.append(a)
                dates.append(dt)
                indices.append(idx)

            if len(amounts) < self.min_occurrences or len(dates) < self.min_occurrences:
                continue

            avg_amount = sum(amounts) / len(amounts)
            if avg_amount == 0:
                continue

            amount_variance = max(abs(a - avg_amount) / avg_amount for a in amounts)

            dates_sorted = sorted(dates)
            intervals = [(dates_sorted[i] - dates_sorted[i - 1]).days for i in range(1, len(dates_sorted))]
            if not intervals:
                continue

            avg_interval = sum(intervals) / len(intervals)

            is_weekly = self.WEEKLY_MIN_DAYS <= avg_interval <= self.WEEKLY_MAX_DAYS
            is_fortnightly = self.FORTNIGHTLY_MIN_DAYS <= avg_interval <= self.FORTNIGHTLY_MAX_DAYS
            is_monthly = self.MONTHLY_MIN_DAYS <= avg_interval <= self.MONTHLY_MAX_DAYS
            is_quarterly = self.QUARTERLY_MIN_DAYS <= avg_interval <= self.QUARTERLY_MAX_DAYS

            if not (is_weekly or is_fortnightly or is_monthly or is_quarterly):
                continue

            day_of_month_consistent = False
            if is_monthly and len(dates_sorted) >= 3:
                days = [d.day for d in dates_sorted]
                avg_day = sum(days) / len(days)
                day_variance = max(abs(d - avg_day) for d in days)
                if day_variance <= 3:
                    day_of_month_consistent = True

            # enforce variance thresholds
            if is_monthly and day_of_month_consistent:
                if amount_variance > self.SALARY_TIGHT_VARIANCE:
                    continue
            else:
                if amount_variance > self.SALARY_LOOSE_VARIANCE:
                    continue

            # std dev
            variance = sum((a - avg_amount) ** 2 for a in amounts) / len(amounts)
            std_dev = variance ** 0.5

            source_type, confidence = self._classify_income_source(
                description=desc_pattern,
                amount=avg_amount,
                occurrence_count=len(amounts),
                frequency_days=avg_interval,
                day_of_month_consistent=day_of_month_consistent
            )

            if confidence <= 0:
                continue

            recurring_sources.append(RecurringIncomeSource(
                description_pattern=desc_pattern,
                amount_avg=avg_amount,
                amount_std_dev=std_dev,
                frequency_days=avg_interval,
                occurrence_count=len(amounts),
                transaction_indices=indices,
                confidence=confidence,
                source_type=source_type,
                day_of_month_consistent=day_of_month_consistent
            ))

        recurring_sources.sort(key=lambda x: x.confidence, reverse=True)
        return recurring_sources

    def _classify_income_source(
        self,
        description: str,
        amount: float,
        occurrence_count: int,
        frequency_days: float,
        day_of_month_consistent: bool = False
    ) -> Tuple[str, float]:
        desc_upper = (description or "").upper()

        if any(k in desc_upper for k in self.EXCLUSION_KEYWORDS):
            return ("unknown", 0.0)
        if any(k in desc_upper for k in self.LOAN_KEYWORDS):
            return ("unknown", 0.0)

        base_conf = min(0.7, 0.4 + (occurrence_count * 0.1))

        if self.matches_payroll_patterns(description):
            if (self.WEEKLY_MIN_DAYS <= frequency_days <= self.WEEKLY_MAX_DAYS or
                self.FORTNIGHTLY_MIN_DAYS <= frequency_days <= self.FORTNIGHTLY_MAX_DAYS):
                return ("salary", min(0.97, base_conf + 0.27))
            if self.MONTHLY_MIN_DAYS <= frequency_days <= self.MONTHLY_MAX_DAYS:
                if day_of_month_consistent:
                    return ("salary", min(0.97, base_conf + 0.32))
                return ("salary", min(0.95, base_conf + 0.22))
            return ("salary", min(0.92, base_conf + 0.18))

        if self.matches_benefit_patterns(description):
            if self.MONTHLY_MIN_DAYS <= frequency_days <= self.MONTHLY_MAX_DAYS:
                return ("benefits", min(0.95, base_conf + 0.25))
            return ("benefits", min(0.90, base_conf + 0.15))

        if self._matches_pension_patterns(description):
            if self.MONTHLY_MIN_DAYS <= frequency_days <= self.MONTHLY_MAX_DAYS:
                return ("pension", min(0.95, base_conf + 0.25))
            if self.QUARTERLY_MIN_DAYS <= frequency_days <= self.QUARTERLY_MAX_DAYS:
                return ("pension", min(0.93, base_conf + 0.23))
            return ("pension", min(0.90, base_conf + 0.15))

        # company suffix heuristic
        if re.search(r"\b(LTD|LIMITED|PLC|LLP|INC|CORP)\b", desc_upper):
            if self.MONTHLY_MIN_DAYS <= frequency_days <= self.MONTHLY_MAX_DAYS:
                if day_of_month_consistent:
                    return ("salary", min(0.90, base_conf + 0.25))
                return ("salary", min(0.85, base_conf + 0.15))
            if self.FORTNIGHTLY_MIN_DAYS <= frequency_days <= self.FORTNIGHTLY_MAX_DAYS:
                return ("salary", min(0.85, base_conf + 0.15))
            return ("salary", min(0.78, base_conf + 0.10))

        # behavioural salary detection without keywords
        if amount >= 200 and self.MONTHLY_MIN_DAYS <= frequency_days <= self.MONTHLY_MAX_DAYS and day_of_month_consistent:
            return ("salary", min(0.95, base_conf + 0.30))
        if amount >= 200 and self.FORTNIGHTLY_MIN_DAYS <= frequency_days <= self.FORTNIGHTLY_MAX_DAYS:
            return ("salary", min(0.90, base_conf + 0.20))
        if amount >= 200 and self.WEEKLY_MIN_DAYS <= frequency_days <= self.WEEKLY_MAX_DAYS:
            return ("salary", min(0.85, base_conf + 0.15))

        return ("unknown", min(0.70, base_conf + 0.10))

    # ----------------------------
    # TRANSFER_IN promotion
    # ----------------------------
    def _is_transfer_in(self, plaid_category_primary: Optional[str], plaid_category_detailed: Optional[str]) -> bool:
        p = (plaid_category_primary or "").upper()
        d = (plaid_category_detailed or "").upper()
        return ("TRANSFER_IN" in p) or d.startswith("TRANSFER_IN")

    def _transfer_in_promotion(
        self,
        description: str,
        amount: float,
        plaid_category_primary: Optional[str],
        plaid_category_detailed: Optional[str],
        all_transactions: Optional[List[Dict]] = None,
        current_txn_index: Optional[int] = None,
    ) -> Tuple[bool, float, str]:
        """
        ENHANCED: More aggressive transfer-to-income promotion with batch context.
    
        This method is called when Plaid labels a credit as TRANSFER_IN but we suspect
        it might be legitimate income (salary, benefits, gig payout, etc.).
    
        Changes from original:
        - Lower thresholds for promotion
        - Better use of batch context for recurring detection
        - More granular confidence scoring
        """
        if amount >= 0:
            return (False, 0.0, "not_credit")
    
        if not self._is_transfer_in(plaid_category_primary, plaid_category_detailed):
            return (False, 0.0, "not_transfer_in")
    
     # EXCLUSIONS: Real internal transfers
        if self._looks_like_internal_transfer(description):
            return (False, 0.0, "transfer_in_excluded_internal")
        if self._looks_like_loan_disbursement(description, plaid_category_detailed):
            return (False, 0.0, "transfer_in_excluded_loan")
    
        desc_upper = (description or "").upper()
        abs_amount = abs(amount)
    
        # TIER 1: STRONG SIGNALS (95%+ confidence)
    
        # Explicit payroll keywords
        if self.matches_payroll_patterns(description):
            return (True, 0.96, "transfer_in_promoted_payroll_keyword")
    
        # Government benefits
        if self.matches_benefit_patterns(description):
            return (True, 0.94, "transfer_in_promoted_benefit_keyword")
    
        # Pension payments
        if self._matches_pension_patterns(description):
            return (True, 0.94, "transfer_in_promoted_pension_keyword")
    
        # TIER 2: MODERATE SIGNALS (85-90% confidence)
    
        # Company suffix + meaningful amount
        if re.search(r"\b(LTD|LIMITED|PLC|LLP|INC|CORP)\b", desc_upper):
            if abs_amount >= 150:  # Lowered from 500
                return (True, 0.88, "transfer_in_promoted_company_suffix")
    
        # Faster Payment prefix (common for salary)
        if desc_upper.startswith("FP-") or " FP-" in desc_upper:
            if abs_amount >= 150:
                return (True, 0.86, "transfer_in_promoted_faster_payment")
    
        # Gig economy payouts
        if self._matches_gig_patterns(description):
            return (True, 0.85, "transfer_in_promoted_gig_payout")
    
        # TIER 3: BATCH-BASED RECURRING DETECTION (80-85% confidence)
    
        # If we have batch context, check for recurring pattern
        if all_transactions and current_txn_index is not None:
            # Look for similar transactions (same normalized description, similar amount)
            this_norm = self._normalize_description(description)
            if not this_norm:
                return (False, 0.0, "transfer_in_not_promoted")
        
            similar_count = 0
            similar_dates = []
        
            for i, txn in enumerate(all_transactions):
                if i == current_txn_index:
                    continue
            
                txn_amount = txn.get("amount", 0)
                if txn_amount >= 0:  # Not a credit
                    continue
            
                # Check description similarity
                txn_norm = self._normalize_description(txn.get("name", ""))
                if txn_norm != this_norm:
                    continue
            
                # Check amount similarity (within 25%)
                if abs(abs(txn_amount) - abs_amount) / abs_amount > 0.25:
                    continue
            
                # This is a similar transaction
                similar_count += 1
            
                # Track dates for cadence analysis
                date_str = txn.get("date")
                if date_str:
                    try:
                        similar_dates.append(datetime.strptime(date_str, "%Y-%m-%d"))
                    except ValueError:
                        pass
        
            # If we found 2+ similar transactions, analyze cadence
            if similar_count >= 2 and len(similar_dates) >= 2:
                dates_sorted = sorted(similar_dates)
                intervals = [
                    (dates_sorted[i] - dates_sorted[i-1]).days 
                    for i in range(1, len(dates_sorted))
                ]
            
                if intervals:
                    avg_interval = sum(intervals) / len(intervals)
                
                    # Check for regular payment cadence
                    is_weekly = self.WEEKLY_MIN_DAYS <= avg_interval <= self.WEEKLY_MAX_DAYS
                    is_fortnightly = self.FORTNIGHTLY_MIN_DAYS <= avg_interval <= self.FORTNIGHTLY_MAX_DAYS
                    is_monthly = self.MONTHLY_MIN_DAYS <= avg_interval <= self.MONTHLY_MAX_DAYS
                
                    if is_weekly or is_fortnightly or is_monthly:
                        # Regular payment pattern detected
                        if abs_amount >= 200:
                            return (True, 0.85, "transfer_in_promoted_recurring_large")
                        elif abs_amount >= 100:
                            return (True, 0.80, "transfer_in_promoted_recurring_medium")
                        else:
                            return (True, 0.75, "transfer_in_promoted_recurring_small")
    
        # TIER 4: LARGE ONE-OFF PAYMENTS (70-75% confidence)
    
        # Large payment with specific identifier (not generic "PAYMENT")
        if abs_amount >= 400:  # Lowered from 500
            generic_words = {"PAYMENT", "TRANSFER", "CREDIT", "DEBIT", "TFR", "FROM", "TO"}
            words = set(desc_upper.split())
            specific_words = words - generic_words
        
            # Has meaningful name + large amount = likely income
            if len(specific_words) >= 2:
                return (True, 0.72, "transfer_in_promoted_large_named_payment")
    
        # DEFAULT: Do not promote
        return (False, 0.0, "transfer_in_not_promoted")
    


    # ----------------------------
    # Batch cache
    # ----------------------------
    def analyze_batch(self, transactions: List[Dict]) -> None:
        """Build recurring pattern cache for fast per-transaction lookups."""
        self.clear_batch_cache()

        sources = self.find_recurring_income_sources(transactions)
        self._cached_recurring_sources = sources

        idx_map: Dict[int, RecurringIncomeSource] = {}
        for src in sources:
            for idx in src.transaction_indices:
                idx_map[idx] = src

        self._transaction_index_map = idx_map
        self._cache_valid = True

    def clear_batch_cache(self) -> None:
        self._cached_recurring_sources = []
        self._transaction_index_map = {}
        self._cache_valid = False

    # ----------------------------
    # Public API
    # ----------------------------
    def is_likely_income(
        self,
        description: str,
        amount: float,
        plaid_category_primary: Optional[str] = None,
        plaid_category_detailed: Optional[str] = None,
        all_transactions: Optional[List[Dict]] = None,
        current_txn_index: Optional[int] = None
    ) -> Tuple[bool, float, str]:
        """
        ENHANCED: Better income detection with stronger transfer promotion.
    
        Changes from original:
        - Transfer promotion runs BEFORE keyword fallback
        - Recurring pattern detection integrated into transfer promotion
        - Lower confidence thresholds to catch more legitimate income
        """
    
        # Credits only
        if amount >= 0:
            return (False, 0.0, "not_credit")
    
        # Hard exclusions first
        if self._looks_like_internal_transfer(description):
            return (False, 0.0, "excluded_internal_transfer")
        if self._looks_like_loan_disbursement(description, plaid_category_detailed):
            return (False, 0.0, "loan_disbursement")
    
        # PRIORITY 1: PLAID INCOME (highest trust)
        if plaid_category_detailed:
            d = plaid_category_detailed.upper()
            if "INCOME_WAGES" in d or ("INCOME" in d and ("SALARY" in d or "PAYROLL" in d)):
                return (True, 0.96, "plaid_detailed_income_wages")
            if "INCOME_RETIREMENT" in d or ("INCOME" in d and "RETIREMENT" in d):
                return (True, 0.94, "plaid_detailed_income_retirement")
            if "INCOME_GOVERNMENT" in d or ("INCOME" in d and ("GOVERNMENT" in d or "BENEFIT" in d)):
                return (True, 0.94, "plaid_detailed_income_government")
            if "INCOME" in d:
                return (True, 0.88, "plaid_detailed_income")
    
        if plaid_category_primary and "INCOME" in plaid_category_primary.upper():
            return (True, 0.86, "plaid_primary_income")
    
        # PRIORITY 2: TRANSFER PROMOTION (rescue mislabeled salary)
        # **MOVED UP** - This now runs before keyword fallback
        promoted, p_conf, p_reason = self._transfer_in_promotion(
            description=description,
            amount=amount,
            plaid_category_primary=plaid_category_primary,
            plaid_category_detailed=plaid_category_detailed,
            all_transactions=all_transactions,
            current_txn_index=current_txn_index,
        )
        if promoted:
            return (True, p_conf, p_reason)
    
        # PRIORITY 3: RECURRING PATTERN (if batch cache is available)
        if self._cache_valid and current_txn_index is not None:
            src = self._transaction_index_map.get(current_txn_index)
            if src and src.confidence >= 0.75:  # Lowered from 0.80
                return (True, min(0.92, src.confidence), f"recurring_{src.source_type}")
    
        # PRIORITY 4: KEYWORD FALLBACK
        if self.matches_payroll_patterns(description):
            return (True, 0.82, "keyword_payroll")  # Increased from 0.80
        if self.matches_benefit_patterns(description):
            return (True, 0.78, "keyword_benefits")  # Increased from 0.75
        if self._matches_pension_patterns(description):
            return (True, 0.78, "keyword_pension")  # Increased from 0.75
        if self._matches_gig_patterns(description):
            return (True, 0.72, "keyword_gig")  # Increased from 0.70
        if self._matches_interest_patterns(description):
            return (True, 0.85, "keyword_interest")
    
        # DEFAULT: Not income
        return (False, 0.0, "no_income_signals")

    def is_likely_income_from_batch(
        self,
        description: str,
        amount: float,
        transaction_index: int,
        plaid_category_primary: Optional[str] = None,
        plaid_category_detailed: Optional[str] = None,
        all_transactions: Optional[List[Dict]] = None
    ) -> Tuple[bool, float, str]:
        return self.is_likely_income(
            description=description,
            amount=amount,
            plaid_category_primary=plaid_category_primary,
            plaid_category_detailed=plaid_category_detailed,
            all_transactions=all_transactions,
            current_txn_index=transaction_index
        )
    def is_recurring_like(
        self,
        description: str,
        amount: float,
        all_transactions: Optional[List[Dict]],
        current_txn_index: Optional[int],
        min_similar: int = 2,          # "2 other occurrences" = 3 total incl current
        amount_tolerance: float = 0.25 # 25% band
    ) -> bool:
        """
        Returns True if this credit/debit looks recurring based on normalized description,
        similar amount, and cadence roughly weekly/fortnightly/monthly.
        """
        if not all_transactions or current_txn_index is None:
            return False
        this_norm = self._normalize_description(description or "")
        if not this_norm:
            return False

        this_amt = abs(amount)
        is_credit = amount < 0
        if this_amt <= 0:
            return False
        dates = []
        for i, t in enumerate(all_transactions):
            if i == current_txn_index:
                continue
            a = t.get("amount", 0)
            if abs(a) < self.min_amount:
                continue

            # Must be same direction (credit vs debit) to be a true recurrence
            if (a < 0) != is_credit:
                continue

            # same normalized name
            name = t.get("name", "")
            if self._normalize_description(name) != this_norm:
                continue

            # similar amount
            if abs(abs(a) - this_amt) / this_amt > amount_tolerance:
                continue

            ds = t.get("date")
            if not ds:
                continue
            try:
                dates.append(datetime.strptime(ds, "%Y-%m-%d"))
            except ValueError:
                continue
        # Need at least N similar other occurrences
        if len(dates) < min_similar:
            return False

        dates_sorted = sorted(dates)
        intervals = [(dates_sorted[i] - dates_sorted[i - 1]).days for i in range(1, len(dates_sorted))]
        if not intervals:
            return False

        avg = sum(intervals) / len(intervals)
        is_weekly = self.WEEKLY_MIN_DAYS <= avg <= self.WEEKLY_MAX_DAYS
        is_fortnightly = self.FORTNIGHTLY_MIN_DAYS <= avg <= self.FORTNIGHTLY_MAX_DAYS
        is_monthly = self.MONTHLY_MIN_DAYS <= avg <= self.MONTHLY_MAX_DAYS

        return is_weekly or is_fortnightly or is_monthly
