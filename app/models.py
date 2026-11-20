"""
Pydantic Models for Supply Chain Disruption Analyser.
Strictly defines models matching ARCHITECTURE.md Section 5.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from app.vocabularies import (
    Country, Sector, Commodity, Mechanism, Metric,
    TimeHorizon, EventStatus, ClaimType, ClaimStatus,
    ResponseType, RulingVerdict, FindingClassification, ConfidenceLevel
)


class TableRef(BaseModel):
    doc_id: str
    row: int
    column: str


class EvidenceRef(BaseModel):
    evidence_id: str
    doc_id: str
    paragraph: Optional[int] = None
    quote: Optional[str] = None
    table_ref: Optional[TableRef] = None


class Estimate(BaseModel):
    value: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None
    unit: str = ""
    base: Optional[str] = None
    method: str = "Empirical documentary derivation"
    assumptions: List[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if self.value is None:
            if self.high is not None and self.low is not None:
                self.value = (self.low + self.high) / 2.0
            elif self.high is not None:
                self.value = self.high
            elif self.low is not None:
                self.value = self.low
        if self.value is not None:
            if self.low is None:
                self.low = self.value
            if self.high is None:
                self.high = self.value


class DisruptionScenario(BaseModel):
    trigger: Optional[str] = None
    assumed_duration_days: Optional[int] = None
    assumed_severity: Optional[str] = None


class Claim(BaseModel):
    claim_id: str
    side: str  # "prosecutor" or "defence"
    scenario_id: str
    subject: Optional[str] = None
    title: Optional[str] = None
    mechanism: Mechanism
    geography: Country
    sector: Sector
    commodity: Commodity
    time_horizon: TimeHorizon
    metric: Metric
    estimate: Estimate
    claim_type: ClaimType
    evidence: List[EvidenceRef] = Field(default_factory=list)
    status: ClaimStatus = ClaimStatus.ORIGINAL
    supersedes: Optional[str] = None
    status_reason: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        if not self.subject and self.title:
            self.subject = self.title
        elif not self.subject:
            self.subject = f"Disruption claim [{self.claim_id}]"

    @classmethod
    def sanitize_field(cls, field_name: str, val: Any) -> Any:
        if field_name == "geography":
            val_str = str(val).upper().strip()
            if val_str in Country.__members__:
                return Country[val_str]
            return Country.GLOBAL
        elif field_name == "commodity":
            val_str = str(val).lower().strip()
            for c in Commodity:
                if c.value == val_str:
                    return c
            return Commodity.CRUDE_OIL
        elif field_name == "sector":
            val_str = str(val).lower().strip()
            for s in Sector:
                if s.value == val_str:
                    return s
            return Sector.ENERGY_UPSTREAM
        return val


class EvidenceCard(BaseModel):
    evidence_id: str
    doc_id: str
    paragraph: Optional[int] = None
    quote: Optional[str] = None
    table_ref: Optional[TableRef] = None
    title: str
    published_at: Optional[str] = None
    source_tier: int = Field(ge=1, le=4)
    source_type: str = "unknown"
    source_category: str = "journalistic"  # official, corporate, journalistic, social, anonymous
    primary_reporting: bool = True
    independent: bool = True
    sentiment_only: bool = False
    retracted: bool = False
    event_id: str = "NONE"
    country: Optional[str] = None
    sector: Optional[str] = None
    hash: str = ""


class NamedScenario(BaseModel):
    scenario_id: str
    duration_days: int
    severity: str
    description: str


class ExcludedDocument(BaseModel):
    doc_id: str
    reason: str


class CaseFile(BaseModel):
    case_id: str
    question: str
    event_summary: str
    as_of_date: str
    event_status: EventStatus
    event_status_reasoning: str
    perspective: str = "general"
    reference_region: List[Country] = Field(default_factory=list)
    reference_sectors: List[str] = Field(default_factory=list)
    scenarios: List[NamedScenario] = Field(default_factory=list)
    approved_pool: List[str] = Field(default_factory=list)  # list of evidence_ids
    excluded_documents: List[ExcludedDocument] = Field(default_factory=list)
    coverage_matrix: Dict[str, bool] = Field(default_factory=dict)
    disputed_cells: List[str] = Field(default_factory=list)
    target_commodities: List[str] = Field(default_factory=list)
    target_countries: List[str] = Field(default_factory=list)
    target_sectors: List[str] = Field(default_factory=list)
    low_coverage: bool = False
    coverage_warning: Optional[str] = None
    is_degraded: bool = False
    degraded_reason: Optional[str] = None


class Round2Response(BaseModel):
    response_id: str
    side: str  # "prosecutor" or "defence"
    response_type: ResponseType
    targets: str  # opposing claim_id
    claim_produced: Optional[str] = None
    reasoning: str
    concession_action: Optional[str] = None


class AcceptedEstimate(BaseModel):
    low: float
    high: float
    unit: str
    estimate_type: str = "direct"  # "direct" or "mitigated"
    basis: Optional[str] = None
    derivation: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        if not self.basis and self.derivation:
            self.basis = self.derivation
        elif not self.basis:
            self.basis = "Derived from documentary evidence and advocate bounds"


class Ruling(BaseModel):
    ruling_id: Optional[str] = None
    dispute_thread_id: Optional[str] = None
    thread_id: Optional[str] = None
    prosecutor_claim_ids: List[str] = Field(default_factory=list)
    defence_claim_ids: List[str] = Field(default_factory=list)
    ruling: RulingVerdict
    ruled_for: Optional[str] = None  # "prosecutor", "defence", or None
    classification: FindingClassification
    claim_type_assessment: ClaimType = ClaimType.SOURCED_FACT
    accepted_estimate: Optional[AcceptedEstimate] = None
    engagement_quality: Optional[str] = None
    model_used: Optional[str] = None
    supporting_quote: Optional[str] = None
    reasoning: str = ""
    relevance_ok: Optional[bool] = None
    comparable: Optional[bool] = None
    confidence: Optional[str] = None
    headline_eligible: Optional[bool] = None
    engagement_notes: Optional[str] = None
    assumptions: List[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if not self.dispute_thread_id and self.thread_id:
            self.dispute_thread_id = self.thread_id
        if not self.ruling_id:
            self.ruling_id = f"RUL-{self.dispute_thread_id or 'GEN'}"


class GapObject(BaseModel):
    gap_id: str
    description: str
    scope: Dict[str, str]  # geography, sector, commodity, time_horizon
    severity: str = "material"
    already_searched: bool = False


class DismissalReport(BaseModel):
    case_id: str
    event_status: EventStatus
    reasoning: str
    coverage_found: Dict[str, Any] = Field(default_factory=dict)
    suggestion: Optional[str] = None


class EvidenceRequest(BaseModel):
    request_id: str
    requester: str  # "prosecutor" or "defence"
    request: str
    reason: str  # private to requester + Gatekeeper
    missing_scope: Dict[str, str]
    results: List[str] = Field(default_factory=list)
    fulfilled: bool = False


class DisputeThread(BaseModel):
    thread_id: str
    key: str  # country:sector:commodity:time_horizon:metric:scenario_id
    prosecutor_claims: List[Claim] = Field(default_factory=list)
    defence_claims: List[Claim] = Field(default_factory=list)
    context_claims: List[Claim] = Field(default_factory=list)
    is_loose_match: bool = False
    match_level: str = "exact"  # "exact", "relaxed", or "related"
    comparable: bool = True  # False if metrics/bases differ or one claim has no number


class ExposureCell(BaseModel):
    country: str
    sector: str
    commodity: str
    time_horizon: str
    metric: str = "volume_shortfall"
    scenario_id: str
    direct_exposure: Optional[Dict[str, Any]] = None
    mitigated_exposure: Optional[Dict[str, Any]] = None
    status: str = "known"  # "known", "unknown"
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    supporting_rulings: List[str] = Field(default_factory=list)
    label: str = "derived_from_rulings"


class FinalBriefing(BaseModel):
    case_id: str
    event_status: EventStatus
    headline: Optional[str] = None
    executive_summary: str
    established_findings: List[str] = Field(default_factory=list)
    contested_findings: List[str] = Field(default_factory=list)
    conceded_findings: List[str] = Field(default_factory=list)
    insufficient_findings: List[str] = Field(default_factory=list)
    withdrawn_claims: List[Dict[str, Any]] = Field(default_factory=list)
    exposure_table: List[ExposureCell] = Field(default_factory=list)
    outlook: str
    assumptions: List[str] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    source_list: List[Dict[str, Any]] = Field(default_factory=list)
    is_degraded: bool = False
    is_partial_degraded: bool = False
    degraded_reason: Optional[str] = None
    ruling_models: List[str] = Field(default_factory=list)

