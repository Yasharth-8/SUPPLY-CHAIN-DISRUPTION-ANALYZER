"""
LangGraph Workflow: Compiles the 4-Agent Court Case StateGraph with Delta Loops.
No central planner or supervisor: edges define flow, agents argue independently, Judge only rules.
"""

from typing import Dict, Any, List
from langgraph.graph import StateGraph, END

from app.graph.state import TrialState
from app.graph.nodes.gatekeeper import GatekeeperNode
from app.graph.nodes.prosecutor import ProsecutorNode
from app.graph.nodes.defence import DefenceNode
from app.graph.nodes.judge import JudgeNode
from app.services.court_services import CourtServices
from app.services.exposure_service import ExposureService
from app.services.briefing_renderer import BriefingRenderer
from app.constants import MAX_RUNS


# Node instances
gk_node = GatekeeperNode()
pros_node = ProsecutorNode()
def_node = DefenceNode()
judge_node = JudgeNode()
exposure_service = ExposureService()
briefing_renderer = BriefingRenderer()


def intake_node(state: TrialState) -> Dict[str, Any]:
    """Gatekeeper intake, verification, and pool building."""
    case_id = state.get("case_id", "CASE-001")
    question = state.get("question", "")
    print(f"\n[Gatekeeper] Examining case intake for: '{question[:60]}...'")

    case_file, dismissal, ev_svc, search_svc = gk_node.run(question=question, case_id=case_id)

    if dismissal:
        print(f"[Gatekeeper] Case dismissed: {dismissal.event_status.value} - {dismissal.reasoning}")
        return {
            "case_id": case_id,
            "dismissal_report": dismissal,
            "status": "dismissed",
            "evidence_cards": ev_svc.evidence_cards,
        }

    print(f"[Gatekeeper] Case approved! Status: {case_file.event_status.value}. Approved pool: {len(case_file.approved_pool)} cards.")
    return {
        "case_id": case_id,
        "case_file": case_file,
        "evidence_cards": ev_svc.evidence_cards,
        "status": "intake_approved",
        "run_number": 1,
    }


def gatekeeper_conditional(state: TrialState) -> str:
    """Branches: if dismissed -> END, else -> round1."""
    if state.get("dismissal_report") is not None:
        return "dismissed"
    return "proceed_to_round1"


def round1_node(state: TrialState) -> Dict[str, Any]:
    """Runs Prosecutor R1 and Defence R1 concurrently with strict adversarial isolation."""
    print("[Round 1] Prosecutor & Defence generating adversarial claims...")
    import concurrent.futures
    from app.services.search import SearchService
    case_file = state["case_file"]
    cards = list(state["evidence_cards"].values())
    search_svc = SearchService(cards)

    # Run both advocates concurrently in worker threads with timeout guard
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_pros = executor.submit(pros_node.run_round1, case_file=case_file, search_service=search_svc, max_claims=5)
        f_def = executor.submit(def_node.run_round1, case_file=case_file, search_service=search_svc, max_claims=5)
        try:
            pros_out = f_pros.result(timeout=45.0)
        except Exception as e:
            print(f"[Round 1] Prosecutor thread timed out or encountered error: {e}. Recovering.")
            from app.graph.nodes.prosecutor import ProsecutorRound1Output
            pros_out = ProsecutorRound1Output(claims=[])
        try:
            def_out = f_def.result(timeout=45.0)
        except Exception as e:
            print(f"[Round 1] Defence thread timed out or encountered error: {e}. Recovering.")
            from app.graph.nodes.defence import DefenceRound1Output
            def_out = DefenceRound1Output(claims=[])

    print(f"[Round 1] Submitted: Prosecutor {len(pros_out.claims)} claims, Defence {len(def_out.claims)} claims.")

    # Track degradation states: full vs partial
    pros_degraded = any(c.claim_id.startswith("P-00") for c in pros_out.claims) or pros_node.llm.last_model_used == "fallback"
    def_degraded = any(c.claim_id.startswith("D-00") for c in def_out.claims) or def_node.llm.last_model_used == "fallback"

    if pros_degraded and def_degraded:
        is_degraded = True
        is_partial_degraded = False
        degraded_reason = "Both advocates operating under grounded documentary fallback due to model cooldowns."
    elif pros_degraded or def_degraded:
        is_degraded = False
        is_partial_degraded = True
        side_name = "Prosecutor" if pros_degraded else "Defence"
        degraded_reason = f"{side_name} operated under grounded documentary fallback due to rate limits."
    else:
        is_degraded = False
        is_partial_degraded = False
        degraded_reason = None

    return {
        "prosecutor_claims": pros_out.claims,
        "defence_claims": def_out.claims,
        "is_degraded": is_degraded,
        "is_partial_degraded": is_partial_degraded,
        "degraded_reason": degraded_reason,
        "status": "round1_completed",
    }


