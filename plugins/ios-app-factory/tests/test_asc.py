import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from appfactory.asc import auth
from appfactory.asc.client import Client
from appfactory.asc.executor import Executor
from appfactory.asc.fake import FakeASC
from appfactory.asc.ledger import Ledger
from appfactory.asc.planner import build_plan, validate_plan
from appfactory.asc.state import desired_state, empty_snapshot, fetch_snapshot
from conftest import copy_artifacts
from helpers_sim import fake_raw_captures


@pytest.fixture
def asc_project(project):
    copy_artifacts(project, "mvp", "design", "aso")
    fake_raw_captures(project)
    from appfactory.screenshots.pipeline import render_all

    render_all(project)
    return project


def _apply(project, fake, ledger_name="ledger.json"):
    client = Client(fake, sleep=lambda s: None)
    cfg = project.config()
    snap = fetch_snapshot(client, cfg["app"]["bundle_id"], cfg["app"]["version"])
    plan = build_plan(desired_state(project), snap, "live", "apply")
    assert validate_plan(plan) == []
    ledger = Ledger(project.asc_dir / ledger_name)
    stats = Executor(client, ledger, project.root, snap).apply(plan)
    return plan, stats, client


def test_dry_run_plan_from_empty_remote(asc_project):
    plan = build_plan(desired_state(asc_project), empty_snapshot(), "empty", "dry-run")
    kinds = [o["kind"] for o in plan["operations"]]
    assert validate_plan(plan) == []
    for k in ("app_store_version.create", "version_localization.create", "iap.create", "iap.price_schedule",
              "iap_localization.create", "screenshot.upload", "app.price_schedule", "app_info.category"):
        assert k in kinds, k
    assert sum(k == "screenshot.upload" for k in kinds) == 6
    assert not any("reviewSubmission" in o["path"] for o in plan["operations"])
    assert plan["warnings"]  # app record unknown offline
    # Deterministic keys -> identical plan on re-run
    plan2 = build_plan(desired_state(asc_project), empty_snapshot(), "empty", "dry-run")
    assert [o["key"] for o in plan2["operations"]] == [o["key"] for o in plan["operations"]]


def test_apply_converges_and_is_idempotent(asc_project, tmp_path):
    fake = FakeASC(tmp_path / "fake.json", bundle_id="com.example.stillnote")
    plan, stats, client = _apply(asc_project, fake)
    assert stats["applied"] > 10
    # Re-plan against the updated remote: nothing left to do.
    cfg = asc_project.config()
    after = fetch_snapshot(client, cfg["app"]["bundle_id"], cfg["app"]["version"])
    assert build_plan(desired_state(asc_project), after, "live", "apply")["operations"] == []
    assert after["version"]["releaseType"] == "MANUAL"
    assert after["iaps"]["com.example.stillnote.pro"]["price"] == "4.99"
    assert after["version"]["localizations"]["ja"]["keywords"].startswith("メモ帳")
    # Re-applying the *old* plan sends no write at all: the ledger skips every op.
    writes_before = fake.writes
    stats2 = Executor(client, Ledger(asc_project.asc_dir / "ledger.json"), asc_project.root, after).apply(plan)
    assert stats2["applied"] == 0 and stats2["skipped_ledger"] == len(plan["operations"])
    assert fake.writes == writes_before


def test_crash_midway_then_resume_without_duplicates(asc_project, tmp_path):
    state = tmp_path / "fake.json"
    crashing = FakeASC(state, bundle_id="com.example.stillnote", fail_after=7)
    with pytest.raises(Exception):
        _apply(asc_project, crashing)
    ledger = json.loads((asc_project.asc_dir / "ledger.json").read_text())
    assert sum(1 for e in ledger["ops"].values() if e["status"] == "applied") >= 5
    healthy = FakeASC(state, bundle_id="com.example.stillnote")
    _, stats, client = _apply(asc_project, healthy)
    db = healthy.db
    assert len(db.get("appStoreVersions", {})) == 1
    assert len(db.get("inAppPurchases", {})) == 1
    locales = [l["attributes"]["locale"] for l in db["appStoreVersionLocalizations"].values()]
    assert sorted(locales) == ["en-US", "ja"]


