"""App icon and combined support/privacy page stages."""
import json

import pytest
from PIL import Image

from appfactory import icon, support_page as sp
from appfactory.engine import Engine
from appfactory.gates import run_gate
from appfactory.jsonio import read_json, write_json_atomic
from conftest import HELP_URL, copy_artifacts, pass_planning, pass_stage, run, run_json

EMAIL = "help@stillnote.example"


def _failed(project, stage):
    eng = Engine(project)
    rep = run_gate(project, eng.pipeline.get(stage), eng.load_state())
    return {c["id"] for c in rep["checks"] if not c["passed"] and c["severity"] == "error"}


def _clear_links(project):
    cfg = project.config()
    cfg["app"]["links"]["support"] = None
    cfg["app"]["links"]["privacy_policy"] = None
    write_json_atomic(project.config_path, cfg)


# ------------------------------------------------------------------ app icon
@pytest.fixture
def icon_ready(project):
    pass_planning(project, until="aso")
    copy_artifacts(project, "app_icon")
    return project


def test_icon_render_variants_and_contents(icon_ready):
    out = icon.render(icon_ready)
    assert len(out) == 4
    d = icon_ready.root / icon.ICON_DIR
    for name in icon.VARIANTS.values():
        with Image.open(d / name) as im:
            assert im.size == (1024, 1024) and im.mode == "RGB"
    contents = json.loads((d / "Contents.json").read_text())
    appearances = [i.get("appearances", [{}])[0].get("value") for i in contents["images"]]
    assert appearances == [None, "dark", "tinted"]
    assert icon.render(icon_ready)[icon.APP_ICON] == "unchanged"  # deterministic


def test_icon_gate_passes_for_sample(icon_ready):
    icon.render(icon_ready)
    pass_stage(icon_ready, "app_icon")


def test_icon_gate_detects_problems(icon_ready):
    p = icon_ready.artifact("app_icon", "icon.json")
    spec = read_json(p)
    spec["layers"][0]["fill"] = "#FF00FF"                 # off-palette, low-contrast glyph
    spec["concept"]["derived_from_principles"] = ["P9"]   # not in charter
    spec["aso"]["keywords_reflected"] = ["blockchain"]    # not an ASO keyword
    spec["app_name"] = "Other"
    write_json_atomic(p, spec)
    failed = _failed(icon_ready, "app_icon")
    assert {"palette.from-design", "concept.charter", "aso.keywords", "aso.name", "assets.current"} <= failed


def test_icon_gate_rejects_tiny_motif(icon_ready):
    p = icon_ready.artifact("app_icon", "icon.json")
    spec = read_json(p)
    spec["layers"] = [{"shape": "circle", "role": "glyph", "center": [0.5, 0.5], "radius": 0.05, "fill": "#F7F8F5"}]
    write_json_atomic(p, spec)
    icon.render(icon_ready)
    assert "legibility.coverage" in _failed(icon_ready, "app_icon")


def test_implementation_needs_app_icon(project):
    pass_planning(project, until="aso")
    nxt = Engine(project).next_stage()
    assert nxt["id"] == "app_icon"


# ------------------------------------------------------------- support page
@pytest.fixture
def page_project(project, monkeypatch):
    pass_planning(project, until="design")
    _clear_links(project)
    monkeypatch.setenv(sp.EMAIL_ENV, EMAIL)
    monkeypatch.setattr(sp, "check_url", lambda url, timeout=15: 200)
    return project


def test_draft_keeps_email_out_of_repo(page_project, capsys):
    rc, st = run_json(page_project.root, capsys, "support-page", "status")
    assert st["links_user_specified"] is False and st["email_env_set"] is True
    assert run(page_project.root, "support-page", "draft") == 0
    text = page_project.artifact("support_page", "page.md").read_text()
    assert EMAIL not in text and text.count(sp.PLACEHOLDER) >= 2
    assert "## Privacy Policy" in text and "## プライバシーポリシー" in text and "購入を復元" in text
    rc, rendered = run_json(page_project.root, capsys, "support-page", "render")
    body = (page_project.root / rendered["rendered"]).read_text()
    assert EMAIL in body and sp.PLACEHOLDER not in body
    assert ".factory-tmp" in rendered["rendered"]


def test_record_sets_both_links_and_gate_passes(page_project, capsys):
    run(page_project.root, "support-page", "draft")
    run(page_project.root, "support-page", "render")
    rc, pub = run_json(page_project.root, capsys, "support-page", "record", "--url", HELP_URL,
                       "--provider", "notion", "--notion-page-id", "abc123")
    assert rc == 0 and pub["http_status"] == 200 and pub["notion_page_id"] == "abc123"
    assert EMAIL not in json.dumps(pub)
    links = page_project.config()["app"]["links"]
    assert links["support"] == links["privacy_policy"] == HELP_URL
    pass_stage(page_project, "support_page")
    copy_artifacts(page_project, "aso")
    pass_stage(page_project, "aso")  # store URLs == the published page


def test_editing_page_requires_republish(page_project):
    run(page_project.root, "support-page", "draft")
    sp.record(page_project, HELP_URL, "notion")
    pass_stage(page_project, "support_page")
    p = page_project.artifact("support_page", "page.md")
    p.write_text(p.read_text() + "\nNew FAQ entry.\n")
    assert "publication.current" in _failed(page_project, "support_page")
    assert Engine(page_project).refresh()[0]["stage"] == "support_page"


def test_hardcoded_email_is_rejected(page_project):
    run(page_project.root, "support-page", "draft")
    sp.record(page_project, HELP_URL, "notion")
    p = page_project.artifact("support_page", "page.md")
    p.write_text(p.read_text().replace(sp.PLACEHOLDER, EMAIL, 1))
    assert "page.no-literal-email" in _failed(page_project, "support_page")


def test_missing_email_env_blocks_render(page_project, monkeypatch):
    run(page_project.root, "support-page", "draft")
    monkeypatch.delenv(sp.EMAIL_ENV)
    with pytest.raises(sp.SupportPageError, match="FACTORY_SUPPORT_EMAIL"):
        sp.render(page_project)


def test_unreachable_page_fails_gate(page_project, monkeypatch):
    run(page_project.root, "support-page", "draft")
    monkeypatch.setattr(sp, "check_url", lambda url, timeout=15: 404)
    sp.record(page_project, HELP_URL, "notion")
    assert "publication.reachable" in _failed(page_project, "support_page")


def test_user_specified_links_skip_generation(project, capsys):
    pass_planning(project, until="design")  # conftest config already has the human's own links
    rc, st = run_json(project.root, capsys, "support-page", "status")
    assert st["links_user_specified"] is True
    with pytest.raises(SystemExit):
        run(project.root, "support-page", "draft")
    assert run(project.root, "support-page", "use-existing") == 0
    pass_stage(project, "support_page")
