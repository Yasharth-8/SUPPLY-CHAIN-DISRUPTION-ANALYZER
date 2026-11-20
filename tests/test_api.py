"""
API Integration Tests: Validates FastAPI routes, feed, and case lifecycle.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_feed_endpoint(client):
    res = client.get("/api/feed")
    assert res.status_code == 200
    feed = res.json()
    assert isinstance(feed, list)
    assert len(feed) > 0
    first = feed[0]
    assert "doc_id" in first
    assert "tier" in first


def test_doc_detail_endpoint(client):
    res = client.get("/api/docs/CRX-1004")
    assert res.status_code == 200
    doc = res.json()
    assert doc["doc_id"] == "CRX-1004"
    assert "Fujairah" in doc["title"]


def test_submit_case_and_status(client, monkeypatch):
    from unittest.mock import AsyncMock
    import app.routers.case_router as router_mod
    monkeypatch.setattr(router_mod, "_run_workflow_async", AsyncMock())

    payload = {"question": "What is the crude oil exposure if the Strait of Hormuz is blocked?"}
    res = client.post("/api/case/submit", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "case_id" in data
    case_id = data["case_id"]

    status_res = client.get(f"/api/case/{case_id}/status")
    assert status_res.status_code == 200
    assert status_res.json()["status"] in ("submitted", "processing", "completed")

