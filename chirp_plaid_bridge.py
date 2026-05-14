"""
Map Chirp Open Banking JSON transactions into the shape expected by openbanking_engine.

- Plaid convention: negative amount = credit (money in), positive = debit (out).
- Chirp sample: positive amounts with type CREDIT/DEBIT.

This module lives only under Chirp/ and does not modify the UK engine.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from chirp_xml import chirp_xml_bytes_to_payload

_CHIRP_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _CHIRP_DIR.parent
_MAPPING_CSV = _CHIRP_DIR / "plaid_pfc_to_chirp_semantic_mapping.csv"

_QUALITY = {"high": 3, "medium": 2, "low": 1}

# Common merchant category codes for gambling (US); Chirp rarely labels gambling explicitly.
_GAMBLING_MCC = frozenset({7800, 7801, 7802, 7995})


def _load_chirp_to_plaid_map() -> Dict[Tuple[str, str], Tuple[str, str]]:
    """(top_level_category, category) -> (plaid_primary, plaid_detailed). Best quality wins."""
    best: Dict[Tuple[str, str], Tuple[Tuple[str, str], int]] = {}
    if not _MAPPING_CSV.exists():
        return {}

    with _MAPPING_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tlc = (row.get("chirp_top_level_category") or "").strip()
            cat = (row.get("chirp_category") or "").strip()
            primary = (row.get("plaid_primary") or "").strip()
            detailed = (row.get("plaid_detailed") or "").strip()
            mq = _QUALITY.get((row.get("match_quality") or "").strip().lower(), 0)
            if not tlc or not cat or not primary:
                continue
            key = (tlc.lower(), cat.lower())
            prev = best.get(key)
            if prev is None or mq > prev[1]:
                best[key] = ((primary, detailed), mq)

    return {k: v[0] for k, v in best.items()}


_CHIRP_TO_PLAID = _load_chirp_to_plaid_map()


def load_chirp_upload_raw(filename: str, content: bytes) -> Any:
    """Decode uploaded bytes as JSON or Chirp XML; returns object for ``normalize_chirp_payload``."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "xml":
        return chirp_xml_bytes_to_payload(content)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"File is not valid UTF-8: {e}") from e
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e


def _lookup_plaid_categories(top_level: str, category: str) -> Tuple[Optional[str], Optional[str]]:
    key = (top_level.strip().lower(), category.strip().lower())
    hit = _CHIRP_TO_PLAID.get(key)
    if hit:
        return hit[0], hit[1]
    return None, None


def _combined_text(txn: Dict[str, Any]) -> str:
    parts = [
        str(txn.get("description") or ""),
        str(txn.get("original_description") or ""),
        str(txn.get("localized_description") or ""),
    ]
    return " ".join(parts).upper()


def _looks_like_us_outflow_payment(text: str) -> bool:
    """Heuristics: money leaving the account (payments, transfers out, bills)."""
    if re.search(
        r"\b("
        r"CREDIT\s+CARD\s+PAYMENT|CARD\s+PAYMENT|CARD\s+PAYMT|"
        r"LOAN\s+PAYMENT|AUTO\s+LOAN|MORTGAGE\s+PAYMENT|"
        r"PROPERTY\s+PAYMENT|RENT\s+PAYMENT|RENT\s+PAY|"
        r"STUDENT\s+LOAN|CAR\s+PAYMENT|AUTO\s+PAY|"
        r"PAYMENT\s+TO|PAY\s+TO|BILL\s+PAY|AUTOPAY|"
        r"DEBIT\s+CARD|WITHDRAWAL|ATM\s+WITHDRAWAL"
        r")\b",
        text,
    ):
        return True
    if text.strip() == "PAYMENT" or re.match(r"^\s*PAYMENT\s*$", text):
        return True
    return False


