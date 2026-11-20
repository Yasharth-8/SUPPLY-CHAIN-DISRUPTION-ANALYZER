"""
Case-Scoped Private Memory Manager with Immutable Snapshots.
Strictly ensures no cross-case contamination and preserves audit snapshots.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from app.config import MEMORY_DIR


class CaseMemory:
    def __init__(self, case_id: str):
        self.case_id = case_id
        self.namespaces: Dict[str, Dict[str, Any]] = {
            "gatekeeper": {"queries": [], "excluded_docs": [], "requests_log": []},
            "prosecutor": {"claims_history": [], "requests": [], "concessions": []},
            "defence": {"claims_history": [], "requests": [], "concessions": []},
            "judge": {"rulings_history": [], "gaps": [], "engagement_notes": []},
        }

    def append(self, namespace: str, key: str, value: Any):
        if namespace not in self.namespaces:
            self.namespaces[namespace] = {}
        if key not in self.namespaces[namespace]:
            self.namespaces[namespace][key] = []
        if isinstance(self.namespaces[namespace][key], list):
            self.namespaces[namespace][key].append(value)
        else:
            self.namespaces[namespace][key] = value

    def get(self, namespace: str, key: str) -> Any:
        return self.namespaces.get(namespace, {}).get(key)

    def snapshot(self, tag: str) -> str:
        """Saves an immutable snapshot and returns the snapshot ID."""
        now_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snapshot_id = f"SNAP-{self.case_id}-{tag}-{now_str}"
        filepath = MEMORY_DIR / f"{snapshot_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({
                "snapshot_id": snapshot_id,
                "case_id": self.case_id,
                "timestamp": now_str,
                "tag": tag,
                "memory": self.namespaces,
            }, f, indent=2)
        return snapshot_id

