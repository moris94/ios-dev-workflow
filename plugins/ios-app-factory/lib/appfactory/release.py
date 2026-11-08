"""App Store Connect sync, TestFlight verification, readiness, submission and release."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from . import approval
from . import fastlane_release as fl
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
    errors = validate_plan(plan)  # validates every value (lengths, types) whichever backend uploads it
    backend = fl.backend(project)
    api_ops = plan["operations"]
    files: dict = {}
    if backend == "fastlane":
        files = fl.deliver_files(project, desired)
        api_ops = [o for o in plan["operations"] if fl.api_kept(o["kind"])]
        delegated = [o for o in plan["operations"] if not fl.api_kept(o["kind"])]
        written = dict(plan, operations=api_ops, backend="fastlane",
                       fastlane={"lane": fl.LANES["sync"], "digest": fl.digest(files), "files": sorted(files),
                                 "delegated": [o["description"] for o in delegated]})
    else:
        written = dict(plan, backend="api")
    write_json_atomic(project.asc_dir / "plan.json", written)
    log(describe(written))
    if backend == "fastlane":
        log(f"fastlane {fl.LANES['sync']} (deliver): {len(files)} files, digest {written['fastlane']['digest'][:12]} — "
            f"covers {len(written['fastlane']['delegated'])} change(s): metadata, screenshots, category, releaseType MANUAL")
    report = {"at": now_iso(), "backend": backend, "mode": mode, "simulated": simulate, "remote_snapshot": kind,
              "desired_digest": plan["desired_digest"], "plan_digest": sha256_json(written["operations"]),
              "operations": len(plan["operations"]), "validation_errors": errors, "blocking": plan["blocking"]}
    if backend == "fastlane":
        report["fastlane"] = {"digest": written["fastlane"]["digest"], "lane": fl.LANES["sync"], "status": "planned"}
    if errors:
        write_json_atomic(project.asc_dir / "sync-report.json", report)
        raise ReleaseError("plan validation failed:\n  " + "\n  ".join(errors))
    if apply:
        ledger = Ledger(project.asc_dir / ("ledger.simulated.json" if simulate else "ledger.json"))
        if backend == "api" or simulate:
            # api backend, or rehearsal: the simulator stands in for deliver's effects as well
            stats = Executor(client, ledger, project.root, snapshot).apply(plan)
            if backend == "fastlane":
                report["fastlane"]["status"] = "simulated"
        else:
            stats = Executor(client, ledger, project.root, snapshot).apply(dict(plan, operations=api_ops))
            report["fastlane"]["status"] = _deliver_metadata(project, desired, files, client, ledger)
        # Verify: re-read remote state; a converged sync re-plans to zero operations (deliver's work included).
        after, _ = _snapshot(project, client, None)
        remaining = build_plan(desired, after, "live", "apply")["operations"]
        report.update({"stats": stats, "requests_sent": client.requests_sent, "verify_noop": not remaining,
                       "remaining": [o["description"] for o in remaining],
                       "app_id": (after.get("app") or {}).get("id"), "version_id": (after.get("version") or {}).get("id")})
    write_json_atomic(project.asc_dir / "sync-report.json", report)
    return report


def _deliver_metadata(project: Project, desired: dict, files: dict, client: Client, ledger: Ledger) -> str:
    """Run `deliver` unless the same content was already delivered and the remote still matches."""
    digest = fl.digest(files)
    op = {"key": sha256_json({"lane": fl.LANES["sync"], "digest": digest,
                              "version": desired["version"]["versionString"]})[:24],
          "kind": "fastlane.sync_metadata", "target": f"version:{desired['version']['versionString']}"}
    if ledger.is_applied(op["key"]):
        current, _ = _snapshot(project, client, None)
        drift = [o for o in build_plan(desired, current, "live", "apply")["operations"] if not fl.api_kept(o["kind"])]
        if not drift:
            log("deliver: identical content already delivered and remote unchanged — not re-sent")
            return "skipped_ledger"
        log(f"deliver: remote drifted from the delivered content ({len(drift)} difference(s)) — re-delivering")
    tree = fl.write_tree(project, files)
    try:
        fl.run_lane(project, fl.LANES["sync"], {"FACTORY_METADATA_PATH": tree["metadata_path"],
                                                 "FACTORY_SCREENSHOTS_PATH": tree["screenshots_path"],
                                                 "FACTORY_DELIVER_DIGEST": digest})
    except fl.FastlaneError as exc:
        ledger.record(op, "failed", note=str(exc))
        raise
    ledger.record(op, "applied")
    return "applied"


# ---------------------------------------------------------------- testflight
def testflight_verify(project: Project, simulate: bool = False, build_id_hint: Optional[str] = None) -> dict:
    cfg = project.config()
    if fl.backend(project) == "fastlane" and not simulate:
        r = fl.run_lane(project, fl.LANES["status"], {})
        tests = read_json(project.reports / "tests.json") or {}
        report = {"backend": "fastlane", "version": r["version"], "build_number": str(r["build_number"]),
                  "build_id": r["build_id"], "processing_state": r["processing_state"], "uploaded_at": now_iso(),
                  "uses_non_exempt_encryption": r.get("uses_non_exempt_encryption"),
                  "source_digest": tests.get("source_digest") or source_digest(project.root), "simulated": False}
        write_json_atomic(project.reports / "testflight.json", report)
        return report
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
        readiness = _require_approval(project, "submit")
    elif not simulate:
        log("dry-run: approval not checked; no request will be sent")
    if fl.backend(project) == "fastlane" and not simulate:
        return _submit_fastlane(project, dry_run, readiness if not dry_run else None)
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
    plan.ops.extend(_iap_submission_ops(snap).ops)
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


def _iap_submission_ops(snap: dict) -> Plan:
    plan = Plan()
    for pid, iap in snap.get("iaps", {}).items():
        if iap.get("state") == "READY_TO_SUBMIT":
            plan.add("submit.iap", f"iap_submit:{pid}", "POST", "/v1/inAppPurchaseSubmissions",
                     {"data": {"type": "inAppPurchaseSubmissions",
                               "relationships": {"inAppPurchaseV2": {"data": {"type": "inAppPurchases", "id": "{ref:iap.%s}" % pid}}}}},
                     f"Submit IAP {pid} with this version (App Store Connect API: not supported by fastlane)")
    return plan


def _submit_fastlane(project: Project, dry_run: bool, readiness: Optional[dict]) -> dict:
    cfg = project.config()
    snap = empty_snapshot()
    client = None
    if not dry_run or auth.credentials_present():
        client, _ = make_client(project, False)
        snap = fetch_snapshot(client, cfg["app"]["bundle_id"], cfg["app"]["version"], cfg.get("asc", {}).get("app_id"))
    iap_plan = _iap_submission_ops(snap)
    lane_desc = (f"fastlane {fl.LANES['submit']}: deliver submit_for_review (version {cfg['app']['version']}, "
                 f"build {cfg['app']['build_number']}, automatic_release false)")
    if dry_run:
        return {"dry_run": True, "backend": "fastlane", "operations": [o["description"] for o in iap_plan.ops] + [lane_desc]}
    ledger = Ledger(project.asc_dir / "ledger.json")
    stats = Executor(client, ledger, project.root, snap, scope="submit").apply({"operations": iap_plan.ops, "blocking": []})
    op = {"key": sha256_json({"lane": fl.LANES["submit"], "readiness": readiness["readiness_digest"]})[:24],
          "kind": "fastlane.submit_review", "target": f"version:{cfg['app']['version']}"}
    previous = read_json(project.reports / "submission.json")
    if ledger.is_applied(op["key"]) and previous:
        log("submission already sent for this readiness — not re-sent")
        return previous
    try:
        result = fl.run_lane(project, fl.LANES["submit"], {})
    except fl.FastlaneError as exc:
        # deliver may have created the submission before failing: never assume it is safe to resend blindly
        ledger.record(op, "uncertain", note=str(exc), scope="submit")
        raise
    ledger.record(op, "applied", result_id=result.get("review_submission_id"), scope="submit")
    out = {"backend": "fastlane", "submitted": bool(result.get("submitted")), "submitted_at": now_iso(),
           "review_submission_id": result.get("review_submission_id"), "version_id": result.get("version_id"),
           "build_number": str(cfg["app"]["build_number"]), "iap_stats": stats, "simulated": False,
           "readiness_digest": readiness["readiness_digest"]}
    write_json_atomic(project.reports / "submission.json", out)
    return out


def publish(project: Project, dry_run: bool = False, simulate: bool = False) -> dict:
    if not dry_run:
        _require_approval(project, "publish")
    sub = read_json(project.reports / "submission.json")
    if not sub:
        raise ReleaseError("not submitted yet")
    if fl.backend(project) == "fastlane" and not simulate:
        if dry_run:
            return {"dry_run": True, "backend": "fastlane",
                    "operations": [f"fastlane {fl.LANES['publish']}: release request for the version pending developer release"]}
        ledger = Ledger(project.asc_dir / "ledger.json")
        op = {"key": sha256_json({"lane": fl.LANES["publish"], "version_id": sub.get("version_id"),
                                  "version": project.config()["app"]["version"]})[:24],
              "kind": "fastlane.release_version", "target": f"version:{project.config()['app']['version']}"}
        if ledger.is_applied(op["key"]) and read_json(project.reports / "release.json"):
            return read_json(project.reports / "release.json")
        result = fl.run_lane(project, fl.LANES["publish"], {})
        ledger.record(op, "applied", result_id=result.get("version_id"), scope="publish")
        out = {"backend": "fastlane", "released": bool(result.get("released")), "released_at": now_iso(),
               "version_id": result.get("version_id"), "simulated": False}
        write_json_atomic(project.reports / "release.json", out)
        return out
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


def verify_approval(project: Project, kind: str) -> dict:
    """Used by the fastlane submit/release lanes to re-check the human approval (fail closed)."""
    return _require_approval(project, kind)


def simulate_apple_approval(project: Project) -> None:
    """Test helper for --simulate: pretend App Review approved the version."""
    fake = FakeASC(project.tmp / "fake-asc.json", bundle_id=project.config()["app"]["bundle_id"])
    fake.set_version_state("PENDING_DEVELOPER_RELEASE")


def env_summary() -> dict:
    return {"asc_credentials": auth.credentials_present(),
            "asc_missing_env": auth.missing_env(),
            "approver_key_exists": approval.key_path().exists()}
