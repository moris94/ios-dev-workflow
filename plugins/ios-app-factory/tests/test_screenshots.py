import pytest
from PIL import Image

from appfactory.jsonio import read_json, write_json_atomic
from appfactory.screenshots import compose
from appfactory.screenshots.pipeline import collect, render_all
from conftest import copy_artifacts
from helpers_sim import fake_raw_captures

pytestmark = pytest.mark.skipif(not any(__import__("os").path.exists(p) for p in compose.FONT_CANDIDATES["ja"]),
                                reason="no CJK font installed")


@pytest.fixture
def shots(project):
    copy_artifacts(project, "mvp", "design", "aso")
    fake_raw_captures(project)
    return project


def test_render_exact_size_rgb_and_deterministic(shots):
    m = render_all(shots)
    assert len(m["items"]) == 2 * 1 * 3
    for item in m["items"]:
        with Image.open(shots.root / item["final"]) as im:
            assert im.size == (1320, 2868) and im.mode == "RGB"
    first = (shots.root / m["items"][0]["final"]).read_bytes()
    m2 = render_all(shots)
    assert (shots.root / m2["items"][0]["final"]).read_bytes() == first
    assert m2["recipe_digest"] == m["recipe_digest"]


def test_caption_change_changes_recipe(shots):
    m = render_all(shots)
    p = shots.artifact("aso", "aso.json")
    d = read_json(p)
    d["locales"]["ja"]["screenshot_captions"]["home"]["headline"] = "静かにメモ"
    write_json_atomic(p, d)
    from appfactory.screenshots.pipeline import current_recipe_digest

    assert current_recipe_digest(shots) != m["recipe_digest"]


def test_font_without_japanese_glyphs_is_rejected(shots):
    latin = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if not __import__("os").path.exists(latin):
        pytest.skip("DejaVu not installed")
    assert compose.missing_glyphs(latin, "静かなメモ")
    cfg = shots.config()
    cfg["screenshots"]["fonts"] = {"ja": latin}
    with pytest.raises(compose.ComposeError, match="lacks glyphs"):
        compose.compose(shots.screenshots_dir / "raw/ja/iphone_6_9/home.png", "iphone_6_9", "ja",
                        {"headline": "静かなメモ"}, read_json(shots.artifact("design", "design.json"))["screenshot_style"], cfg)


def test_collect_from_attachment_export(shots, tmp_path):
    src = tmp_path / "export"
    src.mkdir()
    for scene in ("home", "editor", "pro"):
        Image.new("RGB", (1320, 2868), (1, 2, 3)).save(src / f"{scene}_0_ABC.png")
    manifest = [{"testIdentifier": "ScreenshotTests/test01Home()", "attachments": [
        {"exportedFileName": f"{s}_0_ABC.png", "suggestedHumanReadableName": f"scene-{s}_0_ABC.png"}]} for s in ("home", "editor", "pro")]
    (src / "manifest.json").write_text(__import__("json").dumps(manifest))
    out = collect(shots, src, "en-US", "iphone_6_9", ["home", "editor", "pro"])
    assert set(out) == {"home", "editor", "pro"}


def test_collect_reports_missing_scene(shots, tmp_path):
    src = tmp_path / "export2"
    src.mkdir()
    Image.new("RGB", (10, 10)).save(src / "scene-home.png")
    with pytest.raises(compose.ComposeError, match="missing"):
        collect(shots, src, "en-US", "iphone_6_9", ["home", "editor"])
