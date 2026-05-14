"""
Generic pattern matching utilities for transaction categorization.
Supports keyword, regex, and fuzzy matching.
"""

import re
from typing import Dict, List, Optional, Tuple

try:
    from rapidfuzz import fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False


# Minimum confidence threshold for fuzzy matching
FUZZY_THRESHOLD = 80


def match_patterns(text: str, patterns: Dict, fuzzy_threshold: int = FUZZY_THRESHOLD) -> Optional[Tuple[str, float]]:
    """
    Match text against pattern dictionary using keyword, regex, and fuzzy matching.
    
    Args:
        text: Normalized text to match
        patterns: Pattern dictionary with 'keywords' and 'regex_patterns'
        fuzzy_threshold: Minimum score for fuzzy matching (default 80)
        
    Returns:
        Tuple of (match_method, confidence) if match found, None otherwise
    """
    # 1. Check exact keyword matches (highest confidence)
    if "keywords" in patterns:
        for keyword in patterns["keywords"]:
            if keyword in text:
                return ("keyword", 0.95)
    
    # 2. Check regex patterns
    if "regex_patterns" in patterns:
        for pattern in patterns["regex_patterns"]:
            if re.search(pattern, text):
                return ("regex", 0.90)
    
    # 3. Fuzzy matching (if available) - check if any keyword is similar
    if RAPIDFUZZ_AVAILABLE and "keywords" in patterns:
        for keyword in patterns["keywords"]:
            score = fuzz.partial_ratio(keyword, text)
            if score >= fuzzy_threshold:
                confidence = 0.70 + (score - fuzzy_threshold) / 100
                return ("fuzzy", min(confidence, 0.89))
    
    return None


def match_keyword_list(text: str, keywords: List[str]) -> bool:
    """
    Check if text matches any keyword in list.
    
    Args:
        text: Normalized text to match
        keywords: List of keywords
        
    Returns:
        True if any keyword matches
    """
    for keyword in keywords:
        if keyword in text:
            return True
    return False


def match_regex_list(text: str, regex_patterns: List[str]) -> bool:
    """
    Check if text matches any regex pattern in list.
    
    Args:
        text: Text to match
        regex_patterns: List of regex patterns
        
    Returns:
        True if any pattern matches
    """
    for pattern in regex_patterns:
        if re.search(pattern, text):
            return True
    return False


def fuzzy_match_keywords(text: str, keywords: List[str], threshold: int = FUZZY_THRESHOLD) -> Optional[float]:
    """
    Fuzzy match text against keywords.
    
    Args:
        text: Text to match
        keywords: List of keywords
        threshold: Minimum score threshold
        
    Returns:
        Best match score if above threshold, None otherwise
    """
    if not RAPIDFUZZ_AVAILABLE:
        return None
    
    best_score = 0
    for keyword in keywords:
        score = fuzz.partial_ratio(keyword, text)
        if score > best_score:
            best_score = score
    
    if best_score >= threshold:
        return best_score
    return None
