"""Desired state (from artifacts) and remote snapshot (from ASC, fixture or empty).

Both use the same normalized shape so the planner is a pure diff::

    {
      "app": {"id", "bundleId"} | None,
      "app_info": {"id", "primaryCategory", "localizations": {loc: {"id", "name", "subtitle", "privacyPolicyUrl"}}},
      "version": {"id", "versionString", "appStoreState", "releaseType", "build",
                  "localizations": {loc: {"id", <attrs>, "screenshot_sets": {display_type: {"id", "screenshots": [...]}}}}},
      "iaps": {product_id: {"id", "name", "state", "familySharable", "reviewNote", "localizations": {...},
                            "price": "2.99"|None, "availability": bool, "review_screenshot": {"id", "sourceFileChecksum"}|None}},
      "app_price": {"customerPrice": "0.0"} | None
    }
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..hashing import md5_file, sha256_json
from ..jsonio import read_json
from ..project import Project
from ..screenshots.compose import DEVICES

VERSION_LOC_FIELDS = ("description", "keywords", "promotionalText", "supportUrl", "marketingUrl", "whatsNew")
EDITABLE_INFO_STATES = {"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED", "WAITING_FOR_REVIEW",
                        "READY_FOR_REVIEW", None}


def _price_str(value) -> str:
    return f"{float(value):.2f}"


def desired_state(project: Project) -> dict:
    cfg = project.config()
    aso = read_json(project.artifact("aso", "aso.json"))
    mvp = read_json(project.artifact("mvp", "mvp.json"))
    manifest = read_json(project.screenshots_dir / "manifest.json") or {"items": []}
    if not aso or not mvp:
        raise RuntimeError("aso.json and mvp.json are required to build the App Store Connect plan")
    first_release = cfg["app"].get("first_release", True)
    locales = cfg["app"]["locales"]
    version_locs, info_locs = {}, {}
    for loc in locales:
        meta = aso["locales"][loc]
        info_locs[loc] = {"name": meta["name"], "subtitle": meta["subtitle"], "privacyPolicyUrl": meta["privacy_policy_url"]}
        v = {"description": meta["description"], "keywords": meta["keywords"], "promotionalText": meta["promotional_text"],
             "supportUrl": meta["support_url"]}
        if meta.get("marketing_url"):
            v["marketingUrl"] = meta["marketing_url"]
        if not first_release and meta.get("whats_new"):
            v["whatsNew"] = meta["whats_new"]
        sets = {}
        for item in sorted((i for i in manifest["items"] if i["locale"] == loc), key=lambda i: (i["device"], i["order"])):
            dt = DEVICES[item["device"]]["display_type"]
            path = project.root / item["final"]
            sets.setdefault(dt, {"screenshots": []})["screenshots"].append({
                "fileName": Path(item["final"]).name,
                "file": item["final"],
                "fileSize": path.stat().st_size if path.exists() else 0,
                "sourceFileChecksum": md5_file(path) if path.exists() else None,
                "scene": item["scene"],
            })
        v["screenshot_sets"] = sets
        version_locs[loc] = v

    iaps = {}
    review_shot = None
    paywall_scene = next((s["id"] for s in mvp["screenshot_scenes"] if "paywall" in s["screen"].lower()), None)
    if paywall_scene:
        raw = project.screenshots_dir / "raw" / "en-US" / cfg["screenshots"]["devices"][0] / f"{paywall_scene}.png"
        if raw.exists():
            review_shot = {"file": project.rel(raw), "fileName": f"review-{paywall_scene}.png",
                           "fileSize": raw.stat().st_size, "sourceFileChecksum": md5_file(raw)}
    for p in mvp["monetization"]["products"]:
        iaps[p["product_id"]] = {
            "name": p["reference_name"],
            "inAppPurchaseType": p["type"],
            "familySharable": bool(p.get("family_sharable", False)),
            "reviewNote": p.get("review_note", ""),
            "localizations": {loc: {"name": p["localizations"][loc]["name"], "description": p["localizations"][loc]["description"]}
                              for loc in locales},
            "price": _price_str(p["price_usd"]),
            "availability": True,
            "review_screenshot": review_shot,
        }
    return {
        "app": {"bundleId": cfg["app"]["bundle_id"], "id": cfg.get("asc", {}).get("app_id")},
        "app_info": {"primaryCategory": mvp["category"], "localizations": info_locs},
        "version": {"versionString": cfg["app"]["version"], "releaseType": "MANUAL", "localizations": version_locs},
        "iaps": iaps,
        "app_price": {"customerPrice": "0.00", "baseTerritory": cfg.get("asc", {}).get("price_base_territory", "USA")},
    }


def desired_digest(desired: dict) -> str:
    return sha256_json(desired)


def empty_snapshot() -> dict:
    return {"app": None, "app_info": None, "version": None, "iaps": {}, "app_price": None}


def load_fixture(path: Path) -> dict:
    snap = empty_snapshot()
    snap.update(read_json(path) or {})
    return snap


# ---------------------------------------------------------------- live fetch
def fetch_snapshot(client, bundle_id: str, version_string: str, app_id: Optional[str] = None) -> dict:
    snap = empty_snapshot()
    if app_id:
        app = (client.get(f"/v1/apps/{app_id}", allow_404=True) or {}).get("data")
    else:
        apps = client.get_all("/v1/apps", params={"filter[bundleId]": bundle_id})
        app = apps[0] if apps else None
    if not app:
        return snap
    aid = app["id"]
    snap["app"] = {"id": aid, "bundleId": app["attributes"].get("bundleId", bundle_id)}

    infos = client.get_all(f"/v1/apps/{aid}/appInfos", params={"include": "primaryCategory"})
    info = next((i for i in infos if i["attributes"].get("state", i["attributes"].get("appStoreState")) in EDITABLE_INFO_STATES), None)
    if info:
        cat = ((info.get("relationships") or {}).get("primaryCategory") or {}).get("data")
        locs = client.get_all(f"/v1/appInfos/{info['id']}/appInfoLocalizations")
        snap["app_info"] = {"id": info["id"], "primaryCategory": cat["id"] if cat else None,
                            "localizations": {l["attributes"]["locale"]: {"id": l["id"], **{k: l["attributes"].get(k) for k in ("name", "subtitle", "privacyPolicyUrl")}} for l in locs}}

    versions = client.get_all(f"/v1/apps/{aid}/appStoreVersions",
                              params={"filter[versionString]": version_string, "filter[platform]": "IOS", "include": "build"})
    if versions:
        v = versions[0]
        build = (((v.get("relationships") or {}).get("build") or {}).get("data") or {}).get("id")
        vlocs = {}
        for l in client.get_all(f"/v1/appStoreVersions/{v['id']}/appStoreVersionLocalizations"):
            entry = {"id": l["id"], **{k: l["attributes"].get(k) for k in VERSION_LOC_FIELDS}, "screenshot_sets": {}}
            for s in client.get_all(f"/v1/appStoreVersionLocalizations/{l['id']}/appScreenshotSets"):
                shots = client.get_all(f"/v1/appScreenshotSets/{s['id']}/appScreenshots")
                entry["screenshot_sets"][s["attributes"]["screenshotDisplayType"]] = {
                    "id": s["id"],
                    "screenshots": [{"id": x["id"], "fileName": x["attributes"].get("fileName"),
                                     "sourceFileChecksum": x["attributes"].get("sourceFileChecksum"),
                                     "state": ((x["attributes"].get("assetDeliveryState") or {}).get("state"))} for x in shots],
                }
            vlocs[l["attributes"]["locale"]] = entry
        snap["version"] = {"id": v["id"], "versionString": v["attributes"]["versionString"],
                           "appStoreState": v["attributes"].get("appStoreState") or v["attributes"].get("appVersionState"),
                           "releaseType": v["attributes"].get("releaseType"), "build": build, "localizations": vlocs}

    for iap in client.get_all(f"/v1/apps/{aid}/inAppPurchasesV2", params={"limit": 200}):
        a = iap["attributes"]
        locs = client.get_all(f"/v2/inAppPurchases/{iap['id']}/inAppPurchaseLocalizations")
        prices = []
        sched = client.get(f"/v2/inAppPurchases/{iap['id']}/iapPriceSchedule", allow_404=True)
        if sched and sched.get("data"):
            prices = client.get_all(f"/v1/inAppPurchasePriceSchedules/{sched['data']['id']}/manualPrices",
                                    params={"include": "inAppPurchasePricePoint"})
            points = {i["id"]: i for i in getattr(client, "last_included", []) if i["type"] == "inAppPurchasePricePoints"}
            prices = [points.get(((p.get("relationships") or {}).get("inAppPurchasePricePoint") or {}).get("data", {}).get("id"), {})
                      for p in prices]
        avail = client.get(f"/v2/inAppPurchases/{iap['id']}/inAppPurchaseAvailability", allow_404=True)
        shot = client.get(f"/v2/inAppPurchases/{iap['id']}/appStoreReviewScreenshot", allow_404=True)
        snap["iaps"][a["productId"]] = {
            "id": iap["id"], "name": a.get("name"), "state": a.get("state"), "inAppPurchaseType": a.get("inAppPurchaseType"),
            "familySharable": a.get("familySharable"), "reviewNote": a.get("reviewNote") or "",
            "localizations": {l["attributes"]["locale"]: {"id": l["id"], "name": l["attributes"].get("name"),
                                                          "description": l["attributes"].get("description")} for l in locs},
            "price": _price_str(prices[0]["attributes"]["customerPrice"]) if prices and prices[0] else None,
            "availability": bool(avail and avail.get("data")),
            "review_screenshot": ({"id": shot["data"]["id"], "sourceFileChecksum": shot["data"]["attributes"].get("sourceFileChecksum")}
                                  if shot and shot.get("data") else None),
        }
    sched = client.get(f"/v1/apps/{aid}/appPriceSchedule", allow_404=True)
    if sched and sched.get("data"):
        manual = client.get_all(f"/v1/appPriceSchedules/{sched['data']['id']}/manualPrices", params={"include": "appPricePoint"})
        points = {i["id"]: i for i in getattr(client, "last_included", []) if i["type"] == "appPricePoints"}
        if manual:
            pid = ((manual[0].get("relationships") or {}).get("appPricePoint") or {}).get("data", {}).get("id")
            cp = points.get(pid, {}).get("attributes", {}).get("customerPrice")
            snap["app_price"] = {"customerPrice": _price_str(cp) if cp is not None else None}
    return snap
