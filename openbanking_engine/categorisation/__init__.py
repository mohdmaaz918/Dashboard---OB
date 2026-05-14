"""
Categorisation Module for HCSTC Scoring Engine.   

Orchestrates transaction categorization through:   
- Preprocessing (normalization, transfer detection)
- Pattern matching (keyword and regex-based)
- PFC mapping (Plaid Personal Finance Category)
- Income detection (behavioral patterns)
"""

from .engine import TransactionCategorizer, CategoryMatch
from .preprocess import (
    normalize_text,
    normalize_hcstc_lender,
    combine_description_merchant,
    is_internal_transfer,
    map_pfc_to_category,
    HCSTC_LENDER_CANONICAL_NAMES,
)
from .pattern_matching import (
    match_patterns,
    match_keyword_list,
    match_regex_list,
    fuzzy_match_keywords,
)

__all__ = [
    # Main categorizer
    "TransactionCategorizer",
    "CategoryMatch",
    # Preprocessing utilities
    "normalize_text",
    "normalize_hcstc_lender",
    "combine_description_merchant",
    "is_internal_transfer",
    "map_pfc_to_category",
    "HCSTC_LENDER_CANONICAL_NAMES",
    # Pattern matching utilities
    "match_patterns",
    "match_keyword_list",
    "match_regex_list",
    "fuzzy_match_keywords",
]