def test_uncertain_post_is_reconciled_not_duplicated(asc_project, tmp_path):
    state = tmp_path / "fake.json"
    flaky = FakeASC(state, bundle_id="com.example.stillnote", uncertain_after=3)
    with pytest.raises(Exception):
        _apply(asc_project, flaky)
    entries = json.loads((asc_project.asc_dir / "ledger.json").read_text())["ops"].values()
    assert any(e["status"] == "uncertain" for e in entries)
    healthy = FakeASC(state, bundle_id="com.example.stillnote")
    _apply(asc_project, healthy)
    assert len(healthy.db.get("appStoreVersions", {})) == 1
    assert len(healthy.db.get("inAppPurchases", {})) == 1


def test_changed_screenshot_only_reuploads_that_image(asc_project, tmp_path):
    fake = FakeASC(tmp_path / "fake.json", bundle_id="com.example.stillnote")
    _apply(asc_project, fake)
    final = sorted((asc_project.screenshots_dir / "final" / "ja").rglob("*.png"))[0]
    from PIL import Image

    im = Image.open(final).convert("RGB")
    im.putpixel((5, 5), (0, 0, 0))
    im.save(final)
    client = Client(fake, sleep=lambda s: None)
    snap = fetch_snapshot(client, "com.example.stillnote", "1.0.0")
    plan = build_plan(desired_state(asc_project), snap, "live", "apply")
    kinds = sorted(o["kind"] for o in plan["operations"])
    assert kinds == ["screenshot.delete", "screenshot.upload", "screenshot_set.reorder"]


def test_validate_plan_rejects_forbidden_and_invalid(asc_project):
    plan = build_plan(desired_state(asc_project), empty_snapshot(), "empty", "dry-run")
    plan["operations"].append({"key": "f" * 24, "kind": "evil", "method": "POST", "path": "/v1/reviewSubmissions",
                               "body": {"data": {"type": "reviewSubmissions"}}, "description": "x"})
    plan["operations"][0]["body"]["data"]["attributes"] = {"releaseType": "AFTER_APPROVAL", "bogus": 1}
    errors = "\n".join(validate_plan(plan))
    assert "never submit" in errors and "unsupported attributes" in errors


def _set_key(monkeypatch, wrap=False):
    import base64

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    b64 = base64.b64encode(pem).decode()
    if wrap:  # `base64` without -w0 wraps lines; must still work
        b64 = "\n".join(b64[i:i + 76] for i in range(0, len(b64), 76))
    monkeypatch.setenv("ASC_KEY_ID", "KEY123")
    monkeypatch.setenv("ASC_ISSUER_ID", "issuer-uuid")
    monkeypatch.setenv("ASC_KEY_CONTENT_BASE64", b64)
    return key


@pytest.mark.parametrize("wrap", [False, True])
def test_jwt_token_claims(monkeypatch, wrap):
    key = _set_key(monkeypatch, wrap)
    token = auth.TokenProvider(lifetime=3600).token()
    header = jwt.get_unverified_header(token)
    assert header == {"alg": "ES256", "kid": "KEY123", "typ": "JWT"}
    claims = jwt.decode(token, key.public_key(), algorithms=["ES256"], audience="appstoreconnect-v1")
    assert claims["iss"] == "issuer-uuid" and claims["exp"] - claims["iat"] <= 20 * 60
    assert claims["iat"] <= time.time() + 1


def test_missing_credentials(monkeypatch):
    with pytest.raises(auth.MissingCredentials, match="ASC_KEY_CONTENT_BASE64"):
        auth.TokenProvider()


def test_invalid_key_content_never_echoed(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setenv("ASC_KEY_CONTENT_BASE64", "bm90LWEta2V5LXNlY3JldA==")  # base64("not-a-key-secret")
    with pytest.raises(auth.MissingCredentials) as exc:
        auth.TokenProvider().token()
    assert "bm90" not in str(exc.value) and "secret" not in str(exc.value)
