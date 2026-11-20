"""
Benchmark Runner for the 50 Supply Chain Disruption Queries.
Executes the full pipeline via trial_graph.invoke for each query, logs Gatekeeper, Prosecutor,
Defence, Court Clerk, and Judge stages, extracts ground truth from documents,
and compiles comprehensive findings.
"""

import sys
import os
import json
import time
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph.workflow import trial_graph

QUERIES_50 = [
    # A. Core exposure of India (10)
    {"id": "A1", "group": "A. Core exposure of India", "query": "How exposed is India’s crude oil supply to the Strait of Hormuz disruption over the next 30 days?"},
    {"id": "A2", "group": "A. Core exposure of India", "query": "What does the 0.85% war-risk insurance surcharge do to Indian import costs?"},
    {"id": "A3", "group": "A. Core exposure of India", "query": "Is the 11–14 day Cape of Good Hope rerouting a delay or a real shortage for Indian container trade?"},
    {"id": "A4", "group": "A. Core exposure of India", "query": "How exposed are Indian refiners to losing Persian Gulf crude and LPG?"},
    {"id": "A5", "group": "A. Core exposure of India", "query": "How exposed is India’s urea supply to the Gulf crisis?"},
    {"id": "A6", "group": "A. Core exposure of India", "query": "What happens to India’s diesel and jet fuel exports to Europe if Gibraltar transit is disrupted?"},
    {"id": "A7", "group": "A. Core exposure of India", "query": "How exposed is India’s LNG supply through the Petronet terminal at Cochin?"},
    {"id": "A8", "group": "A. Core exposure of India", "query": "Which Indian ports are most exposed to the shock, and which are insulated?"},
    {"id": "A9", "group": "A. Core exposure of India", "query": "Which Indian industries are most exposed: automotive, textiles, electronics or fertilizer?"},
    {"id": "A10", "group": "A. Core exposure of India", "query": "Does the crisis cause a shortage or only a delay and a price rise for India’s edible oil imports via Kandla?"},

    # B. Corridors and ports (7)
    {"id": "B1", "group": "B. Corridors and ports", "query": "How much extra transit time would a Suez and Red Sea closure add on the Mumbai–Europe route?"},
    {"id": "B2", "group": "B. Corridors and ports", "query": "Can IMEC (13.5 days versus 32 via the Cape) replace the Cape route for Indian exports to Europe?"},
    {"id": "B3", "group": "B. Corridors and ports", "query": "How exposed is India’s trade with ASEAN and China to disruption in the Strait of Malacca?"},
    {"id": "B4", "group": "B. Corridors and ports", "query": "How exposed are Tirupur textile exports through Tuticorin to the Colombo transshipment hub?"},
    {"id": "B5", "group": "B. Corridors and ports", "query": "What happens to Chennai and Ennore automotive and electronics flows if Malacca is disrupted?"},
    {"id": "B6", "group": "B. Corridors and ports", "query": "How reliable is the INSTC corridor via Chabahar as an alternative to the Gulf route?"},
    {"id": "B7", "group": "B. Corridors and ports", "query": "How exposed are lithium spodumene and coking coal flows from Australia to Vizag and Paradip?"},

    # C. Buffers and mitigation (6)
    {"id": "C1", "group": "C. Buffers and mitigation", "query": "How many days can India’s strategic reserves and commercial stocks cover if Hormuz closes?"},
    {"id": "C2", "group": "C. Buffers and mitigation", "query": "Do discounted Russian Urals imports (1.65M bpd) offset a loss of Gulf crude for India?"},
    {"id": "C3", "group": "C. Buffers and mitigation", "query": "Does the OMIFCO Oman fertilizer line protect India from a Hormuz closure?"},
    {"id": "C4", "group": "C. Buffers and mitigation", "query": "How much does the Western Dedicated Freight Corridor reduce India’s inland logistics exposure?"},
    {"id": "C5", "group": "C. Buffers and mitigation", "query": "Does rupee settlement through SRVA reduce India’s exposure to payment bottlenecks?"},
    {"id": "C6", "group": "C. Buffers and mitigation", "query": "How much do Indian-flagged coastal tankers reduce domestic fuel distribution risk?"},

    # D. Hypotheticals and duration tests (8)
    {"id": "D1", "group": "D. Hypotheticals and duration tests", "query": "What if Hormuz were fully closed for 30 days? What happens to India’s fuel supply?"},
    {"id": "D2", "group": "D. Hypotheticals and duration tests", "query": "What if the Hormuz closure lasted 90 days instead?"},
    {"id": "D3", "group": "D. Hypotheticals and duration tests", "query": "What if the Fujairah ADCOP bypass (1.75M bpd) were also shut?"},
    {"id": "D4", "group": "D. Hypotheticals and duration tests", "query": "What if India’s Russian crude imports stopped tomorrow?"},
    {"id": "D5", "group": "D. Hypotheticals and duration tests", "query": "What if the Colombo hub were closed for two weeks?"},
    {"id": "D6", "group": "D. Hypotheticals and duration tests", "query": "What if the Cape of Good Hope route also became unsafe?"},
    {"id": "D7", "group": "D. Hypotheticals and duration tests", "query": "What if war-risk premiums doubled from 0.85% to 1.7%?"},
    {"id": "D8", "group": "D. Hypotheticals and duration tests", "query": "What if China banned urea exports?"},

    # E. Decoy traps (6)
    {"id": "E1", "group": "E. Decoy traps", "query": "Is the Bab-el-Mandeb Strait closed by sea mines?"},
    {"id": "E2", "group": "E. Decoy traps", "query": "Is the Strait of Malacca blockaded by submarines?"},
    {"id": "E3", "group": "E. Decoy traps", "query": "Are floating mines trapping Mumbai and Kandla ports?"},
    {"id": "E4", "group": "E. Decoy traps", "query": "Is there no nitrogen fertilizer left in the world?"},
    {"id": "E5", "group": "E. Decoy traps", "query": "How exposed is Europe if Bab-el-Mandeb is closed by 400 sea mines?"},
    {"id": "E6", "group": "E. Decoy traps", "query": "Based on a Telegram report, what happens to shipping through Malacca?"},

    # F. Temporal traps (3)
    {"id": "F1", "group": "F. Temporal traps", "query": "What did the Geneva peace treaty change for Gulf shipping risk?"},
    {"id": "F2", "group": "F. Temporal traps", "query": "What did the Q1 2027 WTO audit conclude about trade losses?"},
    {"id": "F3", "group": "F. Temporal traps", "query": "Will the Gulf crisis be over by April 2027?"},

    # G. Unsupported or damaged files (3)
    {"id": "G1", "group": "G. Unsupported or damaged files", "query": "What do the tanker fixtures in the spreadsheet show about freight rates?"},
    {"id": "G2", "group": "G. Unsupported or damaged files", "query": "What do the AIS vessel telemetry records show about tanker traffic in the Gulf?"},
    {"id": "G3", "group": "G. Unsupported or damaged files", "query": "What does the customs manifest say about Indian imports?"},

    # H. Gatekeeper rejection (4)
    {"id": "H1", "group": "H. Gatekeeper rejection", "query": "Who are the keynote speakers at the Global AI Summit 2026?"},
    {"id": "H2", "group": "H. Gatekeeper rejection", "query": "What is the best biryani recipe?"},
    {"id": "H3", "group": "H. Gatekeeper rejection", "query": "Write a Python function that calculates shipping costs."},
    {"id": "H4", "group": "H. Gatekeeper rejection", "query": "Will Indian stock markets rise next week?"},

    # I. Other countries (3)
    {"id": "I1", "group": "I. Other countries", "query": "How exposed are Germany and the Netherlands (Rotterdam) to the crisis, given 71.4% gas storage?"},
    {"id": "I2", "group": "I. Other countries", "query": "How exposed are South Korea and China to the Gulf shock, given their oil stockpiles?"},
    {"id": "I3", "group": "I. Other countries", "query": "Compare the exposure of India and the UAE, given Fujairah and Jebel Ali."}
]

