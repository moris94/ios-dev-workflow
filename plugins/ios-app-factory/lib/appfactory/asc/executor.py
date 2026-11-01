"""Apply a plan against App Store Connect with ledger-based idempotency."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Optional

from ..logutil import log
from .client import ASCError, Client, UncertainOutcome
from .ledger import Ledger
from .planner import initial_refs

REF_RE = re.compile(r"\{ref:([^}]+)\}")
LOOKUP_RE = re.compile(r"^\{lookup:([^}]+)\}$")


class ExecutionError(RuntimeError):
    pass


def _resolve(value, refs: Dict[str, str], lookups: Dict[str, object]):
    if isinstance(value, str):
        m = LOOKUP_RE.match(value)
        if m:
            if m.group(1) not in lookups:
                raise ExecutionError(f"unresolved lookup {m.group(1)}")
            return lookups[m.group(1)]

        def sub(match):
            name = match.group(1)
            if name not in refs:
                raise ExecutionError(f"unresolved reference {name} (did an earlier operation fail?)")
            return refs[name]

        return REF_RE.sub(sub, value)
    if isinstance(value, list):
        return [_resolve(v, refs, lookups) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, refs, lookups) for k, v in value.items()}
    return value


def _same_price(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.001
    except (TypeError, ValueError):
        return False


class Executor:
    def __init__(self, client: Client, ledger: Ledger, project_root: Path, snapshot: dict, scope: str = "sync"):
        self.c = client
        self.ledger = ledger
        self.root = Path(project_root)
        self.refs = initial_refs(snapshot)
        self.scope = scope
        self.stats = {"applied": 0, "skipped_ledger": 0, "reconciled": 0}

    # ------------------------------------------------------------- lookups
    def _lookup(self, spec: dict):
        kind = spec["type"]
        if kind == "iap_price_point":
            iap_id = self.refs[spec["iap_ref"]]
            for p in self.c.get_all(f"/v2/inAppPurchases/{iap_id}/pricePoints",
                                    params={"filter[territory]": spec["territory"], "limit": 200}):
                if _same_price(p["attributes"]["customerPrice"], spec["price"]):
                    return p["id"]
            raise ExecutionError(f"no IAP price point {spec['price']} in {spec['territory']}")
        if kind == "app_price_point":
            for p in self.c.get_all(f"/v1/apps/{self.refs['app']}/appPricePoints",
                                    params={"filter[territory]": spec["territory"], "limit": 200}):
                if _same_price(p["attributes"]["customerPrice"], spec["price"]):
                    return p["id"]
            raise ExecutionError(f"no app price point {spec['price']} in {spec['territory']}")
        if kind == "territories":
            return [{"type": "territories", "id": t["id"]} for t in self.c.get_all("/v1/territories", params={"limit": 200})]
        raise ExecutionError(f"unknown lookup {kind}")

    def _reconcile(self, op: dict) -> Optional[str]:
        """Find an existing resource matching a create op (crash/uncertain recovery, auto-created defaults)."""
        rec = op.get("reconcile")
        if not rec:
            return None
        path = _resolve(rec["path"], self.refs, {})
        for item in self.c.get_all(path, params=rec.get("params")):
            attrs = item.get("attributes", {})
            if all(attrs.get(k) == v for k, v in rec["match"].items()):
                want = rec.get("update_attributes") or {}
                diff = {k: v for k, v in want.items() if (attrs.get(k) or "") != (v or "")}
                if diff:
                    self.c.call("PATCH", f"/v1/{rec['update_type']}/{item['id']}",
                                body={"data": {"type": rec["update_type"], "id": item["id"], "attributes": diff}})
                return item["id"]
        return None

    # ------------------------------------------------------------- uploads
    def _upload(self, op: dict, body: dict, prior: Optional[dict]) -> str:
        up = op["upload"]
        commit_tpl = up["commit_path"]
        if prior and prior.get("status") == "reserved" and prior.get("result_id"):
            # Previous run reserved but never committed: discard the dangling reservation.
            try:
                self.c.call("DELETE", commit_tpl.format(id=prior["result_id"]))
            except ASCError as exc:
                if exc.status != 404:
                    raise
        data = (self.root / up["file"]).read_bytes()
        try:
            resp = self.c.call("POST", op["path"], body=body)
        except UncertainOutcome:
            self.ledger.record(op, "uncertain", note="reservation outcome unknown", scope=self.scope)
            raise
        res = resp.body["data"]
        self.ledger.record(op, "reserved", result_id=res["id"], scope=self.scope)
        for part in res["attributes"].get("uploadOperations") or []:
            chunk = data[part["offset"]: part["offset"] + part["length"]]
            self.c.upload_part(part, chunk)
        self.c.call("PATCH", commit_tpl.format(id=res["id"]),
                    body={"data": {"type": up["type"], "id": res["id"],
                                   "attributes": {"uploaded": True, "sourceFileChecksum": up["sourceFileChecksum"]}}})
        return res["id"]

    # ------------------------------------------------------------------ run
    def apply(self, plan: dict) -> dict:
        if plan.get("blocking"):
            raise ExecutionError("plan has blocking issues: " + " | ".join(plan["blocking"]))
        for op in plan["operations"]:
            prior = self.ledger.get(op["key"])
            if prior and prior["status"] == "applied":
                if op.get("produces") and prior.get("result_id"):
                    self.refs[op["produces"]] = prior["result_id"]
                self.stats["skipped_ledger"] += 1
                log(f"skip (already applied): {op['description']}")
                continue
            lookups = {name: self._lookup(spec) for name, spec in (op.get("lookup") or {}).items()}
            path = _resolve(op["path"], self.refs, lookups)
            body = _resolve(op["body"], self.refs, lookups) if op.get("body") is not None else None
            result_id = None
            try:
                if op["method"] in ("POST", "UPLOAD") and (op.get("reconcile") or (prior and prior["status"] == "uncertain")):
                    result_id = self._reconcile(op)
                    if result_id:
                        self.stats["reconciled"] += 1
                if result_id is None:
                    if op["method"] == "UPLOAD":
                        result_id = self._upload(op, body, prior)
                    else:
                        try:
                            resp = self.c.call(op["method"], path, body=body)
                        except UncertainOutcome:
                            self.ledger.record(op, "uncertain", scope=self.scope)
                            raise
                        data = (resp.body or {}).get("data") if isinstance(resp.body, dict) else None
                        result_id = data.get("id") if isinstance(data, dict) else None
            except ASCError as exc:
                self.ledger.record(op, "failed", note=str(exc), scope=self.scope)
                raise
            if op.get("produces") and result_id:
                self.refs[op["produces"]] = result_id
            self.ledger.record(op, "applied", result_id=result_id, scope=self.scope)
            self.stats["applied"] += 1
            log(f"applied: {op['description']}")
        return dict(self.stats)


def describe(plan: dict) -> str:
    lines = [f"Plan ({plan['mode']}, remote={plan['remote_snapshot']}): {len(plan['operations'])} operation(s)"]
    for op in plan["operations"]:
        lines.append(f"  [{op['key'][:8]}] {op['method']:6} {op['path']}  — {op['description']}")
    for w in plan.get("warnings", []):
        lines.append(f"  WARNING: {w}")
    for b in plan.get("blocking", []):
        lines.append(f"  BLOCKING: {b}")
    return "\n".join(lines)


def dump(plan: dict) -> str:
    return json.dumps(plan, ensure_ascii=False, indent=2)
