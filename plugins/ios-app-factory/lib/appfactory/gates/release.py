"""Release-side gates: ASC sync, TestFlight, readiness, submission, publication."""
from __future__ import annotations

from .. import approval
from ..asc.planner import validate_plan
from ..asc.state import desired_digest, desired_state
from ..hashing import source_digest
from ..schemas_util import validate
from . import gate


def _sim_ok() -> bool:
    from ..release import rehearsal

    return rehearsal()


@gate("asc_sync")
def asc_sync_gate(ctx):
    plan = ctx.load_json("factory/asc/plan.json")
    report = ctx.load_json("factory/asc/sync-report.json")
    if not plan or not report:
        return
    errors = validate(plan, "asc_plan")
    ctx.check("plan.schema", not errors, "plan valid against schema", details=errors[:20] or None)
    from ..fastlane_release import backend as release_backend

    ctx.check("plan.backend", plan.get("backend", "api") == release_backend(ctx.project),
              f"plan made for the configured release backend ({release_backend(ctx.project)})")
    perrs = validate_plan(plan)
    ctx.check("plan.requests", not perrs, f"{len(plan['operations'])} request bodies structurally valid; no submit/release ops",
              details=perrs[:20] or None)
    ctx.check("plan.current", plan["desired_digest"] == desired_digest(desired_state(ctx.project)),
              "plan built from current aso/mvp/screenshots (re-run `app-factory asc plan`)")
    ctx.check("plan.not-blocked", not plan.get("blocking"), "no blocking issues", details=plan.get("blocking") or None)
    mode = ctx.config.get("asc", {}).get("mode", "dry-run")
    if mode == "apply":
        ctx.check("sync.applied", report.get("mode") == "apply" and (not report.get("simulated") or _sim_ok()),
                  "changes applied to App Store Connect (live)")
        ctx.check("sync.converged", report.get("verify_noop") is True, "post-apply re-plan is empty (remote == desired)",
                  details=report.get("remaining") or None)
        ctx.check("sync.report-current", report.get("desired_digest") == plan["desired_digest"], "sync report matches plan")
        if plan.get("backend") == "fastlane":
            fl_rep = report.get("fastlane") or {}
            ctx.check("sync.fastlane-delivered", fl_rep.get("digest") == plan["fastlane"]["digest"] and
                      fl_rep.get("status") in ("applied", "skipped_ledger", "simulated"),
                      f"metadata & screenshots delivered by fastlane ({fl_rep.get('status')})")
    else:
        ctx.check("sync.dry-run", report.get("mode") == "dry-run" and not report.get("validation_errors"),
                  "dry-run validated (config asc.mode=dry-run; release readiness will require apply)")
        ctx.warn("sync.not-applied", False, "App Store Connect not updated yet (dry-run mode)")


@gate("testflight")
def testflight_gate(ctx):
    rep = ctx.load_json("factory/reports/testflight.json")
    if not rep:
        return
    errors = validate(rep, "testflight_report")
    ctx.check("report.schema", not errors, "TestFlight report valid", details=errors or None)
    app = ctx.config["app"]
    ctx.check("build.processed", rep.get("processing_state") == "VALID", f"processing state {rep.get('processing_state')}")
    ctx.check("build.number", str(rep.get("build_number")) == str(app["build_number"]) and rep.get("version") == app["version"],
              "build/version match config")
    ctx.check("build.sources", rep.get("source_digest") == source_digest(ctx.project.root), "uploaded build built from current sources")
    ctx.check("build.encryption", rep.get("uses_non_exempt_encryption") in (False, None), "export compliance declared (no non-exempt encryption)")
    ctx.check("build.live", not rep.get("simulated") or _sim_ok(), "build verified against live App Store Connect")


@gate("release_readiness")
def readiness_gate(ctx):
    from ..release import READINESS, compute_readiness

    rec = ctx.load_json(READINESS)
    if not rec:
        return
    fresh = compute_readiness(ctx.project)
    ctx.check("readiness.current", rec["readiness_digest"] == fresh["readiness_digest"], "readiness.json reflects current state")
    for c in fresh["checks"]:
        ctx.check(f"readiness.{c['id']}", c["passed"], c["message"])
    if ctx.config.get("release", {}).get("require_manual_purchase_test", True):
        p = ctx.load_json("factory/reports/purchase-test.json")
        if p:
            errors = validate(p, "purchase_test")
            ctx.check("purchase-test.schema", not errors, "purchase test evidence valid", details=errors or None)


def _approved_stage(ctx, kind: str, report_rel: str, flag: str):
    from ..release import READINESS

    readiness = ctx.load_json(READINESS)
    rep = ctx.load_json(report_rel)
    if not readiness or not rep:
        return
    rec = ctx.load_json(f"factory/approvals/{kind}.json")
    if rec:
        errors = validate(rec, "approval")
        ctx.check("approval.schema", not errors, "approval record valid", details=errors or None)
    ok, msg = approval.verify(ctx.project, kind, readiness["readiness_digest"])
    ctx.check("approval.human", ok, msg)
    ctx.check(f"{kind}.done", rep.get(flag) is True and (not rep.get("simulated") or _sim_ok()), f"{kind} executed against live App Store Connect")


@gate("submit")
def submit_gate(ctx):
    _approved_stage(ctx, "submit", "factory/reports/submission.json", "submitted")


@gate("publish")
def publish_gate(ctx):
    _approved_stage(ctx, "publish", "factory/reports/release.json", "released")