def run_single_benchmark_case(item: Dict[str, Any]) -> Dict[str, Any]:
    qid = item["id"]
    group = item["group"]
    question = item["query"]

    print(f"\n=======================================================")
    print(f"[{qid}] ({group}) Query: {question}")
    print(f"=======================================================", flush=True)

    t0 = time.time()
    state = {
        "case_id": f"CASE-{qid}",
        "question": question
    }

    res = trial_graph.invoke(state)
    elapsed = round(time.time() - t0, 2)

    dismissal = res.get("dismissal_report")
    if dismissal:
        print(f"-> Gatekeeper Dismissed in {elapsed}s: {dismissal.event_status.value} - {dismissal.reasoning[:80]}...", flush=True)
        return {
            "id": qid,
            "group": group,
            "query": question,
            "elapsed_seconds": elapsed,
            "gatekeeper": {
                "outcome": "dismissed",
                "status": dismissal.event_status.value,
                "reasoning": dismissal.reasoning,
                "suggestion": dismissal.suggestion,
                "approved_pool_count": 0,
                "excluded_count": len(dismissal.coverage_found or {})
            },
            "prosecutor": None,
            "defence": None,
            "pairing": None,
            "judge": None,
            "briefing": None,
            "exposure_matrix_active": []
        }

    case_file = res.get("case_file")
    p_claims = res.get("prosecutor_claims", [])
    d_claims = res.get("defence_claims", [])
    threads = res.get("threads", [])
    rulings = res.get("rulings", [])
    briefing = res.get("briefing")
    exp_cells = res.get("exposure_cells", [])

    print(f"-> Finished in {elapsed}s | Status={case_file.event_status.value} | Rulings={len(rulings)} | Headline={getattr(briefing, 'headline', '')}", flush=True)

    return {
        "id": qid,
        "group": group,
        "query": question,
        "elapsed_seconds": elapsed,
        "gatekeeper": {
            "outcome": "approved",
            "status": case_file.event_status.value,
            "as_of_date": case_file.as_of_date,
            "event_summary": case_file.event_summary,
            "target_countries": case_file.target_countries,
            "target_sectors": case_file.target_sectors,
            "target_commodities": case_file.target_commodities,
            "approved_pool_count": len(case_file.approved_pool),
            "excluded_docs_count": len(case_file.excluded_documents),
            "low_coverage": getattr(case_file, "low_coverage", False)
        },
        "prosecutor": {
            "claims_count": len(p_claims),
            "claims": [{"id": c.claim_id, "subject": c.subject, "metric": c.metric, "val": getattr(c.estimate, "value", None), "unit": getattr(c.estimate, "unit", ""), "docs": [e.doc_id for e in c.evidence]} for c in p_claims]
        },
        "defence": {
            "claims_count": len(d_claims),
            "claims": [{"id": c.claim_id, "subject": c.subject, "metric": c.metric, "val": getattr(c.estimate, "value", None), "unit": getattr(c.estimate, "unit", ""), "docs": [e.doc_id for e in c.evidence]} for c in d_claims]
        },
        "pairing": {
            "threads_count": len(threads),
            "unpaired_count": len(res.get("unpaired_claims", []))
        },
        "judge": {
            "rulings_count": len(rulings),
            "rulings": [{"id": r.ruling_id, "thread": r.dispute_thread_id, "verdict": r.ruling.value, "classification": r.classification.value if hasattr(r.classification, 'value') else str(r.classification), "range": f"{getattr(r.accepted_estimate, 'low', None)}–{getattr(r.accepted_estimate, 'high', None)} {getattr(r.accepted_estimate, 'unit', '')}" if r.accepted_estimate else None, "reasoning": r.reasoning} for r in rulings]
        },
        "briefing": {
            "headline": getattr(briefing, "headline", ""),
            "executive_summary": getattr(briefing, "executive_summary", ""),
            "established_count": len(getattr(briefing, "established_findings", []) or []),
            "contested_count": len(getattr(briefing, "contested_findings", []) or []),
            "conceded_count": len(getattr(briefing, "conceded_findings", []) or []),
            "insufficient_count": len(getattr(briefing, "insufficient_findings", []) or [])
        },
        "exposure_matrix_active": [
            {
                "country": getattr(c.country, "value", str(c.country)),
                "sector": getattr(c.sector, "value", str(c.sector)),
                "commodity": getattr(c.commodity, "value", str(c.commodity)),
                "horizon": getattr(c.time_horizon, "value", str(c.time_horizon)),
                "metric": getattr(c.metric, "value", str(c.metric)),
                "direct": c.direct_exposure,
                "mitigated": c.mitigated_exposure,
                "confidence": getattr(c.confidence, "value", str(c.confidence))
            } for c in exp_cells if c.direct_exposure or c.mitigated_exposure
        ]
    }

def main():
    out_file = Path("cases/benchmark_50_results.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    results = []
    if out_file.exists():
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                results = json.load(f)
            print(f"Loaded {len(results)} existing results from {out_file}", flush=True)
        except Exception:
            results = []

    done_ids = {r["id"] for r in results}

    for item in QUERIES_50:
        if item["id"] in done_ids:
            print(f"Skipping already completed {item['id']}", flush=True)
            continue

        try:
            res = run_single_benchmark_case(item)
            results.append(res)
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"ERROR on query {item['id']}: {e}", flush=True)
            import traceback
            traceback.print_exc()
            results.append({
                "id": item["id"],
                "group": item["group"],
                "query": item["query"],
                "error": str(e)
            })
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

        time.sleep(1.0)

    print(f"\n=======================================================", flush=True)
    print(f"BENCHMARK COMPLETE: {len(results)}/50 queries processed.", flush=True)
    print(f"Results saved to: {out_file}", flush=True)
    print(f"=======================================================", flush=True)

if __name__ == "__main__":
    main()
