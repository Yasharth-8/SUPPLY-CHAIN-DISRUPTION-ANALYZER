import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from app.graph.workflow import trial_graph

question = "what happens if mumbai/bombay port closes permanently ?"
print(f"Running query: {question}")
initial_state = {
    "case_id": "TEST-MUMBAI",
    "question": question,
    "run_number": 1
}

res = trial_graph.invoke(initial_state)

print("\n--- RESULTS ---")
print(f"Status: {res.get('status')}")
p_claims = res.get("prosecutor_claims", [])
d_claims = res.get("defence_claims", [])
threads = res.get("threads", [])
unpaired = res.get("unpaired_claims", [])
rulings = res.get("rulings", [])

print(f"\nProsecutor Claims ({len(p_claims)}):")
for c in p_claims:
    print(f"  [{c.claim_id}] {c.geography} | {c.sector} | {c.commodity} | {c.metric} | {c.time_horizon} | val={c.estimate.value} {c.estimate.unit} | {c.subject}")

print(f"\nDefence Claims ({len(d_claims)}):")
for c in d_claims:
    print(f"  [{c.claim_id}] {c.geography} | {c.sector} | {c.commodity} | {c.metric} | {c.time_horizon} | val={c.estimate.value} {c.estimate.unit} | {c.subject}")

print(f"\nDispute Threads ({len(threads)}):")
for t in threads:
    print(f"  [{t.thread_id}] key={t.key} | P={[c.claim_id for c in t.prosecutor_claims]} | D={[c.claim_id for c in t.defence_claims]}")

print(f"\nUnpaired Claims ({len(unpaired)}):")
for c in unpaired:
    print(f"  [{c.claim_id}] ({c.side}) {c.geography} | {c.sector} | {c.commodity} | {c.metric} | {c.time_horizon}")

print(f"\nRulings ({len(rulings)}):")
for r in rulings:
    est_str = f"[{r.accepted_estimate.low}-{r.accepted_estimate.high} {r.accepted_estimate.unit}]" if r.accepted_estimate else "None"
    print(f"  [{r.dispute_thread_id}] {r.ruling.value} ({r.classification.value}) | est={est_str} | {r.reasoning[:80]}...")