def court_services_pass1_node(state: TrialState) -> Dict[str, Any]:
    """CourtServices Pass 1: Citation validation and Claim Pairing into DisputeThreads."""
    print("[Court Services Pass 1] Validating documentary citations & pairing claims...")
    cards = state["evidence_cards"]
    court = CourtServices(approved_cards=cards, raw_docs=gk_node.loader.__dict__.get("_cached_docs", {}))

    p_claims = state.get("prosecutor_claims", [])
    d_claims = state.get("defence_claims", [])

    # Scope enforcement: reject off-topic claims (e.g. oil claims during fertilizer inquiry)
    case_file = state.get("case_file")
    p_claims, rejected_p = court.filter_off_scope_claims(p_claims, case_file)
    d_claims, rejected_d = court.filter_off_scope_claims(d_claims, case_file)

    # Validate citations
    for c in p_claims + d_claims:
        court.validate_citation(c)

    # Pair into threads
    threads, unpaired = court.pair_claims(p_claims, d_claims)
    print(f"[Court Services Pass 1] Formed {len(threads)} paired dispute threads ({len(unpaired)} unpaired).")

    return {
        "prosecutor_claims": p_claims,
        "defence_claims": d_claims,
        "threads": threads,
        "unpaired_claims": unpaired,
        "status": "paired",
    }


def round2_node(state: TrialState) -> Dict[str, Any]:
    """Runs Prosecutor R2 and Defence R2 concurrently: rebut, narrow, contextualize, concede."""
    print("[Round 2] Exchanging claims for rebuttals, narrowing, contextualizing, or concessions...")
    import concurrent.futures
    from app.services.search import SearchService
    case_file = state["case_file"]
    cards = list(state["evidence_cards"].values())
    search_svc = SearchService(cards)

    p_claims = state.get("prosecutor_claims", [])
    d_claims = state.get("defence_claims", [])

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_pros = executor.submit(
            pros_node.run_round2,
            case_file=case_file,
            prosecutor_claims=p_claims,
            opposing_claims=d_claims,
            search_service=search_svc
        )
        f_def = executor.submit(
            def_node.run_round2,
            case_file=case_file,
            defence_claims=d_claims,
            opposing_claims=p_claims,
            search_service=search_svc
        )
        try:
            pros_r2 = f_pros.result(timeout=45.0)
        except Exception as e:
            print(f"[Round 2] Prosecutor rebuttal thread timed out or error: {e}.")
            from app.graph.nodes.prosecutor import ProsecutorRound2Output
            pros_r2 = ProsecutorRound2Output(responses=[])
        try:
            def_r2 = f_def.result(timeout=45.0)
        except Exception as e:
            print(f"[Round 2] Defence rebuttal thread timed out or error: {e}.")
            from app.graph.nodes.defence import DefenceRound2Output
            def_r2 = DefenceRound2Output(responses=[])

    print(f"[Round 2] Completed: Prosecutor {len(pros_r2.responses)} responses, Defence {len(def_r2.responses)} responses.")

    return {
        "prosecutor_responses": pros_r2.responses,
        "defence_responses": def_r2.responses,
        "status": "round2_completed",
    }


def court_services_pass2_node(state: TrialState) -> Dict[str, Any]:
    """CourtServices Pass 2: Silence check and rebuttal validation."""
    print("[Court Services Pass 2] Running deterministic silence check on material claims...")
    cards = state["evidence_cards"]
    court = CourtServices(approved_cards=cards)

    p_claims = state.get("prosecutor_claims", [])
    d_claims = state.get("defence_claims", [])
    p_resp = state.get("prosecutor_responses", [])
    d_resp = state.get("defence_responses", [])

    unanswered_d = court.check_silence(d_claims, p_resp)
    unanswered_p = court.check_silence(p_claims, d_resp)

    return {
        "unanswered_material": unanswered_d + unanswered_p,
        "status": "ready_for_judge",
    }


def judge_adjudication_node(state: TrialState) -> Dict[str, Any]:
    """The Bench rules on every thread, checks sufficiency, notes engagement."""
    print("[The Bench] Adjudicating claims under burden of proof standards...")
    threads = state.get("threads", [])
    unpaired = state.get("unpaired_claims", [])
    unanswered = state.get("unanswered_material", [])
    case_file = state.get("case_file")
    cards = state.get("evidence_cards", {})
    p_resp = state.get("prosecutor_responses", [])
    d_resp = state.get("defence_responses", [])

    judge_out = judge_node.rule_threads(
        threads=threads,
        unpaired_claims=unpaired,
        unanswered_material=unanswered,
        case_file=case_file,
        evidence_cards=cards,
        prosecutor_responses=p_resp,
        defence_responses=d_resp
    )
    print(f"[The Bench] Delivered {len(judge_out.rulings)} rulings. Sufficiency: {judge_out.is_sufficient}.")

    return {
        "threads": judge_out.threads,
        "rulings": judge_out.rulings,
        "gaps": judge_out.material_gaps,
        "is_sufficient": judge_out.is_sufficient,
        "status": "adjudicated",
    }


