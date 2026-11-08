"""Quality gates.

Each gate is a pure function ``fn(ctx) -> None`` that records checks on a
:class:`GateContext`. Gates are deterministic and machine-verifiable: they
only read files in the repository (and, where stated, reports produced by
the bundled scripts) and never call the network.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..jsonio import read_json
from ..project import Project
from ..schemas_util import validate
from ..timeutil import now_iso

GATES: Dict[str, Callable[["GateContext"], None]] = {}


def gate(name: str):
    def deco(fn):
        GATES[name] = fn
        return fn

    return deco


class GateContext:
    def __init__(self, project: Project, stage_id: str, state: dict):
        self.project = project
        self.stage_id = stage_id
        self.state = state
        self.config = project.config()
        self.checks: List[dict] = []
        self._cache: Dict[str, Any] = {}

    # -- recording --------------------------------------------------------
    def check(self, check_id: str, ok: bool, message: str = "", severity: str = "error", details: Any = None) -> bool:
        entry = {"id": check_id, "passed": bool(ok), "severity": severity, "message": message}
        if details is not None:
            entry["details"] = details
        self.checks.append(entry)
        return bool(ok)

    def warn(self, check_id: str, ok: bool, message: str = "", details: Any = None) -> bool:
        return self.check(check_id, ok, message, severity="warning", details=details)

    # -- helpers ----------------------------------------------------------
    def path(self, rel: str) -> Path:
        return self.project.root / rel

    def load_json(self, rel: str, required: bool = True) -> Optional[Any]:
        if rel in self._cache:
            return self._cache[rel]
        p = self.path(rel)
        if not p.exists():
            if required:
                self.check(f"exists:{rel}", False, f"required file missing: {rel}")
            return None
        try:
            data = read_json(p)
        except ValueError as exc:
            self.check(f"json:{rel}", False, f"invalid JSON: {exc}")
            return None
        self._cache[rel] = data
        return data

    def load_artifact(self, rel: str, schema: str) -> Optional[Any]:
        data = self.load_json(rel)
        if data is None:
            return None
        errors = validate(data, schema)
        self.check(f"schema:{schema}", not errors,
                   "valid against schema" if not errors else f"{len(errors)} schema error(s)",
                   details=errors[:30] or None)
        return data if not errors else None

    def require_text(self, rel: str, min_chars: int = 200) -> None:
        p = self.path(rel)
        ok = p.exists() and len(p.read_text(encoding="utf-8").strip()) >= min_chars
        self.check(f"doc:{rel}", ok, f"human-readable document present (>= {min_chars} chars)")

    def stage_passed(self, stage_id: str) -> bool:
        return self.state["stages"].get(stage_id, {}).get("status") == "passed"

    def report(self) -> dict:
        errors = [c for c in self.checks if not c["passed"] and c["severity"] == "error"]
        return {
            "stage": self.stage_id,
            "gate": self.stage_id,
            "evaluated_at": now_iso(),
            "passed": bool(self.checks) and not errors,
            "summary": {
                "checks": len(self.checks),
                "errors": len(errors),
                "warnings": len([c for c in self.checks if not c["passed"] and c["severity"] == "warning"]),
            },
            "checks": self.checks,
        }


def run_gate(project: Project, stage, state: dict) -> dict:
    # import side-effect: registers all gates
    from . import planning, design, build, l10n, screenshots, release, brand, ux  # noqa: F401

    ctx = GateContext(project, stage.id, state)
    not_passed = [d for d in stage.depends_on if state["stages"][d]["status"] != "passed"]
    ctx.check("dependencies", not not_passed,
              "all upstream stages passed" if not not_passed else f"upstream not passed: {', '.join(not_passed)}")
    fn = GATES.get(stage.gate)
    if fn is None:
        ctx.check("gate-defined", False, f"no gate registered for {stage.gate}")
    else:
        try:
            fn(ctx)
        except Exception as exc:  # a crashing gate is a failing gate
            ctx.check("gate-execution", False, f"gate raised {type(exc).__name__}: {exc}")
    return ctx.report()
