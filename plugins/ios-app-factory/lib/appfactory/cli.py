"""`app-factory` command line interface.

Machine-readable JSON goes to stdout; human logs go to stderr (redacted) and
to .factory-tmp/logs/factory.log.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .logutil import log, set_log_file
from .redact import redact


def _out(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _project(args, must_exist=True):
    from .project import Project

    return Project.find(Path(args.project) if getattr(args, "project", None) else None, must_exist=must_exist)


def _owner(args) -> str:
    return args.owner or os.environ.get("FACTORY_OWNER") or os.environ.get("CLAUDE_SESSION_ID") or f"pid-{os.getppid()}"


# ------------------------------------------------------------------ commands
def cmd_init(args):
    from .project import Project
    from .scaffold import init, scaffold

    root = Path(args.project or os.getcwd()).resolve()
    idea = args.idea or (Path(args.idea_file).read_text(encoding="utf-8") if args.idea_file else None)
    if not idea:
        raise SystemExit("--idea or --idea-file is required")
    result = init(root, idea, args.name, args.bundle_id, args.team_id, force=args.force)
    if args.scaffold:
        result["scaffolded"] = scaffold(Project(root), force=False)
    from .engine import Engine

    eng = Engine(Project(root))
    if not eng.project.state_path.exists():
        eng.save_state(eng.load_state())
    _out(result)


def cmd_scaffold(args):
    from .scaffold import scaffold

    _out({"written": scaffold(_project(args), force=args.force)})


def cmd_status(args):
    from .engine import Engine

    st = Engine(_project(args)).status()
    if args.json:
        _out(st)
        return
    icons = {"passed": "✔", "failed": "✘", "running": "▶", "stale": "↻", "interrupted": "⏸", "pending": "·"}
    for row in st["stages"]:
        extra = f" — {row['reason']}" if row.get("reason") else ""
        lock = f" [lock: {row['lock_owner']}]" if row.get("lock_owner") else ""
        print(f"{icons.get(row['status'], '?')} {row['id']:<18} {row['status']:<12} attempts={row['attempts']}{lock}{extra}")
    nxt = st["next"]
    print("\nnext:", json.dumps(nxt, ensure_ascii=False) if nxt else "pipeline complete")


def cmd_next(args):
    from .engine import Engine

    _out(Engine(_project(args)).next_stage())


def cmd_start(args):
    from .engine import Engine

    _out(Engine(_project(args)).start(args.stage, _owner(args), force=args.force, takeover=args.takeover))


def cmd_heartbeat(args):
    from .engine import Engine

    _out({"ok": Engine(_project(args)).heartbeat(args.stage, _owner(args))})


def cmd_gate(args):
    from .engine import Engine
    from .gates import run_gate
    from . import locking

    project = _project(args)
    eng = Engine(project)
    stage = eng.pipeline.get(args.stage)
    owner = _owner(args)
    with locking.state_mutex(project.locks_dir):
        state = eng.load_state()
    lock = locking.read_lock(project.locks_dir, stage.id)
    if lock is None:  # re-validation without a running stage still takes the lock to avoid concurrent gating
        locking.acquire(project.locks_dir, stage.id, owner, "gate", eng._stale_after())
    report = run_gate(project, stage, state)
    result = eng.record_gate(stage.id, owner, report)
    if not args.quiet:
        for c in report["checks"]:
            if not c["passed"]:
                log(f"  {'ERROR' if c['severity'] == 'error' else 'warn '} {c['id']}: {c['message']}")
                if c.get("details"):
                    log("        " + json.dumps(c["details"], ensure_ascii=False)[:800])
    result["summary"] = report["summary"]
    _out(result)
    return 0 if report["passed"] else 2


def cmd_check(args):
    from .engine import Engine

    _out({"changes": Engine(_project(args)).refresh()})


def cmd_revalidate(args):
    from .engine import Engine

    project = _project(args)
    eng = Engine(project)
    eng.refresh()
    results = []
    for stage in eng.pipeline.stages:
        st = eng.load_state()["stages"][stage.id]
        if st["status"] != "stale":
            continue
        args.stage = stage.id
        args.quiet = True
        rc = cmd_gate(args)
        results.append({"stage": stage.id, "passed": rc == 0})
        if rc != 0:
            break
    log(json.dumps(results))
    return 0 if all(r["passed"] for r in results) else 2


def cmd_fail(args):
    from .engine import Engine

    _out(Engine(_project(args)).fail(args.stage, _owner(args), args.reason))


def cmd_invalidate(args):
    from .engine import Engine

    _out({"stale": Engine(_project(args)).invalidate(args.stage, args.reason)})


def cmd_unlock(args):
    from .engine import Engine

    Engine(_project(args)).unlock(args.stage)
    _out({"unlocked": args.stage})


def cmd_validate(args):
    from .jsonio import read_json
    from .schemas_util import validate

    errors = validate(read_json(Path(args.file)), args.schema)
    _out({"valid": not errors, "errors": errors})
    return 0 if not errors else 2


def cmd_codegen(args):
    from .codegen import generate

    _out(generate(_project(args)))


def cmd_digest(args):
    from .hashing import source_digest

    _out({"source_digest": source_digest(_project(args).root)})


def cmd_report(args):
    from .reports import write_build_report, write_test_report

    project = _project(args)
    if args.kind == "build":
        _out(write_build_report(project, args.status, args.scheme, args.configuration, args.destination, args.started_at,
                                log=args.log or "", xcode_version=args.xcode_version or "", warnings=args.warnings, errors=args.errors))
    else:
        per_locale = dict(item.split("=", 1) for item in args.results)
        rep = write_test_report(project, {k: Path(v) for k, v in per_locale.items()}, args.destination or "", args.xcode_version or "")
        _out({k: rep[k] for k in ("status", "totals", "suites", "locales_tested")})
        return 0 if rep["status"] == "passed" else 2


def cmd_screenshots(args):
    from .jsonio import read_json
    from .screenshots import pipeline

    project = _project(args)
    if args.action == "collect":
        mvp = read_json(project.artifact("mvp", "mvp.json"))
        scenes = [s["id"] for s in mvp["screenshot_scenes"]]
        _out(pipeline.collect(project, Path(args.source), args.locale, args.device, scenes))
    elif args.action == "render":
        m = pipeline.render_all(project)
        _out({"items": len(m["items"]), "recipe_digest": m["recipe_digest"]})
    elif args.action == "devices":
        from .screenshots.compose import DEVICES

        cfg = project.config()
        _out({d: DEVICES[d] for d in cfg["screenshots"]["devices"]})


def cmd_asc(args):
    from .release import sync

    project = _project(args)
    if args.action == "plan":
        rep = sync(project, apply=False, simulate=args.simulate, fixture=args.fixture)
    else:
        cfg = project.config()
        if not args.simulate and cfg.get("asc", {}).get("mode") != "apply":
            raise SystemExit("asc.mode is 'dry-run' in factory/config.json; set it to 'apply' to write to App Store Connect "
                             "(or use --simulate for an offline end-to-end check)")
        rep = sync(project, apply=True, simulate=args.simulate)
    _out(rep)
    return 0 if not rep.get("validation_errors") and not rep.get("blocking") else 2


def cmd_testflight(args):
    from .release import testflight_verify

    project = _project(args)
    if args.action == "verify":
        _out(testflight_verify(project, simulate=args.simulate))


def cmd_evidence(args):
    from .approval import is_interactive
    from .jsonio import write_json_atomic
    from .timeutil import now_iso

    project = _project(args)
    if os.environ.get("CLAUDECODE") or not is_interactive():
        raise SystemExit("purchase-test evidence must be recorded by a human in an interactive terminal")
    cfg = project.config()
    print(f"Record manual purchase test for {cfg['app']['name']} {cfg['app']['version']} build {cfg['app']['build_number']}")
    tester = input("Tester name: ").strip()
    env = input("Environment [sandbox/testflight]: ").strip() or "testflight"
    cases = []
    for cid, desc in [("purchase", "Buy the Pro product"), ("restore", "Restore purchases on a fresh install"),
                      ("en_paywall", "Paywall correct in English"), ("ja_paywall", "Paywall correct in Japanese"),
                      ("cancel", "Cancel purchase sheet leaves app usable"), ("interrupted", "Interrupted purchase handled")]:
        res = input(f"{desc}? [pass/fail/n/a]: ").strip() or "n/a"
        note = input("  notes (optional): ").strip()
        cases.append({"id": cid, "result": res, **({"notes": note} if note else {})})
    rec = {"tester": tester, "tested_at": now_iso(), "build_number": str(cfg["app"]["build_number"]), "environment": env,
           "cases": cases, "recorded_interactively": True}
    write_json_atomic(project.reports / "purchase-test.json", rec)
    _out(rec)


def cmd_release(args):
    from . import release

    project = _project(args)
    if args.action == "readiness":
        r = release.write_readiness(project)
        _out({k: r[k] for k in ("ready", "readiness_digest", "summary")})
        return 0 if r["ready"] else 2
    if args.action == "submit":
        _out(release.submit(project, dry_run=args.dry_run, simulate=args.simulate))
    elif args.action == "publish":
        _out(release.publish(project, dry_run=args.dry_run, simulate=args.simulate))
    elif args.action == "simulate-apple-approval":
        release.simulate_apple_approval(project)
        _out({"simulated_state": "PENDING_DEVELOPER_RELEASE"})


def cmd_approve(args):
    from . import approval
    from .jsonio import read_json
    from .release import READINESS, compute_readiness

    project = _project(args)
    readiness = read_json(project.root / READINESS)
    if not readiness:
        raise SystemExit("run `app-factory release readiness` first")
    fresh = compute_readiness(project)
    if fresh["readiness_digest"] != readiness["readiness_digest"] or not fresh["ready"]:
        raise SystemExit("release is not ready or readiness.json is outdated; re-run `app-factory release readiness`")
    rec = approval.create(project, args.kind, fresh, approver=args.approver, note=args.note or "")
    _out({"approved": rec["kind"], "expires_at": rec["expires_at"]})


def cmd_doctor(args):
    from .project import Project

    checks = {}
    for mod in ("jsonschema", "PIL", "jwt", "requests", "cryptography"):
        try:
            __import__(mod)
            checks[f"python:{mod}"] = "ok"
        except ImportError:
            checks[f"python:{mod}"] = "MISSING (pip install -r requirements.txt)"
    for tool in ("xcodebuild", "xcrun", "xcodegen", "fastlane", "git"):
        checks[f"tool:{tool}"] = "ok" if shutil.which(tool) else "missing"
    from .asc.auth import credentials_present

    checks["env:asc_credentials"] = "present" if credentials_present() else "absent (dry-run only)"
    try:
        project = Project.find(Path(args.project) if args.project else None)
        checks["project"] = str(project.root)
        if shutil.which("git"):
            tracked = subprocess.run(["git", "ls-files", ".factory-tmp", "*.xcresult", "*.p8", "DerivedData", ".env"],
                                     cwd=project.root, capture_output=True, text=True).stdout.split()
            checks["git:no-temp-files-tracked"] = "ok" if not tracked else f"TRACKED: {tracked[:10]}"
        from .screenshots.compose import ComposeError, resolve_font

        for loc in project.config()["app"]["locales"]:
            try:
                checks[f"font:{loc}"] = resolve_font(loc, project.config())
            except ComposeError as exc:
                checks[f"font:{loc}"] = f"missing: {exc}"
    except Exception as exc:  # noqa: BLE001
        checks["project"] = f"not initialised ({exc})"
    _out(checks)


def cmd_hook(args):
    from . import guards

    return guards.main(args.hook)


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="app-factory", description="ios-app-factory workflow engine")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--project", help="app repository root (default: discover from cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="initialise factory metadata in an app repository")
    s.add_argument("--idea")
    s.add_argument("--idea-file")
    s.add_argument("--name", required=True)
    s.add_argument("--bundle-id", required=True)
    s.add_argument("--team-id")
    s.add_argument("--scaffold", action="store_true", help="also render the SwiftUI app template")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("scaffold", help="render the SwiftUI/SwiftData/StoreKit 2 template")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_scaffold)

    s = sub.add_parser("status")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)
    sub.add_parser("next").set_defaults(fn=cmd_next)

    for name, fn in (("start", cmd_start), ("heartbeat", cmd_heartbeat), ("gate", cmd_gate), ("fail", cmd_fail)):
        s = sub.add_parser(name)
        s.add_argument("stage")
        s.add_argument("--owner")
        if name == "start":
            s.add_argument("--force", action="store_true", help="re-run a passed stage")
            s.add_argument("--takeover", action="store_true", help="take over a lock held by another (dead) session")
        if name == "fail":
            s.add_argument("--reason", required=True)
        if name == "gate":
            s.add_argument("--quiet", action="store_true")
        s.set_defaults(fn=fn)

    sub.add_parser("check", help="detect changed artifacts and mark dependants stale").set_defaults(fn=cmd_check)
    s = sub.add_parser("revalidate", help="re-run gates of stale stages in order")
    s.add_argument("--owner")
    s.set_defaults(fn=cmd_revalidate)
    s = sub.add_parser("invalidate", help="spec change: mark a stage and its dependants stale")
    s.add_argument("stage")
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_invalidate)
    s = sub.add_parser("unlock")
    s.add_argument("stage")
    s.set_defaults(fn=cmd_unlock)

    s = sub.add_parser("validate", help="validate a JSON file against a factory schema")
    s.add_argument("file")
    s.add_argument("--schema", required=True)
    s.set_defaults(fn=cmd_validate)
    sub.add_parser("codegen", help="generate DesignTokens.swift, ProductCatalog.swift, Products.storekit").set_defaults(fn=cmd_codegen)
    sub.add_parser("digest", help="print the source digest").set_defaults(fn=cmd_digest)

    s = sub.add_parser("report", help="write build/test reports (used by scripts/xcode/*.sh)")
    rs = s.add_subparsers(dest="kind", required=True)
    b = rs.add_parser("build")
    for a in ("--status", "--scheme", "--configuration", "--destination", "--started-at"):
        b.add_argument(a, required=True)
    b.add_argument("--log")
    b.add_argument("--xcode-version")
    b.add_argument("--warnings", type=int, default=0)
    b.add_argument("--errors", type=int, default=0)
    t = rs.add_parser("tests")
    t.add_argument("results", nargs="+", help="LOCALE=path/to/test-results.json")
    t.add_argument("--destination")
    t.add_argument("--xcode-version")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("screenshots")
    s.add_argument("action", choices=["collect", "render", "devices"])
    s.add_argument("--source")
    s.add_argument("--locale")
    s.add_argument("--device")
    s.set_defaults(fn=cmd_screenshots)

    s = sub.add_parser("asc", help="App Store Connect sync (never submits)")
    s.add_argument("action", choices=["plan", "apply"])
    s.add_argument("--fixture", help="offline remote snapshot JSON for dry-run")
    s.add_argument("--simulate", action="store_true", help="use the built-in App Store Connect simulator")
    s.set_defaults(fn=cmd_asc)

    s = sub.add_parser("testflight")
    s.add_argument("action", choices=["verify"])
    s.add_argument("--simulate", action="store_true")
    s.set_defaults(fn=cmd_testflight)

    s = sub.add_parser("evidence", help="record manual purchase-test evidence (human, interactive)")
    s.add_argument("kind", choices=["purchase-test"])
    s.set_defaults(fn=cmd_evidence)

    s = sub.add_parser("release")
    s.add_argument("action", choices=["readiness", "submit", "publish", "simulate-apple-approval"])
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--simulate", action="store_true")
    s.set_defaults(fn=cmd_release)

    s = sub.add_parser("approve", help="HUMAN ONLY: approve submission/publication (interactive terminal)")
    s.add_argument("kind", choices=["submit", "publish"])
    s.add_argument("--approver")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_approve)

    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    s = sub.add_parser("hook", help="Claude Code hook entrypoints")
    s.add_argument("hook", choices=["guard-bash", "guard-files", "session-start"])
    s.set_defaults(fn=cmd_hook)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd != "hook":
        try:
            from .project import Project

            proj = Project.find(Path(args.project) if args.project else None, must_exist=False)
            if (proj.factory / "config.json").exists():
                set_log_file(proj.logs_dir / "factory.log")
        except Exception:  # noqa: BLE001
            pass
    try:
        rc = args.fn(args)
        return int(rc or 0)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        log(f"error: {type(exc).__name__}: {redact(str(exc))}", level="error")
        if os.environ.get("FACTORY_DEBUG"):
            import traceback

            log(redact(traceback.format_exc()), level="debug")
        return 1