def _looks_like_us_inflow_credit(text: str, txn: Dict[str, Any]) -> bool:
    """Heuristics: money into the account (payroll, refunds, deposits)."""
    if txn.get("is_income") or txn.get("is_direct_deposit"):
        return True
    if re.search(
        r"\b("
        r"PAYROLL|DIRECT\s+DEP|DIRECT\s+DEPOSIT|DD\s+FROM|"
        r"PAYCHEX|ADP|GUSTO|RIPPLING|DEPOSIT|"
        r"SALARY|WAGES|REFUND|INTEREST\s+PAID"
        r")\b",
        text,
    ):
        return True
    return False


def _payment_outflow_plaid_debit(txn: Dict[str, Any], text: str) -> bool:
    """
    True when this row is paying down debt / bills and must be a Plaid *debit* (positive),
    even if Chirp marks type=CREDIT on a credit-card or loan account.

    Excludes refunds/cashback to the card.
    """
    if re.search(r"\b(REFUND|CASHBACK|REWARD|CREDIT\s+ADJUSTMENT)\b", text):
        return False
    cat = str(txn.get("category") or "").upper()
    if cat in (
        "CREDIT CARD PAYMENT",
        "MORTGAGE PAYMENT",
        "LOAN PAYMENT",
    ):
        return True
    if "PROPERTY" in cat and "PAYMENT" in cat:
        return True
    if re.search(
        r"\b("
        r"CREDIT\s+CARD\s+PAYMENT|CARD\s+PAYMENT|"
        r"LOAN\s+PAYMENT|MORTGAGE\s+PAYMENT|"
        r"PROPERTY\s+PAYMENT|RENT\s+PAYMENT|STUDENT\s+LOAN"
        r")\b",
        text,
    ):
        return True
    return False


def chirp_amount_to_plaid_signed(txn: Dict[str, Any]) -> float:
    """
    Convert Chirp amount + type to Plaid-style signed amount.

    Plaid: negative = credit in, positive = debit out.

    Chirp variants:
    - **API sample style**: positive amount + type CREDIT/DEBIT.
    - **US bank export style**: negative = money out, positive = money in (no or unreliable type).
    - **Payments on card/loan accounts**: often type=CREDIT with positive amount (paying balance);
      those must still map to Plaid *debit* for the scoring engine.
    """
    try:
        a = float(txn.get("amount") or 0.0)
    except (TypeError, ValueError):
        a = 0.0
    t = str(txn.get("type") or "").upper().strip()
    text = _combined_text(txn)

    # Paying credit card / loan / mortgage / rent bill — always outflow for underwriting
    if _payment_outflow_plaid_debit(txn, text):
        return abs(a)

    if t == "CREDIT":
        return -abs(a)
    if t == "DEBIT":
        return abs(a)

    # --- Ambiguous type: infer (common with US MX / bank feeds) ---
    if a < 0:
        # Negative amount almost always = outflow → Plaid debit (positive)
        return abs(a)

    # a > 0: could be ChirpOB-style debit, or a deposit / transfer in
    if _looks_like_us_inflow_credit(text, txn):
        return -abs(a)
    if _looks_like_us_outflow_payment(text):
        return abs(a)
    # "Transfer from …" / "from savings" → money into this account (Plaid credit = negative)
    if re.search(r"\bTRANSFER\s+FROM\b", text) or re.search(
        r"\bFROM\s+(SAVINGS|CHECKING|MONEY\s+MARKET|MM)\b", text
    ):
        return -abs(a)
    # Default: treat as spend / outflow (safer than inventing income)
    return abs(a)


