"""
Exposure Calculation Service: Cell Mapping, Aggregation, and Scenario Matrix.
Computes exposure ranges strictly from accepted rulings, never by simple partisan averaging.
"""

from typing import List, Dict, Any, Optional
from collections import defaultdict

from app.models import (
    Ruling, ExposureCell, DisputeThread, AcceptedEstimate
)
from app.vocabularies import (
    RulingVerdict, ConfidenceLevel
)


class ExposureService:
    def compute_exposure_matrix(
        self,
        rulings: List[Ruling],
        threads: List[DisputeThread],
        include_unadjudicated_horizons: bool = True
    ) -> List[ExposureCell]:
        """
        Maps rulings into time-bounded exposure matrix cells:
        {country, sector, commodity, time_horizon, scenario_id} -> ExposureCell
        """
        thread_map = {t.thread_id: t for t in threads}
        cells_dict: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "direct": [],
            "mitigated": [],
            "rulings": [],
            "insufficient": False,
        })

        for r in rulings:
            t = thread_map.get(r.dispute_thread_id)
            thread_comm = "general"
            if t:
                sample_claim = (t.prosecutor_claims[0] if t.prosecutor_claims else (t.defence_claims[0] if t.defence_claims else None))
                if sample_claim and hasattr(sample_claim, "commodity"):
                    thread_comm = (sample_claim.commodity.value if hasattr(sample_claim.commodity, "value") else str(sample_claim.commodity)).lower()

            if t and t.key:
                parts = t.key.split(":")
                geo = parts[0] if len(parts) > 0 else "GLOBAL"
                sector = parts[1] if len(parts) > 1 else "general"
                comm = parts[2] if len(parts) > 2 else thread_comm
                th = parts[3] if len(parts) > 3 else "0-7d"
                metric = parts[4] if len(parts) > 4 else "volume_shortfall"
                scen_id = parts[5] if len(parts) > 5 else "base"
            else:
                geo, sector, comm, th, metric, scen_id = "GLOBAL", "general", thread_comm, "0-7d", "volume_shortfall", "base"

            # Sanitize raw enum strings and hierarchy resolution
            geo = geo.replace("Country.", "")
            from app.vocabularies import Sector
            sector = Sector.get_parent(sector)
            comm = comm.replace("Commodity.", "").lower()
            th = th.replace("TimeHorizon.", "").replace("TIMEHORIZON.", "")
            metric = metric.replace("Metric.", "").lower()

            # Metric is strictly included in the cell_key to prevent disparate metrics from merging
            cell_key = f"{geo}:{sector}:{comm}:{th}:{metric}:{scen_id}"

            if r.ruling == RulingVerdict.INSUFFICIENT_EVIDENCE:
                cells_dict[cell_key]["insufficient"] = True
                cells_dict[cell_key]["rulings"].append(r.ruling_id)
                continue

            if r.accepted_estimate:
                est = r.accepted_estimate
                cells_dict[cell_key]["rulings"].append(r.ruling_id)
                if est.estimate_type == "mitigated":
                    cells_dict[cell_key]["mitigated"].append(est)
                else:
                    cells_dict[cell_key]["direct"].append(est)

        # Build ExposureCell models with strict cross-metric aggregation guard
        def _aggregate_estimates(est_list: List[AcceptedEstimate]) -> Optional[Dict[str, Any]]:
            if not est_list:
                return None
            # Group strictly by unit to prevent adding or blending disparate units
            by_unit: Dict[str, List[AcceptedEstimate]] = defaultdict(list)
            for e in est_list:
                by_unit[e.unit.lower()].append(e)

            dominant_unit = max(by_unit.keys(), key=lambda u: len(by_unit[u]))
            matched = by_unit[dominant_unit]

            # Cross-metric aggregation guard: Never sum figures that may represent the same physical flow.
            # Bounded range ensures non-additive reconciliation.
            min_low = min(e.low for e in matched)
            max_high = max(e.high for e in matched)
            return {"low": min_low, "high": max_high, "unit": dominant_unit}

        result_cells: List[ExposureCell] = []
        for cell_key, data in cells_dict.items():
            geo, sector, comm, th, metric, scen_id = cell_key.split(":")

            direct_obj = _aggregate_estimates(data["direct"])
            mitigated_obj = _aggregate_estimates(data["mitigated"])

            # Calibrated Confidence Rubric based on adversarial opposition, documentary depth, and range width
            primary_obj = direct_obj or mitigated_obj
            if primary_obj:
                status = "known"
                low_val = primary_obj["low"]
                high_val = primary_obj["high"]
                is_wide_range = (low_val > 0 and high_val > low_val * 2.0) or (high_val - low_val > 50.0)
                
                # Check adversarial opposition by resolving supporting rulings to their threads
                supporting_threads = [thread_map.get(r.dispute_thread_id) for r in rulings if r.ruling_id in data["rulings"]]
                is_opposed = any(bool(t and t.prosecutor_claims and t.defence_claims) for t in supporting_threads)

                if not is_opposed:
                    # Unopposed single-sided claims carry LOW confidence as they lack adversarial stress-testing
                    conf = ConfidenceLevel.LOW
                elif is_wide_range:
                    conf = ConfidenceLevel.MEDIUM
                else:
                    conf = ConfidenceLevel.HIGH
            else:
                status = "unknown"
                conf = ConfidenceLevel.LOW

            cell = ExposureCell(
                country=geo,
                sector=sector,
                commodity=comm,
                time_horizon=th,
                metric=metric,
                scenario_id=scen_id,
                direct_exposure=direct_obj,
                mitigated_exposure=mitigated_obj,
                status=status,
                confidence=conf,
                supporting_rulings=data["rulings"],
                label="Insufficient documentary evidence" if data["insufficient"] else "derived_from_rulings"
            )
            result_cells.append(cell)

        # Represent missing medium-term horizons as explicit unadjudicated rows
        # Avoids silent gaps when briefing references horizons beyond 21d
        if include_unadjudicated_horizons:
            target_combos = {(c.country, c.sector, c.commodity, c.metric, c.scenario_id) for c in result_cells if c.country != "GLOBAL"}
            for (geo, sector, comm, metric, scen_id) in target_combos:
                for medium_th in ["22-60d", "61-90d"]:
                    already_covered = any(
                        c.country == geo and c.sector == sector and c.commodity == comm and c.metric == metric and c.time_horizon == medium_th
                        for c in result_cells
                    )
                    if not already_covered:
                        result_cells.append(
                            ExposureCell(
                                country=geo,
                                sector=sector,
                                commodity=comm,
                                time_horizon=medium_th,
                                metric=metric,
                                scenario_id=scen_id,
                                direct_exposure=None,
                                mitigated_exposure=None,
                                status="unknown",
                                confidence=ConfidenceLevel.LOW,
                                supporting_rulings=[],
                                label="Unadjudicated: No documentary evidence submitted"
                            )
                        )

        return result_cells

