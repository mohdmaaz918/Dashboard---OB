"""
PFC (Personal Financial Category) mapping loader.
Loads CSV files containing transaction categorization mappings.
"""

import csv
from typing import Dict, List, Optional
from pathlib import Path


def load_pfc_mapping_csv(csv_path: str) -> Dict[str, Dict]:
    """
    Load PFC mapping from CSV file.
    
    Args:
        csv_path: Path to CSV file containing PFC mappings
        
    Returns:
        Dictionary mapping keys to category information
        
    Example CSV format:
        pfc_code,category,subcategory,description
        PFC001,income,salary,Salary payments
        PFC002,expense,groceries,Grocery shopping
    """
    mapping = {}
    
    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise FileNotFoundError(f"PFC mapping file not found: {csv_path}")
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pfc_code = row.get('pfc_code', '').strip()
            if pfc_code:
                mapping[pfc_code] = {
                    'category': row.get('category', '').strip(),
                    'subcategory': row.get('subcategory', '').strip(),
                    'description': row.get('description', '').strip(),
                }
    
    return mapping


def get_category_from_pfc(pfc_code: str, mapping: Dict[str, Dict]) -> Optional[Dict]:
    """
    Get category information for a given PFC code.
    
    Args:
        pfc_code: PFC code to look up
        mapping: PFC mapping dictionary
        
    Returns:
        Category information dict or None if not found
    """
    return mapping.get(pfc_code)
