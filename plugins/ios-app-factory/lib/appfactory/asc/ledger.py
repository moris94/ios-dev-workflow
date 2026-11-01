"""Operation ledger: guarantees successful App Store Connect writes are not re-sent.

Stored in factory/asc/ledger.json (committed) so the guarantee survives
session loss and machine changes. Statuses:

* ``applied``   – confirmed success; never re-sent
* ``reserved``  – upload reserved (asset id known) but not committed
* ``uncertain`` – request may or may not have been applied; reconcile first
* ``failed``    – confirmed failure (safe to retry)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..jsonio import read_json, write_json_atomic
from ..timeutil import now_iso


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = read_json(self.path, None) or {"version": 1, "ops": {}}

    def get(self, key: str) -> Optional[dict]:
        return self.data["ops"].get(key)

    def is_applied(self, key: str) -> bool:
        entry = self.get(key)
        return bool(entry and entry["status"] == "applied")

    def record(self, op: dict, status: str, result_id: Optional[str] = None, note: Optional[str] = None, scope: str = "sync") -> None:
        entry = self.data["ops"].get(op["key"], {})
        entry.update({"status": status, "kind": op["kind"], "target": op.get("target"), "scope": scope, "at": now_iso()})
        if result_id:
            entry["result_id"] = result_id
        if note:
            entry["note"] = note[:500]
        self.data["ops"][op["key"]] = entry
        self.save()

    def save(self) -> None:
        write_json_atomic(self.path, self.data)
