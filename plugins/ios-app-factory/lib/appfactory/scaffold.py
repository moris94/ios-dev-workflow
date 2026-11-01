"""`init` (factory metadata) and `scaffold` (SwiftUI app template) for an app repository."""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Dict, List

from .jsonio import write_json_atomic, write_text_atomic
from .project import TEMPLATE_DIR, Project

GITIGNORE_BLOCK = """
# --- ios-app-factory (generated) ---
.factory-tmp/
*.xcodeproj/
!*.xcodeproj/project.xcworkspace/xcshareddata/
DerivedData/
build/
*.xcresult
*.ipa
*.dSYM.zip
fastlane/report.xml
fastlane/Preview.html
fastlane/test_output/
fastlane/screenshots/
*.p8
.env
.env.*
.DS_Store
xcuserdata/
# --- end ios-app-factory ---
"""

TEXT_SUFFIXES = {".swift", ".yml", ".yaml", ".json", ".xcstrings", ".storekit", ".plist", ".xcprivacy", ".md", ".rb", "", ".txt",
                 ".entitlements", ".gitignore"}


def default_config(name: str, bundle_id: str, team_id: str = None) -> dict:
    project_name = re.sub(r"[^A-Za-z0-9]", "", name) or "App"
    return {
        "$schema": "https://ios-app-factory/schemas/config.schema.json",
        "app": {"name": name, "project_name": project_name, "scheme": project_name, "bundle_id": bundle_id,
                "team_id": team_id, "sku": bundle_id.replace(".", "-"), "version": "1.0.0", "build_number": 1,
                "primary_locale": "en-US", "locales": ["en-US", "ja"], "min_ios": "17.0", "first_release": True,
                "links": {"support": None, "privacy_policy": None,
                          "terms": "https://www.apple.com/legal/internet-services/itunes/dev/stdeula/"}},
        "research": {"min_competitors": 5, "min_sources": 8},
        "asc": {"mode": "dry-run", "app_id": None, "price_base_territory": "USA", "remote_fixture": None},
        "screenshots": {"devices": ["iphone_6_9"], "fonts": {}},
        "release": {"require_manual_purchase_test": True, "approval_ttl_hours": 72, "release_type": "MANUAL"},
        "locks": {"stale_after_minutes": 30},
    }


def ensure_gitignore(root: Path) -> bool:
    gi = root / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if "# --- ios-app-factory" in text:
        return False
    write_text_atomic(gi, text.rstrip("\n") + ("\n" if text else "") + GITIGNORE_BLOCK.lstrip("\n"))
    return True


def init(root: Path, idea: str, name: str, bundle_id: str, team_id: str = None, force: bool = False) -> Dict[str, str]:
    project = Project(root)
    out = {}
    if project.config_path.exists() and not force:
        raise FileExistsError(f"{project.config_path} exists (use --force to overwrite config)")
    write_json_atomic(project.config_path, default_config(name, bundle_id, team_id))
    out["config"] = project.rel(project.config_path)
    idea_path = project.factory / "idea.md"
    write_text_atomic(idea_path, f"# App idea\n\n{idea.strip()}\n")
    out["idea"] = project.rel(idea_path)
    for d in ("artifacts", "gates", "reports", "approvals", "asc", "screenshots"):
        (project.factory / d).mkdir(parents=True, exist_ok=True)
        keep = project.factory / d / ".gitkeep"
        if not any((project.factory / d).iterdir()):
            keep.write_text("")
    project.tmp.mkdir(exist_ok=True)
    out["gitignore"] = "updated" if ensure_gitignore(project.root) else "unchanged"
    return out


def _render(text: str, values: Dict[str, str]) -> str:
    for k, v in values.items():
        text = text.replace(k, v)
    return text


def scaffold(project: Project, force: bool = False) -> List[str]:
    cfg = project.config()["app"]
    values = {
        "__APP_NAME__": cfg["name"],
        "__PROJECT_NAME__": cfg["project_name"],
        "__BUNDLE_ID__": cfg["bundle_id"],
        "__TEAM_ID__": cfg.get("team_id") or "",
        "__MIN_IOS__": cfg["min_ios"],
        "__VERSION__": cfg["version"],
        "__BUILD_NUMBER__": str(cfg["build_number"]),
    }
    src_root = TEMPLATE_DIR / "ios-app"
    written = []
    for src in sorted(src_root.rglob("*")):
        if src.is_dir():
            continue
        rel = Path(_render(src.relative_to(src_root).as_posix(), values))
        if rel.name.endswith(".tmpl"):
            rel = rel.with_name(rel.name[:-5])
        dest = project.root / rel
        if dest.exists() and not force:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in TEXT_SUFFIXES or src.name.endswith(".tmpl"):
            dest.write_text(_render(src.read_text(encoding="utf-8"), values), encoding="utf-8")
        else:
            shutil.copyfile(src, dest)
        written.append(rel.as_posix())
    return written