def _enrich_plaid_from_chirp_flags_and_text(
    txn: Dict[str, Any],
    primary: Optional[str],
    detailed: Optional[str],
) -> Tuple[str, str]:
    """Refine synthetic Plaid categories using Chirp booleans and text/MCC."""
    text = _combined_text(txn)
    mcc = txn.get("merchant_category_code")
    try:
        mcc_int = int(mcc) if mcc is not None and str(mcc).strip() != "" else None
    except (TypeError, ValueError):
        mcc_int = None

    p = (primary or "TRANSFER_IN").upper()
    d = (detailed or "TRANSFER_IN_OTHER").upper()

    tlc = str(txn.get("top_level_category") or "").upper()
    cat = str(txn.get("category") or "").upper()

    # Late fee only → same engine bucket as UK NSF/unpaid bank fees (expense / unpaid)
    if cat == "LATE FEE" or "LATE FEE" in text or re.search(r"\bLATE\s+FEE\b", text):
        return "BANK_FEES", "BANK_FEES_INSUFFICIENT_FUNDS"

    # Gambling: no Chirp leaf; use MCC or keywords
    if mcc_int in _GAMBLING_MCC or re.search(
        r"\b(CASINO|GAMBLING|BETTING|SPORTSBOOK|DRAFTKINGS|FANDUEL)\b", text
    ):
        return "ENTERTAINMENT", "ENTERTAINMENT_CASINOS_AND_GAMBLING"

    # Explicit payment rails (avoid misrouting to TRANSFER_IN / income)
    if re.search(r"\bCREDIT\s+CARD\s+PAYMENT\b", text) or re.search(
        r"\bCARD\s+PAYMENT\b", text
    ):
        return "LOAN_PAYMENTS", "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"
    if re.search(r"\bLOAN\s+PAYMENT\b", text) and "DISBURSE" not in text:
        return "LOAN_PAYMENTS", "LOAN_PAYMENTS_OTHER_PAYMENT"
    if re.search(r"\bMORTGAGE\s+PAYMENT\b", text):
        return "LOAN_PAYMENTS", "LOAN_PAYMENTS_MORTGAGE_PAYMENT"
    if re.search(r"\bPROPERTY\s+PAYMENT\b", text) or re.search(
        r"\bRENT\s+PAYMENT\b", text
    ):
        return "RENT_AND_UTILITIES", "RENT_AND_UTILITIES_RENT"
    if re.search(r"\bAUTO\s+PAYMENT\b", text) or re.search(r"\bCAR\s+PAYMENT\b", text):
        return "LOAN_PAYMENTS", "LOAN_PAYMENTS_CAR_PAYMENT"
    if text.strip() == "PAYMENT" or re.match(r"^\s*PAYMENT\s*$", text):
        return "TRANSFER_OUT", "TRANSFER_OUT_OTHER"

    # Fees: overdraft / NSF / ATM stay as bank-fee Plaid codes; generic "Fee" / Banking Fee /
    # Service Fee are ambiguous → other expense (TRANSFER_OUT_OTHER strict mapping), not unpaid.
    if tlc == "FEES & CHARGES" or "FEE" in cat or txn.get("is_fee"):
        if txn.get("is_overdraft_fee") or "OVERDRAFT" in text:
            return "BANK_FEES", "BANK_FEES_OVERDRAFT"
        if "NSF" in text or "INSUFFICIENT" in text or "NON-SUFFICIENT" in text:
            return "BANK_FEES", "BANK_FEES_INSUFFICIENT_FUNDS"
        if cat == "ATM FEE":
            return "BANK_FEES", "BANK_FEES_ATM_FEES"
        if cat in ("BANKING FEE", "FEE", "SERVICE FEE"):
            return "TRANSFER_OUT", "TRANSFER_OUT_OTHER"
        if cat == "FINANCE CHARGE" or "INTEREST" in text:
            return "BANK_FEES", "BANK_FEES_OTHER"

    # Chirp utility leaves often map to Plaid RENT_AND_UTILITIES_* names, but the shared
    # UK engine treats any detailed category containing "RENT" as housing before utilities.
    # Emit Chirp-only synthetic utility categories so UK behavior remains unchanged.
    if tlc == "BILLS & UTILITIES":
        if cat == "UTILITIES":
            return "UTILITIES", "UTILITIES_OTHER"
        if cat == "INTERNET":
            return "UTILITIES", "UTILITIES_INTERNET_AND_CABLE"
        if cat in ("MOBILE PHONE", "HOME PHONE", "TELEVISION"):
            return "UTILITIES", "UTILITIES_COMMUNICATIONS"

    # Payroll-like income signals (US) — only when Chirp marks credit + income
    if str(txn.get("type", "")).upper() == "CREDIT":
        if txn.get("is_direct_deposit") or txn.get("is_income"):
            return "INCOME", "INCOME_WAGES"
        if re.search(r"\b(PAYROLL|DIRECT DEP|DD FROM|PAYCHEX|ADP|GUSTO|RIPPLING)\b", text):
            return "INCOME", "INCOME_WAGES"

    return p, d


