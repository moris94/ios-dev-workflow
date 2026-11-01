import json
import os
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "lib"))

from appfactory import cli  # noqa: E402
from appfactory.jsonio import read_json, write_json_atomic  # noqa: E402
from appfactory.project import Project  # noqa: E402

SAMPLE = PLUGIN / "examples" / "sample-app"
LINKS = {"support": "https://fixtures.example.org/stillnote/support",
         "privacy_policy": "https://fixtures.example.org/stillnote/privacy",
         "terms": "https://www.apple.com/legal/internet-services/itunes/dev/stdeula/"}


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_PRIVATE_KEY_PATH",
              "ASC_PRIVATE_KEY", "ASC_PRIVATE_KEY_BASE64", "APP_FACTORY_PROJECT", "FACTORY_REHEARSAL", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FACTORY_APPROVER_KEY_PATH", str(tmp_path / "approver-home" / "approver.key"))


def run(project_root: Path, *args) -> int:
    return cli.main(["--project", str(project_root), *args])


def run_json(project_root: Path, capsys, *args):
    capsys.readouterr()
    rc = run(project_root, *args)
    out = capsys.readouterr().out
    return rc, (json.loads(out) if out.strip() else None)


@pytest.fixture
def project(tmp_path) -> Project:
    root = tmp_path / "app"
    root.mkdir()
    assert run(root, "init", "--idea", "A calm, minimal notes app", "--name", "Stillnote",
               "--bundle-id", "com.example.stillnote") == 0
    cfg = read_json(root / "factory/config.json")
    cfg["app"]["links"] = dict(LINKS)
    write_json_atomic(root / "factory/config.json", cfg)
    return Project(root)


def copy_artifacts(project: Project, *stages):
    for st in stages:
        src = SAMPLE / "factory/artifacts" / st
        dst = project.artifacts / st
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)


def pass_stage(project: Project, stage: str, owner: str = "test") -> dict:
    from appfactory.engine import Engine
    from appfactory.gates import run_gate

    eng = Engine(project)
    res = eng.start(stage, owner)
    report = run_gate(project, eng.pipeline.get(stage), eng.load_state())
    out = eng.record_gate(stage, owner, report)
    if not report["passed"]:
        bad = [c for c in report["checks"] if not c["passed"] and c["severity"] == "error"]
        raise AssertionError(f"gate {stage} failed: {json.dumps(bad, ensure_ascii=False, indent=1)[:3000]}")
    return out
