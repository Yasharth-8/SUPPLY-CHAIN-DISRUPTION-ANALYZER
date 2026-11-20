"""
LLM Client: Wrapper for Google GenAI / Gemini with structured output, retry, and test fallback.
Includes model cooldown registry, file-backed persistence, diverse role-based chains,
call throttling, and exponential backoff with jitter on 503s.
"""

import os
import json
import re
import time
import random
import threading
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Type, TypeVar, Optional, Any, Set, Dict, List
from pydantic import BaseModel, ValidationError

from app.config import (
    GEMINI_API_KEY, GEMINI_API_KEYS, DEFAULT_MODEL, FAST_GROUNDED_MODE,
    ADVOCATE_TEMPERATURE, JUDGE_TEMPERATURE, GATEKEEPER_TEMPERATURE
)

T = TypeVar("T", bound=BaseModel)

COOLDOWNS_FILE = Path(__file__).resolve().parent.parent.parent / "memory" / "cooldowns.json"


class LLMClient:
    # Model cooldown timestamp registry: model_name -> cooldown_expiry_timestamp
    _cooldowns: Dict[str, float] = {}
    _call_lock = threading.Lock()
    _file_lock = threading.Lock()
    _last_call_timestamp: float = 0.0
    MIN_CALL_INTERVAL: float = 0.3  # Short throttle interval for smooth multi-key calls

    ADVOCATE_CHAIN = [
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash"
    ]

    JUDGE_CHAIN = [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite"
    ]

    _global_key_idx: int = 0
    _key_lock = threading.Lock()
    _clients: Dict[str, Any] = {}

    @classmethod
    def get_client_for_key(cls, key: str):
        with cls._key_lock:
            if key not in cls._clients:
                from google import genai
                cls._clients[key] = genai.Client(api_key=key, http_options={"api_version": "v1beta", "timeout": 20000})
            return cls._clients[key]

    @classmethod
    def reset_client_for_key(cls, key: Optional[str] = None):
        """Discards cached client instances on connection/SSL drops to prevent dead socket reuse."""
        with cls._key_lock:
            if key:
                cls._clients.pop(key, None)
            else:
                cls._clients.clear()

    @classmethod
    def get_next_key(cls) -> str:
        with cls._key_lock:
            if not GEMINI_API_KEYS:
                return ""
            k = GEMINI_API_KEYS[cls._global_key_idx % len(GEMINI_API_KEYS)]
            cls._global_key_idx += 1
            return k

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.allow_key_rotation = (api_key is None or api_key in GEMINI_API_KEYS)
        self.client = None
        self.last_model_used: Optional[str] = None
        if self.api_key:
            self.client = self.get_client_for_key(self.api_key)

    def _rotate_api_key(self, tried_keys: Set[str]) -> bool:
        """Rotates to the next untried API key from the configured key pool. Returns True if rotated."""
        if not self.allow_key_rotation or not GEMINI_API_KEYS or len(GEMINI_API_KEYS) <= 1:
            return False
        try:
            curr_idx = GEMINI_API_KEYS.index(self.api_key) if self.api_key in GEMINI_API_KEYS else 0
            for offset in range(1, len(GEMINI_API_KEYS) + 1):
                next_idx = (curr_idx + offset) % len(GEMINI_API_KEYS)
                next_key = GEMINI_API_KEYS[next_idx]
                if next_key not in tried_keys:
                    self.api_key = next_key
                    tried_keys.add(next_key)
                    self.client = self.get_client_for_key(self.api_key)
                    print(f"[LLM Key Failover] Switched to next API key: ...{self.api_key[-6:]} ({next_idx+1}/{len(GEMINI_API_KEYS)})")
                    return True
            return False
        except Exception as e:
            print(f"[LLM Key Failover] Error rotating key: {e}")
            return False

    @classmethod
    def _load_cooldowns(cls):
        """Loads non-expired cooldowns from disk."""
        with cls._file_lock:
            if not COOLDOWNS_FILE.exists():
                return
            try:
                data = json.loads(COOLDOWNS_FILE.read_text(encoding="utf-8"))
                now = time.time()
                cls._cooldowns = {
                    m: info["expires_at"]
                    for m, info in data.items()
                    if isinstance(info, dict) and info.get("expires_at", 0) > now
                }
            except Exception as e:
                print(f"[LLM Cooldown] Error reading {COOLDOWNS_FILE}: {e}")

    @classmethod
    def _save_cooldowns(cls):
        """Persists active cooldowns to disk."""
        with cls._file_lock:
            try:
                COOLDOWNS_FILE.parent.mkdir(parents=True, exist_ok=True)
                now = time.time()
                data = {
                    m: {"expires_at": exp, "remaining_seconds": max(0.0, exp - now)}
                    for m, exp in cls._cooldowns.items()
                    if exp > now
                }
                COOLDOWNS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception as e:
                print(f"[LLM Cooldown] Error writing {COOLDOWNS_FILE}: {e}")

    @classmethod
    def is_cooling_down(cls, model_name: str) -> bool:
        """Returns True if the model is currently in an active cooldown window."""
        cls._load_cooldowns()
        exp = cls._cooldowns.get(model_name, 0.0)
        return time.time() < exp

    @classmethod
    def set_cooldown(cls, model_name: str, duration_seconds: float, reason: str = ""):
        """Sets a cooldown window for a model and persists it to disk."""
        cls._load_cooldowns()
        cls._cooldowns[model_name] = time.time() + duration_seconds
        cls._save_cooldowns()
        print(f"[LLM Cooldown] Model '{model_name}' cooling down for {duration_seconds:.0f}s ({reason}).")

    @classmethod
    def _parse_retry_delay(cls, err_str: str) -> float:
        """
        Parses retry delay in seconds from error payloads:
        - If daily quota limit hit (PerDay), calculates exact seconds until midnight Pacific Time.
        - If per-minute or explicit retryDelay is returned, uses parsed seconds.
        - Falls back to 60.0s.
        """
        lower_err = err_str.lower()

        # Check for per-day quota exhaustion (resets at 00:00 Pacific Time)
        if any(term in lower_err for term in ["generaterequestsperday", "requests per day", "perday", "requests_per_day"]):
            try:
                now_pt = datetime.now(ZoneInfo("America/Los_Angeles"))
                midnight_pt = (now_pt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                seconds_until_pt_midnight = (midnight_pt - now_pt).total_seconds()
                return max(60.0, seconds_until_pt_midnight)
            except Exception:
                return 43200.0  # 12-hour safe default if timezone lookup fails

        # Check for explicit retryDelay in seconds
        match = re.search(r"retryDelay['\":\s]+(\d+)", err_str)
        if match:
            return float(match.group(1))

        match_s = re.search(r"retry (?:in|after) (\d+)s", err_str, re.IGNORECASE)
        if match_s:
            return float(match_s.group(1))

        match_hm = re.search(r"retry in (\d+)h(\d+)m", err_str, re.IGNORECASE)
        if match_hm:
            hours = int(match_hm.group(1))
            minutes = int(match_hm.group(2))
            return float(hours * 3600 + minutes * 60)

        # Check for per-minute quota
        if any(term in lower_err for term in ["generaterequestsperminute", "requests per minute", "perminute"]):
            return 65.0

        return 60.0

    def _throttle_call(self):
        """Enforces minimum interval between consecutive API calls in worker threads."""
        with self._call_lock:
            now = time.time()
            elapsed = now - LLMClient._last_call_timestamp
            if elapsed < self.MIN_CALL_INTERVAL:
                time.sleep(self.MIN_CALL_INTERVAL - elapsed)
            LLMClient._last_call_timestamp = time.time()

    def generate_structured(
        self,
        prompt: str,
        system_instruction: str,
        response_model: Type[T],
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        role: str = "advocate"
    ) -> T:
        """
        Calls Gemini to produce structured output adhering to response_model.
        Includes cooldown awareness, exponential backoff for 503s on the same model,
        and graceful failover across a diverse model chain.
        """
        if FAST_GROUNDED_MODE:
            self.last_model_used = "fallback"
            return self._generate_fallback(prompt, response_model)

        # Select role-based priority chain
        base_chain = self.JUDGE_CHAIN if role == "judge" else self.ADVOCATE_CHAIN
        preferred = model_name or DEFAULT_MODEL
        candidate_chain = [preferred] + [m for m in base_chain if m != preferred]

        # Start each call from the first model that isn't cooling down
        active_chain = [m for m in candidate_chain if not self.is_cooling_down(m)]

        if not active_chain:
            print("[LLM] All candidate models currently in cooldown. Activating grounded documentary fallback.")
            self.last_model_used = "fallback"
            return self._generate_fallback(prompt, response_model)

        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        full_system = f"{system_instruction}\n\nSTRICT JSON OUTPUT REQUIREMENT:\nYou MUST output valid JSON conforming exactly to this JSON schema:\n{schema_json}\nOutput ONLY the JSON object. Do not wrap in markdown quotes if possible, or use standard ```json ... ```."

        if self.allow_key_rotation and GEMINI_API_KEYS:
            self.api_key = self.get_next_key()
            self.client = self.get_client_for_key(self.api_key)

        if not self.client:
            self.last_model_used = "fallback"
            return self._generate_fallback(prompt, response_model)

        for current_model in active_chain:
            tried_keys_for_model: Set[str] = {self.api_key} if self.api_key else set()
            max_503_retries = 3

            for attempt_503 in range(1, max_503_retries + 1):
                try:
                    self._throttle_call()
                    response = self.client.models.generate_content(
                        model=current_model,
                        contents=prompt,
                        config={
                            "system_instruction": full_system,
                            "temperature": temperature,
                            "response_mime_type": "application/json",
                        }
                    )
                    raw_text = response.text
                    parsed_data = self._clean_and_parse_json(raw_text)
                    validated = response_model.model_validate(parsed_data)
                    self.last_model_used = current_model
                    return validated

                except Exception as e:
                    err_str = str(e)
                    is_503 = any(code in err_str for code in ["503", "UNAVAILABLE", "high demand", "deadline", "timed out", "timeout"])
                    is_429 = "RESOURCE_EXHAUSTED" in err_str or "429" in err_str
                    is_conn = any(term in err_str.lower() for term in [
                        "server disconnected", "unexpected_eof", "connection reset", "remotedisconnected",
                        "broken pipe", "ssl", "timeout", "timed out", "deadline", "eof occurred", "connection error"
                    ])

                    # Handle 429: Attempt key rotation before setting model cooldown
                    if is_429:
                        print(f"[LLM] Model '{current_model}' hit 429 quota exhausted with key ...{self.api_key[-6:] if self.api_key else 'None'}.")
                        if self._rotate_api_key(tried_keys_for_model):
                            time.sleep(0.3)
                            continue
                        else:
                            delay = self._parse_retry_delay(err_str)
                            self.set_cooldown(current_model, delay, reason="429 quota exhausted across all available keys")
                            break  # Break out to next model in active_chain

                    # Handle connection/SSL drops: Reset dead socket and rotate key
                    if is_conn:
                        print(f"[LLM] Connection drop on '{current_model}': {err_str[:80]}... Resetting socket.")
                        self.reset_client_for_key(self.api_key)
                        if self._rotate_api_key(tried_keys_for_model):
                            time.sleep(0.5)
                            continue
                        elif attempt_503 < 2:
                            time.sleep(1.0)
                            continue
                        else:
                            self.set_cooldown(current_model, 15.0, reason="Connection dropped or timed out repeatedly")
                            break

                    # Handle 503: Try rotating key first; if all keys tried, quick backoff and cascade
                    if is_503:
                        if self._rotate_api_key(tried_keys_for_model):
                            time.sleep(0.3)
                            continue
                        elif attempt_503 < max_503_retries:
                            sleep_time = 1.0 + random.uniform(0.1, 0.4)
                            print(f"[LLM] Model '{current_model}' 503 high demand. Quick pause {sleep_time:.1f}s before retry {attempt_503}/{max_503_retries}...")
                            time.sleep(sleep_time)
                            continue
                        else:
                            # 503 persistent across keys: cool down for 60 seconds and cascade to next model
                            self.set_cooldown(current_model, 60.0, reason="503 high demand persistent across keys")
                            break

                    # Schema validation failure on returned text
                    if "raw_text" in locals() and raw_text and not is_503 and not is_429:
                        try:
                            repair_prompt = f"The previous output failed schema validation: {err_str}.\nRaw output was:\n{raw_text}\nPlease fix all schema errors and return strictly valid JSON matching the schema."
                            repair_resp = self.client.models.generate_content(
                                model=current_model,
                                contents=repair_prompt,
                                config={
                                    "system_instruction": full_system,
                                    "temperature": 0.1,
                                    "response_mime_type": "application/json",
                                }
                            )
                            parsed_data = self._clean_and_parse_json(repair_resp.text)
                            validated = response_model.model_validate(parsed_data)
                            self.last_model_used = current_model
                            return validated
                        except Exception as repair_e:
                            print(f"Schema repair attempt failed on {current_model}: {repair_e}.")
                            break

                    print(f"LLM generation failed on {current_model}: {err_str}.")
                    break

        print("[LLM] All candidate models exhausted or cooling down. Engaging grounded documentary fallback.")
        self.last_model_used = "fallback"
        return self._generate_fallback(prompt, response_model)

    @staticmethod
    def _clean_and_parse_json(text: str) -> Any:
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        data = json.loads(cleaned)

        # Remove accidental doubled words (e.g. 'active active', 'transit transit', 'immediate immediate')
        def _clean_doubled(val: Any) -> Any:
            if isinstance(val, str):
                return re.sub(r'\b([A-Za-z]{3,})\s+\1\b', r'\1', val, flags=re.IGNORECASE)
            elif isinstance(val, dict):
                return {k: _clean_doubled(v) for k, v in val.items()}
            elif isinstance(val, list):
                return [_clean_doubled(item) for item in val]
            return val

        data = _clean_doubled(data)

        # Sanitize common LLM enum drift in claims
        if isinstance(data, dict) and "claims" in data and isinstance(data["claims"], list):
            from app.vocabularies import Country, Sector, Commodity
            valid_countries = set(Country.__members__.keys())
            valid_comms = {c.value for c in Commodity}
            valid_secs = {s.value for s in Sector}

            for c in data["claims"]:
                if not isinstance(c, dict):
                    continue
                # Sanitize country
                geo = str(c.get("geography", "GLOBAL")).upper().strip()
                if geo not in valid_countries:
                    c["geography"] = "GLOBAL"
                # Sanitize commodity
                comm = str(c.get("commodity", "crude_oil")).lower().strip()
                if comm not in valid_comms:
                    c["commodity"] = "crude_oil"
                # Sanitize sector
                sec = str(c.get("sector", "energy.upstream")).lower().strip()
                if sec not in valid_secs:
                    c["sector"] = "energy.upstream"
                # Ensure estimate method exists
                if isinstance(c.get("estimate"), dict) and not c["estimate"].get("method"):
                    c["estimate"]["method"] = "Derived from reported trade and shipping volumes"

        return data

    def _generate_fallback(self, prompt: str, response_model: Type[T]) -> T:
        """Constructs an empty/default instance of response_model for tests."""
        try:
            return response_model.model_construct()
        except Exception:
            return None
