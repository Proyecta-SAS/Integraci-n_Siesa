from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SyncState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._keys = self._load()

    def _load(self) -> set[str]:
        if not self.path.exists():
            return set()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return {str(item) for item in data.get("processed_keys", [])}

    def contains(self, key: str) -> bool:
        return key in self._keys

    def add(self, key: str) -> None:
        self._keys.add(key)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"processed_keys": sorted(self._keys)}
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class JsonlAuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