def judge_conditional(state: TrialState) -> str:
    """Branches: if sufficient or max runs reached -> exposure; only remand to delta if genuine new evidence is found."""
    run_num = state.get("run_number", 1)
    is_suff = state.get("is_sufficient", True)
    gaps = state.get("gaps", [])

    if is_suff or run_num >= MAX_RUNS or not gaps:
        return "proceed_to_exposure"

    # Check if there are genuine unsearched material gaps that could find new repository documents
    unsearched_gaps = [g for g in gaps if not getattr(g, "already_searched", False)]
    if not unsearched_gaps:
        print("[Workflow] Gaps noted by The Bench, but all repository documents have already been admitted to the case pool. Proceeding to exposure without a wasted duplicate pass.")
        return "proceed_to_exposure"

    # In the closed repository, the initial intake loads all eligible cards. Unless a new document pool is mounted, proceed to exposure.
    print("[Workflow] No additional unsearched external evidence available in repository for reported gaps. Proceeding directly to exposure with honest gap reporting.")
    return "proceed_to_exposure"


def delta_re_search_node(state: TrialState) -> Dict[str, Any]:
    """Re-search on Judge material gaps for delta run."""
    run_num = state.get("run_number", 1)
    gaps = state.get("gaps", [])
    for g in gaps:
        g.already_searched = True

    return {
        "run_number": run_num + 1,
        "gaps": gaps,
        "status": "delta_run",
    }


def exposure_calculation_node(state: TrialState) -> Dict[str, Any]:
    """Computes time-bounded exposure matrix from accepted rulings."""
    rulings = state.get("rulings", [])
    threads = state.get("threads", [])

    cells = exposure_service.compute_exposure_matrix(rulings=rulings, threads=threads)
    return {
        "exposure_cells": cells,
        "status": "exposure_calculated",
    }


def briefing_node(state: TrialState) -> Dict[str, Any]:
    """Renders final briefing from rulings only."""
    case_file = state["case_file"]
    rulings = state.get("rulings", [])
    cells = state.get("exposure_cells", [])
    p_claims = state.get("prosecutor_claims", [])
    d_claims = state.get("defence_claims", [])
    cards = state.get("evidence_cards", {})

    briefing = briefing_renderer.render_briefing(
        case_file=case_file,
        rulings=rulings,
        exposure_cells=cells,
        all_claims=p_claims + d_claims,
        evidence_cards=cards,
        is_degraded=state.get("is_degraded", False),
        is_partial_degraded=state.get("is_partial_degraded", False),
        degraded_reason=state.get("degraded_reason"),
        ruling_models=list({r.model_used for r in rulings if getattr(r, "model_used", None)})
    )
    return {
        "briefing": briefing,
        "status": "completed",
    }


def build_trial_graph():
    """Builds and compiles the StateGraph."""
    builder = StateGraph(TrialState)

    builder.add_node("intake", intake_node)
    builder.add_node("round1", round1_node)
    builder.add_node("court_pass1", court_services_pass1_node)
    builder.add_node("round2", round2_node)
    builder.add_node("court_pass2", court_services_pass2_node)
    builder.add_node("judge", judge_adjudication_node)
    builder.add_node("delta_re_search", delta_re_search_node)
    builder.add_node("exposure", exposure_calculation_node)
    builder.add_node("briefing", briefing_node)

    builder.set_entry_point("intake")

    builder.add_conditional_edges(
        "intake",
        gatekeeper_conditional,
        {
            "dismissed": END,
            "proceed_to_round1": "round1",
        }
    )

    builder.add_edge("round1", "court_pass1")
    builder.add_edge("court_pass1", "round2")
    builder.add_edge("round2", "court_pass2")
    builder.add_edge("court_pass2", "judge")

    builder.add_conditional_edges(
        "judge",
        judge_conditional,
        {
            "proceed_to_exposure": "exposure",
            "remand_to_delta": "delta_re_search",
        }
    )

    builder.add_edge("delta_re_search", "court_pass1")
    builder.add_edge("exposure", "briefing")
    builder.add_edge("briefing", END)

    return builder.compile()


# Compiled singleton graph
trial_graph = build_trial_graph()

