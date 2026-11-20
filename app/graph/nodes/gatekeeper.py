"""
Gatekeeper Node: Intake, Rule-Based Event Verification, Approved Pool Construction.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel

from app.models import (
    CaseFile, NamedScenario, ExcludedDocument, DismissalReport, EvidenceCard
)
from app.vocabularies import EventStatus, Country, Sector
from app.services.document_loader import DocumentLoader, ParsedDocument
from app.services.evidence_service import EvidenceService
from app.services.search import SearchService
from app.services.llm_client import LLMClient
from app.prompts.gatekeeper import GATEKEEPER_SYSTEM_PROMPT
from app.config import DOCS_DIR, GATEKEEPER_TEMPERATURE


class GatekeeperAnalysisOutput(BaseModel):
    is_off_topic: bool = False
    on_topic: Optional[bool] = None
    reject_reason: Optional[str] = None
    is_hypothetical: bool = False
    mode: Optional[str] = None
    event_summary: str = ""
    as_of_date: str = "2027-02-20"
    beyond_cutoff: bool = False
    perspective: str = "general"
    reference_region: List[Country] = []
    origin_countries: List[Country] = []
    affected_countries: List[Country] = []
    reference_sectors: List[str] = []
    sectors: List[str] = []
    commodities: List[str] = []
    scenarios: List[NamedScenario] = []
    event_status: Optional[str] = None
    status_reasoning: Optional[str] = None
    scope_interpretation: Optional[str] = None
    ambiguity_flags: List[str] = []
    reasoning: str = ""

    def model_post_init(self, __context: Any) -> None:
        if self.on_topic is not None and not self.on_topic:
            self.is_off_topic = True
        if self.mode and "hypo" in self.mode.lower():
            self.is_hypothetical = True
        if not self.reference_region:
            combined = set()
            for c in (self.affected_countries + self.origin_countries):
                combined.add(c)
            if combined:
                self.reference_region = list(combined)
        if not self.reference_sectors and self.sectors:
            self.reference_sectors = self.sectors
        if self.scope_interpretation and self.scope_interpretation not in self.event_summary:
            self.event_summary = f"{self.event_summary} [{self.scope_interpretation}]" if self.event_summary else self.scope_interpretation


class GatekeeperNode:
    def __init__(self, docs_dir: Optional[Path] = None):
        self.docs_dir = docs_dir or DOCS_DIR
        self.loader = DocumentLoader()
        self.evidence_service = EvidenceService()
        self.llm = LLMClient()

    def run(self, question: str, case_id: str = "CASE-001") -> Tuple[Optional[CaseFile], Optional[DismissalReport], EvidenceService, SearchService]:
        """
        Executes Gatekeeper pipeline:
        1. Parse question and extract scope via LLM.
        2. Handle off-topic rejection.
        3. Load all documents from docs_dir and apply exclusion filters.
        4. Rule-based event status classification.
        5. Build CaseFile or DismissalReport.
        """
        # Check deterministic off-topic heuristics first
        q_lower = question.lower()
        off_topic_keywords = ["poem", "joke", "recipe", "song", "weather in", "write me a story", "love"]
        supply_chain_keywords = [
            "supply", "chain", "port", "ship", "vessel", "cargo", "tanker", "crude", "oil",
            "gas", "lng", "export", "import", "strike", "blockade", "chokepoint", "hormuz",
            "suez", "canal", "trade", "tariff", "fertilizer", "urea", "grain", "wheat",
            "logistics", "freight", "container", "refinery", "sanction"
        ]

        is_obviously_off_topic = any(k in q_lower for k in off_topic_keywords) and not any(k in q_lower for k in supply_chain_keywords)

        # Step 1: LLM scoping analysis
        prompt = f"Analyze this supply chain question:\n\"{question}\"\nProvide event summary, as_of_date, scenarios, and check if off-topic or hypothetical."
        analysis: GatekeeperAnalysisOutput = self.llm.generate_structured(
            prompt=prompt,
            system_instruction=GATEKEEPER_SYSTEM_PROMPT,
            response_model=GatekeeperAnalysisOutput,
            temperature=GATEKEEPER_TEMPERATURE,
        )

        if is_obviously_off_topic or analysis.is_off_topic:
            reason = "The submitted inquiry is not related to a supply chain disruption scenario."
            if analysis.reject_reason:
                reason = f"{reason} ({analysis.reject_reason})"
            elif analysis.reasoning:
                reason = f"{reason} ({analysis.reasoning})"
            dismissal = DismissalReport(
                case_id=case_id,
                event_status=EventStatus.UNSUPPORTED,
                reasoning=reason,
                coverage_found={"relevant_documents": 0},
                suggestion="Please submit a question concerning ports, shipping, commodity trade, or geopolitical chokepoints."
            )
            return None, dismissal, self.evidence_service, SearchService([])

        # Defaults if LLM returns empty
        summary = analysis.event_summary or question
        as_of = analysis.as_of_date or "2027-02-20"
        
        q_lower = question.lower()
        import re
        q_words = set(re.findall(r'\b[a-z0-9_-]+\b', q_lower))

        # Disambiguate and interpret ambiguous maritime entities (e.g. Mumbai port)
        is_mumbai = bool(q_words & {"mumbai", "bombay", "jnpt", "nhava", "sheva"})
        if is_mumbai:
            mumbai_interp = "Interpreted as the greater Mumbai maritime cluster: Jawaharlal Nehru Port (JNPT / Nhava Sheva container gateway handling ~50% of national container volume) and Mumbai Port Trust (MbPT bulk/liquid berths)."
            if "jnpt" not in summary.lower() and "nhava" not in summary.lower():
                summary = f"{summary} [{mumbai_interp}]"

        # Check for permanent closure duration
        is_permanent = any(w in q_lower for w in ["permanent", "permanently", "forever", "indefinite", "indefinitely", "destroy", "destroyed", "destruction"])

        # Enforce canonical named scenarios to prevent LLM scenario fragmentation
        if is_permanent:
            scenarios = [
                NamedScenario(scenario_id="permanent", duration_days=9999, severity="full", description="Permanent closure: indefinite multi-gateway rerouting and structural realignment"),
                NamedScenario(scenario_id="base", duration_days=365, severity="full", description="First-year permanent diversion and rerouting shock"),
                NamedScenario(scenario_id="short", duration_days=30, severity="partial", description="Initial 30-day diversion and congestion shock"),
            ]
        else:
            scenarios = [
                NamedScenario(scenario_id="base", duration_days=60, severity="partial", description="Sustained 60-day disruption"),
                NamedScenario(scenario_id="short", duration_days=14, severity="partial", description="Brief 14-day disruption"),
                NamedScenario(scenario_id="severe", duration_days=180, severity="full", description="Extended 180-day severe blockage"),
            ]

        # Determine target focus (countries, sectors, commodities) from inquiry using token boundaries
        target_countries = []
        indian_maritime_entities = {
            "india", "indian", "mumbai", "bombay", "jnpt", "nhava", "sheva", "mundra", "kandla",
            "cochin", "chennai", "ennore", "tuticorin", "vizag", "visakhapatnam",
            "paradip", "haldia", "kolkata", "hazira", "dahej", "nagothane",
            "tirupur", "delhi", "wdfc", "imec", "chabahar"
        }
        if q_words & indian_maritime_entities: target_countries.append("IN")
        if q_words & {"china", "chinese"}: target_countries.append("CN")
        if q_words & {"brazil", "brazilian"}: target_countries.append("BR")
        if q_words & {"germany", "german"}: target_countries.append("DE")
        if q_words & {"us", "usa", "america", "american"} or "united states" in q_lower: target_countries.append("US")
        if not target_countries and analysis.reference_region:
            target_countries = [c.value if hasattr(c, "value") else str(c) for c in analysis.reference_region]
        if not target_countries:
            target_countries = ["GLOBAL"]

        target_sectors = []
        if q_words & {"fertilizer", "fertilizers", "urea", "crop", "crops", "agriculture", "potash", "dap", "farming", "food"}:
            target_sectors.extend(["chemicals", "agriculture"])
        if q_words & {"crude", "oil", "petroleum", "fuel", "diesel", "gas", "lng", "refining", "energy", "hormuz"}:
            target_sectors.append("energy")
        if q_words & {"port", "ports", "shipping", "dockworker", "dockworkers", "strike", "transit", "canal", "gateway", "berth"}:
            target_sectors.append("logistics")
        has_specific_commodity_query = bool(
            q_words & {"fertilizer", "fertilizers", "urea", "potash", "dap", "crude", "oil", "petroleum", "fuel", "diesel", "gas", "lng", "methane", "wheat", "rice", "grain", "soybeans", "sugar", "coal", "iron_ore"}
        )
        is_multimodal_hub = bool(
            is_mumbai or (q_words & {"port", "ports", "shipping", "gateway", "corridor", "maritime", "dockworker", "strike", "canal", "chokepoint"})
        )

        if is_multimodal_hub and not has_specific_commodity_query:
            # Broaden scope across all major commodity sectors handled by the trade corridor
            for s in ["logistics", "energy", "agriculture", "chemicals", "automotive", "electronics"]:
                if s not in target_sectors:
                    target_sectors.append(s)
        elif is_mumbai:
            for s in ["logistics", "automotive", "electronics", "chemicals"]:
                if s not in target_sectors:
                    target_sectors.append(s)

        if not target_sectors and analysis.reference_sectors:
            target_sectors = [Sector.get_parent(s) for s in analysis.reference_sectors]
        if not target_sectors:
            target_sectors = ["energy", "logistics"]

        target_commodities = []
        if q_words & {"fertilizer", "fertilizers", "urea", "potash", "dap"}:
            target_commodities.extend(["urea", "fertilizer", "dap", "potash"])
        if q_words & {"crude", "oil", "petroleum", "diesel", "fuel", "gasoline"}:
            target_commodities.extend(["crude_oil", "refined_fuels"])
        if q_words & {"lng", "gas", "methane"}:
            target_commodities.append("lng")

        if is_multimodal_hub and not has_specific_commodity_query:
            # Multi-commodity coverage across bulk energy, agriculture, containerized tech, and chemicals
            for comm in ["crude_oil", "refined_fuels", "grain", "rice", "fertilizer", "urea", "electronic_components", "semiconductors", "polymers"]:
                if comm not in target_commodities:
                    target_commodities.append(comm)
        elif is_mumbai:
            target_commodities.extend(["electronic_components", "semiconductors", "polymers", "grain", "crude_oil", "urea"])

        if analysis.commodities:
            for c in analysis.commodities:
                c_clean = c.value.lower() if hasattr(c, "value") else str(c).lower()
                if c_clean not in target_commodities:
                    target_commodities.append(c_clean)

        ref_region = target_countries

        # Step 2: Load docs and apply Gatekeeper exclusion filters
        approved_cards: List[EvidenceCard] = []
        excluded_docs: List[ExcludedDocument] = []
        tier1_2_independent_count = 0
        contradiction_found = False

        if self.docs_dir.exists():
            for fpath in self.docs_dir.iterdir():
                if fpath.is_file():
                    parsed = self.loader.load_document(str(fpath))
                    cards, excl = self.evidence_service.process_document(
                        doc=parsed,
                        as_of_date=as_of,
                        event_id="CRX-2027",
                        reference_region=ref_region,
                        reference_sectors=target_sectors,
                        is_hypothetical=analysis.is_hypothetical,
                    )
                    if excl:
                        excluded_docs.append(excl)
                    else:
                        approved_cards.extend(cards)
                        for c in cards:
                            if c.source_tier in (1, 2) and c.independent:
                                tier1_2_independent_count += 1
                            if c.retracted:
                                contradiction_found = True

        # Step 3: Rule-based Event Classification (Section 11)
        if analysis.is_hypothetical:
            event_status = EventStatus.HYPOTHETICAL
            status_reasoning = "User submitted a hypothetical 'what if' scenario. Analysis proceeding as scenario."
        elif contradiction_found:
            event_status = EventStatus.CONTRADICTED
            status_reasoning = "Event reports were retracted or contradicted by higher-tier sources."
        elif tier1_2_independent_count >= 2:
            event_status = EventStatus.CONFIRMED
            status_reasoning = f"Event verified by {tier1_2_independent_count} independent Tier 1-2 source reports."
        elif tier1_2_independent_count >= 1:
            event_status = EventStatus.REPORTED
            status_reasoning = "Event reported by Tier 1-2 source but uncorroborated by multiple independent bodies."
        else:
            event_status = EventStatus.UNSUPPORTED
            status_reasoning = "No corroborating Tier 1-2 evidence found in the document pool."

        # Handle dismissal for contradicted or unsupported
        if event_status in (EventStatus.CONTRADICTED, EventStatus.UNSUPPORTED):
            dismissal = DismissalReport(
                case_id=case_id,
                event_status=event_status,
                reasoning=status_reasoning,
                coverage_found={"tier1_2_sources_found": tier1_2_independent_count, "approved_cards": len(approved_cards)},
                suggestion="Rephrase the inquiry as a hypothetical scenario: 'What if [event] occurred?'" if event_status == EventStatus.UNSUPPORTED else None
            )
            return None, dismissal, self.evidence_service, SearchService(approved_cards)

        # Step 4: Construct approved CaseFile and extract high-priority disputed cells
        coverage = self.evidence_service.compute_coverage_matrix(approved_cards)

        # Check documentary coverage on the specific case topic
        topic_words = set(target_commodities + [s for s in target_sectors])
        matching_topic_cards = [
            c for c in approved_cards
            if any(w in (c.title + " " + (c.quote or "")).lower() for w in topic_words)
        ]
        low_coverage = len(matching_topic_cards) < 6
        coverage_warning = None
        if low_coverage:
            coverage_warning = f"Thin documentary coverage: only {len(matching_topic_cards)} cards directly address {target_commodities} in {target_countries}."
            print(f"[Gatekeeper Advisory] {coverage_warning}")

        # Check bilateral documentary coverage if multiple distinct countries are posited (e.g. US and IN)
        if len(target_countries) >= 2 and "GLOBAL" not in target_countries:
            COUNTRY_SYNONYMS = {
                "US": ["united states", "usa", "america", "american", "u.s."],
                "CN": ["china", "chinese"],
                "RU": ["russia", "russian"],
                "IN": ["india", "indian"],
                "IR": ["iran", "iranian"],
                "DE": ["germany", "german"],
                "BR": ["brazil", "brazilian"],
            }
            counts_per_country = {}
            for c_code in target_countries:
                syns = COUNTRY_SYNONYMS.get(c_code, [c_code.lower()])
                match_count = sum(
                    1 for card in approved_cards
                    if any(re.search(rf"\b{re.escape(s)}\b", (card.title + " " + (card.quote or "")).lower()) for s in syns)
                )
                counts_per_country[c_code] = match_count

            zero_coverage_countries = [c for c, count in counts_per_country.items() if count == 0]
            if zero_coverage_countries:
                bilateral_warning = f"Zero documentary evidence in repository concerning {zero_coverage_countries} in the context of this disruption inquiry."
                print(f"[Gatekeeper Advisory] {bilateral_warning}")
                coverage_warning = f"{coverage_warning} | {bilateral_warning}" if coverage_warning else bilateral_warning

        # Build concrete, structured disputed cells strictly aligned with case target countries, sectors, commodities, and primary scenario
        disputed_cells: List[str] = []
        default_scen = scenarios[0].scenario_id
        primary_comm = target_commodities[0] if target_commodities else "general"

        for c in target_countries:
            # 1. Logistics / Container gateway
            if "logistics" in target_sectors:
                disputed_cells.append(f"{c}:logistics.shipping:electronic_components:delay_days:0-7d:{default_scen}")
                disputed_cells.append(f"{c}:logistics.shipping:electronic_components:volume_shortfall:0-7d:{default_scen}")
            # 2. Energy / Liquid bulk
            if "energy" in target_sectors:
                e_comm = "crude_oil" if "crude_oil" in target_commodities else ("refined_fuels" if "refined_fuels" in target_commodities else primary_comm)
                disputed_cells.append(f"{c}:energy.upstream:{e_comm}:volume_shortfall:0-7d:{default_scen}")
            # 3. Agriculture & Food / Rice & Grain
            if "agriculture" in target_sectors:
                ag_comm = "rice" if "rice" in target_commodities else ("grain" if "grain" in target_commodities else primary_comm)
                disputed_cells.append(f"{c}:agriculture.farming:{ag_comm}:volume_shortfall:0-7d:{default_scen}")
            # 4. Chemicals & Petrochemicals / Polymers
            if "chemicals" in target_sectors and "polymers" in target_commodities:
                disputed_cells.append(f"{c}:chemicals.petrochemicals:polymers:import_volume_at_risk:0-7d:{default_scen}")
            # 5. Fertilizer / Urea
            if ("chemicals" in target_sectors or "agriculture" in target_sectors) and ("urea" in target_commodities or "fertilizer" in target_commodities):
                f_comm = "urea" if "urea" in target_commodities else "fertilizer"
                disputed_cells.append(f"{c}:chemicals.fertilizer:{f_comm}:volume_shortfall:0-7d:{default_scen}")
            # 6. Electronics & Semiconductors
            if "electronics" in target_sectors or "automotive" in target_sectors:
                if "semiconductors" in target_commodities:
                    disputed_cells.append(f"{c}:electronics:semiconductors:production_at_risk:0-7d:{default_scen}")
                if "electronic_components" in target_commodities and "automotive" in target_sectors:
                    disputed_cells.append(f"{c}:automotive:electronic_components:production_at_risk:0-7d:{default_scen}")

            # Generic fallback if no sector matched
            if not disputed_cells:
                disputed_cells.append(f"{c}:logistics.shipping:{primary_comm}:volume_shortfall:0-7d:{default_scen}")

        case_file = CaseFile(
            case_id=case_id,
            question=question,
            event_summary=summary,
            as_of_date=as_of,
            event_status=event_status,
            event_status_reasoning=status_reasoning,
            perspective=analysis.perspective,
            reference_region=analysis.reference_region,
            reference_sectors=target_sectors,
            scenarios=scenarios,
            approved_pool=[c.evidence_id for c in approved_cards],
            excluded_documents=excluded_docs,
            coverage_matrix=coverage,
            disputed_cells=disputed_cells,
            target_commodities=target_commodities,
            target_countries=target_countries,
            target_sectors=target_sectors,
            low_coverage=low_coverage,
            coverage_warning=coverage_warning,
        )

        search_service = SearchService(approved_cards)
        return case_file, None, self.evidence_service, search_service
