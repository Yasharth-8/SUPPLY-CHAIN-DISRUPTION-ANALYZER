"""
Test Suite: Fertilizer Export Ban Inquiry & Mentor Review Verification
Verifies the exact scenario: 'what will happend to india if china bans the fertilizer exports ?'
Ensures:
1. Gatekeeper targets India/China and Fertilizer/Urea/Chemicals/Agriculture.
2. Disjoint maritime energy documents (CRX-1001, CRX-1002) are excluded from the pool.
3. Claims are strictly scoped to fertilizer/agriculture/chemicals, rejecting crude oil/refined fuels.
4. Silence is never treated as a concession.
5. Exposure matrix keeps volume shortfall and price increases in separate cells.
6. Judicial estimates are strictly bounded by claim inputs (no invented numbers).
7. Enum values are cleanly formatted without raw Python prefixes.
"""

import pytest
from unittest.mock import patch
from app.graph.nodes.gatekeeper import GatekeeperNode, GatekeeperAnalysisOutput
from app.graph.nodes.judge import JudgeNode
from app.services.court_services import CourtServices
from app.services.exposure_service import ExposureService
from app.services.briefing_renderer import BriefingRenderer
from app.models import (
    CaseFile, Claim, Estimate, EvidenceRef, DisputeThread,
    Ruling, AcceptedEstimate, Metric, Mechanism, ClaimType, NamedScenario
)
from app.vocabularies import (
    Sector, Commodity, Country, TimeHorizon, EventStatus,
    FindingClassification, RulingVerdict
)


