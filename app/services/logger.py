"""
Structured JSON Logger for Observability and Auditing.
Logs every claim, query, evidence request, validation result, and ruling.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.config import LOGS_DIR


class StructuredLogger:
    def __init__(self, case_id: str):
        self.case_id = case_id
        self.log_file = LOGS_DIR / f"{case_id}.jsonl"

    def log(self, event_type: str, payload: Dict[str, Any]):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "case_id": self.case_id,
            "event_type": event_type,
            "payload": payload,
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_logs(self) -> list:
        if not self.log_file.exists():
            return []
        entries = []
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line.strip()))
        return entries

