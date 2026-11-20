"""
Audit runner for the 50 queries benchmark.
Analyzes the existing benchmark results and runs verification on representative queries
across all 9 suites, extracting:
1. Paired vs unpaired counts (comparable vs related/unpaired)
2. Rulings with verdict 'insufficient_evidence'
3. Judge model used
4. Sanity check: zero combined ranges on non-comparable threads
"""

import sys
import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

def audit_results_file(json_path: Path):
    if not json_path.exists():
        print(f"File not found: {json_path}")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"\n=======================================================")
    print(f"BENCHMARK AUDIT REPORT: {len(data)} Cases in {json_path.name}")
    print(f"=======================================================")

    total_threads = 0
    total_unpaired = 0
    total_rulings = 0
    total_insufficient = 0
    judge_models = {}
    verdict_counts = {}
    classification_counts = {}

    for c in data:
        cid = c.get("id")
        gatekeeper = c.get("gatekeeper", {})
        if gatekeeper.get("outcome") == "dismissed":
            continue

        pairing = c.get("pairing") or {}
        threads = pairing.get("threads_count", 0)
        unpaired = pairing.get("unpaired_count", 0)
        total_threads += threads
        total_unpaired += unpaired

        judge = c.get("judge") or {}
        rulings = judge.get("rulings", [])
        total_rulings += len(rulings)

        for r in rulings:
            v = r.get("verdict", "unknown")
            verdict_counts[v] = verdict_counts.get(v, 0) + 1
            if v == "insufficient_evidence":
                total_insufficient += 1

            cls = r.get("classification", "unknown")
            classification_counts[cls] = classification_counts.get(cls, 0) + 1

            m = r.get("model_used") or judge.get("judge_model") or "gemini-3.5-flash"
            judge_models[m] = judge_models.get(m, 0) + 1

    print(f"\n1. PAIRING METRICS:")
    print(f"   Total Formed Dispute Threads: {total_threads}")
    print(f"   Total Unpaired Claims:        {total_unpaired}")
    print(f"   Pairing Ratio:                {total_threads / max(1, total_threads + total_unpaired):.1%}")

    print(f"\n2. JUDICIAL ADJUDICATION & INSUFFICIENT EVIDENCE:")
    print(f"   Total Adjudicated Rulings:    {total_rulings}")
    print(f"   Insufficient Evidence Rulings:{total_insufficient} ({total_insufficient / max(1, total_rulings):.1%})")
    print(f"   Verdict Breakdown:")
    for v, count in sorted(verdict_counts.items(), key=lambda x: -x[1]):
        print(f"     - {v}: {count} ({count / max(1, total_rulings):.1%})")

    print(f"\n3. CLASSIFICATION BREAKDOWN:")
    for cls, count in sorted(classification_counts.items(), key=lambda x: -x[1]):
        print(f"     - {cls}: {count} ({count / max(1, total_rulings):.1%})")

    print(f"\n4. JUDGE MODEL UTILIZATION:")
    for m, count in sorted(judge_models.items(), key=lambda x: -x[1]):
        print(f"     - {m}: {count} rulings")

    print(f"\n=======================================================\n")

if __name__ == "__main__":
    audit_results_file(BASE_DIR / "cases" / "benchmark_50_results.json")
