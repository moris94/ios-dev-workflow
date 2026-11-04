"""App Store Connect sync, TestFlight verification, readiness, submission and release."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from . import approval
from .asc import auth
from .asc.client import Client, HttpTransport
from .asc.executor import Executor, describe
from .asc.fake import FakeASC
from .asc.ledger import Ledger
from .asc.planner import Plan, build_plan, validate_plan
from .asc.state import desired_digest, desired_state, empty_snapshot, fetch_snapshot, load_fixture
from .engine import Engine
from .hashing import sha256_file, sha256_json, source_digest
from .jsonio import read_json, write_json_atomic
from .logutil import log
from .project import Project
from .timeutil import now_iso

READINESS = "factory/artifacts/release/readiness.json"
PRE_RELEASE_STAGES = ["research", "proposal", "charter", "mvp", "design", "implementation", "localization", "testing",
                      "aso", "screenshots", "asc_sync", "testflight"]


class ReleaseError(RuntimeError):
    pass


def rehearsal() -> bool:
    """FACTORY_REHEARSAL=1: accept results from the built-in ASC simulator (offline end-to-end rehearsal).
    Never affects live App Store Connect: simulated operations only ever reach the in-memory simulator."""
    return os.environ.get("FACTORY_REHEARSAL") == "1"


# ------------------------------------------------------------------ clients
def make_client(project: Project, simulate: bool) -> Tuple[Client, str]:
    if simulate:
        fake = FakeASC(project.tmp / "fake-asc.json", bundle_id=project.config()["app"]["bundle_id"])
        return Client(fake, sleep=lambda s: None), "simulated"
    return Client(HttpTransport(auth.TokenProvider())), "live"


def _snapshot(project: Project, client: Optional[Client], fixture: Optional[str]) -> Tuple[dict, str]:
    cfg = project.config()
    if client is not None:
        return fetch_snapshot(client, cfg["app"]["bundle_id"], cfg["app"]["version"], cfg.get("asc", {}).get("app_id")), "live"
    fixture = fixture or cfg.get("asc", {}).get("remote_fixture")
    if fixture:
        return load_fixture(project.root / fixture), "fixture"
    return empty_snapshot(), "empty"


# --------------------------------------------------------------------- sync
def sync(project: Project, apply: bool = False, simulate: bool = False, fixture: Optional[str] = None) -> dict:
    """Plan (always) and optionally apply App Store Connect changes. Never submits."""
    desired = desired_state(project)
    client = None
    if apply or simulate or (auth.credentials_present() and not fixture):
        client, _ = make_client(project, simulate)
    snapshot, kind = _snapshot(project, client, fixture)
    mode = "apply" if apply else "dry-run"
    plan = build_plan(desired, snapshot, kind, mode)
    errors = validate_plan(plan)
    write_json_atomic(project.asc_dir / "plan.json", plan)
    log(describe(plan))
    report = {"at": now_iso(), "mode": mode, "simulated": simulate, "remote_snapshot": kind,
              "desired_digest": plan["desired_digest"], "plan_digest": sha256_json(plan["operations"]),
              "operations": len(plan["operations"]), "validation_errors": errors, "blocking": plan["blocking"]}
    if errors:
        write_json_atomic(project.asc_dir / "sync-report.json", report)
        raise ReleaseError("plan validation failed:\n  " + "\n  ".join(errors))
    if apply:
        ledger = Ledger(project.asc_dir / ("ledger.simulated.json" if simulate else "ledger.json"))
        stats = Executor(client, ledger, project.root, snapshot).apply(plan)
        # Verify: re-read remote state; a converged sync re-plans to zero operations.
        after, _ = _snapshot(project, client, None)
        remaining = build_plan(desired, after, "live", "apply")["operations"]
        report.update({"stats": stats, "requests_sent": client.requests_sent, "verify_noop": not remaining,
                       "remaining": [o["description"] for o in remaining],
                       "app_id": (after.get("app") or {}).get("id"), "version_id": (after.get("version") or {}).get("id")})
    write_json_atomic(project.asc_dir / "sync-report.json", report)
    return report


# ---------------------------------------------------------------- testflight
def testflight_verify(project: Project, simulate: bool = False, build_id_hint: Optional[str] = None) -> dict:
    cfg = project.config()
    client, kind = make_client(project, simulate)
    snap, _ = _snapshot(project, client, None)
    if not snap.get("app"):
        raise ReleaseError("app record not found in App Store Connect")
    if simulate and build_id_hint is None:
        fake: FakeASC = client.t  # type: ignore[assignment]
        if not fake.db.get("builds"):
            fake.add_build(cfg["app"]["version"], str(cfg["app"]["build_number"]))
    builds = client.get_all("/v1/builds", params={"filter[app]": snap["app"]["id"], "filter[version]": str(cfg["app"]["build_number"]),
                                                  "filter[preReleaseVersion.version]": cfg["app"]["version"]})
    if not builds:
        raise ReleaseError(f"build {cfg['app']['build_number']} not found yet (still uploading/processing?) — retry later")
    b = builds[0]
    tests = read_json(project.reports / "tests.json") or {}
    report = {
        "version": cfg["app"]["version"], "build_number": str(cfg["app"]["build_number"]), "build_id": b["id"],
        "processing_state": b["attributes"].get("processingState"), "uploaded_at": now_iso(),
        "uses_non_exempt_encryption": b["attributes"].get("usesNonExemptEncryption"),
        "source_digest": tests.get("source_digest") or source_digest(project.root), "simulated": simulate,
    }
    write_json_atomic(project.reports / "testflight.json", report)
    return report


# ---------------------------------------------------------------- readiness
def compute_readiness(project: Project) -> dict:
    cfg = project.config()
    engine = Engine(project)
    engine.refresh()
    state = engine.load_state()
    checks = []

    def check(cid, ok, msg):
        checks.append({"id": cid, "passed": bool(ok), "message": msg})

    not_passed = [s for s in PRE_RELEASE_STAGES if state["stages"][s]["status"] != "passed"]
    check("stages.passed", not not_passed, "all pre-release stages passed" if not not_passed else f"not passed: {not_passed}")
    sync_report = read_json(project.asc_dir / "sync-report.json") or {}
    sim_ok = rehearsal()
    check("asc.applied", sync_report.get("mode") == "apply" and (not sync_report.get("simulated") or sim_ok),
          "App Store Connect sync applied against the live API")
    check("asc.converged", sync_report.get("verify_noop") is True, "re-planning after sync yields zero operations")
    check("asc.current", sync_report.get("desired_digest") == (desired_digest(desired_state(project)) if sync_report else None),
          "ASC sync reflects current metadata/screenshots/IAP")
    tf = read_json(project.reports / "testflight.json") or {}
    tests = read_json(project.reports / "tests.json") or {}
    check("testflight.valid", tf.get("processing_state") == "VALID" and (not tf.get("simulated") or sim_ok), f"TestFlight build state {tf.get('processing_state')}")
    check("testflight.build", str(tf.get("build_number")) == str(cfg["app"]["build_number"]) and tf.get("version") == cfg["app"]["version"],
          "TestFlight build matches config version/build")
    check("testflight.same-sources", tf.get("source_digest") == tests.get("source_digest") == source_digest(project.root),
          "uploaded build == tested sources == current sources")
    purchase = read_json(project.reports / "purchase-test.json")
    require_manual = cfg.get("release", {}).get("require_manual_purchase_test", True)
    if require_manual:
        ok = bool(purchase) and purchase.get("recorded_interactively") is True and \
            str(purchase.get("build_number")) == str(cfg["app"]["build_number"]) and \
            {c["id"] for c in purchase.get("cases", []) if c["result"] == "pass"} >= {"purchase", "restore", "en_paywall", "ja_paywall"}
        check("purchase-test", ok, "sandbox/TestFlight purchase, restore and en/ja paywall verified by a human on this build")
    components = {
        "app_version": cfg["app"]["version"],
        "build_number": str(cfg["app"]["build_number"]),
        "build_id": tf.get("build_id"),
        "source_digest": tests.get("source_digest"),
        "stage_outputs": {s: state["stages"][s].get("output_digest") for s in PRE_RELEASE_STAGES},
        "asc_desired_digest": sync_report.get("desired_digest"),
        "purchase_test": sha256_file(project.reports / "purchase-test.json") if purchase else None,
        "rehearsal": sim_ok,
    }
    digest = sha256_json(components)
    mvp = read_json(project.artifact("mvp", "mvp.json")) or {"monetization": {"products": []}}
    summary = [
        f"Version {cfg['app']['version']} build {cfg['app']['build_number']} (ASC build id {tf.get('build_id')})",
        f"IAP: " + ", ".join(f"{p['product_id']} ${p['price_usd']}" for p in mvp["monetization"]["products"]),
        f"Locales: {', '.join(cfg['app']['locales'])}",
        "Release type: MANUAL (publishing needs a separate `approve publish`)",
    ] + [f"[{'OK' if c['passed'] else 'NG'}] {c['message']}" for c in checks]
    return {"generated_at": now_iso(), "ready": all(c["passed"] for c in checks), "readiness_digest": digest,
            "app_version": cfg["app"]["version"], "build_number": str(cfg["app"]["build_number"]),
            "components": components, "checks": checks, "summary": summary}


def write_readiness(project: Project) -> dict:
    r = compute_readiness(project)
    write_json_atomic(project.root / READINESS, r)
    return r


# ------------------------------------------------------- submit & publish
def _require_approval(project: Project, kind: str) -> dict:
    readiness = read_json(project.root / READINESS)
    if not readiness:
        raise ReleaseError("readiness.json missing; run `app-factory release readiness`")
    fresh = compute_readiness(project)
    if fresh["readiness_digest"] != readiness["readiness_digest"]:
        raise ReleaseError("release readiness changed since readiness.json was written; regenerate and re-approve")
    if not fresh["ready"]:
        raise ReleaseError("release is not ready: " + "; ".join(c["message"] for c in fresh["checks"] if not c["passed"]))
    ok, msg = approval.verify(project, kind, fresh["readiness_digest"])
    if not ok:
        raise ReleaseError(f"HUMAN APPROVAL REQUIRED: {msg}")
    log(f"{kind} approval verified: {msg}")
    return fresh


def submit(project: Project, dry_run: bool = False, simulate: bool = False) -> dict:
    if not dry_run:
        _require_approval(project, "submit")
    elif not simulate:
        log("dry-run: approval not checked; no request will be sent")
    tf = read_json(project.reports / "testflight.json") or {}
    client = None
    snap = empty_snapshot()
    if not dry_run or simulate or auth.credentials_present():
        client, _ = make_client(project, simulate)
        cfg = project.config()
        snap = fetch_snapshot(client, cfg["app"]["bundle_id"], cfg["app"]["version"], cfg.get("asc", {}).get("app_id"))
    plan = Plan()
    plan.add("submit.attach_build", "version_build", "PATCH", "/v1/appStoreVersions/{ref:version}",
             {"data": {"type": "appStoreVersions", "id": "{ref:version}",
                       "relationships": {"build": {"data": {"type": "builds", "id": tf.get("build_id") or "{ref:build}"}}}}},
             f"Attach build {tf.get('build_number')} to version")
    for pid, iap in snap.get("iaps", {}).items():
        if iap.get("state") == "READY_TO_SUBMIT":
            plan.add("submit.iap", f"iap_submit:{pid}", "POST", "/v1/inAppPurchaseSubmissions",
                     {"data": {"type": "inAppPurchaseSubmissions",
                               "relationships": {"inAppPurchaseV2": {"data": {"type": "inAppPurchases", "id": "{ref:iap.%s}" % pid}}}}},
                     f"Submit IAP {pid} with this version")
    plan.add("submit.review_submission", "review_submission", "POST", "/v1/reviewSubmissions",
             {"data": {"type": "reviewSubmissions", "attributes": {"platform": "IOS"},
                       "relationships": {"app": {"data": {"type": "apps", "id": "{ref:app}"}}}}},
             "Create review submission", produces="review_submission")
    plan.add("submit.item", "review_item", "POST", "/v1/reviewSubmissionItems",
             {"data": {"type": "reviewSubmissionItems",
                       "relationships": {"reviewSubmission": {"data": {"type": "reviewSubmissions", "id": "{ref:review_submission}"}},
                                         "appStoreVersion": {"data": {"type": "appStoreVersions", "id": "{ref:version}"}}}}},
             "Add app version to review submission", depends_on_refs=["review_submission"])
    plan.add("submit.confirm", "review_submit", "PATCH", "/v1/reviewSubmissions/{ref:review_submission}",
             {"data": {"type": "reviewSubmissions", "id": "{ref:review_submission}", "attributes": {"submitted": True}}},
             "Submit for App Review", depends_on_refs=["review_submission"])
    planned = {"mode": "dry-run" if dry_run else "apply", "remote_snapshot": "live" if client else "empty",
               "operations": plan.ops, "warnings": [], "blocking": []}
    log(describe(planned))
    if dry_run:
        return {"dry_run": True, "operations": [o["description"] for o in plan.ops]}
    ledger = Ledger(project.asc_dir / ("ledger.simulated.json" if simulate else "ledger.json"))
    ex = Executor(client, ledger, project.root, snap, scope="submit")
    stats = ex.apply(planned)
    out = {"submitted": True, "submitted_at": now_iso(), "review_submission_id": ex.refs.get("review_submission"),
           "version_id": ex.refs.get("version"), "build_id": tf.get("build_id"), "stats": stats, "simulated": simulate,
           "readiness_digest": read_json(project.root / READINESS)["readiness_digest"]}
    write_json_atomic(project.reports / "submission.json", out)
    return out


def publish(project: Project, dry_run: bool = False, simulate: bool = False) -> dict:
    if not dry_run:
        _require_approval(project, "publish")
    sub = read_json(project.reports / "submission.json")
    if not sub:
        raise ReleaseError("not submitted yet")
    if dry_run:
        return {"dry_run": True, "operations": ["POST /v1/appStoreVersionReleaseRequests (after Apple approval)"]}
    client, _ = make_client(project, simulate)
    ver = client.get(f"/v1/appStoreVersions/{sub['version_id']}")["data"]
    state = ver["attributes"].get("appStoreState") or ver["attributes"].get("appVersionState")
    if state != "PENDING_DEVELOPER_RELEASE":
        raise ReleaseError(f"version state is {state}; release is only possible in PENDING_DEVELOPER_RELEASE (approved by Apple)")
    plan = Plan()
    plan.add("publish.release_request", "release", "POST", "/v1/appStoreVersionReleaseRequests",
             {"data": {"type": "appStoreVersionReleaseRequests",
                       "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": sub["version_id"]}}}}},
             "Release the approved version to the App Store")
    ledger = Ledger(project.asc_dir / ("ledger.simulated.json" if simulate else "ledger.json"))
    stats = Executor(client, ledger, project.root, empty_snapshot(), scope="publish").apply(
        {"operations": plan.ops, "blocking": []})
    out = {"released": True, "released_at": now_iso(), "version_id": sub["version_id"], "stats": stats, "simulated": simulate}
    write_json_atomic(project.reports / "release.json", out)
    return out


def simulate_apple_approval(project: Project) -> None:
    """Test helper for --simulate: pretend App Review approved the version."""
    fake = FakeASC(project.tmp / "fake-asc.json", bundle_id=project.config()["app"]["bundle_id"])
    fake.set_version_state("PENDING_DEVELOPER_RELEASE")


def env_summary() -> dict:
    return {"asc_credentials": auth.credentials_present(),
            "asc_missing_env": auth.missing_env(),
            "approver_key_exists": approval.key_path().exists()}