class TestFertilizerCaseReview:
    
    @pytest.fixture
    def mock_gk_analysis(self):
        return GatekeeperAnalysisOutput(
            is_off_topic=False,
            is_hypothetical=True,
            event_summary="Impact of Chinese export restrictions on fertilizers to India",
            as_of_date="2027-02-20",
            perspective="economic_security",
            reference_region=[Country.IN, Country.CN],
            reference_sectors=["chemicals", "agriculture"],
            scenarios=[
                NamedScenario(scenario_id="base", duration_days=60, severity="partial", description="Sustained disruption")
            ],
            reasoning="Inquiry focuses on agricultural fertilizer supply security between India and China."
        )

    @pytest.fixture
    def fert_case_file(self, mock_gk_analysis):
        gk = GatekeeperNode()
        with patch.object(gk.llm, "generate_structured", return_value=mock_gk_analysis):
            case_file, _, _, _ = gk.run(
                question="what will happend to india if china bans the fertilizer exports ?",
                case_id="CASE-FERT-TEST"
            )
        return case_file

    def test_gatekeeper_targets_and_disputed_cells(self, fert_case_file):
        """Verify deterministic scoping for fertilizer export ban inquiry."""
        assert fert_case_file is not None
        assert fert_case_file.event_status in (EventStatus.HYPOTHETICAL, EventStatus.CONFIRMED, EventStatus.REPORTED)
        assert "IN" in fert_case_file.target_countries
        assert "fertilizer" in fert_case_file.target_commodities or "urea" in fert_case_file.target_commodities
        assert "chemicals" in fert_case_file.target_sectors or "agriculture" in fert_case_file.target_sectors

        # Ensure disputed cells focus on India and fertilizer/agriculture
        assert len(fert_case_file.disputed_cells) > 0
        assert any(cell.startswith("IN:chemicals") or cell.startswith("IN:agriculture") for cell in fert_case_file.disputed_cells)
        # Ensure energy disputed cells were not injected
        assert not any(cell.startswith("IN:energy") for cell in fert_case_file.disputed_cells)

    def test_gatekeeper_excludes_disjoint_energy_documents(self, fert_case_file):
        """Verify disjoint maritime energy crisis documents are excluded for fertilizer inquiry."""
        assert fert_case_file is not None
        approved_pool = set(fert_case_file.approved_pool)
        
        # Maritime oil/insurance documents should not be approved for a pure fertilizer inquiry
        assert "CRX-1001" not in approved_pool  # Persian Gulf transit
        assert "CRX-1002" not in approved_pool  # Marine insurance on Gulf

        # Check exclusion report
        excluded_ids = {e.doc_id for e in fert_case_file.excluded_documents}
        assert "CRX-1001" in excluded_ids
        assert "CRX-1002" in excluded_ids
        
        # Verify that topic mismatch is cited in exclusion reasons
        reasons = {e.doc_id: e.reason for e in fert_case_file.excluded_documents}
        assert "topic_mismatch" in reasons.get("CRX-1001", "")
        assert "topic_mismatch" in reasons.get("CRX-1002", "")

    def test_court_services_rejects_off_scope_energy_claims(self, fert_case_file):
        """Claims about crude oil or Cape rerouting must be rejected for a fertilizer case."""
        court = CourtServices(approved_cards={}, raw_docs={})

        valid_claim = Claim(
            claim_id="P-FERT-001",
            side="prosecutor",
            subject="Urea import shortfall for Indian agricultural kharif season",
            geography=Country.IN,
            sector=Sector.CHEMICALS_FERTILIZER,
            commodity=Commodity.UREA,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            mechanism=Mechanism.REGULATORY_CHANGE,
            estimate=Estimate(value=25.0, unit="percent", method="Quota gap analysis"),
            scenario_id="base",
            claim_type=ClaimType.SOURCED_FACT,
            evidence=[EvidenceRef(evidence_id="EV-CRX-1038-P1", doc_id="CRX-1038", paragraph=1, quote="Fertilizer buffer stocks")]
        )

        off_scope_claim = Claim(
            claim_id="P-OIL-002",
            side="prosecutor",
            subject="Crude oil transit delay around Cape of Good Hope",
            geography=Country.GLOBAL,
            sector=Sector.ENERGY_UPSTREAM,
            commodity=Commodity.CRUDE_OIL,
            time_horizon=TimeHorizon.T_8_21D,
            metric=Metric.DELAY_DAYS,
            mechanism=Mechanism.ROUTE_REROUTING,
            estimate=Estimate(value=14.0, unit="days", method="Nautical detour"),
            scenario_id="base",
            claim_type=ClaimType.SOURCED_FACT,
            evidence=[]
        )

        kept, rejected = court.filter_off_scope_claims([valid_claim, off_scope_claim], fert_case_file)
        assert len(kept) == 1
        assert kept[0].claim_id == "P-FERT-001"
        assert len(rejected) == 1
        assert rejected[0].claim_id == "P-OIL-002"
        assert "off-scope" in rejected[0].status_reason.lower()

    def test_silence_is_never_treated_as_concession(self):
        """Unopposed claims must not be marked CONCEDED unless explicit concession occurred."""
        judge = JudgeNode()

        p_claim = Claim(
            claim_id="P-001",
            side="prosecutor",
            subject="Indian fertilizer import deficit",
            geography=Country.IN,
            sector=Sector.CHEMICALS_FERTILIZER,
            commodity=Commodity.UREA,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            mechanism=Mechanism.REGULATORY_CHANGE,
            estimate=Estimate(value=20.0, unit="percent", method="Documentary analysis"),
            scenario_id="base",
            claim_type=ClaimType.SOURCED_FACT,
            evidence=[EvidenceRef(evidence_id="EV-CRX-1038-P1", doc_id="CRX-1038", paragraph=1, quote="Buffer stock")]
        )
        thread = DisputeThread(
            thread_id="DT-001",
            key="IN:chemicals:urea:0-7d:volume_shortfall:base",
            prosecutor_claims=[p_claim],
            defence_claims=[]
        )

        # Mock LLM to return empty so deterministic judicial fallback rules
        with patch.object(judge.llm, "generate_structured", return_value=None):
            output = judge.rule_threads([thread], unpaired_claims=[], unanswered_material=[])

        assert len(output.rulings) == 1
        ruling = output.rulings[0]
        assert ruling.classification != FindingClassification.CONCEDED
        assert "conceded" not in ruling.reasoning.lower() or "not a concession" in ruling.reasoning.lower() or "uncontested" in ruling.reasoning.lower()
        # Accepted range must be strictly single input [20, 20], not an invented range
        assert ruling.accepted_estimate.low == 20.0
        assert ruling.accepted_estimate.high == 20.0

    def test_exposure_matrix_separates_metrics(self):
        """Volume shortfall and price increase must never mix into the same cell."""
        exposure_svc = ExposureService()

        ruling_vol = Ruling(
            ruling_id="R-01",
            dispute_thread_id="DT-01",
            ruling=RulingVerdict.SUSTAINED,
            classification=FindingClassification.CONTESTED,
            claim_type_assessment=ClaimType.SOURCED_FACT,
            reasoning="Valid shortfall based on export curbs.",
            accepted_estimate=AcceptedEstimate(low=15.0, high=25.0, unit="percent", estimate_type="direct", basis="prosecutor_claim")
        )
        thread_vol = DisputeThread(
            thread_id="DT-01",
            key="IN:chemicals:urea:0-7d:volume_shortfall:base",
            prosecutor_claims=[
                Claim(
                    claim_id="P-1", side="prosecutor", subject="Shortfall",
                    geography=Country.IN, sector=Sector.CHEMICALS_FERTILIZER,
                    commodity=Commodity.UREA, time_horizon=TimeHorizon.T_0_7D,
                    metric=Metric.VOLUME_SHORTFALL, mechanism=Mechanism.REGULATORY_CHANGE,
                    estimate=Estimate(value=25.0, unit="percent", method="Analysis"),
                    claim_type=ClaimType.SOURCED_FACT, scenario_id="base", evidence=[]
                )
            ]
        )

        ruling_price = Ruling(
            ruling_id="R-02",
            dispute_thread_id="DT-02",
            ruling=RulingVerdict.SUSTAINED,
            classification=FindingClassification.CONTESTED,
            claim_type_assessment=ClaimType.SOURCED_FACT,
            reasoning="Surge in spot price.",
            accepted_estimate=AcceptedEstimate(low=50.0, high=466.67, unit="percent", estimate_type="direct", basis="prosecutor_claim")
        )
        thread_price = DisputeThread(
            thread_id="DT-02",
            key="IN:chemicals:urea:0-7d:price_increase:base",
            prosecutor_claims=[
                Claim(
                    claim_id="P-2", side="prosecutor", subject="Price surge",
                    geography=Country.IN, sector=Sector.CHEMICALS_FERTILIZER,
                    commodity=Commodity.UREA, time_horizon=TimeHorizon.T_0_7D,
                    metric=Metric.PRICE_INCREASE, mechanism=Mechanism.REGULATORY_CHANGE,
                    estimate=Estimate(value=466.67, unit="percent", method="Analysis"),
                    claim_type=ClaimType.SOURCED_FACT, scenario_id="base", evidence=[]
                )
            ]
        )

        matrix = exposure_svc.compute_exposure_matrix([ruling_vol, ruling_price], [thread_vol, thread_price], include_unadjudicated_horizons=False)
        
        # Must produce 2 separate cells, not merged into [15 - 466.67]!
        assert len(matrix) == 2
        metrics = {c.metric for c in matrix}
        assert Metric.VOLUME_SHORTFALL in metrics
        assert Metric.PRICE_INCREASE in metrics

        # Verify values in volume cell
        vol_cell = next(c for c in matrix if c.metric == Metric.VOLUME_SHORTFALL)
        assert vol_cell.direct_exposure["low"] == 15.0
        assert vol_cell.direct_exposure["high"] == 25.0

        # Verify values in price cell
        price_cell = next(c for c in matrix if c.metric == Metric.PRICE_INCREASE)
        assert price_cell.direct_exposure["high"] == 466.67

    def test_briefing_does_not_mention_irrelevant_pipelines_in_fertilizer_case(self):
        """Briefing for fertilizer case must refer to buffers and reserves, not crude oil bypasses."""
        renderer = BriefingRenderer()
        case_file = CaseFile(
            case_id="CASE-FERT-001",
            question="what will happend to india if china bans the fertilizer exports ?",
            event_status_reasoning="China export restrictions verified.",
            as_of_date="2027-02-20",
            perspective="economic_security",
            event_status=EventStatus.HYPOTHETICAL,
            event_summary="Impact of Chinese fertilizer export restrictions on India",
            target_countries=["IN", "CN"],
            target_sectors=["chemicals", "agriculture"],
            target_commodities=["urea", "fertilizer"],
            low_coverage=True,
            coverage_warning="Evidence pool lacks direct Indian state procurement figures."
        )

        briefing = renderer.render_briefing(
            case_file=case_file,
            rulings=[],
            exposure_cells=[],
            all_claims=[],
            evidence_cards={}
        )

        # Check assumptions and outlook
        assert "fertilizer" in briefing.outlook.lower() or "agricultural" in briefing.outlook.lower()
        assert not any("pipeline" in a.lower() for a in briefing.assumptions)
        assert not any("cape of good hope" in a.lower() for a in briefing.assumptions)
        assert any("reserve" in a.lower() or "quota" in a.lower() or "fertilizer" in a.lower() for a in briefing.assumptions)

    def test_non_comparable_metric_and_unit_pairing_rejected(self):
        """Claims with disparate unit families (percent vs tonnes) or disparate metrics must not pair."""
        court = CourtServices(approved_cards={}, raw_docs={})

        p_claim = Claim(
            claim_id="P-YIELD-01",
            side="prosecutor",
            subject="Indian agricultural production at risk",
            geography=Country.IN,
            sector=Sector.AGRICULTURE_FARMING,
            commodity=Commodity.UREA,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.PRODUCTION_AT_RISK,
            mechanism=Mechanism.REGULATORY_CHANGE,
            estimate=Estimate(value=35.0, unit="percent", method="Yield sensitivity"),
            scenario_id="base",
            claim_type=ClaimType.SOURCED_FACT,
            evidence=[]
        )

        d_claim = Claim(
            claim_id="D-VOL-01",
            side="defence",
            subject="India Long-Term Supply Contract Insulation",
            geography=Country.IN,
            sector=Sector.AGRICULTURE_FARMING,
            commodity=Commodity.UREA,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.IMPORT_VOLUME_AT_RISK,
            mechanism=Mechanism.REGULATORY_CHANGE,
            estimate=Estimate(value=1000000.0, unit="tonnes", method="Contract data"),
            scenario_id="base",
            claim_type=ClaimType.SOURCED_FACT,
            evidence=[]
        )

        threads, unpaired = court.pair_claims([p_claim], [d_claim])
        # Must NOT pair into a false dispute: percent vs tonnes is non-comparable!
        assert len(threads) == 0
        assert len(unpaired) == 2

    def test_unadjudicated_horizons_included_in_matrix(self):
        """Missing planning horizons (22-60d, 61-90d) must be explicitly represented as unadjudicated."""
        exposure_svc = ExposureService()
        ruling = Ruling(
            ruling_id="R-01",
            dispute_thread_id="DT-01",
            ruling=RulingVerdict.SUSTAINED,
            classification=FindingClassification.CONTESTED,
            claim_type_assessment=ClaimType.SOURCED_FACT,
            reasoning="Valid 0-7d delay.",
            accepted_estimate=AcceptedEstimate(low=7.0, high=21.0, unit="days", estimate_type="direct", basis="Rerouting")
        )
        thread = DisputeThread(
            thread_id="DT-01",
            key="IN:logistics:urea:0-7d:delay_days:base",
            prosecutor_claims=[
                Claim(
                    claim_id="P-01", side="prosecutor", subject="Delay",
                    geography=Country.IN, sector=Sector.LOGISTICS_SHIPPING,
                    commodity=Commodity.UREA, time_horizon=TimeHorizon.T_0_7D,
                    metric=Metric.DELAY_DAYS, mechanism=Mechanism.ROUTE_REROUTING,
                    estimate=Estimate(value=21.0, unit="days", method="Transit calculation"),
                    claim_type=ClaimType.SOURCED_FACT, scenario_id="base", evidence=[]
                )
            ]
        )

        cells = exposure_svc.compute_exposure_matrix([ruling], [thread], include_unadjudicated_horizons=True)
        horizons = {c.time_horizon for c in cells}
        assert "0-7d" in horizons
        assert "22-60d" in horizons
        assert "61-90d" in horizons

        unadjudicated = [c for c in cells if c.status == "unknown"]
        assert len(unadjudicated) >= 2
        for u in unadjudicated:
            assert u.direct_exposure is None
            assert u.mitigated_exposure is None
            assert "Unadjudicated" in u.label

    def test_word_deduplication_removes_stutters(self):
        """LLMClient cleaner must eliminate stuttered doubled words like 'active active' or 'transit transit'."""
        from app.services.llm_client import LLMClient
        client = LLMClient()
        test_json = '{"reasoning": "Active active bulk shipping bill verification fails to account for compounding transit transit delays across immediate immediate harvest failure."}'
        parsed = client._clean_and_parse_json(test_json)
        cleaned_text = parsed["reasoning"]
        assert "active active" not in cleaned_text.lower()
        assert "transit transit" not in cleaned_text.lower()
        assert "immediate immediate" not in cleaned_text.lower()
        assert "active" in cleaned_text.lower()
        assert "transit" in cleaned_text.lower()
        assert "immediate" in cleaned_text.lower()

    def test_prima_facie_rule_rejects_standalone_defence_mitigation(self):
        """Defence claims standing alone without a Prosecutor disruption claim must be ruled INSUFFICIENT_EVIDENCE."""
        from app.graph.nodes.judge import JudgeNode
        judge = JudgeNode()
        def_claim = Claim(
            claim_id="CLM-DEF-001",
            side="defence",
            subject="India agricultural sector buffer",
            geography=Country.IN,
            sector=Sector.AGRICULTURE_FARMING,
            commodity=Commodity.UREA,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            mechanism=Mechanism.REGULATORY_CHANGE,
            estimate=Estimate(value=4250000.0, unit="metric_tonnes", method="Opening buffer stocks"),
            claim_type=ClaimType.SOURCED_FACT,
            scenario_id="base",
            evidence=[]
        )
        thread = DisputeThread(
            thread_id="DT-U-CLM-DEF-001",
            key="IN:agriculture:urea:0-7d:volume_shortfall:base",
            prosecutor_claims=[],
            defence_claims=[def_claim]
        )

        from unittest.mock import patch
        from app.graph.nodes.judge import JudgeBatchRulingsOutput
        # Mock LLM returning a sustained ruling to verify the post-processing prima facie override
        mock_output = JudgeBatchRulingsOutput(
            threads=[thread],
            rulings=[
                Ruling(
                    ruling_id="R-TEST",
                    dispute_thread_id="DT-U-CLM-DEF-001",
                    prosecutor_claim_ids=[],
                    defence_claim_ids=["CLM-DEF-001"],
                    ruling=RulingVerdict.SUSTAINED,
                    classification=FindingClassification.ESTABLISHED,
                    claim_type_assessment=ClaimType.SOURCED_FACT,
                    accepted_estimate=AcceptedEstimate(low=4250000.0, high=4250000.0, unit="metric_tonnes", estimate_type="mitigated", basis="buffer"),
                    reasoning="Unopposed buffer."
                )
            ],
            is_sufficient=True
        )
        with patch.object(judge.llm, "generate_structured", return_value=mock_output):
            output = judge.rule_threads(threads=[thread], unpaired_claims=[], unanswered_material=[])
        assert len(output.rulings) == 1
        ruling = output.rulings[0]
        assert ruling.ruling == RulingVerdict.INSUFFICIENT_EVIDENCE
        assert ruling.classification == FindingClassification.INSUFFICIENT
        assert ruling.accepted_estimate is None
        assert "prima facie" in ruling.reasoning.lower() or "no underlying disruption" in ruling.reasoning.lower()

    def test_briefing_reports_insufficient_evidence_when_no_disruption(self):
        """When all rulings are insufficient evidence, the executive briefing must not claim buffers absorbed shocks."""
        renderer = BriefingRenderer()
        case_file = CaseFile(
            case_id="CASE-USA-001",
            question="Analysis of supply chain exposure in India resulting from a hypothetical complete ban on imports from the USA to India.",
            event_summary="Hypothetical complete ban on imports from the USA to India.",
            event_status=EventStatus.HYPOTHETICAL,
            event_status_reasoning="Hypothetical analysis.",
            as_of_date="2027-02-20",
            perspective="economic_security",
            target_sectors=["chemicals", "agriculture"],
            target_commodities=["urea"],
            reference_region=[Country.IN, Country.US]
        )
        ruling = Ruling(
            ruling_id="R-01",
            dispute_thread_id="DT-01",
            ruling=RulingVerdict.INSUFFICIENT_EVIDENCE,
            classification=FindingClassification.INSUFFICIENT,
            claim_type_assessment=ClaimType.SOURCED_FACT,
            reasoning="No prima facie disruption established.",
            accepted_estimate=None
        )
        briefing = renderer.render_briefing(
            case_file=case_file,
            rulings=[ruling],
            all_claims=[],
            evidence_cards={},
            exposure_cells=[]
        )
        assert "insufficient evidence" in briefing.outlook.lower()
        assert "no prima facie shortfall" in briefing.outlook.lower()
        assert "absorb near-term shock" not in briefing.outlook.lower()
