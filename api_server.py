"""
Chirp deployment/API handoff service.

This API wraps the existing Chirp mapping, categorisation, and scoring modules in this repo.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

_KIT_DIR = Path(__file__).resolve().parent
_CHIRP_DIR = _KIT_DIR.parent
_REPO_ROOT = _CHIRP_DIR.parent
for _path in (_REPO_ROOT, _CHIRP_DIR, _KIT_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from chirp_engine_runner import _chirp_label_match_method, run_chirp_scoring_pipeline
from chirp_plaid_bridge import (
    chirp_json_to_engine_transactions,
    load_chirp_upload_raw,
    normalize_chirp_payload,
)
from chirp_product_config import (
    CHIRP_PRICING_ANCHORS,
    CHIRP_PRICING_SCHEDULE,
    CHIRP_PRODUCT_CONFIG,
    build_chirp_product_config,
    resolve_chirp_scheduled_daily_rate,
)
from openbanking_engine.categorisation.engine import TransactionCategorizer


class ScoreRequest(BaseModel):
    payload: Dict[str, Any] = Field(..., description="Chirp JSON object payload")
    requested_amount: float = Field(500.0, ge=300, le=1000)
    requested_term: int = Field(4, ge=3, le=6)
    lookback_months: int = Field(3, ge=1, le=12)
    pricing_cadence: Literal["monthly", "biweekly"] = "monthly"
    override_daily_interest_pct: Optional[float] = Field(
        None, ge=0.0001, le=5.0, description="Optional override in percent per day"
    )


class CategorizeRequest(BaseModel):
    payload: Dict[str, Any]


app = FastAPI(
    title="Chirp Scoring API",
    description="API wrapper for Chirp mapping, categorisation, and scoring pipeline.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory decision store; persisted to decisions.json on each write.
_DECISIONS_FILE = _KIT_DIR / "decisions.json"
_decisions: Dict[str, Any] = json.loads(_DECISIONS_FILE.read_text()) if _DECISIONS_FILE.exists() else {}


def _build_product_config(
    requested_amount: float,
    pricing_cadence: str,
    override_daily_interest_pct: Optional[float],
) -> Dict[str, Any]:
    scheduled_daily_dec, tier_anchor, simple_pa_pct = resolve_chirp_scheduled_daily_rate(
        requested_amount, pricing_cadence
    )
    daily_dec = (
        override_daily_interest_pct / 100.0
        if override_daily_interest_pct is not None
        else scheduled_daily_dec
    )
    cfg = build_chirp_product_config(daily_dec)
    cfg["chirp_pricing_cadence"] = pricing_cadence
    cfg["chirp_pricing_override"] = override_daily_interest_pct is not None
    cfg["chirp_pricing_tier_anchor"] = tier_anchor
    cfg["chirp_pricing_simple_pa_pct"] = round(simple_pa_pct, 2)
    return cfg


def _rows_for_categorisation(engine_transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    categorizer = TransactionCategorizer()
    categorized = categorizer.categorize_transactions_batch(engine_transactions)
    out: List[Dict[str, Any]] = []
    for txn, category_match in categorized:
        chirp_meta = txn.get("_chirp") if isinstance(txn.get("_chirp"), dict) else {}
        pfc = txn.get("personal_finance_category")
        if not isinstance(pfc, dict):
            pfc = {}
        out.append(
            {
                "date": txn.get("date") or "",
                "description": txn.get("description") or txn.get("name") or "Unknown",
                "merchant_name": txn.get("merchant_name") or "",
                "amount": txn.get("amount", 0),
                "engine_amount_convention": "negative=credit_in; positive=debit_out",
                "chirp_top_level_category": chirp_meta.get("top_level_category") or "",
                "chirp_category": chirp_meta.get("category") or "",
                "chirp_type": chirp_meta.get("type") or "",
                "chirp_category_code": chirp_meta.get("categoryCode") or "",
                "chirp_parent_category_code": chirp_meta.get("parentCategoryCode") or "",
                "chirp_merchant_category_code": chirp_meta.get("merchant_category_code") or "",
                "synthetic_pfc_primary": str(pfc.get("primary") or ""),
                "synthetic_pfc_detailed": str(pfc.get("detailed") or ""),
                "category": category_match.category,
                "subcategory": category_match.subcategory,
                "confidence": round(category_match.confidence, 3),
                "match_method": _chirp_label_match_method(category_match.match_method),
                "description_text": category_match.description,
                "risk_level": category_match.risk_level or "",
                "weight": category_match.weight,
                "is_stable": category_match.is_stable,
                "is_housing": category_match.is_housing,
            }
        )
    return out


def _summary_for_rows(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "total_transactions": len(results),
        "by_category": defaultdict(int),
        "by_subcategory": defaultdict(int),
        "by_chirp_category": defaultdict(int),
        "by_match_method": defaultdict(int),
        "amount_by_category": defaultdict(float),
        "amount_by_subcategory": defaultdict(float),
        "amount_by_chirp_category": defaultdict(float),
        "by_confidence_level": {"high": 0, "medium": 0, "low": 0},
        "income_count": 0,
        "expense_count": 0,
        "transfer_count": 0,
        "income_amount": 0.0,
        "expense_amount": 0.0,
        "transfer_amount": 0.0,
    }
    for result in results:
        category = result["category"]
        subcategory_key = f"{category}/{result['subcategory']}"
        chirp_key = (
            f"{result['chirp_top_level_category']}/{result['chirp_category']}"
            if result["chirp_top_level_category"] or result["chirp_category"]
            else "Unknown"
        )
        summary["by_category"][category] += 1
        summary["by_subcategory"][subcategory_key] += 1
        summary["by_chirp_category"][chirp_key] += 1
        summary["by_match_method"][result["match_method"]] += 1
        raw_amt = float(result.get("amount") or 0.0)
        amount = abs(raw_amt)
        summary["amount_by_category"][category] += amount
        summary["amount_by_subcategory"][subcategory_key] += amount
        summary["amount_by_chirp_category"][chirp_key] += amount
        if category == "income" and raw_amt < 0:
            summary["income_count"] += 1
            summary["income_amount"] += amount
        elif category == "transfer":
            summary["transfer_count"] += 1
            summary["transfer_amount"] += amount
        else:
            summary["expense_count"] += 1
            summary["expense_amount"] += amount
        conf = float(result.get("confidence") or 0)
        if conf >= 0.80:
            summary["by_confidence_level"]["high"] += 1
        elif conf >= 0.60:
            summary["by_confidence_level"]["medium"] += 1
        else:
            summary["by_confidence_level"]["low"] += 1

    for key in (
        "by_category",
        "by_subcategory",
        "by_chirp_category",
        "by_match_method",
        "amount_by_category",
        "amount_by_subcategory",
        "amount_by_chirp_category",
    ):
        summary[key] = dict(summary[key])
    for key in ("income_amount", "expense_amount", "transfer_amount"):
        summary[key] = round(summary[key], 2)
    return summary


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/pricing")
def pricing() -> Dict[str, Any]:
    return {
        "min_loan_amount": CHIRP_PRODUCT_CONFIG["min_loan_amount"],
        "max_loan_amount": CHIRP_PRODUCT_CONFIG["max_loan_amount"],
        "anchors": CHIRP_PRICING_ANCHORS,
        "schedule": CHIRP_PRICING_SCHEDULE,
    }


@app.post("/v1/score-json")
def score_json(req: ScoreRequest) -> Dict[str, Any]:
    try:
        normalized = normalize_chirp_payload(req.payload)
        tx = chirp_json_to_engine_transactions(normalized)
        if not tx:
            raise ValueError("No transactions after Chirp mapping")
        cfg = _build_product_config(
            req.requested_amount, req.pricing_cadence, req.override_daily_interest_pct
        )
        result, _ = run_chirp_scoring_pipeline(
            tx,
            requested_amount=req.requested_amount,
            requested_term=req.requested_term,
            product_config=cfg,
            lookback_months=req.lookback_months,
        )
        return {"success": True, "product_config": cfg, "result": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/v1/categorize-json")
def categorize_json(req: CategorizeRequest) -> Dict[str, Any]:
    try:
        normalized = normalize_chirp_payload(req.payload)
        tx = chirp_json_to_engine_transactions(normalized)
        if not tx:
            raise ValueError("No transactions after Chirp mapping")
        rows = _rows_for_categorisation(tx)
        return {
            "success": True,
            "total_transactions": len(rows),
            "results": rows,
            "summary": _summary_for_rows(rows),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/v1/score-file")
async def score_file(
    file: UploadFile = File(...),
    requested_amount: float = Form(500.0),
    requested_term: int = Form(4),
    lookback_months: int = Form(3),
    pricing_cadence: Literal["monthly", "biweekly"] = Form("monthly"),
    override_daily_interest_pct: Optional[float] = Form(None),
) -> Dict[str, Any]:
    try:
        name = file.filename or "upload.json"
        content = await file.read()
        raw = load_chirp_upload_raw(name, content)
        normalized = normalize_chirp_payload(raw)
        tx = chirp_json_to_engine_transactions(normalized)
        if not tx:
            raise ValueError("No transactions after Chirp mapping")
        cfg = _build_product_config(
            requested_amount, pricing_cadence, override_daily_interest_pct
        )
        result, _ = run_chirp_scoring_pipeline(
            tx,
            requested_amount=requested_amount,
            requested_term=requested_term,
            product_config=cfg,
            lookback_months=max(1, min(12, int(lookback_months))),
        )
        return {"success": True, "filename": name, "product_config": cfg, "result": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/v1/categorize-file")
async def categorize_file(file: UploadFile = File(...)) -> Dict[str, Any]:
    try:
        name = file.filename or "upload.json"
        content = await file.read()
        raw = load_chirp_upload_raw(name, content)
        normalized = normalize_chirp_payload(raw)
        tx = chirp_json_to_engine_transactions(normalized)
        if not tx:
            raise ValueError("No transactions after Chirp mapping")
        rows = _rows_for_categorisation(tx)
        return {
            "success": True,
            "filename": name,
            "total_transactions": len(rows),
            "results": rows,
            "summary": _summary_for_rows(rows),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/v1/example-score-payload")
def example_score_payload() -> Dict[str, Any]:
    return {
        "payload": {
            "Success": True,
            "TransactionSummaries": [],
            "Accounts": [],
        },
        "requested_amount": 500,
        "requested_term": 4,
        "lookback_months": 3,
        "pricing_cadence": "monthly",
        "override_daily_interest_pct": None,
    }


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def serve_dashboard() -> HTMLResponse:
    html = (_KIT_DIR / "dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


# ── Bulk ZIP scoring ──────────────────────────────────────────────────────────

@app.post("/v1/bulk-score-zip")
async def bulk_score_zip(
    file: UploadFile = File(...),
    requested_amount: float = Form(500.0),
    requested_term: int = Form(4),
    lookback_months: int = Form(3),
    pricing_cadence: Literal["monthly", "biweekly"] = Form("monthly"),
    override_daily_interest_pct: Optional[float] = Form(None),
) -> Dict[str, Any]:
    content = await file.read()
    results: List[Dict[str, Any]] = []

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP archive")

    names = [n for n in zf.namelist() if not n.startswith("__MACOSX") and n.lower().endswith((".json", ".xml"))]
    if not names:
        raise HTTPException(status_code=400, detail="ZIP contains no .json or .xml files")

    cfg = _build_product_config(requested_amount, pricing_cadence, override_daily_interest_pct)

    for name in names:
        short = Path(name).name
        try:
            file_bytes = zf.read(name)
            raw = load_chirp_upload_raw(short, file_bytes)
            normalized = normalize_chirp_payload(raw)
            tx = chirp_json_to_engine_transactions(normalized)
            if not tx:
                raise ValueError("No transactions after Chirp mapping")
            result, _ = run_chirp_scoring_pipeline(
                tx,
                requested_amount=requested_amount,
                requested_term=requested_term,
                product_config=cfg,
                lookback_months=max(1, min(12, int(lookback_months))),
            )
            results.append({"filename": short, "success": True, "result": result})
        except Exception as exc:
            results.append({"filename": short, "success": False, "error": str(exc)})

    zf.close()
    return {"files_processed": len(results), "results": results}


# ── Underwriter decisions ─────────────────────────────────────────────────────

class DecisionRequest(BaseModel):
    app_id: str
    filename: Optional[str] = None
    uw_decision: str
    comment: Optional[str] = None
    submitted_at: Optional[str] = None
    system_decision: Optional[str] = None
    score: Optional[float] = None


@app.post("/v1/decision")
def store_decision(req: DecisionRequest) -> Dict[str, Any]:
    _decisions[req.app_id] = req.model_dump()
    _DECISIONS_FILE.write_text(json.dumps(_decisions, indent=2))
    return {"stored": True, "app_id": req.app_id}


@app.get("/v1/decisions")
def list_decisions() -> Dict[str, Any]:
    return {"total": len(_decisions), "decisions": _decisions}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=True)
