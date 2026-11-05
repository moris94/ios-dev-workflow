"""fastlane release backend (default; config release.backend = "fastlane").

* metadata + screenshots → `deliver` (lane sync_metadata) from a tree generated out of
  aso.json / mvp.json / config / screenshot manifest (.factory-tmp/fastlane, reproducible)
* TestFlight build state → lane build_status
* App Review submission → lane submit_review; release → lane release_version
  (both re-verify the human approval inside fastlane, fail-closed)

fastlane has no in-app purchase management and `deliver`'s price_tier relies on Apple's
deprecated price-tier endpoints, so IAPs (creation, localizations, price, availability,
review screenshot), the app price and first-time IAP submission stay on the App Store
Connect API even with this backend.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List

from .hashing import sha256_bytes, sha256_json
from .jsonio import read_json
from .project import PLUGIN_ROOT, Project
from .redact import redact

BACKENDS = ("fastlane", "api")
LANES = {"sync": "sync_metadata", "status": "build_status", "submit": "submit_review", "publish": "release_version"}
API_KINDS_UNDER_FASTLANE = ("iap.", "iap_localization.", "app.price_schedule")


class FastlaneError(RuntimeError):
    pass


def backend(project: Project) -> str:
    value = (project.config().get("release") or {}).get("backend", "fastlane")
    if value not in BACKENDS:
        raise FastlaneError(f"release.backend must be one of {BACKENDS}, got {value!r}")
    return value


def api_kept(op_kind: str) -> bool:
    return op_kind.startswith(API_KINDS_UNDER_FASTLANE)


def deliver_files(project: Project, desired: dict) -> Dict[str, bytes]:
    """Relative path (under .factory-tmp/fastlane) → bytes, in deliver's directory layout."""
    files: Dict[str, bytes] = {}

    def put(rel: str, text: str) -> None:
        files[rel] = (text or "").encode("utf-8")

    put("metadata/primary_category.txt", desired["app_info"]["primaryCategory"])
    for loc, info in desired["app_info"]["localizations"].items():
        put(f"metadata/{loc}/name.txt", info["name"])
        put(f"metadata/{loc}/subtitle.txt", info["subtitle"])
        put(f"metadata/{loc}/privacy_url.txt", info["privacyPolicyUrl"])
    for loc, v in desired["version"]["localizations"].items():
        for field, fname in (("description", "description"), ("keywords", "keywords"),
                             ("promotionalText", "promotional_text"), ("supportUrl", "support_url"),
                             ("marketingUrl", "marketing_url"), ("whatsNew", "release_notes")):
            if v.get(field):
                put(f"metadata/{loc}/{fname}.txt", v[field])
        for _dt, shot_set in sorted(v.get("screenshot_sets", {}).items()):
            for shot in shot_set["screenshots"]:
                files[f"screenshots/{loc}/{shot['fileName']}"] = (project.root / shot["file"]).read_bytes()
    return files


def digest(files: Dict[str, bytes]) -> str:
    return sha256_json({rel: sha256_bytes(data) for rel, data in sorted(files.items())})


def workdir(project: Project) -> Path:
    return project.tmp / "fastlane"


def write_tree(project: Project, files: Dict[str, bytes]) -> dict:
    root = workdir(project)
    for sub in ("metadata", "screenshots"):
        shutil.rmtree(root / sub, ignore_errors=True)
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return {"metadata_path": str(root / "metadata"), "screenshots_path": str(root / "screenshots"),
            "digest": digest(files), "files": sorted(files)}


def _command(project: Project, lane: str) -> List[str]:
    if (project.root / "Gemfile").exists() and shutil.which("bundle"):
        return ["bundle", "exec", "fastlane", "ios", lane]
    if shutil.which("fastlane"):
        return ["fastlane", "ios", lane]
    raise FastlaneError("fastlane not found: `bundle install` (Gemfile) or `brew install fastlane`")


def run_lane(project: Project, lane: str, extra_env: Dict[str, str]) -> dict:
    """Run a Fastfile lane; returns the JSON result the lane wrote. Logs stay in .factory-tmp."""
    cfg = project.config()
    result_file = workdir(project) / f"result-{lane}.json"
    result_file.parent.mkdir(parents=True, exist_ok=True)
    result_file.unlink(missing_ok=True)
    env = dict(os.environ)
    env.update({
        "APP_FACTORY_BIN": str(PLUGIN_ROOT / "bin" / "app-factory"),
        "APP_FACTORY_PROJECT": str(project.root),
        "FACTORY_RESULT_FILE": str(result_file),
        "FACTORY_APP_VERSION": cfg["app"]["version"],
        "FACTORY_BUILD_NUMBER": str(cfg["app"]["build_number"]),
        "FASTLANE_SKIP_UPDATE_CHECK": "1", "FASTLANE_HIDE_TIMESTAMP": "1", "FASTLANE_OPT_OUT_USAGE": "1",
    })
    env.update(extra_env)
    log = project.logs_dir / f"fastlane-{lane}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as fh:
        rc = subprocess.call(_command(project, lane), cwd=project.root, env=env, stdout=fh, stderr=subprocess.STDOUT)
    if rc != 0:
        tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:])
        raise FastlaneError(f"fastlane {lane} failed (exit {rc}, log {project.rel(log)}):\n{redact(tail)}")
    result = read_json(result_file)
    if not result:
        raise FastlaneError(f"fastlane {lane} finished without writing its result file")
    return result
