"""
Court Services: Deterministic Verification, Citation Validation, Pairing, and Silence Checking.
Runs between rounds to enforce strict court standards without LLM bias.
"""

from typing import List, Dict, Tuple, Optional, Set, Any
from rapidfuzz import fuzz

from app.models import (
    Claim, DisputeThread, EvidenceCard, Ruling, AcceptedEstimate,
    GapObject, Round2Response
)
from app.vocabularies import Sector, Commodity, Metric, ResponseType, Country, TimeHorizon
from app.constants import (
    CITATION_FUZZY_MATCH_THRESHOLD, MATERIALITY_THRESHOLDS,
    are_commodities_related, are_sectors_related, bpd_to_tonnes_daily
)

ADJACENT_BUCKETS: Dict[TimeHorizon, Set[TimeHorizon]] = {
    TimeHorizon.T_0_7D: {TimeHorizon.T_8_21D},
    TimeHorizon.T_8_21D: {TimeHorizon.T_0_7D, TimeHorizon.T_22_60D},
    TimeHorizon.T_22_60D: {TimeHorizon.T_8_21D, TimeHorizon.T_61_90D},
    TimeHorizon.T_61_90D: {TimeHorizon.T_22_60D, TimeHorizon.T_90_PLUS},
    TimeHorizon.T_90_PLUS: {TimeHorizon.T_61_90D},
}


class CitationValidationResult:
    def __init__(self, is_valid: bool, reason: str = "", card: Optional[EvidenceCard] = None):
        self.is_valid = is_valid
        self.reason = reason
        self.card = card


def get_unit_family(unit: Optional[str]) -> str:
    """Categorizes measurement units into distinct dimensional families to prevent non-comparable pairing."""
    if not unit:
        return "unknown"
    u = unit.lower().strip()
    if any(k in u for k in ["percent", "%", "ratio", "share"]):
        return "percentage"
    if any(k in u for k in ["tonne", "ton", "mt", "bpd", "barrel", "kg", "million"]):
        return "physical_volume"
    if any(k in u for k in ["day", "hour", "week", "month"]):
        return "time_delay"
    if any(k in u for k in ["usd", "$", "dollar", "eur", "price", "premium", "index"]):
        return "currency_or_price"
    return "other"


def canonical_thread_key(geo: Any, sector: Any, comm: Any, th: Any, metric: Any, scen: Any) -> str:
    """Produces a deterministic, lowercase, clean key for dispute threads and matrix cells."""
    c_geo = (geo.value if hasattr(geo, "value") else str(geo)).replace("Country.", "").upper()
    c_sec = Sector.get_parent(sector).lower()
    c_comm = (comm.value if hasattr(comm, "value") else str(comm)).replace("Commodity.", "").lower()
    c_th = (th.value if hasattr(th, "value") else str(th)).replace("TimeHorizon.", "").replace("TIMEHORIZON.", "").replace("T_", "").replace("_", "-").lower()
    c_metric = (metric.value if hasattr(metric, "value") else str(metric)).replace("Metric.", "").lower()
    c_scen = str(scen).lower()
    return f"{c_geo}:{c_sec}:{c_comm}:{c_th}:{c_metric}:{c_scen}"


