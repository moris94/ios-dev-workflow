#!/usr/bin/env python3
"""Stand-in for `fastlane ios <lane>` in tests.

Emulates what each lane of templates/ios-app/fastlane/Fastfile does, against the App Store
Connect simulator (FAKE_ASC_STATE), including the Fastfile's own approval re-check through
APP_FACTORY_BIN. Every invocation is appended to FAKE_FASTLANE_LOG.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.environ["FAKE_FASTLANE_LIB"])

from appfactory.asc.client import Client  # noqa: E402
from appfactory.asc.executor import Executor  # noqa: E402
from appfactory.asc.fake import FakeASC  # noqa: E402
from appfactory.asc.ledger import Ledger  # noqa: E402
from appfactory.asc.planner import Plan, build_plan  # noqa: E402
from appfactory.asc.state import desired_state, fetch_snapshot  # noqa: E402
from appfactory.fastlane_release import api_kept  # noqa: E402
from appfactory.project import Project  # noqa: E402

lane = sys.argv[-1]
with open(os.environ["FAKE_FASTLANE_LOG"], "a") as fh:
    fh.write(lane + "\n")
project = Project(Path(os.environ["APP_FACTORY_PROJECT"]))
cfg = project.config()
fake = FakeASC(Path(os.environ["FAKE_ASC_STATE"]), bundle_id=cfg["app"]["bundle_id"], shared=True)
client = Client(fake, sleep=lambda s: None)
scratch = Ledger(project.tmp / f"fake-fastlane-{lane}.json")


def result(data):
    Path(os.environ["FACTORY_RESULT_FILE"]).write_text(json.dumps(data))


def approval(kind):
    rc = subprocess.call([os.environ["APP_FACTORY_BIN"], "release", "verify-approval", kind],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if rc:
        print(f"approval for {kind} missing — lane aborted", file=sys.stderr)
        sys.exit(1)


snap = fetch_snapshot(client, cfg["app"]["bundle_id"], cfg["app"]["version"])
if lane == "sync_metadata":
    meta = Path(os.environ["FACTORY_METADATA_PATH"])
    desired = desired_state(project)
    assert (meta / "en-US" / "name.txt").read_text() == desired["app_info"]["localizations"]["en-US"]["name"]
    assert any(Path(os.environ["FACTORY_SCREENSHOTS_PATH"]).rglob("*.png"))
    plan = build_plan(desired, snap, "live", "apply")
    ops = [o for o in plan["operations"] if not api_kept(o["kind"])]
    Executor(client, scratch, project.root, snap).apply(dict(plan, operations=ops))
    result({"lane": lane, "status": "success", "digest": os.environ["FACTORY_DELIVER_DIGEST"]})
elif lane == "build_status":
    if not fake.db.get("builds"):
        fake.add_build(cfg["app"]["version"], str(cfg["app"]["build_number"]))
    b = next(iter(fake.db["builds"].values()))
    result({"lane": lane, "build_id": b["id"], "version": cfg["app"]["version"],
            "build_number": b["attributes"]["version"], "processing_state": "VALID", "uses_non_exempt_encryption": False})
elif lane == "submit_review":
    approval("submit")
    plan = Plan()
    plan.add("s", "s", "POST", "/v1/reviewSubmissions",
             {"data": {"type": "reviewSubmissions", "attributes": {"platform": "IOS"},
                       "relationships": {"app": {"data": {"type": "apps", "id": "{ref:app}"}}}}}, "create", produces="rs")
    plan.add("c", "c", "PATCH", "/v1/reviewSubmissions/{ref:rs}",
             {"data": {"type": "reviewSubmissions", "id": "{ref:rs}", "attributes": {"submitted": True}}}, "submit",
             depends_on_refs=["rs"])
    ex = Executor(client, scratch, project.root, snap)
    ex.apply({"operations": plan.ops, "blocking": []})
    result({"lane": lane, "submitted": True, "review_submission_id": ex.refs["rs"], "version_id": snap["version"]["id"]})
elif lane == "release_version":
    approval("publish")
    if snap["version"]["appStoreState"] != "PENDING_DEVELOPER_RELEASE":
        print("No version is pending developer release", file=sys.stderr)
        sys.exit(1)
    fake.set_version_state("READY_FOR_SALE")
    result({"lane": lane, "released": True, "version_id": snap["version"]["id"]})
else:
    print(f"unknown lane {lane}", file=sys.stderr)
    sys.exit(1)
