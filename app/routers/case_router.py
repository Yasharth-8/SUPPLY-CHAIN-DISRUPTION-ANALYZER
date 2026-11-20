"""
FastAPI Case Router: Full REST API and WebSocket live stream.
"""

import json
import asyncio
from typing import Dict, Any, Optional
from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

from app.graph.workflow import trial_graph
from app.config import CASES_DIR, DOCS_DIR
from app.services.document_loader import DocumentLoader


router = APIRouter(prefix="/api", tags=["Case Management"])

# In-memory case storage and active websocket connections
cases_store: Dict[str, Dict[str, Any]] = {}
active_connections: Dict[str, list[WebSocket]] = {}
loader = DocumentLoader()


class SubmitCaseRequest(BaseModel):
    question: str
    case_id: Optional[str] = None


@router.get("/health")
def health_check():
    return {"status": "ok", "service": "Supply Chain Disruption Analyser"}


@router.post("/case/submit")
async def submit_case(req: SubmitCaseRequest):
    case_id = req.case_id or f"CASE-{len(cases_store) + 1:03d}"

    cases_store[case_id] = {
        "case_id": case_id,
        "question": req.question,
        "status": "processing",
        "state": None,
    }

    # Execute workflow asynchronously or synchronously
    asyncio.create_task(_run_workflow_async(case_id, req.question))

    return {
        "case_id": case_id,
        "status": "submitted",
        "message": "Trial initiated across Gatekeeper, Prosecutor, Defence, and The Bench."
    }


NODE_STAGE_MAP = {
    "intake": ("prosecutor", "Step 2/5: Prosecutor calculating worst-case disruption impact…"),
    "round1": ("defence", "Step 3/5: Defence checking backup pipelines and emergency reserves…"),
    "court_pass1": ("rebuttals", "Step 4/5: Both sides cross-examining numbers and evidence…"),
    "round2": ("rebuttals", "Step 4/5: Both sides cross-examining numbers and evidence…"),
    "court_pass2": ("judge", "Step 5/5: The Bench delivering verified findings…"),
    "judge": ("judge", "Step 5/5: The Bench delivering verified findings…"),
    "delta_re_search": ("judge", "Step 5/5: The Bench delivering verified findings…"),
    "exposure": ("judge", "Step 5/5: The Bench delivering verified findings…"),
    "briefing": ("judge", "Step 5/5: The Bench delivering verified findings…"),
}


async def _run_workflow_async(case_id: str, question: str):
    cases_store[case_id]["current_stage"] = "gatekeeper"
    await _broadcast_event(case_id, {"event": "status_change", "stage": "gatekeeper", "detail": "Gatekeeper examining case and evidence pool..."})

    def _execute():
        accumulated_state = {"case_id": case_id, "question": question}
        for chunk in trial_graph.stream(accumulated_state):
            node_name = list(chunk.keys())[0]
            accumulated_state.update(chunk[node_name])
            if node_name in NODE_STAGE_MAP:
                stage, detail = NODE_STAGE_MAP[node_name]
                cases_store[case_id]["current_stage"] = stage
        return accumulated_state

    try:
        final_state = await asyncio.to_thread(_execute)
        cases_store[case_id]["state"] = final_state
        cases_store[case_id]["status"] = final_state.get("status", "completed")
        cases_store[case_id]["current_stage"] = "judge"

        await _broadcast_event(case_id, {
            "event": "trial_completed",
            "status": final_state.get("status"),
            "case_id": case_id
        })
    except Exception as e:
        cases_store[case_id]["status"] = "error"
        cases_store[case_id]["error"] = str(e)
        await _broadcast_event(case_id, {"event": "error", "error": str(e)})


async def _broadcast_event(case_id: str, message: Dict[str, Any]):
    if case_id in active_connections:
        for ws in active_connections[case_id]:
            try:
                await ws.send_json(message)
            except Exception:
                pass


@router.get("/case/{case_id}/status")
def get_status(case_id: str):
    if case_id not in cases_store:
        raise HTTPException(status_code=404, detail="Case not found")
    case_info = cases_store[case_id]
    state = case_info.get("state") or {}
    return {
        "case_id": case_id,
        "status": case_info["status"],
        "current_stage": case_info.get("current_stage", "gatekeeper"),
        "error": case_info.get("error"),
        "is_degraded": state.get("is_degraded", False),
        "is_partial_degraded": state.get("is_partial_degraded", False),
        "degraded_reason": state.get("degraded_reason"),
    }


