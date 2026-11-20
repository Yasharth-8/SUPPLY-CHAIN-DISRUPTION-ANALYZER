"""
LangGraph Trial State Definition.
TypedDict state holding the full lifecycle of a supply chain court case.
"""

from typing import TypedDict, List, Optional, Dict, Any

from app.models import (
    CaseFile, DismissalReport, Claim, Round2Response, DisputeThread,
    Ruling, GapObject, ExposureCell, FinalBriefing, EvidenceCard
)


class TrialState(TypedDict, total=False):
    case_id: str
    question: str
    case_file: Optional[CaseFile]
    dismissal_report: Optional[DismissalReport]
    evidence_cards: Dict[str, EvidenceCard]
    prosecutor_claims: List[Claim]
    defence_claims: List[Claim]
    prosecutor_responses: List[Round2Response]
    defence_responses: List[Round2Response]
    threads: List[DisputeThread]
    unpaired_claims: List[Claim]
    unanswered_material: List[Claim]
    rulings: List[Ruling]
    gaps: List[GapObject]
    is_sufficient: bool
    run_number: int
    exposure_cells: List[ExposureCell]
    briefing: Optional[FinalBriefing]
    is_degraded: bool
    degraded_reason: Optional[str]
    status: str  # "intake", "round1", "round2", "adjudication", "sufficient", "remand", "completed", "dismissed"

