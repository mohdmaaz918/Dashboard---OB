"""
Preprocessing utilities for transaction categorization.
Handles text normalization, internal transfer detection, and PFC mapping.
"""

from typing import Optional, Dict, Tuple


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
}

# Pre-computed sorted patterns (longest first) for efficient matching
# This avoids sorting on every call to normalize_hcstc_lender
HCSTC_LENDER_PATTERNS_SORTED = sorted(
    HCSTC_LENDER_CANONICAL_NAMES.items(),
    key=lambda x: len(x[0]),
    reverse=True
)


def normalize_text(text: Optional[str]) -> str:
    """
    Normalize text for matching.
    
    Args:
        text: Raw text to normalize
        
    Returns:
        Normalized uppercase text
    """
    if not text:
        return ""
    # Convert to uppercase for matching
    return text.upper().strip()


def normalize_hcstc_lender(merchant_name: str) -> Optional[str]:
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


def combine_description_merchant(description: str, merchant_name: Optional[str]) -> Tuple[str, str, str]:
    """
    Combine description and merchant name for categorization.
    
    Args:
        description: Transaction description
        merchant_name: Optional merchant name
        
    Returns:
        Tuple of (normalized_description, normalized_merchant, combined_text)
    """
    text = normalize_text(description)
    merchant_text = normalize_text(merchant_name) if merchant_name else ""
    combined_text = f"{text} {merchant_text}".strip()
    
    return text, merchant_text, combined_text


def is_internal_transfer(text: str, transfer_keywords: list) -> bool:
    """
    Check if transaction text indicates an internal transfer.
    
    Args:
        text: Normalized transaction text
        transfer_keywords: List of transfer keywords to check
        
    Returns:
        True if text matches internal transfer keywords
    """
    for keyword in transfer_keywords:
        if keyword in text:
            return True
    return False


def map_pfc_to_category(pfc_code: str, pfc_mapping: Dict) -> Optional[Dict]:
    """
    Map PFC code to category information.
    
    Args:
        pfc_code: Personal Finance Category code
        pfc_mapping: PFC mapping dictionary
        
    Returns:
        Category information dict or None if not found
    """
    return pfc_mapping.get(pfc_code)