@router.get("/case/{case_id}/verdict")
def get_verdict(case_id: str):
    case_info = cases_store.get(case_id)
    if not case_info or not case_info.get("state"):
        raise HTTPException(status_code=404, detail="Verdict not ready or case not found")
    state = case_info["state"]
    return {
        "case_id": case_id,
        "rulings": [r.model_dump() for r in state.get("rulings", [])],
        "is_sufficient": state.get("is_sufficient", True),
        "gaps": [g.model_dump() for g in state.get("gaps", [])],
        "threads": [t.model_dump() for t in state.get("threads", [])],
        "prosecutor_responses": [r.model_dump() for r in state.get("prosecutor_responses", [])],
        "defence_responses": [r.model_dump() for r in state.get("defence_responses", [])],
    }


@router.get("/case/{case_id}/casefile")
def get_casefile(case_id: str):
    case_info = cases_store.get(case_id)
    if not case_info or not case_info.get("state"):
        raise HTTPException(status_code=404, detail="Case file not ready")
    state = case_info["state"]
    cf = state.get("case_file")
    if not cf:
        return {"dismissal": state.get("dismissal_report")}
    return cf.model_dump()


@router.get("/case/{case_id}/evidence")
def get_case_evidence(case_id: str):
    case_info = cases_store.get(case_id)
    if not case_info or not case_info.get("state"):
        raise HTTPException(status_code=404, detail="Case evidence not ready")
    state = case_info["state"]
    cards_map = state.get("evidence_cards") or {}
    cf = state.get("case_file")
    pool_ids = set(cf.approved_pool) if cf else set()

    approved_cards = [
        c.model_dump() for c in cards_map.values()
        if not pool_ids or c.evidence_id in pool_ids
    ]
    return {
        "case_id": case_id,
        "total": len(approved_cards),
        "cards": approved_cards
    }


@router.get("/case/{case_id}/claims")
def get_claims(case_id: str):
    case_info = cases_store.get(case_id)
    if not case_info or not case_info.get("state"):
        raise HTTPException(status_code=404, detail="Claims not ready")
    state = case_info["state"]
    return {
        "prosecutor_claims": [c.model_dump() for c in state.get("prosecutor_claims", [])],
        "defence_claims": [c.model_dump() for c in state.get("defence_claims", [])],
        "prosecutor_responses": [r.model_dump() for r in state.get("prosecutor_responses", [])],
        "defence_responses": [r.model_dump() for r in state.get("defence_responses", [])],
        "unanswered_material": [c.model_dump() for c in state.get("unanswered_material", [])],
    }


@router.get("/case/{case_id}/exposure")
def get_exposure(case_id: str):
    case_info = cases_store.get(case_id)
    if not case_info or not case_info.get("state"):
        raise HTTPException(status_code=404, detail="Exposure matrix not ready")
    state = case_info["state"]
    cells = state.get("exposure_cells", [])
    return {
        "case_id": case_id,
        "cells": [c.model_dump() for c in cells]
    }


@router.get("/case/{case_id}/briefing")
def get_briefing(case_id: str):
    case_info = cases_store.get(case_id)
    if not case_info or not case_info.get("state"):
        raise HTTPException(status_code=404, detail="Briefing not ready")
    state = case_info["state"]
    b = state.get("briefing")
    if not b:
        raise HTTPException(status_code=404, detail="Briefing not available")
    return b.model_dump()


@router.get("/feed")
def get_news_feed():
    feed_items = []
    if DOCS_DIR.exists():
        for f in sorted(DOCS_DIR.iterdir()):
            if f.is_file() and f.suffix in (".txt", ".pdf", ".docx"):
                p = loader.load_document(str(f))
                if p.is_valid:
                    feed_items.append({
                        "doc_id": p.doc_id,
                        "title": p.title,
                        "date": p.pub_date,
                        "time": p.pub_time,
                        "tier": p.reliability_tier,
                        "country": p.country,
                        "sector": p.sector,
                        "source_name": p.source_name,
                        "sentiment_only": (p.reliability_tier >= 4)
                    })
    return feed_items[:30]


@router.get("/docs/{doc_id}")
def get_doc(doc_id: str):
    for f in DOCS_DIR.iterdir():
        if f.stem.upper() == doc_id.upper():
            p = loader.load_document(str(f))
            return p.to_dict()
    raise HTTPException(status_code=404, detail="Document not found")


@router.websocket("/ws/case/{case_id}")
async def websocket_case_stream(websocket: WebSocket, case_id: str):
    await websocket.accept()
    if case_id not in active_connections:
        active_connections[case_id] = []
    active_connections[case_id].append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections[case_id].remove(websocket)

