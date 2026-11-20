"""
Unit Tests for LLMClient: Cooldown Registry, 429 Quota Handling, 503 Retries, and Cascade Failover.
All network calls are mocked for instantaneous offline verification.
"""

import time
import json
import pytest
from unittest.mock import MagicMock, patch
from pydantic import BaseModel

from app.services.llm_client import LLMClient, COOLDOWNS_FILE


class MockOutputModel(BaseModel):
    message: str
    value: int


@pytest.fixture(autouse=True)
def clean_cooldowns(tmp_path):
    """Resets cooldowns and uses temporary cooldown file for isolation."""
    LLMClient._cooldowns.clear()
    test_cooldown_file = tmp_path / "cooldowns.json"
    with patch("app.services.llm_client.COOLDOWNS_FILE", test_cooldown_file):
        yield
    LLMClient._cooldowns.clear()


def test_parse_retry_delay_formats():
    """Verifies parsing of explicit retry delays and midnight Pacific daily quota reset."""
    # Explicit seconds delay
    err1 = "RESOURCE_EXHAUSTED: Please retryDelay: 75"
    assert LLMClient._parse_retry_delay(err1) == 75.0

    err2 = "429 Quota exceeded: retry after 90s"
    assert LLMClient._parse_retry_delay(err2) == 90.0

    err3 = "429: retry in 1h30m"
    assert LLMClient._parse_retry_delay(err3) == 5400.0

    # Per-day quota resets at midnight Pacific Time
    err_daily = "429 Quota exceeded for quota metric 'Generate content requests per day'"
    delay_daily = LLMClient._parse_retry_delay(err_daily)
    assert delay_daily > 60.0
    assert delay_daily <= 86400.0

    # Per-minute default fallback
    err_minute = "RESOURCE_EXHAUSTED: GenerateRequestsPerMinute limit reached"
    assert LLMClient._parse_retry_delay(err_minute) == 65.0


def test_429_sets_cooldown_and_skips_model():
    """Verifies that 429 immediately puts model on cooldown and skips it on subsequent calls."""
    client = LLMClient(api_key="mock_key")
    mock_genai = MagicMock()
    client.client = mock_genai

    target_model = "gemini-3.5-flash-lite"
    fallback_model = "gemini-3.1-flash-lite"

    # Setup mock: target_model raises 429, fallback_model succeeds
    def mock_generate(model, contents, config):
        if model == target_model:
            raise Exception("429 RESOURCE_EXHAUSTED: retryDelay: 120s")
        resp = MagicMock()
        resp.text = json.dumps({"message": "success from fallback", "value": 100})
        return resp

    mock_genai.models.generate_content.side_effect = mock_generate

    with patch("time.sleep"):  # Bypass sleep intervals
        res = client.generate_structured(
            prompt="Hello",
            system_instruction="Follow schema",
            response_model=MockOutputModel,
            model_name=target_model,
        )

    # Assertions
    assert res.message == "success from fallback"
    assert client.last_model_used == fallback_model
    assert LLMClient.is_cooling_down(target_model) is True

    # Call again: target_model should be skipped completely from active chain
    mock_genai.models.generate_content.reset_mock()
    with patch("time.sleep"):
        res2 = client.generate_structured(
            prompt="Hello 2",
            system_instruction="Follow schema",
            response_model=MockOutputModel,
            model_name=target_model,
        )

    assert res2.message == "success from fallback"
    # Verify target_model was NEVER called because it was in cooldown
    called_models = [call.kwargs.get("model") for call in mock_genai.models.generate_content.call_args_list]
    assert target_model not in called_models
    assert fallback_model in called_models


def test_503_retries_exactly_three_times_before_cooldown():
    """Verifies that 503 retries on the same model exactly 3 times before setting 45s cooldown."""
    client = LLMClient(api_key="mock_key")
    mock_genai = MagicMock()
    client.client = mock_genai

    target_model = "gemini-3.5-flash-lite"
    next_model = "gemini-3.1-flash-lite"

    call_counts = {target_model: 0, next_model: 0}

    def mock_generate(model, contents, config):
        call_counts[model] = call_counts.get(model, 0) + 1
        if model == target_model:
            raise Exception("503 UNAVAILABLE: high demand")
        resp = MagicMock()
        resp.text = json.dumps({"message": "recovered by next model", "value": 200})
        return resp

    mock_genai.models.generate_content.side_effect = mock_generate

    sleep_calls = []
    with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        res = client.generate_structured(
            prompt="Test 503",
            system_instruction="Follow schema",
            response_model=MockOutputModel,
            model_name=target_model,
        )

    # Target model should have been attempted exactly 3 times (attempt 1, retry 1, retry 2)
    assert call_counts[target_model] == 3
    # Next model should have been called and succeeded
    assert call_counts[next_model] == 1
    assert res.message == "recovered by next model"
    assert client.last_model_used == next_model
    # Target model should now be cooling down for ~45 seconds
    assert LLMClient.is_cooling_down(target_model) is True


def test_cascade_exhaustion_activates_fallback():
    """Verifies that when all models fail, grounded fallback is returned and last_model_used is 'fallback'."""
    client = LLMClient(api_key="mock_key")
    mock_genai = MagicMock()
    client.client = mock_genai

    # All models fail with 429
    def mock_generate(model, contents, config):
        raise Exception("429 RESOURCE_EXHAUSTED: per day limit reached")

    mock_genai.models.generate_content.side_effect = mock_generate

    with patch("time.sleep"):
        res = client.generate_structured(
            prompt="All fail",
            system_instruction="Follow schema",
            response_model=MockOutputModel,
            model_name="gemini-3.5-flash-lite",
        )

    # Fallback default construct
    assert res is not None
    assert client.last_model_used == "fallback"


def test_cooldown_expiration():
    """Verifies that expired cooldowns allow the model to be called again."""
    model = "gemini-test-expiring"
    # Set cooldown in the past
    LLMClient._cooldowns[model] = time.time() - 5.0
    assert LLMClient.is_cooling_down(model) is False

    # Set active cooldown
    LLMClient.set_cooldown(model, 60.0)
    assert LLMClient.is_cooling_down(model) is True


def test_cooldown_disk_persistence(tmp_path):
    """Verifies that cooldowns persist to disk and survive reloads."""
    temp_file = tmp_path / "test_cooldowns.json"
    with patch("app.services.llm_client.COOLDOWNS_FILE", temp_file):
        LLMClient.set_cooldown("model-alpha", 300.0, reason="test persist")
        assert temp_file.exists()

        # Clear in-memory dict to simulate restart / reload
        LLMClient._cooldowns.clear()

        # is_cooling_down should load from disk
        assert LLMClient.is_cooling_down("model-alpha") is True
        assert "model-alpha" in LLMClient._cooldowns

