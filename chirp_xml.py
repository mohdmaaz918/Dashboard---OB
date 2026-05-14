"""Parse Chirp-style XML exports into the same dict shape as JSON (`TransactionSummaries`, etc.)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, List


def _coerce_scalar(text: str) -> Any:
    s = (text or "").strip()
    if not s:
        return ""
    sl = s.lower()
    if sl == "true":
        return True
    if sl == "false":
        return False
    try:
        v = float(s)
        if v.is_integer():
            return int(v)
        return v
    except ValueError:
        return s


def _element_leaf_dict(elem: ET.Element) -> Dict[str, Any]:
    """Map direct child elements to scalars (Chirp export rows are flat)."""
    out: Dict[str, Any] = {}
    for child in elem:
        if len(child) == 0:
            out[child.tag] = _coerce_scalar(child.text or "")
        else:
            out[child.tag] = _element_leaf_dict(child)
    return out


def chirp_xml_bytes_to_payload(content: bytes) -> Dict[str, Any]:
    """
    Build a dict compatible with `normalize_chirp_payload` from Chirp XML.

    Expects `TransactionSummary` rows under `TransactionSummaries`; optionally
    `Account` rows under `Accounts`.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise ValueError(f"Invalid XML: {e}") from e

    payload: Dict[str, Any] = {}

    accounts: List[Dict[str, Any]] = []
    for acc_parent in root.findall(".//Accounts"):
        for acc in acc_parent.findall("Account"):
            accounts.append(_element_leaf_dict(acc))
    if accounts:
        payload["Accounts"] = accounts

    summaries_el = None
    for el in root.findall(".//TransactionSummaries"):
        summaries_el = el
        break

    if summaries_el is None:
        raise ValueError("XML has no TransactionSummaries section")

    txns: List[Dict[str, Any]] = []
    for ts in summaries_el.findall("TransactionSummary"):
        txns.append(_element_leaf_dict(ts))

    if not txns:
        raise ValueError("XML TransactionSummaries contains no TransactionSummary rows")

    payload["TransactionSummaries"] = txns
    return payload
