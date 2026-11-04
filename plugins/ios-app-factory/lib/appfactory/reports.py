"""Convert xcodebuild / xcresulttool output into factory reports.

Test reports support *partial re-runs*: after a full run, only the failed cases may be
re-run when the failure was caused by the environment (nothing changed) or by a defect in
the test code (only test files changed; every test of the changed test classes is re-run).
An app-code change always requires a full run.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .hashing import app_digest, source_digest, test_file_digests
from .jsonio import read_json, write_json_atomic
from .project import Project
from .timeutil import now_iso

RESULT_MAP = {"Passed": "passed", "Failed": "failed", "Skipped": "skipped", "Expected Failure": "expectedFailure"}
RERUN_REASONS = ("environment", "test-defect")
DEFAULT_MAX_PARTIAL_RERUNS = 2


class ReportError(RuntimeError):
    pass


def write_build_report(project: Project, status: str, scheme: str, configuration: str, destination: str,
                       started_at: str, log: str = "", xcode_version: str = "", warnings: int = 0, errors: int = 0) -> dict:
    report = {"status": status, "scheme": scheme, "configuration": configuration, "destination": destination,
              "xcode_version": xcode_version, "source_digest": source_digest(project.root), "started_at": started_at,
              "finished_at": now_iso(), "warnings": warnings, "errors": errors, "log": log}
    write_json_atomic(project.reports / "build.json", report)
    return report


def _walk(nodes, bundle_kind=None, bundle=None, suite=None) -> List[dict]:
    out = []
    for n in nodes or []:
        kind = n.get("nodeType", "")
        b_kind, b_name, s_name = bundle_kind, bundle, suite
        if kind in ("Unit test bundle", "UI test bundle"):
            b_kind = "ui" if kind.startswith("UI") else "unit"
            b_name = n.get("name")
        if kind == "Test Suite":
            s_name = n.get("name")
        if kind == "Test Case":
            name = n.get("name", "?")
            method = name[:-2] if name.endswith("()") else name
            ident = "/".join(p for p in (b_name, s_name, method) if p)
            out.append({"id": ident, "name": name, "target": b_name or "?", "suite_name": s_name, "suite": b_kind or "unit",
                        "result": RESULT_MAP.get(n.get("result", ""), "failed")})
        out.extend(_walk(n.get("children"), b_kind, b_name, s_name))
    return out


def parse_xcresult_tests(path: Path) -> List[dict]:
    """Parse `xcrun xcresulttool get test-results tests --path X.xcresult` (Xcode 16+) JSON."""
    data = read_json(path)
    if data is None:
        raise FileNotFoundError(path)
    return _walk(data.get("testNodes"))


def _summarise(tests: List[dict]) -> Tuple[dict, dict]:
    suites = {"unit": {"passed": 0, "failed": 0, "skipped": 0}, "ui": {"passed": 0, "failed": 0, "skipped": 0}}
    for t in tests:
        key = {"passed": "passed", "expectedFailure": "passed", "failed": "failed", "skipped": "skipped"}[t["result"]]
        suites[t["kind"]][key] += 1
    totals = {k: suites["unit"][k] + suites["ui"][k] for k in ("passed", "failed", "skipped")}
    return suites, totals


def _collect(per_locale: Dict[str, Path]) -> List[dict]:
    tests = []
    for locale, path in per_locale.items():
        for t in parse_xcresult_tests(Path(path)):
            t["locale"] = locale
            t["kind"] = t.pop("suite")
            tests.append(t)
    return tests


def _finish(project: Project, tests: List[dict], locales: List[str], extra: dict) -> dict:
    suites, totals = _summarise(tests)
    report = {"status": "passed" if totals["failed"] == 0 and totals["passed"] > 0 else "failed",
              "source_digest": source_digest(project.root), "app_digest": app_digest(project.root),
              "test_files": test_file_digests(project.root), "totals": totals, "suites": suites,
              "locales_tested": sorted(locales), "tests": tests, "finished_at": now_iso(), **extra}
    write_json_atomic(project.reports / "tests.json", report)
    return report


def write_test_report(project: Project, per_locale: Dict[str, Path], destination: str = "", xcode_version: str = "",
                      coverage=None) -> dict:
    """Full run: replaces any previous report."""
    tests = _collect(per_locale)
    run = {"kind": "full", "at": now_iso(), "source_digest": source_digest(project.root),
           "app_digest": app_digest(project.root), "tests": len(tests)}
    return _finish(project, tests, list(per_locale), {"coverage": coverage, "xcode_version": xcode_version,
                                                      "destination": destination, "runs": [run], "flaky": [],
                                                      "removed_failing_tests": []})


# ------------------------------------------------------------------ partial re-runs
_CLASS_RE = re.compile(r"(?:final\s+)?(?:class|struct)\s+([A-Za-z_]\w*)\b")


def _changed_test_classes(project: Project, base: dict) -> Dict[str, str]:
    """{class name: target} for test classes in test files changed since the full run."""
    before = base.get("test_files") or {}
    now = test_file_digests(project.root)
    changed = [p for p, sha in now.items() if before.get(p) != sha and p.endswith(".swift")]
    out = {}
    for rel in changed:
        text = (project.root / rel).read_text(encoding="utf-8", errors="replace")
        if "XCTestCase" not in text and "@Test" not in text and "@Suite" not in text:
            continue
        for name in _CLASS_RE.findall(text):
            out[name] = rel.split("/", 1)[0]
    return out


def max_partial_reruns(project: Project) -> int:
    return int(project.config().get("testing", {}).get("max_partial_reruns", DEFAULT_MAX_PARTIAL_RERUNS))


def rerun_eligibility(project: Project, reason: str, base: Optional[dict] = None) -> List[str]:
    """Reasons why a partial re-run is NOT allowed (empty list = allowed)."""
    base = base if base is not None else read_json(project.reports / "tests.json")
    problems = []
    if reason not in RERUN_REASONS:
        problems.append(f"reason must be one of {RERUN_REASONS} (app defects need a full run)")
    if not base or not base.get("runs"):
        return problems + ["no previous full test run to re-run from"]
    if base["totals"]["failed"] == 0:
        problems.append("the last run has no failed tests")
    full = base["runs"][0]
    if app_digest(project.root) != full["app_digest"]:
        problems.append("app sources (project.yml / App/**) changed since the full run — run the full suite")
    if reason == "environment" and source_digest(project.root) != base["source_digest"]:
        problems.append("reason 'environment' requires no source changes since the last run (test code changed? use 'test-defect')")
    if reason == "test-defect" and source_digest(project.root) == base["source_digest"]:
        problems.append("reason 'test-defect' requires a fix in the test code (no test file changed)")
    used = sum(1 for r in base["runs"] if r["kind"] == "rerun")
    if used >= max_partial_reruns(project):
        problems.append(f"{used} partial re-runs already used (max {max_partial_reruns(project)}) — run the full suite")
    return problems


def rerun_plan(project: Project, reason: str) -> Dict[str, List[str]]:
    """{locale: [-only-testing identifiers]} that a partial re-run must execute."""
    base = read_json(project.reports / "tests.json")
    problems = rerun_eligibility(project, reason, base)
    if problems:
        raise ReportError("partial re-run not allowed: " + "; ".join(problems))
    plan: Dict[str, Set[str]] = {}
    for t in base["tests"]:
        if t["result"] == "failed":
            plan.setdefault(t["locale"], set()).add(t["id"])
    if reason == "test-defect":
        for cls, target in _changed_test_classes(project, base).items():
            for locale in base["locales_tested"]:
                plan.setdefault(locale, set()).add(f"{target}/{cls}")
    return {loc: sorted(ids) for loc, ids in plan.items()}


def _covers(ident: str, plan_ids: List[str]) -> bool:
    return any(ident == p or ident.startswith(p + "/") for p in plan_ids)


def write_rerun_report(project: Project, per_locale: Dict[str, Path], reason: str, note: str) -> dict:
    """Merge a partial re-run into the last report (latest result per test id + locale wins)."""
    if len((note or "").strip()) < 10:
        raise ReportError("--note must explain the failure cause (>= 10 characters)")
    base = read_json(project.reports / "tests.json")
    plan = rerun_plan(project, reason)
    rerun = _collect(per_locale)
    got = {(t["id"], t["locale"]) for t in rerun}
    current_test_text = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                                  for p in project.root.glob("App*Tests/**/*.swift"))
    removed, missing = [], []
    for t in base["tests"]:
        if t["result"] == "failed" and (t["id"], t["locale"]) not in got:
            method = t["id"].rsplit("/", 1)[-1]
            if reason == "test-defect" and method not in current_test_text:
                removed.append(f"{t['id']} [{t['locale']}]")
            else:
                missing.append(f"{t['id']} [{t['locale']}]")
    for locale, ids in plan.items():
        for p in ids:
            if p.count("/") == 1 and not any(_covers(i, [p]) for i, loc in got if loc == locale):
                missing.append(f"{p} [{locale}] (changed test class)")
    if missing:
        raise ReportError("partial re-run did not cover required tests: " + ", ".join(missing[:20]))
    removed_ids = {r.rsplit(" [", 1)[0] for r in removed}
    merged = [t for t in base["tests"] if (t["id"], t["locale"]) not in got and t["id"] not in removed_ids
              and not (reason == "test-defect" and any(_covers(t["id"], [p]) for p in plan.get(t["locale"], []) if p.count("/") == 1))]
    merged += rerun
    before = {(t["id"], t["locale"]): t["result"] for t in base["tests"]}
    flaky = sorted({f"{t['id']} [{t['locale']}]" for t in rerun
                    if reason == "environment" and before.get((t["id"], t["locale"])) == "failed" and t["result"] == "passed"})
    run = {"kind": "rerun", "at": now_iso(), "reason": reason, "note": note.strip(),
           "locales": sorted(per_locale), "plan": plan, "tests": len(rerun),
           "source_digest": source_digest(project.root), "app_digest": app_digest(project.root)}
    extra = {k: base.get(k) for k in ("coverage", "xcode_version", "destination")}
    extra.update({"runs": base["runs"] + [run], "flaky": sorted(set(base.get("flaky", [])) | set(flaky)),
                  "removed_failing_tests": sorted(set(base.get("removed_failing_tests", [])) | set(removed))})
    return _finish(project, merged, base["locales_tested"], extra)
