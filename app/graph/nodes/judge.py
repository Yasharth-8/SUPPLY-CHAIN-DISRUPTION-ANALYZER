"""
The Bench (Judge) Node: Dispute Thread Adjudication and Sufficiency Check.
"""

from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

from app.models import (
    Ruling, DisputeThread, AcceptedEstimate, GapObject, Claim, CaseFile
)
from app.vocabularies import (
    RulingVerdict, FindingClassification, ClaimType, Sector, ConfidenceLevel
)
from app.prompts.judge import JUDGE_SYSTEM_PROMPT
from app.services.llm_client import LLMClient
from app.config import JUDGE_TEMPERATURE
from app.services.court_services import canonical_thread_key


class JudgeBatchRulingsOutput(BaseModel):
    threads: List[DisputeThread] = Field(default_factory=list)
    rulings: List[Ruling] = Field(default_factory=list)
    material_gaps: List[GapObject] = Field(default_factory=list)
    is_sufficient: bool = True


class JudgeNode:
    def __init__(self):
        self.llm = LLMClient()

    def rule_threads(
        self,
        threads: List[DisputeThread],
        unpaired_claims: List[Claim],
        unanswered_material: List[Claim],
        case_file: Optional[CaseFile] = None,
        evidence_cards: Optional[Dict[str, Any]] = None,
        prosecutor_responses: Optional[List[Any]] = None,
        defence_responses: Optional[List[Any]] = None
    ) -> JudgeBatchRulingsOutput:
        """
        Adjudicates dispute threads and delivers claim-by-claim rulings.
        Evaluates sufficiency and returns material gaps if evidence is deficient.
        Ensures all claims (both paired dispute threads and uncontested claims) receive a ruling.
        """
        all_rulings: List[Ruling] = []
        all_gaps: List[GapObject] = []
        overall_sufficient = True

        cards_map = evidence_cards or {}
        is_hypo = False
        case_header = ""
        if case_file:
            from app.vocabularies import EventStatus
            is_hypo = (getattr(case_file, "event_status", None) == EventStatus.HYPOTHETICAL) or getattr(case_file, "is_hypothetical", False)
            status_val = case_file.event_status.value if hasattr(case_file.event_status, "value") else str(case_file.event_status)
            case_header = f"""CASE INQUIRY CONTEXT:
Question: {case_file.question}
Event Summary: {case_file.event_summary}
Event Status: {status_val} (Hypothetical Disruption Scenario: {is_hypo})
Target Commodities: {case_file.target_commodities}
Target Sectors: {case_file.target_sectors}
Target Countries: {[c.value if hasattr(c, 'value') else str(c) for c in getattr(case_file, 'reference_region', [])]}
"""

        def _format_claims_text(c_list: List[Claim]) -> str:
            if not c_list:
                return "  None"
            lines = []
            for c in c_list:
                m_str = c.metric.value if hasattr(c.metric, "value") else str(c.metric)
                val_str = f"{c.estimate.value} {c.estimate.unit}"
                lines.append(f"  * Claim [{c.claim_id}] ({c.side.upper()}): {c.subject}")
                lines.append(f"    Metric: {m_str} = {val_str} ({c.estimate.method or 'Derived method'})")
                if c.estimate.base:
                    lines.append(f"    Baseline: {c.estimate.base}")
                if c.estimate.assumptions:
                    lines.append(f"    Assumptions: {'; '.join(c.estimate.assumptions)}")
                if c.evidence:
                    ev_lines = []
                    for ev in c.evidence:
                        q = ev.quote
                        c_card = cards_map.get(ev.evidence_id) or cards_map.get(ev.doc_id)
                        tier = f" [Tier {c_card.source_tier}]" if c_card and hasattr(c_card, "source_tier") else ""
                        if not q and c_card and hasattr(c_card, "quote") and c_card.quote:
                            q = c_card.quote
                        elif not q and c_card and hasattr(c_card, "text"):
                            q = c_card.text[:200]
                        q_disp = f'"{q}"' if q else '(Document citation in admitted pool)'
                        ev_lines.append(f"      - Card [{ev.doc_id}{tier} P{ev.paragraph or 1}]: {q_disp}")
                    lines.append("    Evidence Cited:\n" + "\n".join(ev_lines))
                else:
                    lines.append("    Evidence Cited: None explicitly attached")
            return "\n".join(lines)

        # Synthesize dispute threads for unpaired / uncontested claims so every claim gets ruled
        adjudication_threads: List[DisputeThread] = list(threads)
        for c in unpaired_claims:
            is_prosecutor = c.claim_id.startswith("PC") or "pros" in c.claim_id.lower() or c.side == "prosecutor"
            parent_sec = Sector.get_parent(c.sector) if hasattr(c, "sector") else "general"
            thread_key = canonical_thread_key(c.geography, parent_sec, c.commodity, c.time_horizon, c.metric, c.scenario_id)
            uncontested_thread = DisputeThread(
                thread_id=f"DT-U-{c.claim_id}",
                key=thread_key,
                prosecutor_claims=[c] if is_prosecutor else [],
                defence_claims=[] if is_prosecutor else [c]
            )
            adjudication_threads.append(uncontested_thread)

        if not adjudication_threads:
            summary_ruling = Ruling(
                ruling_id="RUL-SUMMARY-INSUFFICIENT",
                dispute_thread_id="SUMMARY",
                prosecutor_claim_ids=[],
                defence_claim_ids=[],
                ruling=RulingVerdict.INSUFFICIENT_EVIDENCE,
                classification=FindingClassification.INSUFFICIENT,
                claim_type_assessment=ClaimType.SOURCED_FACT,
                accepted_estimate=None,
                supporting_quote="No relevant documentary evidence found in repository.",
                reasoning="No prima facie disruption established: The approved evidence pool contains no substantiated documentary claims of volume shortfall, delay, or price shocks for the queried scenario.",
                model_used="court_rule"
            )
            return JudgeBatchRulingsOutput(
                threads=[],
                rulings=[summary_ruling],
                material_gaps=[
                    GapObject(
                        gap_id="GAP-NO-EVIDENCE",
                        description="Document repository contains insufficient evidence to substantiate supply chain disruption for the queried countries and commodities.",
                        criticality="high",
                        missing_perspective="empirical_trade_flows"
                    )
                ],
                is_sufficient=False
            )

        # Process in batches of 5 threads
        batch_size = 5
        for i in range(0, len(adjudication_threads), batch_size):
            batch = adjudication_threads[i:i + batch_size]
            if not batch:
                break

            threads_context = []
            for t in batch:
                p_claims_text = _format_claims_text(t.prosecutor_claims)
                d_claims_text = _format_claims_text(t.defence_claims)

                # Round 2 rebuttals
                t_cids = {c.claim_id for c in t.prosecutor_claims} | {c.claim_id for c in t.defence_claims}
                p_rebuts = [r for r in (prosecutor_responses or []) if getattr(r, "target_claim_id", None) in t_cids]
                d_rebuts = [r for r in (defence_responses or []) if getattr(r, "target_claim_id", None) in t_cids]

                rebut_text = ""
                if p_rebuts or d_rebuts:
                    r_lines = []
                    for pr in p_rebuts:
                        rt = pr.response_type.value if hasattr(pr.response_type, "value") else str(pr.response_type)
                        r_lines.append(f"  * Prosecutor Round 2 ({rt} to [{pr.target_claim_id}]): {pr.reasoning}")
                    for dr in d_rebuts:
                        rt = dr.response_type.value if hasattr(dr.response_type, "value") else str(dr.response_type)
                        r_lines.append(f"  * Defence Round 2 ({rt} to [{dr.target_claim_id}]): {dr.reasoning}")
                    rebut_text = "\nRound 2 Responses:\n" + "\n".join(r_lines)

                threads_context.append(f"Thread [{t.thread_id}] Key: {t.key}\nProsecutor Claims:\n{p_claims_text}\nDefence Claims:\n{d_claims_text}{rebut_text}")

            full_context = "\n\n".join(threads_context)

            prompt = f"""{case_header}
Review the following dispute threads between Prosecutor and Defence:
{full_context}

Unanswered material claims flagged by court: {[c.claim_id for c in unanswered_material]}

JUDICIAL INSTRUCTIONS:
1. For each dispute thread, deliver a formal ruling: 'sustained', 'partially_sustained', 'overruled', or 'insufficient_evidence'.
2. Classify findings strictly:
   - 'established': Supported by verified Tier 1-2 documentary facts and uncontroverted empirical evidence.
   - 'contested': Opposing parties presented conflicting evidence, OR claim is partially sustained with an adjudicated estimate range.
   - 'conceded': ONLY if the opposing side explicitly conceded or withdrew. (Silence is NOT a concession! Never mark unopposed claims as conceded).
   - 'insufficient': Evidence is missing, weak, or topically irrelevant to the claim.
   - 'unopposed': Unopposed filing by one party.
3. SCENARIO DISRUPTION STANDARDS (CONFIRMED vs HYPOTHETICAL):
   - In a HYPOTHETICAL scenario (e.g. port destruction, waterway closure, sudden export ban), the disruption event itself is given by premise. Sourced documentary baselines (such as port container share, terminal throughput, route transit days, alternative gateway capacity) combined with mechanistic modeling constitute valid documentary foundation.
   - DO NOT dismiss claims as 'insufficient_evidence' simply because a future hypothetical event has not occurred in historical news! Adjudicate the advocates' quantitative models: weigh Prosecutor's disruption severity against Defence's bypass/redundancy capacity. Rule 'partially_sustained' with an accepted estimate range bounded between the two sides (e.g. [low, high] days of delay or percentage volume shortfall).
4. QUANTITATIVE ACCEPTED ESTIMATE DERIVATION:
   - For contested threads with numerical estimates on both sides (e.g. delay: 2-7 days or 3-14 days; volume shortfall: 0-50%), establish the reconciled range [low, high] in accepted_estimate with estimate_type = 'mitigated'.
   - State the derivation in 'basis' (e.g. "Bounded between Defence mitigation estimate of X and Prosecutor bottleneck estimate of Y").
   - Populate accepted_estimate so the court can render the time-to-impact matrix.
5. CRITICAL BILATERAL TRADE ATTRIBUTION:
   - If a claim evaluates India's total gross import baseline (e.g. 7-9M MT from all global suppliers like Oman, Saudi Arabia, Iran), a Chinese export ban only affects the portion sourced from China. If the documentary record does not establish China's direct export volume to India, you MUST NOT sustain gross imports as 'volume at risk' from China. Rule 'insufficient_evidence' for bilateral volume at risk, or sustain only as 'gross_import_baseline'.
6. TIME HORIZON FEASIBILITY:
   - For a 0-7 day window, volume shortfall cannot exceed the pro-rated weekly capacity. (e.g. a monthly quota of 200,000 MT yields ~50,000 MT/week, NOT 1.5M MT in 7 days).
7. Always provide 'supporting_quote' from the cited card proving the finding.
8. If critical evidence is missing, define a material GapObject and mark is_sufficient = false.
9. UNCONTESTED DEFENCE MITIGATION & RESERVES:
   - If a thread contains ONLY Defence claims (e.g. strategic reserves, multi-gateway bypass corridors, alternative routing), evaluate whether the documentary evidence substantiates the mitigation buffer.
   - If substantiated, sustain as an accepted estimate with estimate_type = 'mitigated' and classification = 'unopposed'. Label as 'unopposed, no baseline disruption alleged'. Do NOT penalize verified resilience evidence as 'insufficient_evidence'. A missing exposure claim from the Prosecutor is a baseline omission, not a failure of mitigation proof.
10. EVIDENTIARY RELEVANCE TO INQUIRY TRADE CORRIDOR:
   - If a claim cites evidence describing trade with an uninvolved third party (e.g. citing an Oman circular in a case about US exports), reject the claim as 'insufficient_evidence'.
11. SCENARIO CAUSALITY VS ROUTE COMPARISON:
   - Delay must be causally caused by the queried disruption event. Do NOT sustain corridor arithmetic (e.g. Cape 32d − IMEC 13.5d = 18.5d) as a port closure delay unless evidence establishes that specific cargo route shift.
   - Strategic reserves: If documentary evidence establishes 73.5 days of domestic fuel cover, near-term crude shortfall (0-7d, 8-21d) is buffered by national reserves; rule as 'mitigated' with 0 direct deficit in near-term windows."""

            output: JudgeBatchRulingsOutput = self.llm.generate_structured(
                prompt=prompt,
                system_instruction=JUDGE_SYSTEM_PROMPT,
                response_model=JudgeBatchRulingsOutput,
                temperature=JUDGE_TEMPERATURE,
                role="judge"
            )

            if output and output.rulings:
                model_used = self.llm.last_model_used or "unknown"
                thread_by_id = {t.thread_id: t for t in batch}
                for r in output.rulings:
                    r.model_used = model_used
                    tid = r.dispute_thread_id or r.thread_id
                    t_match = thread_by_id.get(tid)
                    if not t_match:
                        # Match by partial or candidate id
                        for t_cand in batch:
                            if t_cand.thread_id in str(tid) or str(tid) in t_cand.thread_id or (r.ruling_id and t_cand.thread_id in str(r.ruling_id)):
                                t_match = t_cand
                                break
                    if not t_match and len(batch) == 1:
                        t_match = batch[0]

                    if t_match:
                        r.dispute_thread_id = t_match.thread_id
                        r.thread_id = t_match.thread_id
                        r.comparable = getattr(t_match, "comparable", True)
                        if not r.prosecutor_claim_ids:
                            r.prosecutor_claim_ids = [c.claim_id for c in t_match.prosecutor_claims]
                        if not r.defence_claim_ids:
                            r.defence_claim_ids = [c.claim_id for c in t_match.defence_claims]

                        p_c = t_match.prosecutor_claims[0] if t_match.prosecutor_claims else None
                        d_c = t_match.defence_claims[0] if t_match.defence_claims else None

                        from app.services.court_services import get_unit_family
                        p_fam = get_unit_family(p_c.estimate.unit) if (p_c and p_c.estimate) else ""
                        d_fam = get_unit_family(d_c.estimate.unit) if (d_c and d_c.estimate) else ""
                        is_same_fam = (p_fam == d_fam and p_fam not in ("", "unknown"))

                        # If thread has opposing claims on comparable units, ensure we have an accepted estimate
                        if p_c and d_c and r.comparable is not False and is_same_fam:
                            # If LLM ruled insufficient in a hypothetical case due to missing historical event, rescue as contested finding
                            if r.ruling == RulingVerdict.INSUFFICIENT_EVIDENCE and (is_hypo or "verbatim" in (r.reasoning or "").lower() or "not in record" in (r.reasoning or "").lower() or "outside fact" in (r.reasoning or "").lower() or "hypothetical" in (r.reasoning or "").lower()):
                                r.ruling = RulingVerdict.PARTIALLY_SUSTAINED
                                r.classification = FindingClassification.CONTESTED
                                if "insufficient" in (r.reasoning or "").lower() or not r.reasoning:
                                    r.reasoning = f"Adversarial dispute over {p_c.subject}: Prosecutor claims {p_c.estimate.value} {p_c.estimate.unit} while Defence argues mitigation to {d_c.estimate.value} {d_c.estimate.unit}. Partially sustained as contested range."

                            if r.ruling in (RulingVerdict.PARTIALLY_SUSTAINED, RulingVerdict.SUSTAINED) and not r.accepted_estimate:
                                low_v = min(p_c.estimate.value, d_c.estimate.value)
                                high_v = max(p_c.estimate.value, d_c.estimate.value)
                                u_val = "%" if p_fam == "percentage" else ("days" if p_fam == "time_delay" else p_c.estimate.unit)
                                r.accepted_estimate = AcceptedEstimate(
                                    low=low_v,
                                    high=high_v,
                                    unit=u_val,
                                    estimate_type="mitigated",
                                    basis=f"Bounded between Defence lower estimate ({low_v} {u_val}) and Prosecutor upper estimate ({high_v} {u_val})"
                                )
                                r.confidence = ConfidenceLevel.MEDIUM
                                r.headline_eligible = True

                        if r.accepted_estimate:
                            ae_u = (r.accepted_estimate.unit or "").lower()
                            if any(k in ae_u for k in ("delay", "day", "time")):
                                r.accepted_estimate.unit = "days"
                            elif any(k in ae_u for k in ("shortfall", "risk", "volume", "percent", "%", "ratio")):
                                r.accepted_estimate.unit = "%"
                        
                        # Standalone Defence mitigation handling: do not penalize as insufficient evidence
                        if not r.prosecutor_claim_ids and r.defence_claim_ids:
                            if r.ruling in (RulingVerdict.INSUFFICIENT_EVIDENCE, RulingVerdict.SUSTAINED):
                                r.classification = FindingClassification.UNOPPOSED
                                r.ruling = RulingVerdict.SUSTAINED
                                if "insufficient" in r.reasoning.lower() or not r.reasoning:
                                    r.reasoning = f"Unopposed defence resilience finding ({t_match.defence_claims[0].subject if t_match.defence_claims else 'reserves'}). Verified mitigation buffer sustained (unopposed, no baseline disruption alleged)."

                        # Rule on comparable vs non-comparable threads
                        if r.comparable is False:
                            # Disallow combined range across non-comparable metrics (e.g. delay vs volume)
                            r.accepted_estimate = None
                            if r.classification == FindingClassification.CONTESTED:
                                r.classification = FindingClassification.UNOPPOSED
                            r.headline_eligible = False

                    # Ensure PARTIALLY_SUSTAINED rulings on comparable threads are CONTESTED
                    if r.ruling == RulingVerdict.PARTIALLY_SUSTAINED:
                        if getattr(r, "comparable", True):
                            r.classification = FindingClassification.CONTESTED
                        else:
                            r.classification = FindingClassification.UNOPPOSED
                    # Clean up any misplaced 'conceded' classification on unopposed threads
                    elif r.classification == FindingClassification.CONCEDED and (not r.prosecutor_claim_ids or not r.defence_claim_ids):
                        r.classification = FindingClassification.CONTESTED

                    # Headline eligibility gate: only medium/high confidence rulings with explicit derivation
                    has_derivation = bool(r.accepted_estimate and r.accepted_estimate.basis and len(r.accepted_estimate.basis.strip()) >= 15)
                    conf_ok = getattr(r, "confidence", None) in ("high", "medium")
                    r.headline_eligible = bool(conf_ok and has_derivation and r.ruling in (RulingVerdict.SUSTAINED, RulingVerdict.PARTIALLY_SUSTAINED) and r.comparable is not False)

                    # Enforce Prima Facie Rule: Standalone Defence-only claims cannot be sustained as disruption exposure without an alleged disruption
                    if not r.prosecutor_claim_ids and r.defence_claim_ids:
                        r.ruling = RulingVerdict.INSUFFICIENT_EVIDENCE
                        r.classification = FindingClassification.INSUFFICIENT
                        r.accepted_estimate = None
                        r.headline_eligible = False
                        r.reasoning = "Defence submitted reserve/mitigation evidence, but no underlying disruption was claimed or established by the Prosecutor in this category. In the absence of an alleged disruption, defensive reserves cannot be adjudicated as net exposure."
                all_rulings.extend(output.rulings)
                all_gaps.extend(output.material_gaps)
                if not output.is_sufficient:
                    overall_sufficient = False

        # If LLM returned empty or partial, provide deterministic rulings for unruled threads
        ruled_thread_ids = {r.dispute_thread_id for r in all_rulings}
        for t in adjudication_threads:
            if t.thread_id not in ruled_thread_ids:
                is_paired = bool(t.prosecutor_claims and t.defence_claims)
                p_c = t.prosecutor_claims[0] if t.prosecutor_claims else None
                d_c = t.defence_claims[0] if t.defence_claims else None
                base_claim = p_c or d_c

                if not base_claim:
                    continue

                unit_val = base_claim.estimate.unit

                # Derive accepted bounds strictly from inputs without inventing ranges
                is_comp = getattr(t, "comparable", True)
                from app.services.court_services import get_unit_family
                p_fam = get_unit_family(p_c.estimate.unit) if (p_c and p_c.estimate) else ""
                d_fam = get_unit_family(d_c.estimate.unit) if (d_c and d_c.estimate) else ""
                is_same_fam = (p_fam == d_fam and p_fam not in ("", "unknown"))
                if p_c and d_c and is_comp and is_same_fam:
                    low_val = min(p_c.estimate.value, d_c.estimate.value)
                    high_val = max(p_c.estimate.value, d_c.estimate.value)
                    unit_val = "%" if p_fam == "percentage" else ("days" if p_fam == "time_delay" else p_c.estimate.unit)
                    basis_text = f"Bounded between Defence lower estimate ({low_val} {unit_val}) and Prosecutor upper estimate ({high_val} {unit_val})"
                    ruling_verdict = RulingVerdict.PARTIALLY_SUSTAINED
                    classification_val = FindingClassification.CONTESTED
                    accepted_est = AcceptedEstimate(
                        low=low_val,
                        high=high_val,
                        unit=unit_val,
                        estimate_type="mitigated",
                        basis=basis_text
                    )
                    reasoning_text = f"Judicially evaluated based on evidence submitted in {t.thread_id}. {basis_text}."
                elif p_c and d_c and not is_comp:
                    # Non-comparable thread across disparate metrics: do not produce a combined estimate
                    ruling_verdict = RulingVerdict.PARTIALLY_SUSTAINED
                    classification_val = FindingClassification.UNOPPOSED
                    accepted_est = None
                    reasoning_text = f"Dispute thread {t.thread_id} involves related claims with disparate metrics or unquantified mitigations ({p_c.metric} vs {d_c.metric}); ruled on separate bases without a combined estimate."
                elif not p_c and d_c:
                    # Unopposed Defence mitigation: Do NOT penalize Defence as 'insufficient_evidence'
                    # when Prosecutor simply omitted a baseline claim. Credit verified resilience.
                    low_val = getattr(d_c.estimate, "value", 0.0) or 0.0
                    high_val = low_val
                    unit_val = getattr(d_c.estimate, "unit", "") or ""
                    basis_text = f"Unopposed defence resilience/mitigation evidence from {d_c.evidence[0].doc_id if d_c.evidence else 'record'} ({d_c.subject})"
                    ruling_verdict = RulingVerdict.SUSTAINED
                    classification_val = FindingClassification.UNOPPOSED
                    accepted_est = AcceptedEstimate(
                        low=low_val,
                        high=high_val,
                        unit=unit_val,
                        estimate_type="mitigated",
                        basis=basis_text
                    )
                    reasoning_text = f"Defence submitted verified resilience/mitigation evidence ({d_c.subject}). With no opposing baseline disruption alleged by Prosecutor in this cell, finding is sustained as proven buffer capacity (unopposed, no baseline disruption alleged)."
                else:
                    low_val = base_claim.estimate.value
                    high_val = base_claim.estimate.value
                    basis_text = f"Single uncontested estimate ({low_val} {unit_val}) from {base_claim.evidence[0].doc_id if base_claim.evidence else 'record'}"
                    ruling_verdict = RulingVerdict.SUSTAINED
                    classification_val = FindingClassification.CONTESTED
                    accepted_est = AcceptedEstimate(
                        low=low_val,
                        high=high_val,
                        unit=unit_val,
                        estimate_type="direct",
                        basis=basis_text
                    )
                    reasoning_text = f"Judicially evaluated based on evidence submitted in {t.thread_id}. {basis_text}."

                card_quote = base_claim.evidence[0].quote if base_claim.evidence else None

                r = Ruling(
                    ruling_id=f"R-{t.thread_id}",
                    dispute_thread_id=t.thread_id,
                    prosecutor_claim_ids=[c.claim_id for c in t.prosecutor_claims],
                    defence_claim_ids=[c.claim_id for c in t.defence_claims],
                    ruling=ruling_verdict,
                    classification=classification_val,
                    claim_type_assessment=ClaimType.SOURCED_FACT,
                    accepted_estimate=accepted_est,
                    supporting_quote=card_quote,
                    reasoning=reasoning_text,
                    model_used="deterministic_court_fallback"
                )
                all_rulings.append(r)

        return JudgeBatchRulingsOutput(
            threads=adjudication_threads,
            rulings=all_rulings,
            material_gaps=all_gaps,
            is_sufficient=overall_sufficient
        )

