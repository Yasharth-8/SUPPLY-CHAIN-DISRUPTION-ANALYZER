"""
Unit tests for Court Services: Quote verification, Claim Pairing, Silence checking, Materiality.
"""

import pytest
from app.services.court_services import CourtServices
from app.services.document_loader import ParsedDocument
from app.models import (
    Claim, Estimate, EvidenceRef, EvidenceCard, Round2Response, Ruling, AcceptedEstimate
)
from app.vocabularies import (
    Country, Sector, Commodity, Mechanism, Metric, TimeHorizon,
    ClaimType, ClaimStatus, ResponseType, RulingVerdict, FindingClassification
)


class TestCourtServices:
    @pytest.fixture
    def court_env(self):
        # Raw parsed document with known text
        raw_doc = ParsedDocument(
            doc_id="CRX-1004",
            path="dummy",
            title="Fujairah Berth Expansion",
            pub_date="2027-01-19",
            paragraphs={
                1: "The Port of Fujairah confirms that the Abu Dhabi Crude Oil Pipeline (ADCOP) delivered a record 1.75 million barrels per day of Murban crude to offshore single-point mooring buoys during the first half of January 2027."
            }
        )
        approved_cards = {
            "EV-CRX1004-P1": EvidenceCard(
                evidence_id="EV-CRX1004-P1",
                doc_id="CRX-1004",
                paragraph=1,
                quote="The Port of Fujairah confirms that ADCOP delivered 1.75 million bpd...",
                title="Fujairah Berth",
                source_tier=1,
                event_id="CRX-2027",
            )
        }
        return CourtServices(approved_cards=approved_cards, raw_docs={"CRX-1004": raw_doc})

    def test_quote_verification_success(self, court_env):
        claim = Claim(
            claim_id="D-001",
            side="defence",
            scenario_id="base",
            subject="Fujairah bypass capacity",
            mechanism=Mechanism.ROUTE_REROUTING,
            geography=Country.AE,
            sector=Sector.ENERGY_UPSTREAM,
            commodity=Commodity.CRUDE_OIL,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=10000, unit="tonnes", method="ADCOP pipeline throughput"),
            claim_type=ClaimType.SOURCED_FACT,
            evidence=[
                EvidenceRef(
                    evidence_id="EV-CRX1004-P1",
                    doc_id="CRX-1004",
                    paragraph=1,
                    quote="Port of Fujairah confirms Abu Dhabi Crude Oil Pipeline delivered record 1.75 million barrels per day"
                )
            ]
        )
        is_valid, errors = court_env.validate_citation(claim)
        assert is_valid is True, f"Expected valid citation, got errors: {errors}"

    def test_quote_verification_failure_mismatch(self, court_env):
        claim = Claim(
            claim_id="D-002",
            side="defence",
            scenario_id="base",
            subject="Fujairah bypass capacity",
            mechanism=Mechanism.ROUTE_REROUTING,
            geography=Country.AE,
            sector=Sector.ENERGY_UPSTREAM,
            commodity=Commodity.CRUDE_OIL,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=10000, unit="tonnes", method="ADCOP pipeline throughput"),
            claim_type=ClaimType.SOURCED_FACT,
            evidence=[
                EvidenceRef(
                    evidence_id="EV-CRX1004-P1",
                    doc_id="CRX-1004",
                    paragraph=1,
                    quote="All wheat imports to Germany were halted indefinitely due to cyber attacks."
                )
            ]
        )
        is_valid, errors = court_env.validate_citation(claim)
        assert is_valid is False
        assert any("Quote verification failed" in err for err in errors)

    def test_claim_pairing_exact_and_related_commodities(self, court_env):
        p_claim = Claim(
            claim_id="P-001",
            side="prosecutor",
            scenario_id="base",
            subject="Strait crude blockage",
            mechanism=Mechanism.CHOKEPOINT_DISRUPTION,
            geography=Country.AE,
            sector=Sector.ENERGY_UPSTREAM,  # parent: energy
            commodity=Commodity.CRUDE_OIL,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=500000, unit="tonnes", method="strait flow loss"),
            claim_type=ClaimType.SOURCED_FACT,
        )

        d_claim = Claim(
            claim_id="D-001",
            side="defence",
            scenario_id="base",
            subject="Fujairah bypass mitigation",
            mechanism=Mechanism.ROUTE_REROUTING,
            geography=Country.AE,
            sector=Sector.ENERGY_REFINING,  # parent: energy (matches energy.upstream!)
            commodity=Commodity.REFINED_FUELS,  # related to crude_oil!
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=200000, unit="tonnes", method="ADCOP throughput"),
            claim_type=ClaimType.SOURCED_FACT,
        )

        threads, unpaired = court_env.pair_claims([p_claim], [d_claim])
        assert len(threads) == 1, "Expected claims to pair into 1 DisputeThread"
        assert len(unpaired) == 0
        thread = threads[0]
        assert thread.prosecutor_claims[0].claim_id == "P-001"
        assert thread.defence_claims[0].claim_id == "D-001"

    def test_silence_checking(self, court_env):
        material_claim = Claim(
            claim_id="P-001",
            side="prosecutor",
            scenario_id="base",
            subject="Heavy impact",
            mechanism=Mechanism.CHOKEPOINT_DISRUPTION,
            geography=Country.AE,
            sector=Sector.ENERGY_UPSTREAM,
            commodity=Commodity.CRUDE_OIL,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=200000, unit="tonnes", method="test"),  # > 100k -> material
            claim_type=ClaimType.SOURCED_FACT,
        )
        immaterial_claim = Claim(
            claim_id="P-002",
            side="prosecutor",
            scenario_id="base",
            subject="Minor delay",
            mechanism=Mechanism.CHOKEPOINT_DISRUPTION,
            geography=Country.AE,
            sector=Sector.LOGISTICS_SHIPPING,
            commodity=Commodity.CRUDE_OIL,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.DELAY_DAYS,
            estimate=Estimate(value=1.0, unit="days", method="test"),  # <= 3 days -> not material
            claim_type=ClaimType.SOURCED_FACT,
        )

        # Defence responds only to P-002, leaving P-001 silent
        responses = [
            Round2Response(
                response_id="DR2-001",
                side="defence",
                response_type=ResponseType.CONCEDE,
                targets="P-002",
                reasoning="Minor delay is confirmed"
            )
        ]

        unanswered = court_env.check_silence([material_claim, immaterial_claim], responses)
        assert len(unanswered) == 1
        assert unanswered[0].claim_id == "P-001"

    def test_offline_claim_pairing_volume_shortfall_and_gross_risk(self, court_env):
        """Tests that gross import volume at risk pairs with net volume shortfall under same parent sector."""
        p_claim = Claim(
            claim_id="P-101",
            side="prosecutor",
            scenario_id="base",
            subject="Gross European oil import exposure",
            mechanism=Mechanism.CHOKEPOINT_DISRUPTION,
            geography=Country.GLOBAL,
            sector=Sector.ENERGY_UPSTREAM,
            commodity=Commodity.CRUDE_OIL,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.IMPORT_VOLUME_AT_RISK,
            estimate=Estimate(value=600000, unit="tonnes", method="strait passage flow"),
            claim_type=ClaimType.SOURCED_FACT,
        )
        d_claim = Claim(
            claim_id="D-101",
            side="defence",
            scenario_id="base",
            subject="Net shortfall mitigated by commercial inventory",
            mechanism=Mechanism.ROUTE_REROUTING,
            geography=Country.DE,  # Regional country pairs with GLOBAL
            sector=Sector.ENERGY_REFINING,  # Parent is energy -> matches energy
            commodity=Commodity.REFINED_FUELS,  # Related commodity
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,  # Volume metric compatibility
            estimate=Estimate(value=150000, unit="tonnes", method="SPR inventory release"),
            claim_type=ClaimType.SOURCED_FACT,
        )

        threads, unpaired = court_env.pair_claims([p_claim], [d_claim])
        assert len(threads) == 1, "Should successfully pair gross import risk with net volume shortfall"
        assert len(unpaired) == 0
        assert threads[0].prosecutor_claims[0].claim_id == "P-101"
        assert threads[0].defence_claims[0].claim_id == "D-101"

    def test_offline_unpaired_claims_diagnosis(self, court_env, capsys):
        """Tests that mismatched claims fail pairing gracefully and log diagnostic keys."""
        p_claim = Claim(
            claim_id="P-FERT",
            side="prosecutor",
            scenario_id="base",
            subject="China urea export restrictions",
            mechanism=Mechanism.EXPORT_BAN,
            geography=Country.CN,
            sector=Sector.CHEMICALS_FERTILIZER,
            commodity=Commodity.UREA,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=50000, unit="tonnes", method="customs halt"),
            claim_type=ClaimType.SOURCED_FACT,
        )
        d_claim = Claim(
            claim_id="D-OIL",
            side="defence",
            scenario_id="base",
            subject="Fujairah bypass capacity",
            mechanism=Mechanism.ROUTE_REROUTING,
            geography=Country.AE,
            sector=Sector.ENERGY_UPSTREAM,
            commodity=Commodity.CRUDE_OIL,
            time_horizon=TimeHorizon.T_22_60D,  # Different time bucket
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=10000, unit="tonnes", method="pipeline flow"),
            claim_type=ClaimType.SOURCED_FACT,
        )

        threads, unpaired = court_env.pair_claims([p_claim], [d_claim])
        assert len(threads) == 0, "Mismatched sector, geography, and commodity should not pair"
        assert len(unpaired) == 2

        captured = capsys.readouterr()
        assert "[Court Pairing Diagnosis]" in captured.out
        assert "P-FERT" in captured.out
        assert "D-OIL" in captured.out

    def test_level2_relaxed_pairing_adjacent_time_horizon(self, court_env):
        """Verifies Level 2 relaxed pairing pairs claims in adjacent time buckets with loose match flag."""
        p_claim = Claim(
            claim_id="P-ADJ",
            side="prosecutor",
            scenario_id="base",
            subject="Urea supply interruption",
            mechanism=Mechanism.EXPORT_BAN,
            geography=Country.CN,
            sector=Sector.CHEMICALS_FERTILIZER,
            commodity=Commodity.UREA,
            time_horizon=TimeHorizon.T_0_7D,  # 0-7d
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=60000, unit="tonnes", method="inspection data"),
            claim_type=ClaimType.SOURCED_FACT,
        )
        d_claim = Claim(
            claim_id="D-ADJ",
            side="defence",
            scenario_id="base",
            subject="Domestic fertilizer reserve release",
            mechanism=Mechanism.ROUTE_REROUTING,
            geography=Country.CN,
            sector=Sector.CHEMICALS_FERTILIZER,
            commodity=Commodity.UREA,
            time_horizon=TimeHorizon.T_8_21D,  # 8-21d is adjacent to 0-7d
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=30000, unit="tonnes", method="state reserves"),
            claim_type=ClaimType.SOURCED_FACT,
        )

        threads, unpaired = court_env.pair_claims([p_claim], [d_claim])
        assert len(threads) == 1, "Adjacent time horizons in same sector/geo should pair in Level 2 relaxed pass"
        assert len(unpaired) == 0
        thread = threads[0]
        assert thread.is_loose_match is True
        assert thread.match_level == "relaxed"

    def test_exposure_service_cross_metric_non_additive_guard(self):
        """Verifies that ExposureService never sums cross-metric volume figures together into an inflated aggregate."""
        from app.services.exposure_service import ExposureService
        from app.models import Ruling, AcceptedEstimate, DisputeThread
        from app.vocabularies import RulingVerdict, FindingClassification

        exp_service = ExposureService()
        thread = DisputeThread(
            thread_id="DT-TEST",
            key="CN:chemicals:urea:0-7d:volume_shortfall:base"
        )
        ruling1 = Ruling(
            ruling_id="R-1",
            dispute_thread_id="DT-TEST",
            ruling=RulingVerdict.SUSTAINED,
            classification=FindingClassification.ESTABLISHED,
            claim_type_assessment=ClaimType.SOURCED_FACT,
            accepted_estimate=AcceptedEstimate(
                low=50000.0,
                high=80000.0,
                unit="tonnes",
                estimate_type="direct",
                basis="Direct import shortfall"
            ),
            reasoning="Verified shortfall"
        )
        ruling2 = Ruling(
            ruling_id="R-2",
            dispute_thread_id="DT-TEST",
            ruling=RulingVerdict.PARTIALLY_SUSTAINED,
            classification=FindingClassification.CONTESTED,
            claim_type_assessment=ClaimType.SOURCED_FACT,
            accepted_estimate=AcceptedEstimate(
                low=40000.0,
                high=70000.0,
                unit="tonnes",
                estimate_type="direct",
                basis="Production at risk"
            ),
            reasoning="Production overlap"
        )

        cells = exp_service.compute_exposure_matrix([ruling1, ruling2], [thread], include_unadjudicated_horizons=False)
        assert len(cells) == 1
        cell = cells[0]
        # Must be bounded (min low=40000, max high=80000), NEVER summed (low!=90000, high!=150000)
        assert cell.direct_exposure["low"] == 40000.0
        assert cell.direct_exposure["high"] == 80000.0
        assert cell.direct_exposure["low"] != 90000.0  # Guard against additive double-counting

    def test_level2_cross_scenario_pairing(self, court_env):
        """Verifies that prosecutor 'severe' claim pairs with defence 'base' claim on same physical parameters."""
        p_claim = Claim(
            claim_id="P-SEV",
            side="prosecutor",
            scenario_id="severe",
            subject="Rotterdam port congestion delay",
            mechanism=Mechanism.CHOKEPOINT_DISRUPTION,
            geography=Country.NL,
            sector=Sector.LOGISTICS_SHIPPING,
            commodity=Commodity.CRUDE_OIL,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.DELAY_DAYS,
            estimate=Estimate(value=14.0, unit="days", method="Cape rerouting delay"),
            claim_type=ClaimType.SOURCED_FACT,
        )
        d_claim = Claim(
            claim_id="D-BASE",
            side="defence",
            scenario_id="base",
            subject="Rotterdam port operational buffer delay",
            mechanism=Mechanism.CHOKEPOINT_DISRUPTION,
            geography=Country.NL,
            sector=Sector.LOGISTICS_SHIPPING,
            commodity=Commodity.CRUDE_OIL,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.DELAY_DAYS,
            estimate=Estimate(value=7.0, unit="days", method="berth scheduling"),
            claim_type=ClaimType.SOURCED_FACT,
        )

        threads, unpaired = court_env.pair_claims([p_claim], [d_claim])
        assert len(threads) == 1, "Cross-scenario claims on identical metric/commodity/geo should pair in Level 2"
        assert len(unpaired) == 0
        thread = threads[0]
        assert thread.is_loose_match is True
        assert thread.match_level == "scenario_cross"
        assert thread.prosecutor_claims[0].claim_id == "P-SEV"
        assert thread.defence_claims[0].claim_id == "D-BASE"

    def test_level2_cross_sector_intertwined_pairing(self, court_env):
        """Verifies upstream chemical fertilizer pairs with downstream agricultural farming on urea."""
        p_claim = Claim(
            claim_id="P-AGRI",
            side="prosecutor",
            scenario_id="base",
            subject="Agricultural fertilizer shortage",
            mechanism=Mechanism.EXPORT_BAN,
            geography=Country.IN,
            sector=Sector.AGRICULTURE_FARMING,
            commodity=Commodity.UREA,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=500000, unit="tonnes", method="kharif deficit"),
            claim_type=ClaimType.SOURCED_FACT,
        )
        d_claim = Claim(
            claim_id="D-CHEM",
            side="defence",
            scenario_id="base",
            subject="Chemical buffer stocks",
            mechanism=Mechanism.EXPORT_BAN,
            geography=Country.IN,
            sector=Sector.CHEMICALS_FERTILIZER,
            commodity=Commodity.UREA,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=425000, unit="tonnes", method="opening buffer"),
            claim_type=ClaimType.SOURCED_FACT,
        )

        threads, unpaired = court_env.pair_claims([p_claim], [d_claim])
        assert len(threads) == 1, "Intertwined chemicals and agriculture on urea should pair in Level 2"
        assert len(unpaired) == 0
        thread = threads[0]
        assert thread.is_loose_match is True

    def test_delay_versus_volume_must_not_produce_combined_range(self, court_env):
        """Cross-metric claims with disparate dimensions (delay in days vs volume in tonnes) must not pair or produce a combined range."""
        p_claim = Claim(
            claim_id="P-DELAY",
            side="prosecutor",
            scenario_id="base",
            subject="Port congestion delay",
            mechanism=Mechanism.PORT_STRIKE,
            geography=Country.IN,
            sector=Sector.LOGISTICS_SHIPPING,
            commodity=Commodity.ELECTRONIC_COMPONENTS,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.DELAY_DAYS,
            estimate=Estimate(value=14.0, unit="days", method="Vessel congestion"),
            claim_type=ClaimType.SOURCED_FACT,
        )
        d_claim = Claim(
            claim_id="D-VOL",
            side="defence",
            scenario_id="base",
            subject="Domestic component volume",
            mechanism=Mechanism.ROUTE_REROUTING,
            geography=Country.IN,
            sector=Sector.LOGISTICS_SHIPPING,
            commodity=Commodity.ELECTRONIC_COMPONENTS,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=5000.0, unit="tonnes", method="Rail bypass"),
            claim_type=ClaimType.SOURCED_FACT,
        )

        threads, unpaired = court_env.pair_claims([p_claim], [d_claim])
        # Disparate dimensional families (time delay vs physical volume) must NOT pair into a combined dispute
        assert len(threads) == 0, "Delay in days and volume in tonnes must never pair into a combined thread"
        assert len(unpaired) == 2

        # Check deterministic Judge handling: ruled on separately without any combined range
        from app.graph.nodes.judge import JudgeNode
        judge = JudgeNode()
        out = judge.rule_threads(threads=[], unpaired_claims=unpaired, unanswered_material=[])
        assert len(out.rulings) == 2
        for r in out.rulings:
            assert r.comparable is not True or r.accepted_estimate is None or r.accepted_estimate.low == r.accepted_estimate.high, "Must never produce a cross-metric range between delay and volume"

    def test_unrelated_commodity_must_not_pair_through_sector_link(self, court_env):
        """An unrelated commodity must not pair simply because parent sectors are related."""
        p_claim = Claim(
            claim_id="P-CHEM",
            side="prosecutor",
            scenario_id="base",
            subject="Chemical polymer shortfall",
            mechanism=Mechanism.INFRASTRUCTURE_FAILURE,
            geography=Country.IN,
            sector=Sector.CHEMICALS_PETROCHEMICALS,
            commodity=Commodity.POLYMERS,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=20000.0, unit="tonnes", method="Feedstock cut"),
            claim_type=ClaimType.SOURCED_FACT,
        )
        d_claim = Claim(
            claim_id="D-AGRI",
            side="defence",
            scenario_id="base",
            subject="Wheat harvest buffer",
            mechanism=Mechanism.ROUTE_REROUTING,
            geography=Country.IN,
            sector=Sector.AGRICULTURE_FARMING,
            commodity=Commodity.WHEAT,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=100000.0, unit="tonnes", method="Grain silo stocks"),
            claim_type=ClaimType.SOURCED_FACT,
        )

        threads, unpaired = court_env.pair_claims([p_claim], [d_claim])
        assert len(threads) == 0, "Polymers and wheat must never pair even though chemicals and agriculture are related sectors"
        assert len(unpaired) == 2

    def test_loosely_paired_thread_is_labelled_as_loose(self, court_env):
        """A loosely paired thread across adjacent time horizons or scenarios is strictly marked loose."""
        p_claim = Claim(
            claim_id="P-HORIZ-1",
            side="prosecutor",
            scenario_id="base",
            subject="Early shock",
            mechanism=Mechanism.CHOKEPOINT_DISRUPTION,
            geography=Country.IN,
            sector=Sector.LOGISTICS_SHIPPING,
            commodity=Commodity.CRUDE_OIL,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=100000.0, unit="tonnes", method="Tanker tracker"),
            claim_type=ClaimType.SOURCED_FACT,
        )
        d_claim = Claim(
            claim_id="D-HORIZ-2",
            side="defence",
            scenario_id="base",
            subject="Later mitigation",
            mechanism=Mechanism.ROUTE_REROUTING,
            geography=Country.IN,
            sector=Sector.LOGISTICS_SHIPPING,
            commodity=Commodity.CRUDE_OIL,
            time_horizon=TimeHorizon.T_8_21D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=80000.0, unit="tonnes", method="Bypass flow"),
            claim_type=ClaimType.SOURCED_FACT,
        )

        threads, unpaired = court_env.pair_claims([p_claim], [d_claim])
        assert len(threads) == 1
        thread = threads[0]
        assert thread.is_loose_match is True
        assert thread.match_level in ("relaxed", "related")

    def test_defence_claim_without_number_is_not_paired_as_numeric_dispute(self, court_env):
        """A Defence claim without a numeric estimate must be marked comparable=False and not form a numeric dispute."""
        p_claim = Claim(
            claim_id="P-NUM",
            side="prosecutor",
            scenario_id="base",
            subject="Quantified port shortfall",
            mechanism=Mechanism.CHOKEPOINT_DISRUPTION,
            geography=Country.IN,
            sector=Sector.LOGISTICS_SHIPPING,
            commodity=Commodity.ELECTRONIC_COMPONENTS,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=50000.0, unit="tonnes", method="Gateway traffic model"),
            claim_type=ClaimType.SOURCED_FACT,
        )
        d_claim = Claim(
            claim_id="D-QUAL",
            side="defence",
            scenario_id="base",
            subject="Qualitative resilience assertion without number",
            mechanism=Mechanism.ROUTE_REROUTING,
            geography=Country.IN,
            sector=Sector.LOGISTICS_SHIPPING,
            commodity=Commodity.ELECTRONIC_COMPONENTS,
            time_horizon=TimeHorizon.T_0_7D,
            metric=Metric.VOLUME_SHORTFALL,
            estimate=Estimate(value=None, unit="", method="Qualitative operational adaptation"),
            claim_type=ClaimType.INFERENCE,
        )

        threads, unpaired = court_env.pair_claims([p_claim], [d_claim])
        assert len(threads) == 1
        thread = threads[0]
        assert thread.comparable is False, "Unquantified claim must not be paired as comparable=True"
        assert thread.match_level == "related"