class CourtServices:
    def __init__(self, approved_cards: Dict[str, EvidenceCard], raw_docs: Optional[Dict[str, Any]] = None):
        self.approved_cards = approved_cards  # card_id -> EvidenceCard
        self.raw_docs = raw_docs or {}        # doc_id -> ParsedDocument
        self.approved_doc_ids: Set[str] = {c.doc_id for c in approved_cards.values()}

    def validate_citation(self, claim: Claim) -> Tuple[bool, List[str]]:
        """
        Validates all evidence references in a claim:
        1. Pool membership check (doc_id must be in approved pool).
        2. Paragraph / TableRef existence check.
        3. Fuzzy quote verification (quote text must exist in cited paragraph).
        """
        if not claim.evidence:
            return False, ["No evidence cited for claim"]

        errors = []
        for ev in claim.evidence:
            # Check 1: Pool membership
            if ev.doc_id not in self.approved_doc_ids:
                errors.append(f"Document {ev.doc_id} is not in the Gatekeeper-approved pool")
                continue

            # Check 2: Table reference vs Paragraph
            if ev.table_ref:
                raw_doc = self.raw_docs.get(ev.doc_id)
                if not raw_doc or not raw_doc.table_rows:
                    errors.append(f"Cited table {ev.doc_id} contains no tabular data")
                elif ev.table_ref.row > len(raw_doc.table_rows):
                    errors.append(f"Row {ev.table_ref.row} exceeds table length {len(raw_doc.table_rows)}")
            else:
                # Paragraph check
                raw_doc = self.raw_docs.get(ev.doc_id)
                if not raw_doc:
                    # Check if card exists in approved cards
                    card = self.approved_cards.get(ev.evidence_id)
                    if not card:
                        errors.append(f"Evidence card {ev.evidence_id} not found")
                    continue

                if ev.paragraph is not None and ev.paragraph not in raw_doc.paragraphs:
                    errors.append(f"Paragraph [P{ev.paragraph}] not found in document {ev.doc_id}")
                    continue

                # Check 3: Fuzzy quote verification
                if ev.quote and ev.paragraph is not None:
                    actual_text = raw_doc.paragraphs.get(ev.paragraph, "")
                    clean_quote = ev.quote.strip()
                    if clean_quote.endswith("..."):
                        clean_quote = clean_quote[:-3].strip()

                    # Token set ratio handles substrings and minor punctuation differences
                    ratio = fuzz.token_set_ratio(clean_quote.lower(), actual_text.lower()) / 100.0
                    if ratio < CITATION_FUZZY_MATCH_THRESHOLD:
                        errors.append(
                            f"Quote verification failed (overlap {ratio:.2f} < {CITATION_FUZZY_MATCH_THRESHOLD:.2f}) "
                            f"for {ev.doc_id} [P{ev.paragraph}]"
                        )

        return (len(errors) == 0), errors

    def is_claim_material(self, claim: Claim) -> bool:
        """Determines if a claim meets the materiality threshold."""
        metric = claim.metric
        val = getattr(claim.estimate, "value", None)
        if val is None:
            return False
        unit = (getattr(claim.estimate, "unit", "") or "").lower()

        if metric in (Metric.VOLUME_SHORTFALL, Metric.IMPORT_VOLUME_AT_RISK, Metric.PERMANENT_CAPACITY_LOSS):
            thresholds = MATERIALITY_THRESHOLDS[metric]
            if "bpd" in unit:
                return val > thresholds["bpd"]
            return val > thresholds["tonnes"]

        elif metric == Metric.PRODUCTION_AT_RISK:
            return val > MATERIALITY_THRESHOLDS[Metric.PRODUCTION_AT_RISK]

        elif metric == Metric.DELAY_DAYS:
            return val > MATERIALITY_THRESHOLDS[Metric.DELAY_DAYS]

        elif metric == Metric.PRICE_INCREASE:
            return val > MATERIALITY_THRESHOLDS[Metric.PRICE_INCREASE]

        return True

    def filter_off_scope_claims(
        self,
        claims: List[Claim],
        case_file: Optional[Any]
    ) -> Tuple[List[Claim], List[Claim]]:
        """Filters out claims that completely diverge from the case file's target sectors/commodities.
        
        Defence claims are given wider latitude because mitigation arguments
        (alternative ports, strategic reserves, bypass corridors) legitimately
        reference sectors and commodities outside the primary attack vector.
        """
        if not case_file or not getattr(case_file, "target_sectors", None):
            return claims, []

        valid_claims: List[Claim] = []
        rejected_claims: List[Claim] = []
        target_secs = set(case_file.target_sectors)
        target_comms = set(getattr(case_file, "target_commodities", []) or [])

        # Build an expanded scope for Defence that includes related sectors/commodities
        from app.constants import RELATED_SECTORS, are_commodities_related
        expanded_secs = set(target_secs)
        for s in target_secs:
            expanded_secs.update(RELATED_SECTORS.get(s, set()))
        # Also allow logistics (alternative routes) and general
        expanded_secs.add("logistics")
        expanded_secs.add("general")

        for c in claims:
            c_parent_sec = Sector.get_parent(c.sector)
            c_comm = c.commodity.value if hasattr(c.commodity, "value") else str(c.commodity)
            is_defence = (c.side == "defence")

            # Defence gets expanded scope: sector match includes related sectors,
            # and any commodity related to target commodities is accepted
            if is_defence:
                sector_matches = (c_parent_sec in expanded_secs) or (c_parent_sec == "general")
                comm_matches = True  # Defence mitigation can reference any commodity in scope
                if target_comms:
                    # Accept if the commodity matches or is related to any target commodity
                    comm_matches = (c_comm in target_comms) or any(
                        are_commodities_related(c_comm, tc) for tc in target_comms
                    ) or (c_parent_sec in expanded_secs)  # sector-match alone is enough for defence
            else:
                # Prosecutor: strict scope enforcement
                sector_matches = (c_parent_sec in target_secs) or (c_parent_sec == "general")
                comm_matches = (c_comm in target_comms) if target_comms else True

            if not sector_matches and not comm_matches:
                c.status_reason = f"Rejected by Court: Claim topic '{c_comm}/{c_parent_sec}' is off-scope for case inquiry focused on {list(target_secs)}"
                rejected_claims.append(c)
                print(f"[Court Scope Enforcement] Rejected off-scope claim [{c.claim_id}] ({c_comm} in {c_parent_sec}) [side={c.side}]")
                continue

            valid_claims.append(c)

        if rejected_claims:
            print(f"[Court Scope Enforcement] Passed {len(valid_claims)} claims, rejected {len(rejected_claims)} off-scope claims.")

        return valid_claims, rejected_claims

    def pair_claims(
        self,
        prosecutor_claims: List[Claim],
        defence_claims: List[Claim]
    ) -> Tuple[List[DisputeThread], List[Claim]]:
        """
        Pairs opposing claims by {geography, parent_sector, commodity, time_horizon, metric, scenario_id}.
        Strictly distinguishes:
        - Exact/Comparable Pairs (comparable=True): Same or compatible metric, same unit family,
          numeric estimates on both sides. Evaluated as true adversarial disputes with an accepted range.
        - Related/Loose Pairs (comparable=False): Cross-metric context (e.g. delay vs volume) or
          qualitative/unquantified claims. Ruled on separately without a combined numeric range.
        Returns (list of DisputeThreads, list of unpaired claims).
        """
        threads_dict: Dict[str, DisputeThread] = {}
        paired_claim_ids: Set[str] = set()

        for p_claim in prosecutor_claims:
            p_parent_sector = Sector.get_parent(p_claim.sector)
            p_unit_fam = get_unit_family(p_claim.estimate.unit if p_claim.estimate else "")
            p_has_num = bool(p_claim.estimate and p_claim.estimate.value is not None)

            for d_claim in defence_claims:
                if d_claim.claim_id in paired_claim_ids:
                    continue
                d_parent_sector = Sector.get_parent(d_claim.sector)
                d_unit_fam = get_unit_family(d_claim.estimate.unit if d_claim.estimate else "")
                d_has_num = bool(d_claim.estimate and d_claim.estimate.value is not None)

                # Match conditions:
                geo_match = (p_claim.geography == d_claim.geography) or (p_claim.geography == Country.GLOBAL) or (d_claim.geography == Country.GLOBAL)
                sector_match = (p_parent_sector == d_parent_sector)
                comm_match = are_commodities_related(
                    p_claim.commodity.value if hasattr(p_claim.commodity, "value") else str(p_claim.commodity),
                    d_claim.commodity.value if hasattr(d_claim.commodity, "value") else str(d_claim.commodity)
                )
                time_match = (p_claim.time_horizon == d_claim.time_horizon)
                scen_match = (p_claim.scenario_id == d_claim.scenario_id)

                # Unit family MUST match. A percentage claim cannot pair with physical volume!
                unit_fam_match = (p_unit_fam == d_unit_fam and p_unit_fam != "unknown")

                # Strictly comparable metric check
                physical_vol_metrics = {Metric.IMPORT_VOLUME_AT_RISK, Metric.VOLUME_SHORTFALL, Metric.PERMANENT_CAPACITY_LOSS}
                is_direct_metric_match = False
                if p_claim.metric == d_claim.metric and unit_fam_match and p_has_num and d_has_num:
                    is_direct_metric_match = True
                elif (p_claim.metric in physical_vol_metrics and d_claim.metric in physical_vol_metrics) and unit_fam_match and p_has_num and d_has_num:
                    is_direct_metric_match = True
                elif (p_claim.metric == Metric.PRODUCTION_AT_RISK and d_claim.metric == Metric.PRODUCTION_AT_RISK) and unit_fam_match and p_has_num and d_has_num:
                    is_direct_metric_match = True

                if geo_match and sector_match and comm_match and time_match and scen_match and is_direct_metric_match:
                    key = canonical_thread_key(p_claim.geography, p_parent_sector, p_claim.commodity, p_claim.time_horizon, p_claim.metric, p_claim.scenario_id)
                    if key not in threads_dict:
                        thread_id = f"DT-{len(threads_dict) + 1:03d}"
                        threads_dict[key] = DisputeThread(
                            thread_id=thread_id,
                            key=key,
                            is_loose_match=False,
                            match_level="exact",
                            comparable=True
                        )

                    threads_dict[key].prosecutor_claims.append(p_claim)
                    threads_dict[key].defence_claims.append(d_claim)
                    paired_claim_ids.add(p_claim.claim_id)
                    paired_claim_ids.add(d_claim.claim_id)
                    break

        # Level 2 Pass: Relaxed pairing for remaining unpaired claims
        unpaired_p = [c for c in prosecutor_claims if c.claim_id not in paired_claim_ids]
        unpaired_d = [c for c in defence_claims if c.claim_id not in paired_claim_ids]

        for p_claim in unpaired_p:
            if p_claim.claim_id in paired_claim_ids:
                continue
            p_parent_sector = Sector.get_parent(p_claim.sector)
            p_unit_fam = get_unit_family(p_claim.estimate.unit if p_claim.estimate else "")
            p_has_num = bool(p_claim.estimate and p_claim.estimate.value is not None)

            for d_claim in unpaired_d:
                if d_claim.claim_id in paired_claim_ids:
                    continue
                d_parent_sector = Sector.get_parent(d_claim.sector)
                d_unit_fam = get_unit_family(d_claim.estimate.unit if d_claim.estimate else "")
                d_has_num = bool(d_claim.estimate and d_claim.estimate.value is not None)

                geo_match = (p_claim.geography == d_claim.geography) or (p_claim.geography == Country.GLOBAL) or (d_claim.geography == Country.GLOBAL)
                sector_match = (p_parent_sector == d_parent_sector) or are_sectors_related(p_parent_sector, d_parent_sector)
                
                # Commodity match is strictly required — an unrelated commodity must NOT pair through the sector link
                comm_match = are_commodities_related(
                    p_claim.commodity.value if hasattr(p_claim.commodity, "value") else str(p_claim.commodity),
                    d_claim.commodity.value if hasattr(d_claim.commodity, "value") else str(d_claim.commodity)
                )

                if not (geo_match and sector_match and comm_match):
                    continue

                unit_fam_match = (p_unit_fam == d_unit_fam and p_unit_fam != "unknown")
                if not unit_fam_match and (p_has_num and d_has_num):
                    # Disparate dimensional unit families (e.g. days vs tonnes, percent vs tonnes) must NEVER pair
                    continue

                physical_vol_metrics_l2 = {Metric.IMPORT_VOLUME_AT_RISK, Metric.VOLUME_SHORTFALL, Metric.PERMANENT_CAPACITY_LOSS}
                
                # Check if metrics are comparable
                is_comparable_metric = (
                    (p_claim.metric == d_claim.metric and unit_fam_match and p_has_num and d_has_num) or
                    (p_claim.metric in physical_vol_metrics_l2 and d_claim.metric in physical_vol_metrics_l2 and unit_fam_match and p_has_num and d_has_num)
                )

                # Relaxed condition: adjacent time bucket or cross-scenario
                time_match_relaxed = (p_claim.time_horizon == d_claim.time_horizon) or (
                    d_claim.time_horizon in ADJACENT_BUCKETS.get(p_claim.time_horizon, set())
                )

                if is_comparable_metric and time_match_relaxed:
                    # Comparable relaxed dispute (e.g. adjacent time bucket or cross-scenario on same metric)
                    key = canonical_thread_key(p_claim.geography, p_parent_sector, p_claim.commodity, p_claim.time_horizon, p_claim.metric, p_claim.scenario_id)
                    if key not in threads_dict:
                        thread_id = f"DT-{len(threads_dict) + 1:03d}"
                        match_lvl = "scenario_cross" if p_claim.scenario_id != d_claim.scenario_id else "relaxed"
                        threads_dict[key] = DisputeThread(
                            thread_id=thread_id,
                            key=key,
                            is_loose_match=True,
                            match_level=match_lvl,
                            comparable=True
                        )
                    threads_dict[key].prosecutor_claims.append(p_claim)
                    threads_dict[key].defence_claims.append(d_claim)
                    paired_claim_ids.add(p_claim.claim_id)
                    paired_claim_ids.add(d_claim.claim_id)
                    break
                elif time_match_relaxed and (not p_has_num or not d_has_num or p_claim.metric != d_claim.metric):
                    # Related context, NOT directly comparable (e.g. unquantified claim or different metric in same unit family)
                    key = canonical_thread_key(p_claim.geography, p_parent_sector, p_claim.commodity, p_claim.time_horizon, p_claim.metric, p_claim.scenario_id)
                    if key not in threads_dict:
                        thread_id = f"DT-{len(threads_dict) + 1:03d}"
                        threads_dict[key] = DisputeThread(
                            thread_id=thread_id,
                            key=key,
                            is_loose_match=True,
                            match_level="related",
                            comparable=False
                        )
                    threads_dict[key].prosecutor_claims.append(p_claim)
                    threads_dict[key].defence_claims.append(d_claim)
                    paired_claim_ids.add(p_claim.claim_id)
                    paired_claim_ids.add(d_claim.claim_id)
                    break

        # Collect and diagnose unpaired claims
        unpaired = []
        for c in prosecutor_claims + defence_claims:
            if c.claim_id not in paired_claim_ids:
                unpaired.append(c)
                claim_key = canonical_thread_key(c.geography, c.sector, c.commodity, c.time_horizon, c.metric, c.scenario_id)
                print(f"[Court Pairing Diagnosis] Unpaired Claim [{c.claim_id}] ({c.side}) -> Key: {claim_key}")

        if unpaired and not threads_dict:
            print(f"[Court Pairing Diagnosis] Note: 0 paired threads formed across {len(prosecutor_claims)} P-claims and {len(defence_claims)} D-claims. The Bench will adjudicate all {len(unpaired)} unpaired claims as uncontested threads.")

        return list(threads_dict.values()), unpaired

    def check_silence(
        self,
        opposing_claims: List[Claim],
        responses: List[Round2Response]
    ) -> List[Claim]:
        """
        Pass 2 check: Detects unanswered material claims.
        Returns list of material claims that had zero responses.
        """
        responded_target_ids: Set[str] = {r.targets for r in responses}
        unanswered_material = []

        for c in opposing_claims:
            if self.is_claim_material(c) and c.claim_id not in responded_target_ids:
                unanswered_material.append(c)

        return unanswered_material

    def validate_accepted_estimate(
        self,
        ruling: Ruling,
        prosecutor_claims: List[Claim],
        defence_claims: List[Claim]
    ) -> Tuple[bool, Optional[str]]:
        """
        Deterministic check: accepted_estimate must fall within the range bounded by
        both sides' claims, unless explicit calculation basis is stated.
        Rejects arbitrary invented ranges and flags extreme percentage values.
        """
        if not ruling.accepted_estimate:
            return True, None

        acc = ruling.accepted_estimate
        all_vals = [c.estimate.value for c in prosecutor_claims + defence_claims if c.estimate.unit.lower() == acc.unit.lower()]
        if not all_vals:
            return True, None

        min_val = min(all_vals)
        max_val = max(all_vals)

        # Flag extreme percentages that may misattribute hull insurance jumps to commodity price hikes
        if acc.unit.lower() in ("percent", "%", "percentage") and acc.high > 200.0:
            if not acc.basis or "insurance" in acc.basis.lower() and "price" in ruling.reasoning.lower():
                return False, f"Extreme percentage [{acc.high}%] flagged: insurance hull rate spike misattributed as general commodity price increase"

        # Range bounds enforcement: accepted estimate must be strictly bounded by claim inputs
        if acc.low < min_val * 0.85 or acc.high > max_val * 1.15:
            if not acc.basis or len(acc.basis.strip()) < 10:
                return False, f"Accepted estimate [{acc.low}, {acc.high}] exceeds input bounds [{min_val}, {max_val}] without stated mathematical derivation"

        return True, None

    def filter_already_searched_gaps(
        self,
        gaps: List[GapObject],
        query_history: Set[str]
    ) -> List[GapObject]:
        """Filters out Judge gaps where scope was already thoroughly searched."""
        active_gaps = []
        for g in gaps:
            scope_key = f"{g.scope.get('geography')}:{g.scope.get('sector')}:{g.scope.get('commodity')}"
            already_searched = any(scope_key in q for q in query_history)
            g.already_searched = already_searched
            if not already_searched:
                active_gaps.append(g)
        return active_gaps
