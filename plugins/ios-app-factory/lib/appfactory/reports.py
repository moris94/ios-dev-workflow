"""Convert xcodebuild / xcresulttool output into factory reports."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .hashing import source_digest
from .jsonio import read_json, write_json_atomic
from .project import Project
from .timeutil import now_iso

RESULT_MAP = {"Passed": "passed", "Failed": "failed", "Skipped": "skipped", "Expected Failure": "expectedFailure"}


def write_build_report(project: Project, status: str, scheme: str, configuration: str, destination: str,
                       started_at: str, log: str = "", xcode_version: str = "", warnings: int = 0, errors: int = 0) -> dict:
    report = {"status": status, "scheme": scheme, "configuration": configuration, "destination": destination,
              "xcode_version": xcode_version, "source_digest": source_digest(project.root), "started_at": started_at,
              "finished_at": now_iso(), "warnings": warnings, "errors": errors, "log": log}
    write_json_atomic(project.reports / "build.json", report)
    return report


def _walk(nodes, bundle_kind=None, bundle=None) -> List[dict]:
    out = []
    for n in nodes or []:
        kind = n.get("nodeType", "")
        b_kind, b_name = bundle_kind, bundle
        if kind in ("Unit test bundle", "UI test bundle"):
            b_kind = "ui" if kind.startswith("UI") else "unit"
            b_name = n.get("name")
        if kind == "Test Case":
            out.append({"name": n.get("name", "?"), "target": b_name or "?", "suite": b_kind or "unit",
                        "result": RESULT_MAP.get(n.get("result", ""), "failed")})
        out.extend(_walk(n.get("children"), b_kind, b_name))
    return out


def parse_xcresult_tests(path: Path) -> List[dict]:
    """Parse `xcrun xcresulttool get test-results tests --path X.xcresult` (Xcode 16+) JSON."""
    data = read_json(path)
    if data is None:
        raise FileNotFoundError(path)
    return _walk(data.get("testNodes"))


def write_test_report(project: Project, per_locale: Dict[str, Path], destination: str = "", xcode_version: str = "",
                      coverage=None) -> dict:
    tests, suites = [], {"unit": {"passed": 0, "failed": 0, "skipped": 0}, "ui": {"passed": 0, "failed": 0, "skipped": 0}}
    for locale, path in per_locale.items():
        for t in parse_xcresult_tests(Path(path)):
            t["locale"] = locale
            tests.append(t)
            bucket = suites[t.pop("suite")]
            key = {"passed": "passed", "expectedFailure": "passed", "failed": "failed", "skipped": "skipped"}[t["result"]]
            bucket[key] += 1
    totals = {k: suites["unit"][k] + suites["ui"][k] for k in ("passed", "failed", "skipped")}
    report = {"status": "passed" if totals["failed"] == 0 and totals["passed"] > 0 else "failed",
              "source_digest": source_digest(project.root), "totals": totals, "suites": suites,
              "locales_tested": sorted(per_locale), "tests": tests, "coverage": coverage,
              "finished_at": now_iso(), "xcode_version": xcode_version, "destination": destination}
    write_json_atomic(project.reports / "tests.json", report)
    return report
