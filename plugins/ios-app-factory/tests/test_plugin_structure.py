"""The plugin's static wiring: pipeline ↔ agents ↔ skills ↔ schemas ↔ scripts."""
import json
import os

import yaml

from appfactory.gates import GATES
from appfactory.pipeline import load
from conftest import PLUGIN


def _frontmatter(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    return yaml.safe_load(text.split("---", 2)[1])


def test_manifest_and_marketplace():
    manifest = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())
    assert manifest["name"] == "ios-app-factory"
    market = json.loads((PLUGIN.parents[1] / ".claude-plugin/marketplace.json").read_text())
    assert market["plugins"][0]["source"] == "./plugins/ios-app-factory"


def test_every_stage_has_agent_skills_and_gate():
    agents = {p.stem: _frontmatter(p) for p in (PLUGIN / "agents").glob("*.md")}
    skills = {p.parent.name: _frontmatter(p) for p in (PLUGIN / "skills").glob("*/SKILL.md")}
    import appfactory.gates.planning, appfactory.gates.design, appfactory.gates.build  # noqa: F401
    import appfactory.gates.l10n, appfactory.gates.screenshots, appfactory.gates.release  # noqa: F401
    for stage in load().stages:
        assert stage.agent in agents, stage.id
        for s in stage.skills:
            assert s in skills, (stage.id, s)
        assert stage.gate in GATES, stage.id
    for name, fm in agents.items():
        assert fm["name"] == name and fm["description"]
        for s in fm.get("skills", []):
            assert s.split(":", 1)[1] in skills, (name, s)


def test_skill_frontmatter():
    for p in (PLUGIN / "skills").glob("*/SKILL.md"):
        fm = _frontmatter(p)
        assert fm["name"] == p.parent.name
        assert 20 < len(fm["description"]) <= 1536
        assert len(p.read_text().splitlines()) < 500
    approval = _frontmatter(PLUGIN / "skills/release-approval/SKILL.md")
    assert approval["disable-model-invocation"] is True


def test_schemas_are_valid_json_schema():
    import jsonschema

    for p in (PLUGIN / "lib/appfactory/schemas").glob("*.json"):
        jsonschema.validators.validator_for(json.loads(p.read_text())).check_schema(json.loads(p.read_text()))


def test_scripts_executable():
    for p in list((PLUGIN / "scripts/xcode").glob("*.sh")) + [PLUGIN / "bin/app-factory", PLUGIN / "hooks/run_hook.py"]:
        assert os.access(p, os.X_OK), p


def test_template_has_no_unknown_placeholders():
    import re

    known = {"__APP_NAME__", "__PROJECT_NAME__", "__BUNDLE_ID__", "__TEAM_ID__", "__MIN_IOS__", "__VERSION__", "__BUILD_NUMBER__"}
    for p in (PLUGIN / "templates/ios-app").rglob("*"):
        if p.is_file() and p.suffix != ".png":
            found = set(re.findall(r"__[A-Z_]+__", p.read_text(encoding="utf-8")))
            assert found <= known, (p, found - known)
