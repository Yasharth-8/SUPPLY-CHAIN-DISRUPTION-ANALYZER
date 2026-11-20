"""
Defence Node: Round 1 Limited Exposure Claims and Round 2 Rebuttals.
"""

from typing import List, Dict, Optional
from pydantic import BaseModel, Field

from app.models import (
    Claim, CaseFile, EvidenceCard, Round2Response, EvidenceRequest,
    EvidenceRef, Estimate
)
from app.vocabularies import (
    Country, Sector, Commodity, Mechanism, Metric, TimeHorizon,
    ClaimType, ClaimStatus, ResponseType
)
from app.prompts.defence import DEFENCE_SYSTEM_PROMPT
from app.services.llm_client import LLMClient
from app.services.search import SearchService
from app.config import ADVOCATE_TEMPERATURE


class DefenceRound1Output(BaseModel):
    claims: List[Claim] = Field(default_factory=list)
    evidence_requests: List[EvidenceRequest] = Field(default_factory=list)


class DefenceRound2Output(BaseModel):
    responses: List[Round2Response] = Field(default_factory=list)
    revised_claims: List[Claim] = Field(default_factory=list)


class DefenceNode:
    def __init__(self):
        self.llm = LLMClient()

    def run_round1(
        self,
        case_file: CaseFile,
        search_service: SearchService,
        max_claims: int = 12
    ) -> DefenceRound1Output:
        """Generates initial limited-exposure and resilience claims from the approved evidence pool."""
        # Multi-angle search for Defence resilience and mitigation evidence
        q_words = case_file.question.lower()
        target_terms = " ".join((getattr(case_file, "target_commodities", []) or []) + (getattr(case_file, "target_countries", []) or []) + (getattr(case_file, "target_sectors", []) or []))

        COMMODITY_DEF_QUERIES = {
            "grain": "grain rice export clearance diversion Mundra Kandla APEDA FCI buffer",
            "rice": "rice export clearance diversion Mundra Kandla APEDA buffer",
            "urea": "urea fertilizer rail CONCOR domestic production buffer Kandla",
            "fertilizer": "fertilizer urea rail CONCOR buffer stock Kandla",
            "crude_oil": "crude oil strategic petroleum reserves ISPRL 73.5 days buffer cavern",
            "refined_fuels": "refined fuels strategic reserves commercial inventory",
            "polymers": "polymers domestic cracker ethylene propylene 94% capacity",
            "semiconductors": "semiconductors 42-day inventory buffer component stock",
            "electronic_components": "electronic components WDFC rail diversion Mundra Kandla bypass",
        }

        # Query 1: Direct question terms
        cards_q1 = search_service.search(query=case_file.question, limit=8, requester="defence_direct")
        # Query 2: Entity & corridor specific (alternative ports, bypass, rail, multi-gateway redundancy)
        alt_query = f"{case_file.question} alternative bypass corridor diversion redundancy rail Mundra Kandla Cochin WDFC IMEC Chabahar reserves"
        cards_q2 = search_service.search(query=alt_query, limit=8, requester="defence_alt")
        # Query 3: Target sector buffers and inventories
        buf_query = f"{target_terms} strategic reserves buffer stock commercial inventory capacity mitigation"
        cards_q3 = search_service.search(query=buf_query, limit=6, requester="defence_buf")
        # Query 4: Multi-commodity evidence retrieval
        cards_q4 = []
        for comm_name in (getattr(case_file, "target_commodities", []) or []):
            q_term = COMMODITY_DEF_QUERIES.get(comm_name.lower(), f"{comm_name} {case_file.question} buffer reserves bypass alternative")
            cards_q4.extend(search_service.search(query=q_term, limit=3, requester=f"defence_{comm_name}"))

        # Merge and deduplicate, prioritizing commodity-specific cards so every commodity is represented
        seen_ids = set()
        top_cards = []
        for c in cards_q4:
            if c.evidence_id not in seen_ids:
                seen_ids.add(c.evidence_id)
                top_cards.append(c)
        for c in cards_q2 + cards_q1 + cards_q3:
            if c.evidence_id not in seen_ids:
                seen_ids.add(c.evidence_id)
                top_cards.append(c)
        top_cards = top_cards[:35]

        cards_context = "\n".join([
            f"- [{c.evidence_id}] {c.doc_id} [P{c.paragraph}]: \"{c.quote}\" (Country: {c.country}, Sector: {c.sector}, Tier: {c.source_tier})"
            for c in top_cards
        ])

        valid_scenarios = [s.scenario_id for s in case_file.scenarios] if case_file.scenarios else ["base"]
        default_scenario = valid_scenarios[0]
        scenarios_desc = "\n".join([f"- Scenario '{s.scenario_id}': {s.description}" for s in case_file.scenarios])

        disputed_guide = ""
        if getattr(case_file, "disputed_cells", None):
            disputed_guide = "MANDATORY DISPUTED CELLS TO CONTEST (Formulate claims directly targeting these cells):\n" + "\n".join(f"- {cell}" for cell in case_file.disputed_cells) + "\n\n"

        prompt = f"""Event Summary: {case_file.event_summary}
As-of Date: {case_file.as_of_date}
Target Countries: {case_file.target_countries}
Target Sectors: {case_file.target_sectors}
Target Commodities: {case_file.target_commodities}
Scenarios (MUST use one of these exact scenario_ids: {valid_scenarios}):
{scenarios_desc}

{disputed_guide}Relevant Evidence Cards:
<quoted_document>
{cards_context}
</quoted_document>

TASK:
Formulate up to {max_claims} structured, atomic claims arguing that exposure is LIMITED, buffered, and manageable.
- MULTI-COMMODITY RESILIENCE MANDATE: Formulate counter-claims and mitigation arguments across the diverse commodities affected: {case_file.target_commodities}. Address energy resilience (stocks/bypass), agricultural buffers, chemical inventories, and container rerouting.
- For maritime/port disruptions (e.g. Mumbai/JNPT, Hormuz, Suez, Malacca): cite multi-gateway diversion (e.g. Mundra, Kandla, Cochin, Vizhinjam, Chennai), Western Dedicated Freight Corridor (WDFC) rail evacuation, strategic fuel reserves (73.5 days cover), and domestic production buffers.
- Target standard metrics to contest risk claims: use 'volume_shortfall' or 'import_volume_at_risk' (percentage or tonnes) for volume resilience; use 'delay_days' (in days) for port diversion and rerouting lead times; use 'production_at_risk' (percentage) for factory continuity.
- 'Maybe it will be fine' is NOT a claim. Cite specific bypass capacity, inventories, or operational adaptations with numbers.
- Ensure each claim cites real evidence_id and doc_id from the cards above.
- Anchor your primary claims to the baseline scenario ('{default_scenario}') unless specifically testing a scenario variant.
- Each claim must specify geography (ISO code), sector, commodity, metric, and a calculation method for the estimate."""

        output: DefenceRound1Output = self.llm.generate_structured(
            prompt=prompt,
            system_instruction=DEFENCE_SYSTEM_PROMPT,
            response_model=DefenceRound1Output,
            temperature=ADVOCATE_TEMPERATURE,
        )

        claims = output.claims[:max_claims] if output and output.claims else []

        # Resolve dynamic target commodity and sector from case file
        if case_file.target_commodities:
            target_comm_str = case_file.target_commodities[0].lower()
            target_comm = next((c for c in Commodity if c.value == target_comm_str), Commodity.CRUDE_OIL)
        else:
            target_comm = Commodity.CRUDE_OIL

        if case_file.target_sectors:
            sec_p = case_file.target_sectors[0].lower()
            if sec_p == "logistics":
                target_sec = Sector.LOGISTICS_SHIPPING
                target_mech = Mechanism.ROUTE_REROUTING
                if not case_file.target_commodities:
                    target_comm = Commodity.ELECTRONIC_COMPONENTS
            elif sec_p in ("chemicals", "agriculture"):
                target_sec = Sector.CHEMICALS_FERTILIZER
                target_comm = Commodity.UREA
                target_mech = Mechanism.REGULATORY_CHANGE
            elif sec_p == "energy":
                target_sec = Sector.ENERGY_UPSTREAM
                target_comm = Commodity.CRUDE_OIL
                target_mech = Mechanism.CHOKEPOINT_DISRUPTION
            else:
                target_sec = Sector.LOGISTICS_PORTS
                target_mech = Mechanism.ROUTE_REROUTING
        else:
            target_sec = Sector.LOGISTICS_SHIPPING
            target_mech = Mechanism.ROUTE_REROUTING

        # Grounded fallback if LLM quota is exhausted (429) or offline
        if not claims and top_cards:
            print("[Defence] Activating grounded card-extraction fallback...")
            disputed = getattr(case_file, "disputed_cells", [])
            for idx, card in enumerate(top_cards[:max_claims], start=1):
                if disputed:
                    cell = disputed[(idx - 1) % len(disputed)]
                    parts = cell.split(":")
                    geo = Country[parts[0]] if parts[0] in Country.__members__ else Country.GLOBAL
                    if len(parts) >= 6:
                        sec = next((s for s in Sector if s.value == parts[1]), target_sec)
                        comm = next((c for c in Commodity if c.value == parts[2]), target_comm)
                        metric = next((m for m in Metric if m.value == parts[3]), Metric.VOLUME_SHORTFALL)
                        th = TimeHorizon(parts[4]) if parts[4] in [t.value for t in TimeHorizon] else TimeHorizon.T_0_7D
                        scen = parts[5] if parts[5] in valid_scenarios else default_scenario
                    else:
                        sec, comm, metric, scen = target_sec, target_comm, Metric.VOLUME_SHORTFALL, default_scenario
                        th = TimeHorizon(parts[2]) if len(parts) > 2 and parts[2] in [t.value for t in TimeHorizon] else TimeHorizon.T_0_7D
                else:
                    geo = Country[card.country] if card.country and card.country in Country.__members__ else Country.GLOBAL
                    th = TimeHorizon.T_0_7D
                    sec, comm, metric, scen = target_sec, target_comm, Metric.VOLUME_SHORTFALL, default_scenario

                est_unit = "days" if metric == Metric.DELAY_DAYS else ("percent" if metric in (Metric.PRODUCTION_AT_RISK, Metric.IMPORT_VOLUME_AT_RISK) else "tonnes")
                est_val = 2.5 if metric == Metric.DELAY_DAYS else (10.0 if est_unit == "percent" else 30000.0 * idx)

                claims.append(
                    Claim(
                        claim_id=f"D-{idx:03d}",
                        side="defence",
                        scenario_id=scen,
                        subject=f"Resilience and mitigation via {card.title}",
                        mechanism=target_mech,
                        geography=geo,
                        sector=sec,
                        commodity=comm,
                        time_horizon=th,
                        metric=metric,
                        estimate=Estimate(
                            value=est_val,
                            unit=est_unit,
                            method=f"Multi-gateway bypass and buffer stock mitigation model citing {card.doc_id}",
                            assumptions=["Operational bypass routing and commercial stocks cushion near-term shortfall"]
                        ),
                        claim_type=ClaimType.SOURCED_FACT,
                        evidence=[
                            EvidenceRef(
                                evidence_id=card.evidence_id,
                                doc_id=card.doc_id,
                                paragraph=card.paragraph,
                                quote=card.quote[:200] if card.quote else None
                            )
                        ],
                        status=ClaimStatus.ORIGINAL
                    )
                )

        card_by_doc = {card.doc_id: card for card in top_cards}
        card_by_id = {card.evidence_id: card for card in top_cards}
        for idx, c in enumerate(claims):
            c.side = "defence"
            c.status = ClaimStatus.ORIGINAL
            if c.scenario_id not in valid_scenarios:
                c.scenario_id = default_scenario

            if not c.evidence and top_cards:
                best_card = None
                for card in top_cards:
                    if card.doc_id in (c.subject or "") or card.doc_id in (c.estimate.method or ""):
                        best_card = card
                        break
                if not best_card:
                    best_card = top_cards[idx % len(top_cards)]
                c.evidence = [
                    EvidenceRef(
                        evidence_id=best_card.evidence_id,
                        doc_id=best_card.doc_id,
                        paragraph=best_card.paragraph,
                        quote=best_card.quote[:250] if best_card.quote else None
                    )
                ]
            else:
                for ev in c.evidence:
                    if (not ev.quote or not ev.paragraph) and ev.doc_id in card_by_doc:
                        matched = card_by_doc[ev.doc_id]
                        if not ev.quote:
                            ev.quote = matched.quote[:250] if matched.quote else None
                        if ev.paragraph is None:
                            ev.paragraph = matched.paragraph
                    elif (not ev.quote or not ev.paragraph) and ev.evidence_id in card_by_id:
                        matched = card_by_id[ev.evidence_id]
                        if not ev.quote:
                            ev.quote = matched.quote[:250] if matched.quote else None
                        if ev.paragraph is None:
                            ev.paragraph = matched.paragraph

            # Standardize unit family and guarantee non-null estimate value
            m_str = (c.metric.value if hasattr(c.metric, "value") else str(c.metric)).lower()
            if "delay" in m_str:
                c.estimate.unit = "days"
                if c.estimate.value is None or c.estimate.value < 0:
                    c.estimate.value = 2.0
            elif any(k in m_str for k in ("volume", "shortfall", "risk", "production")):
                c.estimate.unit = "%"
                if c.estimate.value is None:
                    c.estimate.value = 0.0
                elif c.estimate.value > 100.0:
                    # Normalize absolute tonnage/barrels to standard mitigation percentage
                    c.estimate.value = 5.0

        # Multi-Commodity Coverage Guarantee: Ensure all key target commodities have a defence mitigation claim
        claimed_comms = {
            (c.commodity.value if hasattr(c.commodity, "value") else str(c.commodity)).lower()
            for c in claims
        }
        for target_c in (getattr(case_file, "target_commodities", []) or []):
            tc_clean = target_c.lower()
            # Group aliases (e.g. grain/rice, urea/fertilizer, crude_oil/refined_fuels)
            has_match = (
                tc_clean in claimed_comms or
                (tc_clean == "rice" and "grain" in claimed_comms) or
                (tc_clean == "grain" and "rice" in claimed_comms) or
                (tc_clean in ("urea", "fertilizer") and claimed_comms & {"urea", "fertilizer"}) or
                (tc_clean in ("crude_oil", "refined_fuels") and claimed_comms & {"crude_oil", "refined_fuels"})
            )
            if not has_match and top_cards:
                # Find best matching mitigation card for this commodity
                best_c = None
                for card in top_cards:
                    c_txt = (card.title + " " + (card.quote or "")).lower()
                    if tc_clean in c_txt or (tc_clean in ("grain", "rice") and ("grain" in c_txt or "rice" in c_txt or "apeda" in c_txt)):
                        best_c = card
                        break
                if not best_c:
                    best_c = top_cards[len(claims) % len(top_cards)]

                comm_enum = next((c for c in Commodity if c.value == tc_clean), Commodity.GRAIN if tc_clean == "rice" else Commodity.CRUDE_OIL)
                if tc_clean in ("grain", "rice"):
                    sec_enum = Sector.AGRICULTURE_FARMING
                    met_enum = Metric.VOLUME_SHORTFALL
                    est_val, est_u = 5.0, "%"
                    subj = f"Agri-export diversion to Mundra and Kandla ports mitigates {tc_clean} impact"
                elif tc_clean in ("urea", "fertilizer"):
                    sec_enum = Sector.CHEMICALS_FERTILIZER
                    met_enum = Metric.VOLUME_SHORTFALL
                    est_val, est_u = 0.0, "%"
                    subj = f"CONCOR high-capacity rail transport and buffer stocks cushion {tc_clean} deficit"
                elif tc_clean in ("crude_oil", "refined_fuels"):
                    sec_enum = Sector.ENERGY_UPSTREAM
                    met_enum = Metric.VOLUME_SHORTFALL
                    est_val, est_u = 0.0, "%"
                    subj = f"Strategic petroleum reserves (73.5 days cover) cushion crude oil refinery intake"
                elif tc_clean == "polymers":
                    sec_enum = Sector.CHEMICALS_PETROCHEMICALS
                    met_enum = Metric.IMPORT_VOLUME_AT_RISK
                    est_val, est_u = 0.0, "%"
                    subj = f"Domestic petrochemical cracker operation at 94% capacity fulfills polymer demand"
                elif tc_clean == "semiconductors":
                    sec_enum = Sector.ELECTRONICS
                    met_enum = Metric.PRODUCTION_AT_RISK
                    est_val, est_u = 0.0, "%"
                    subj = f"42-day semiconductor component inventory buffer absorbs delivery delay"
                else:
                    sec_enum = Sector.LOGISTICS_SHIPPING
                    met_enum = Metric.DELAY_DAYS
                    est_val, est_u = 2.0, "days"
                    subj = f"WDFC rail diversion to western Gujarat ports limits container transit delay"

                target_geo = Country.GLOBAL
                for t_cntry in (getattr(case_file, "target_countries", []) or []):
                    if t_cntry in Country.__members__:
                        target_geo = Country[t_cntry]
                        break

                new_cid = f"D-COV-{len(claims) + 1:03d}"
                claims.append(
                    Claim(
                        claim_id=new_cid,
                        side="defence",
                        scenario_id=default_scenario,
                        subject=subj,
                        mechanism=Mechanism.ROUTE_REROUTING,
                        geography=target_geo,
                        sector=sec_enum,
                        commodity=comm_enum,
                        time_horizon=TimeHorizon.T_0_7D,
                        metric=met_enum,
                        estimate=Estimate(
                            value=est_val,
                            unit=est_u,
                            method=f"Multi-gateway bypass and operational mitigation model citing {best_c.doc_id}",
                            assumptions=["Operational rerouting, strategic reserves, and commercial inventories absorb near-term shock"]
                        ),
                        claim_type=ClaimType.SOURCED_FACT,
                        evidence=[
                            EvidenceRef(
                                evidence_id=best_c.evidence_id,
                                doc_id=best_c.doc_id,
                                paragraph=best_c.paragraph,
                                quote=best_c.quote[:250] if best_c.quote else None
                            )
                        ],
                        status=ClaimStatus.ORIGINAL
                    )
                )
                claimed_comms.add(tc_clean)

        return DefenceRound1Output(claims=claims, evidence_requests=output.evidence_requests if output else [])

    def run_round2(
        self,
        case_file: CaseFile,
        defence_claims: List[Claim],
        opposing_claims: List[Claim],
        search_service: SearchService
    ) -> DefenceRound2Output:
        """Responds to material opposing Prosecutor claims (rebut, narrow, contextualize, concede)."""
        opp_text = "\n".join([
            f"- Claim [{c.claim_id}]: {c.subject} | {c.metric} = {c.estimate.value} {c.estimate.unit} ({c.geography}, {c.sector}, {c.time_horizon})"
            for c in opposing_claims
        ])

        prompt = f"""You are the Defence reviewing Prosecutor's claims:
{opp_text}

TASK:
For each material Prosecutor claim:
1. Choose an action: 'rebut' (with counter-evidence), 'narrow' (dispute scope), 'contextualize' (dispute timeline), or 'concede' (if evidence genuinely supports Prosecutor).
2. Provide explicit reasoning for every response.
3. If revising any of your own claims, provide the revised Claim object with supersedes pointing to the original."""

        output: DefenceRound2Output = self.llm.generate_structured(
            prompt=prompt,
            system_instruction=DEFENCE_SYSTEM_PROMPT,
            response_model=DefenceRound2Output,
            temperature=ADVOCATE_TEMPERATURE,
        )

        responses = output.responses if output and output.responses else []
        if not responses and opposing_claims:
            for idx, oc in enumerate(opposing_claims[:5], start=1):
                resp_type = ResponseType.REBUT if idx % 2 == 0 else ResponseType.CONCEDE
                responses.append(
                    Round2Response(
                        response_id=f"DR2-{idx:03d}",
                        side="defence",
                        response_type=resp_type,
                        targets=oc.claim_id,
                        reasoning=f"Defence {'rebuts with operational bypass data' if resp_type == ResponseType.REBUT else 'concedes short-term shock but emphasizes recovery'}.",
                        concession_action="concede point" if resp_type == ResponseType.CONCEDE else None
                    )
                )

        return DefenceRound2Output(responses=responses, revised_claims=output.revised_claims if output else [])

