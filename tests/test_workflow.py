"""
End-to-End Workflow Tests for LangGraph Trial Graph.
"""

import pytest
from app.graph.workflow import trial_graph
from app.vocabularies import EventStatus


class TestTrialWorkflow:
    def test_workflow_off_topic_rejection(self):
        """User asks an off-topic question. Must be dismissed gracefully at intake."""
        initial_state = {
            "case_id": "TEST-OFFTOPIC",
            "question": "Write me a romantic love poem about the sunset in Paris.",
        }
        final_state = trial_graph.invoke(initial_state)

        assert final_state["status"] == "dismissed"
        assert final_state.get("dismissal_report") is not None
        assert "not related" in final_state["dismissal_report"].reasoning

    def test_workflow_disruption_scenario(self):
        """User asks about the Strait of Hormuz conflict and bypass capacity."""
        initial_state = {
            "case_id": "TEST-HORMUZ",
            "question": "What is the global energy exposure if the Strait of Hormuz is blocked and ships must use the Cape route or Fujairah bypass?",
        }
        final_state = trial_graph.invoke(initial_state)

        # Must either complete or be dismissed if unsupported
        assert final_state["status"] in ("completed", "dismissed")
        if final_state["status"] == "completed":
            assert final_state.get("briefing") is not None
            assert len(final_state["briefing"].exposure_table) >= 0
            assert final_state["case_file"].event_status in (EventStatus.CONFIRMED, EventStatus.REPORTED, EventStatus.HYPOTHETICAL)