def chirp_transaction_to_engine_row(txn: Dict[str, Any]) -> Dict[str, Any]:
    """Single Chirp transaction -> dict for TransactionCategorizer / metrics."""
    tlc = str(txn.get("top_level_category") or "").strip()
    cat = str(txn.get("category") or "").strip()
    primary, detailed = _lookup_plaid_categories(tlc, cat)
    if not primary:
        # Reasonable defaults when not in mapping table
        tt = str(txn.get("type") or "").upper()
        if tt == "CREDIT":
            primary, detailed = "TRANSFER_IN", "TRANSFER_IN_OTHER"
        else:
            primary, detailed = "TRANSFER_OUT", "TRANSFER_OUT_OTHER"

    primary, detailed = _enrich_plaid_from_chirp_flags_and_text(txn, primary, detailed)

    desc = str(txn.get("description") or txn.get("original_description") or "").strip() or "Unknown"
    if (
        tlc.lower() == "transfer"
        and cat.lower() == "transfer"
        and desc.strip().upper() == "PAYMENT"
    ):
        tt = str(txn.get("type") or "").upper()
        if tt == "CREDIT":
            desc = "Account Transfer In"
        elif tt == "DEBIT":
            desc = "Account Transfer Out"
        else:
            desc = "Account Transfer"
    signed = chirp_amount_to_plaid_signed(txn)

    row: Dict[str, Any] = {
        "date": txn.get("date"),
        "name": desc,
        "description": desc,
        "amount": signed,
        "merchant_name": txn.get("merchant_name") or txn.get("localized_description"),
        "personal_finance_category": {
            "primary": primary,
            "detailed": detailed,
        },
        # Preserve Chirp fields for UI/debug
        "_chirp": {
            "top_level_category": tlc,
            "category": cat,
            "type": txn.get("type"),
            "categoryCode": txn.get("categoryCode"),
            "parentCategoryCode": txn.get("parentCategoryCode"),
            "is_direct_deposit": txn.get("is_direct_deposit"),
            "is_income": txn.get("is_income"),
            "is_fee": txn.get("is_fee"),
            "is_overdraft_fee": txn.get("is_overdraft_fee"),
            "merchant_category_code": txn.get("merchant_category_code"),
        },
    }
    return row


def normalize_chirp_payload(raw: Any) -> Dict[str, Any]:
    """
    Return the Chirp object that contains TransactionSummaries.

    Some exports wrap the API body as a JSON string under ``value`` (either a single
    object ``{"value": "..."}`` or a one-element array ``[{"value": "..."}]``).
    """
    if isinstance(raw, dict) and "TransactionSummaries" in raw:
        return raw

    def _from_value_string(s: str) -> Optional[Dict[str, Any]]:
        try:
            inner = json.loads(s)
        except (TypeError, json.JSONDecodeError):
            return None
        if isinstance(inner, dict) and "TransactionSummaries" in inner:
            return inner
        return None

    if isinstance(raw, dict):
        v = raw.get("value")
        if isinstance(v, str):
            got = _from_value_string(v)
            if got is not None:
                return got

    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], dict):
        v = raw[0].get("value")
        if isinstance(v, str):
            got = _from_value_string(v)
            if got is not None:
                return got

    raise ValueError(
        "Expected Chirp payload with TransactionSummaries, or an export whose JSON body is "
        "in a string field `value` (object or single-element array)."
    )


def chirp_json_to_engine_transactions(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse a Chirp API-style JSON object with TransactionSummaries."""
    txns = payload.get("TransactionSummaries") or []
    return [chirp_transaction_to_engine_row(t) for t in txns if isinstance(t, dict)]


def repo_root() -> Path:
    return _REPO_ROOT
