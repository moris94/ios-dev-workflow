"""Workflow engine: persistent stage state, run locks, digests, staleness.

State lives in ``factory/state.json`` (committed, so a pipeline can be
resumed from any machine/session). Run locks and logs live in
``.factory-tmp/`` (gitignored).

Stage lifecycle::

    pending ──start──▶ running ──gate pass──▶ passed
                           │  ╲                 │  (inputs/outputs change)
                           │   ╲gate fail       ▼
                           │    ▶ failed ◀── stale ──gate pass──▶ passed
                           ▼
                     interrupted (lock expired; resumable)
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from . import __version__
from . import locking
from .hashing import digest_files, sha256_json
from .jsonio import append_jsonl, read_json, write_json_atomic
from .pipeline import Pipeline, Stage, load
from .project import Project
from .timeutil import now_iso

STATUSES = ("pending", "running", "passed", "failed", "stale", "interrupted")


class EngineError(RuntimeError):
    pass


def _dotted(data, path: str):
    for part in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


class Engine:
    def __init__(self, project: Project, pipeline: Optional[Pipeline] = None):
        self.project = project
        self.pipeline = pipeline or load()

    # ------------------------------------------------------------------ state
    def _empty_state(self) -> dict:
        return {
            "schema_version": 1,
            "factory_version": __version__,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "stages": {s.id: self._empty_stage() for s in self.pipeline.stages},
        }

    @staticmethod
    def _empty_stage() -> dict:
        return {
            "status": "pending",
            "attempts": 0,
            "run_id": None,
            "owner": None,
            "started_at": None,
            "finished_at": None,
            "input_digest": None,
            "output_digest": None,
            "gate_report": None,
            "reason": None,
        }

    def load_state(self) -> dict:
        state = read_json(self.project.state_path)
        if state is None:
            state = self._empty_state()
        for s in self.pipeline.stages:  # forward compatible with new stages
            state["stages"].setdefault(s.id, self._empty_stage())
        return state

    def save_state(self, state: dict) -> None:
        state["updated_at"] = now_iso()
        write_json_atomic(self.project.state_path, state)

    def event(self, kind: str, stage: Optional[str] = None, **data) -> None:
        record = {"at": now_iso(), "event": kind}
        if stage:
            record["stage"] = stage
        record.update({k: v for k, v in data.items() if v is not None})
        append_jsonl(self.project.history_path, record)

    def _stale_after(self) -> float:
        cfg = self.project.config()
        return float(cfg.get("locks", {}).get("stale_after_minutes", 30)) * 60

    # --------------------------------------------------------------- digests
    def output_digest(self, stage: Stage) -> str:
        return digest_files(self.project.root, stage.outputs_include, stage.outputs_exclude)["digest"]

    def output_files(self, stage: Stage) -> Dict[str, str]:
        return digest_files(self.project.root, stage.outputs_include, stage.outputs_exclude)["files"]

    def input_digest(self, stage: Stage, state: dict) -> str:
        """Digest of upstream outputs + declared inputs. An input ``file.json#a,b.c`` only covers
        the (dotted) keys listed, so unrelated config edits don't invalidate a stage."""
        deps = {d: state["stages"][d].get("output_digest") for d in stage.depends_on}
        plain = [i for i in stage.inputs if "#" not in i]
        files = digest_files(self.project.root, plain)["files"] if plain else {}
        for spec in stage.inputs:
            if "#" in spec:
                rel, keys = spec.split("#", 1)
                data = read_json(self.project.root / rel) or {}
                files[spec] = sha256_json({k: _dotted(data, k) for k in keys.split(",")})
        return sha256_json({"deps": deps, "inputs": files})

    # --------------------------------------------------------------- queries
    def refresh(self, state: Optional[dict] = None, persist: bool = True) -> List[dict]:
        """Detect spec/artifact changes and mark affected stages stale.

        Returns the list of transitions performed.
        """
        own = state is None
        if own:
            ctx = locking.state_mutex(self.project.locks_dir)
            ctx.__enter__()
            state = self.load_state()
        changes = []
        try:
            for stage in self.pipeline.stages:
                st = state["stages"][stage.id]
                if st["status"] == "running":
                    info = locking.read_lock(self.project.locks_dir, stage.id)
                    if info is None or locking.lock_is_stale(info, self._stale_after()):
                        st["status"] = "interrupted"
                        st["reason"] = "run lock missing or expired (session ended?)"
                        changes.append({"stage": stage.id, "to": "interrupted", "reason": st["reason"]})
                    continue
                if st["status"] != "passed":
                    continue
                reason = None
                not_ok = [d for d in stage.depends_on if state["stages"][d]["status"] != "passed"]
                if not_ok:
                    reason = f"upstream not passed: {', '.join(not_ok)}"
                elif self.input_digest(stage, state) != st.get("input_digest"):
                    reason = "inputs changed (upstream artifacts were updated)"
                elif self.output_digest(stage) != st.get("output_digest"):
                    reason = "outputs changed since the gate passed"
                if reason:
                    st["status"] = "stale"
                    st["reason"] = reason
                    changes.append({"stage": stage.id, "to": "stale", "reason": reason})
            if changes and persist:
                self.save_state(state)
                for c in changes:
                    self.event("status_changed", c["stage"], to=c["to"], reason=c["reason"])
        finally:
            if own:
                ctx.__exit__(None, None, None)
        return changes

    def status(self) -> dict:
        self.refresh()
        state = self.load_state()
        rows = []
        for stage in self.pipeline.stages:
            st = state["stages"][stage.id]
            lock = locking.read_lock(self.project.locks_dir, stage.id)
            rows.append(
                {
                    "id": stage.id,
                    "title": stage.title,
                    "status": st["status"],
                    "attempts": st["attempts"],
                    "reason": st.get("reason"),
                    "agent": stage.agent,
                    "lock_owner": lock.get("owner") if lock else None,
                    "gate_report": st.get("gate_report"),
                }
            )
        return {"stages": rows, "next": self.next_stage(state)}

    def deps_ready(self, stage: Stage, state: dict) -> bool:
        return all(state["stages"][d]["status"] == "passed" for d in stage.depends_on)

    def next_stage(self, state: Optional[dict] = None) -> Optional[dict]:
        if state is None:
            self.refresh()
            state = self.load_state()
        for stage in self.pipeline.stages:
            st = state["stages"][stage.id]
            if st["status"] == "passed":
                continue
            if not self.deps_ready(stage, state):
                return {"id": stage.id, "blocked": True, "status": st["status"],
                        "waiting_for": [d for d in stage.depends_on if state["stages"][d]["status"] != "passed"]}
            return {
                "id": stage.id,
                "title": stage.title,
                "status": st["status"],
                "agent": stage.agent,
                "skills": stage.skills,
                "human_approval": stage.human_approval,
                "outputs": stage.outputs_include,
                "reason": st.get("reason"),
                "action": "revalidate" if st["status"] == "stale" else ("resume" if st["status"] in ("interrupted", "running") else "run"),
            }
        return None

    # ------------------------------------------------------------ mutations
    def start(self, stage_id: str, owner: str, force: bool = False, takeover: bool = False) -> dict:
        stage = self.pipeline.get(stage_id)
        with locking.state_mutex(self.project.locks_dir):
            state = self.load_state()
            self.refresh(state, persist=True)
            st = state["stages"][stage_id]
            if not self.deps_ready(stage, state):
                waiting = [d for d in stage.depends_on if state["stages"][d]["status"] != "passed"]
                raise EngineError(f"Cannot start '{stage_id}': dependencies not passed: {', '.join(waiting)}")
            if st["status"] == "passed" and not force:
                return {"action": "skip", "stage": stage_id, "reason": "already passed and inputs/outputs unchanged"}
            run_id = st["run_id"] if (st["status"] == "running" and st.get("owner") == owner) else uuid.uuid4().hex[:12]
            lock = locking.acquire(self.project.locks_dir, stage_id, owner, run_id, self._stale_after(), takeover)
            resumed = lock.get("run_id") == st.get("run_id") and st["status"] == "running"
            run_id = lock["run_id"]
            if not resumed:
                st["attempts"] = int(st.get("attempts") or 0) + 1
                st["started_at"] = now_iso()
            st.update({"status": "running", "run_id": run_id, "owner": owner, "reason": None})
            self.save_state(state)
        self.event("stage_started", stage_id, run_id=run_id, owner=owner, resumed=resumed or None)
        return {"action": "resumed" if resumed else "started", "stage": stage_id, "run_id": run_id,
                "attempt": st["attempts"], "agent": stage.agent, "skills": stage.skills}

    def heartbeat(self, stage_id: str, owner: str) -> bool:
        return locking.heartbeat(self.project.locks_dir, stage_id, owner)

    def record_gate(self, stage_id: str, owner: str, report: dict) -> dict:
        stage = self.pipeline.get(stage_id)
        report_path = self.project.gates_dir / f"{stage_id}.json"
        with locking.state_mutex(self.project.locks_dir):
            state = self.load_state()
            lock = locking.read_lock(self.project.locks_dir, stage_id)
            if lock and lock.get("owner") != owner and not locking.lock_is_stale(lock, self._stale_after()):
                raise locking.LockHeld(stage_id, lock)
            st = state["stages"][stage_id]
            report["input_digest"] = self.input_digest(stage, state)
            report["output_digest"] = self.output_digest(stage)
            report["output_files"] = self.output_files(stage)
            write_json_atomic(report_path, report)
            st["gate_report"] = self.project.rel(report_path)
            st["finished_at"] = now_iso()
            if report["passed"]:
                previous_output = st.get("output_digest")
                st.update({"status": "passed", "input_digest": report["input_digest"],
                           "output_digest": report["output_digest"], "reason": None})
                if previous_output and previous_output != report["output_digest"]:
                    for down in self.pipeline.downstream(stage_id):
                        dst = state["stages"][down]
                        if dst["status"] == "passed":
                            dst["status"] = "stale"
                            dst["reason"] = f"upstream '{stage_id}' changed"
                            self.event("status_changed", down, to="stale", reason=dst["reason"])
            else:
                failed = [c["id"] for c in report["checks"] if not c["passed"] and c.get("severity", "error") == "error"]
                st.update({"status": "failed", "reason": "gate failed: " + ", ".join(failed)})
            self.save_state(state)
            locking.release(self.project.locks_dir, stage_id)
        self.event("gate_" + ("passed" if report["passed"] else "failed"), stage_id,
                   run_id=st.get("run_id"), output_digest=report["output_digest"])
        return {"stage": stage_id, "passed": report["passed"], "status": st["status"],
                "report": st["gate_report"], "reason": st.get("reason")}

    def fail(self, stage_id: str, owner: str, reason: str) -> dict:
        self.pipeline.get(stage_id)
        with locking.state_mutex(self.project.locks_dir):
            state = self.load_state()
            st = state["stages"][stage_id]
            st.update({"status": "failed", "reason": reason, "finished_at": now_iso()})
            self.save_state(state)
            locking.release(self.project.locks_dir, stage_id)
        self.event("stage_failed", stage_id, reason=reason, owner=owner)
        return {"stage": stage_id, "status": "failed", "reason": reason}

    def invalidate(self, stage_id: str, reason: str, include_self: bool = True) -> List[str]:
        """Spec change: mark a stage (and everything downstream) stale."""
        self.pipeline.get(stage_id)
        targets = ([stage_id] if include_self else []) + self.pipeline.downstream(stage_id)
        changed = []
        with locking.state_mutex(self.project.locks_dir):
            state = self.load_state()
            for sid in targets:
                st = state["stages"][sid]
                if st["status"] in ("passed", "failed"):
                    st["status"] = "stale"
                    st["reason"] = f"invalidated: {reason}"
                    changed.append(sid)
            self.save_state(state)
        self.event("invalidated", stage_id, reason=reason, affected=changed)
        return changed

    def unlock(self, stage_id: str) -> None:
        with locking.state_mutex(self.project.locks_dir):
            state = self.load_state()
            locking.release(self.project.locks_dir, stage_id)
            st = state["stages"][stage_id]
            if st["status"] == "running":
                st["status"] = "interrupted"
                st["reason"] = "lock released manually"
            self.save_state(state)
        self.event("unlocked", stage_id)
