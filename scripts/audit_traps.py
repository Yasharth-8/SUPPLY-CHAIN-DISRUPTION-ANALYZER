import json
from pathlib import Path

results_file = Path("cases/benchmark_50_results.json")
with open(results_file, "r", encoding="utf-8") as f:
    data = json.load(f)

cases_by_id = {c["id"]: c for c in data}

print("=== TRAP GROUP AUDIT ===\n")

# 1. Off-topic queries (H1-H4)
print("1. OFF-TOPIC QUERIES (H1-H4):")
for qid in ["H1", "H2", "H3", "H4"]:
    c = cases_by_id.get(qid)
    if c:
        gk = c.get("gatekeeper", {})
        outcome = gk.get("outcome")
        status = gk.get("status")
        reasoning = (gk.get("reasoning") or "")[:80]
        print(f"  [{qid}] Outcome: {outcome} | Status: {status} | {reasoning}")

# 2. Decoy / Hoax queries (E1-E6)
print("\n2. DECOY HOAX QUERIES (E1-E6):")
for qid in ["E1", "E2", "E3", "E4", "E5", "E6"]:
    c = cases_by_id.get(qid)
    if c:
        gk = c.get("gatekeeper", {})
        status = gk.get("status")
        judge = c.get("judge") or {}
        rulings = judge.get("rulings", [])
        sustained = [r for r in rulings if r.get("verdict") == "sustained"]
        insufficient = [r for r in rulings if r.get("verdict") == "insufficient_evidence"]
        partially = [r for r in rulings if r.get("verdict") == "partially_sustained"]
        print(f"  [{qid}] Status: {status} | Total Rulings: {len(rulings)} | Insufficient: {len(insufficient)} | Partially: {len(partially)} | Sustained: {len(sustained)}")
        for r in rulings[:2]:
            print(f"      - {r.get('thread')}: {r.get('verdict')} | {(r.get('reasoning') or '')[:75]}...")

# 3. Post-cutoff queries (F1-F3)
print("\n3. POST-CUTOFF QUERIES (F1-F3):")
for qid in ["F1", "F2", "F3"]:
    c = cases_by_id.get(qid)
    if c:
        gk = c.get("gatekeeper", {})
        print(f"  [{qid}] Excluded docs count: {gk.get('excluded_docs_count')} | Status: {gk.get('status')}")

# 4. Unsupported files (G1-G3)
print("\n4. UNSUPPORTED / DAMAGED FILES (G1-G3):")
for qid in ["G1", "G2", "G3"]:
    c = cases_by_id.get(qid)
    if c:
        gk = c.get("gatekeeper", {})
        print(f"  [{qid}] Status: {gk.get('status')} | Approved pool: {gk.get('approved_pool_count')} | Error: {c.get('error', 'None')}")
