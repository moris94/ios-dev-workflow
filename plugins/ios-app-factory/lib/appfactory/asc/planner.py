"""Diff desired vs remote state into an ordered, idempotent operation plan.

Placeholders inside ``path``/``body``:

* ``{ref:NAME}``     – resource id known from the snapshot or produced by an earlier op
* ``{lookup:NAME}``  – value resolved at execution time with read-only GETs
                       (price points, territories)

Every op has a deterministic ``key`` derived from (kind, target, payload); the
ledger uses it to guarantee a successful operation is never sent twice.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..hashing import sha256_json
from ..timeutil import now_iso
from .state import VERSION_LOC_FIELDS, desired_digest

EDITABLE_VERSION_STATES = {None, "PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED",
                           "INVALID_BINARY", "DEVELOPER_REMOVED_FROM_SALE"}


class Plan:
    def __init__(self):
        self.ops: List[dict] = []
        self.warnings: List[str] = []
        self.blocking: List[str] = []

    def add(self, kind: str, target: str, method: str, path: str, body: Optional[dict], description: str,
            produces: Optional[str] = None, depends_on_refs=(), upload: Optional[dict] = None,
            lookup: Optional[dict] = None, reconcile: Optional[dict] = None) -> dict:
        key = sha256_json({"kind": kind, "target": target, "method": method, "body": body,
                           "upload": (upload or {}).get("sourceFileChecksum")})[:24]
        deps = [o["key"] for o in self.ops if o.get("produces") in set(depends_on_refs)]
        op = {"key": key, "kind": kind, "target": target, "method": method, "path": path, "body": body,
              "description": description, "produces": produces, "depends_on": deps,
              "upload": upload, "lookup": lookup, "reconcile": reconcile}
        self.ops.append(op)
        return op


def _rel(type_: str, ref: str) -> dict:
    return {"data": {"type": type_, "id": "{ref:%s}" % ref}}


def _changed(desired: dict, current: Optional[dict], fields) -> dict:
    current = current or {}
    return {k: desired[k] for k in fields if k in desired and (current.get(k) or "") != (desired[k] or "")}


def initial_refs(snapshot: dict) -> Dict[str, str]:
    refs = {}
    if snapshot.get("app"):
        refs["app"] = snapshot["app"]["id"]
    info = snapshot.get("app_info")
    if info:
        refs["app_info"] = info["id"]
        for loc, l in info.get("localizations", {}).items():
            refs[f"info_loc.{loc}"] = l["id"]
    v = snapshot.get("version")
    if v:
        refs["version"] = v["id"]
        for loc, l in v.get("localizations", {}).items():
            refs[f"version_loc.{loc}"] = l["id"]
            for dt, s in l.get("screenshot_sets", {}).items():
                refs[f"shot_set.{loc}.{dt}"] = s["id"]
    for pid, iap in snapshot.get("iaps", {}).items():
        refs[f"iap.{pid}"] = iap["id"]
        for loc, l in iap.get("localizations", {}).items():
            refs[f"iap_loc.{pid}.{loc}"] = l["id"]
    return refs


def build_plan(desired: dict, snapshot: dict, snapshot_kind: str, mode: str) -> dict:
    plan = Plan()
    live = snapshot_kind == "live"
    if not snapshot.get("app"):
        msg = (f"App record for bundle id {desired['app']['bundleId']} not found. Create the app once in App Store Connect "
               "(the API cannot create app records), then re-run.")
        (plan.blocking if live else plan.warnings).append(msg)

    # --- App info: category + localizations --------------------------------
    info = snapshot.get("app_info") or {}
    if info.get("primaryCategory") != desired["app_info"]["primaryCategory"]:
        cat = desired["app_info"]["primaryCategory"]
        plan.add("app_info.category", "app_info", "PATCH", "/v1/appInfos/{ref:app_info}",
                 {"data": {"type": "appInfos", "id": "{ref:app_info}",
                           "relationships": {"primaryCategory": {"data": {"type": "appCategories", "id": cat}}}}},
                 f"Set primary category to {cat}")
    for loc, want in desired["app_info"]["localizations"].items():
        cur = (info.get("localizations") or {}).get(loc)
        if cur:
            diff = _changed(want, cur, ("name", "subtitle", "privacyPolicyUrl"))
            if diff:
                plan.add("app_info_localization.update", f"info_loc:{loc}", "PATCH", "/v1/appInfoLocalizations/{ref:info_loc.%s}" % loc,
                         {"data": {"type": "appInfoLocalizations", "id": "{ref:info_loc.%s}" % loc, "attributes": diff}},
                         f"Update app name/subtitle/privacy URL [{loc}]: {', '.join(diff)}")
        else:
            plan.add("app_info_localization.create", f"info_loc:{loc}", "POST", "/v1/appInfoLocalizations",
                     {"data": {"type": "appInfoLocalizations", "attributes": {"locale": loc, **want},
                               "relationships": {"appInfo": _rel("appInfos", "app_info")}}},
                     f"Create app info localization [{loc}]", produces=f"info_loc.{loc}",
                     reconcile={"path": "/v1/appInfos/{ref:app_info}/appInfoLocalizations", "match": {"locale": loc},
                                "update_type": "appInfoLocalizations", "update_attributes": want})

    # --- App Store version ---------------------------------------------------
    v = snapshot.get("version")
    dv = desired["version"]
    if not v:
        plan.add("app_store_version.create", f"version:{dv['versionString']}", "POST", "/v1/appStoreVersions",
                 {"data": {"type": "appStoreVersions",
                           "attributes": {"platform": "IOS", "versionString": dv["versionString"], "releaseType": "MANUAL"},
                           "relationships": {"app": _rel("apps", "app")}}},
                 f"Create App Store version {dv['versionString']} (releaseType MANUAL)", produces="version", depends_on_refs=["app"],
                 reconcile={"path": "/v1/apps/{ref:app}/appStoreVersions", "params": {"filter[versionString]": dv["versionString"],
                            "filter[platform]": "IOS"}, "match": {"versionString": dv["versionString"]}})
        v = {"localizations": {}}
    else:
        if v.get("appStoreState") not in EDITABLE_VERSION_STATES:
            plan.blocking.append(f"Version {dv['versionString']} is in state {v.get('appStoreState')} and cannot be edited")
        if v.get("releaseType") != "MANUAL":
            plan.add("app_store_version.release_type", f"version:{dv['versionString']}", "PATCH", "/v1/appStoreVersions/{ref:version}",
                     {"data": {"type": "appStoreVersions", "id": "{ref:version}", "attributes": {"releaseType": "MANUAL"}}},
                     "Force releaseType MANUAL (release only after human approval)")

    for loc, want in dv["localizations"].items():
        attrs = {k: want[k] for k in VERSION_LOC_FIELDS if k in want}
        cur = v["localizations"].get(loc)
        if cur:
            diff = _changed(attrs, cur, VERSION_LOC_FIELDS)
            if diff:
                plan.add("version_localization.update", f"version_loc:{loc}", "PATCH",
                         "/v1/appStoreVersionLocalizations/{ref:version_loc.%s}" % loc,
                         {"data": {"type": "appStoreVersionLocalizations", "id": "{ref:version_loc.%s}" % loc, "attributes": diff}},
                         f"Update version metadata [{loc}]: {', '.join(diff)}")
        else:
            plan.add("version_localization.create", f"version_loc:{loc}", "POST", "/v1/appStoreVersionLocalizations",
                     {"data": {"type": "appStoreVersionLocalizations", "attributes": {"locale": loc, **attrs},
                               "relationships": {"appStoreVersion": _rel("appStoreVersions", "version")}}},
                     f"Create version metadata [{loc}]", produces=f"version_loc.{loc}", depends_on_refs=["version"],
                     reconcile={"path": "/v1/appStoreVersions/{ref:version}/appStoreVersionLocalizations", "match": {"locale": loc},
                                "update_type": "appStoreVersionLocalizations", "update_attributes": attrs})

        # --- screenshots ---------------------------------------------------
        cur_sets = (cur or {}).get("screenshot_sets", {})
        for dt, want_set in want["screenshot_sets"].items():
            set_ref = f"shot_set.{loc}.{dt}"
            cur_set = cur_sets.get(dt)
            if not cur_set:
                plan.add("screenshot_set.create", f"shot_set:{loc}:{dt}", "POST", "/v1/appScreenshotSets",
                         {"data": {"type": "appScreenshotSets", "attributes": {"screenshotDisplayType": dt},
                                   "relationships": {"appStoreVersionLocalization": _rel("appStoreVersionLocalizations", f"version_loc.{loc}")}}},
                         f"Create screenshot set {dt} [{loc}]", produces=set_ref, depends_on_refs=[f"version_loc.{loc}"],
                         reconcile={"path": "/v1/appStoreVersionLocalizations/{ref:version_loc.%s}/appScreenshotSets" % loc,
                                    "match": {"screenshotDisplayType": dt}})
                cur_set = {"screenshots": []}
            existing = {s.get("sourceFileChecksum"): s for s in cur_set["screenshots"]}
            wanted = {s["sourceFileChecksum"] for s in want_set["screenshots"]}
            changed = False
            for s in cur_set["screenshots"]:
                if s.get("sourceFileChecksum") not in wanted:
                    changed = True
                    plan.add("screenshot.delete", f"shot:{s['id']}", "DELETE", f"/v1/appScreenshots/{s['id']}", None,
                             f"Delete outdated screenshot {s.get('fileName')} [{loc} {dt}]")
            order_ids = []
            for s in want_set["screenshots"]:
                if s["sourceFileChecksum"] in existing:
                    order_ids.append(existing[s["sourceFileChecksum"]]["id"])
                    continue
                changed = True
                ref = f"shot.{loc}.{dt}.{s['scene']}"
                plan.add("screenshot.upload", f"shot:{loc}:{dt}:{s['scene']}", "UPLOAD", "/v1/appScreenshots",
                         {"data": {"type": "appScreenshots", "attributes": {"fileName": s["fileName"], "fileSize": s["fileSize"]},
                                   "relationships": {"appScreenshotSet": _rel("appScreenshotSets", set_ref)}}},
                         f"Upload {s['fileName']} [{loc} {dt}]", produces=ref, depends_on_refs=[set_ref],
                         upload={"file": s["file"], "fileSize": s["fileSize"], "sourceFileChecksum": s["sourceFileChecksum"],
                                 "type": "appScreenshots", "commit_path": "/v1/appScreenshots/{id}"})
                order_ids.append("{ref:%s}" % ref)
            current_order = [s["id"] for s in cur_set["screenshots"] if s.get("sourceFileChecksum") in wanted]
            if changed or current_order != order_ids:
                plan.add("screenshot_set.reorder", f"shot_set_order:{loc}:{dt}", "PATCH",
                         "/v1/appScreenshotSets/{ref:%s}/relationships/appScreenshots" % set_ref,
                         {"data": [{"type": "appScreenshots", "id": i} for i in order_ids]},
                         f"Order screenshots [{loc} {dt}]", depends_on_refs=[set_ref] + [i[5:-1] for i in order_ids if i.startswith("{ref:")])

    # --- In-app purchases ----------------------------------------------------
    for pid, want in desired["iaps"].items():
        cur = snapshot.get("iaps", {}).get(pid)
        ref = f"iap.{pid}"
        attrs = {"name": want["name"], "familySharable": want["familySharable"], "reviewNote": want["reviewNote"]}
        if not cur:
            plan.add("iap.create", f"iap:{pid}", "POST", "/v2/inAppPurchases",
                     {"data": {"type": "inAppPurchases",
                               "attributes": {"productId": pid, "inAppPurchaseType": want["inAppPurchaseType"], **attrs},
                               "relationships": {"app": _rel("apps", "app")}}},
                     f"Create {want['inAppPurchaseType']} in-app purchase {pid}", produces=ref,
                     reconcile={"path": "/v1/apps/{ref:app}/inAppPurchasesV2", "params": {"filter[productId]": pid},
                                "match": {"productId": pid}})
            cur = {"localizations": {}, "price": None, "availability": False, "review_screenshot": None}
        else:
            if cur.get("inAppPurchaseType") and cur["inAppPurchaseType"] != want["inAppPurchaseType"]:
                plan.blocking.append(f"IAP {pid} exists with type {cur['inAppPurchaseType']} (cannot change to {want['inAppPurchaseType']})")
            diff = _changed(attrs, cur, ("name", "familySharable", "reviewNote"))
            if diff:
                plan.add("iap.update", f"iap:{pid}", "PATCH", "/v2/inAppPurchases/{ref:%s}" % ref,
                         {"data": {"type": "inAppPurchases", "id": "{ref:%s}" % ref, "attributes": diff}}, f"Update IAP {pid}: {', '.join(diff)}")
        for loc, lw in want["localizations"].items():
            lc = cur["localizations"].get(loc)
            lref = f"iap_loc.{pid}.{loc}"
            if lc:
                diff = _changed(lw, lc, ("name", "description"))
                if diff:
                    plan.add("iap_localization.update", f"iap_loc:{pid}:{loc}", "PATCH", "/v1/inAppPurchaseLocalizations/{ref:%s}" % lref,
                             {"data": {"type": "inAppPurchaseLocalizations", "id": "{ref:%s}" % lref, "attributes": diff}},
                             f"Update IAP localization {pid} [{loc}]")
            else:
                plan.add("iap_localization.create", f"iap_loc:{pid}:{loc}", "POST", "/v1/inAppPurchaseLocalizations",
                         {"data": {"type": "inAppPurchaseLocalizations", "attributes": {"locale": loc, **lw},
                                   "relationships": {"inAppPurchaseV2": _rel("inAppPurchases", ref)}}},
                         f"Create IAP localization {pid} [{loc}]", produces=lref, depends_on_refs=[ref],
                         reconcile={"path": "/v2/inAppPurchases/{ref:%s}/inAppPurchaseLocalizations" % ref, "match": {"locale": loc},
                                    "update_type": "inAppPurchaseLocalizations", "update_attributes": lw})
        if cur.get("price") != want["price"]:
            territory = desired["app_price"]["baseTerritory"]
            plan.add("iap.price_schedule", f"iap_price:{pid}", "POST", "/v1/inAppPurchasePriceSchedules",
                     {"data": {"type": "inAppPurchasePriceSchedules",
                               "relationships": {"inAppPurchase": _rel("inAppPurchases", ref),
                                                 "baseTerritory": {"data": {"type": "territories", "id": territory}},
                                                 "manualPrices": {"data": [{"type": "inAppPurchasePrices", "id": "${price1}"}]}}},
                      "included": [{"type": "inAppPurchasePrices", "id": "${price1}", "attributes": {"startDate": None},
                                    "relationships": {"inAppPurchasePricePoint": {"data": {"type": "inAppPurchasePricePoints",
                                                                                           "id": "{lookup:price_point}"}}}}]},
                     f"Set IAP {pid} price to {want['price']} ({territory}, auto-equalized)", depends_on_refs=[ref],
                     lookup={"price_point": {"type": "iap_price_point", "iap_ref": ref, "territory": territory, "price": want["price"]}})
        if not cur.get("availability"):
            plan.add("iap.availability", f"iap_avail:{pid}", "POST", "/v1/inAppPurchaseAvailabilities",
                     {"data": {"type": "inAppPurchaseAvailabilities", "attributes": {"availableInNewTerritories": True},
                               "relationships": {"inAppPurchase": _rel("inAppPurchases", ref),
                                                 "availableTerritories": {"data": "{lookup:territories}"}}}},
                     f"Make IAP {pid} available in all territories", depends_on_refs=[ref],
                     lookup={"territories": {"type": "territories"}})
        shot = want.get("review_screenshot")
        cur_shot = cur.get("review_screenshot")
        if shot and (not cur_shot or cur_shot.get("sourceFileChecksum") != shot["sourceFileChecksum"]):
            if cur_shot:
                plan.add("iap.review_screenshot.delete", f"iap_shot:{cur_shot['id']}", "DELETE",
                         f"/v1/inAppPurchaseAppStoreReviewScreenshots/{cur_shot['id']}", None, f"Delete old IAP review screenshot {pid}")
            plan.add("iap.review_screenshot.upload", f"iap_shot:{pid}", "UPLOAD", "/v1/inAppPurchaseAppStoreReviewScreenshots",
                     {"data": {"type": "inAppPurchaseAppStoreReviewScreenshots",
                               "attributes": {"fileName": shot["fileName"], "fileSize": shot["fileSize"]},
                               "relationships": {"inAppPurchaseV2": _rel("inAppPurchases", ref)}}},
                     f"Upload App Review screenshot for IAP {pid}", depends_on_refs=[ref],
                     upload={"file": shot["file"], "fileSize": shot["fileSize"], "sourceFileChecksum": shot["sourceFileChecksum"],
                             "type": "inAppPurchaseAppStoreReviewScreenshots",
                             "commit_path": "/v1/inAppPurchaseAppStoreReviewScreenshots/{id}"})
    if not desired["iaps"]:
        plan.warnings.append("No in-app purchases defined: first release ships without payments (waiver required in mvp.json)")

    # --- App price: free download (monetized via IAP) -----------------------------
    ap = snapshot.get("app_price")
    if not ap or ap.get("customerPrice") != desired["app_price"]["customerPrice"]:
        territory = desired["app_price"]["baseTerritory"]
        plan.add("app.price_schedule", "app_price", "POST", "/v1/appPriceSchedules",
                 {"data": {"type": "appPriceSchedules",
                           "relationships": {"app": _rel("apps", "app"),
                                             "baseTerritory": {"data": {"type": "territories", "id": territory}},
                                             "manualPrices": {"data": [{"type": "appPrices", "id": "${price1}"}]}}},
                  "included": [{"type": "appPrices", "id": "${price1}", "attributes": {"startDate": None},
                                "relationships": {"appPricePoint": {"data": {"type": "appPricePoints", "id": "{lookup:app_price_point}"}}}}]},
                 f"Set app price to {desired['app_price']['customerPrice']} (free download, {territory})",
                 lookup={"app_price_point": {"type": "app_price_point", "territory": territory,
                                             "price": desired["app_price"]["customerPrice"]}})

    return {
        "generated_at": now_iso(),
        "mode": mode,
        "remote_snapshot": snapshot_kind,
        "desired_digest": desired_digest(desired),
        "app": {"bundle_id": desired["app"]["bundleId"], "app_id": (snapshot.get("app") or {}).get("id")},
        "warnings": plan.warnings,
        "blocking": plan.blocking,
        "operations": plan.ops,
    }


# ---------------------------------------------------------------- validation
REQUEST_SPECS = {
    "appInfos": {"attributes": set(), "relationships": {"primaryCategory"}},
    "appInfoLocalizations": {"attributes": {"locale", "name", "subtitle", "privacyPolicyUrl", "privacyChoicesUrl", "privacyPolicyText"},
                             "relationships": {"appInfo"}},
    "appStoreVersions": {"attributes": {"platform", "versionString", "releaseType", "copyright", "earliestReleaseDate"},
                         "relationships": {"app", "build"}},
    "appStoreVersionLocalizations": {"attributes": set(VERSION_LOC_FIELDS) | {"locale"}, "relationships": {"appStoreVersion"}},
    "appScreenshotSets": {"attributes": {"screenshotDisplayType"}, "relationships": {"appStoreVersionLocalization"}},
    "appScreenshots": {"attributes": {"fileName", "fileSize", "uploaded", "sourceFileChecksum"}, "relationships": {"appScreenshotSet"}},
    "inAppPurchases": {"attributes": {"name", "productId", "inAppPurchaseType", "familySharable", "reviewNote"}, "relationships": {"app"}},
    "inAppPurchaseLocalizations": {"attributes": {"locale", "name", "description"}, "relationships": {"inAppPurchaseV2"}},
    "inAppPurchasePriceSchedules": {"attributes": set(), "relationships": {"inAppPurchase", "baseTerritory", "manualPrices"}},
    "inAppPurchaseAvailabilities": {"attributes": {"availableInNewTerritories"}, "relationships": {"inAppPurchase", "availableTerritories"}},
    "inAppPurchaseAppStoreReviewScreenshots": {"attributes": {"fileName", "fileSize", "uploaded", "sourceFileChecksum"},
                                               "relationships": {"inAppPurchaseV2"}},
    "appPriceSchedules": {"attributes": set(), "relationships": {"app", "baseTerritory", "manualPrices"}},
}
LIMITS = {"name": 30, "subtitle": 30, "keywords": 100, "promotionalText": 170, "description": 4000, "whatsNew": 4000}
IAP_LIMITS = {"name": 30, "description": 45}
FORBIDDEN_PATHS = ("/v1/reviewSubmissions", "/v1/reviewSubmissionItems", "/v1/appStoreVersionReleaseRequests",
                   "/v1/appStoreVersionSubmissions", "/v1/inAppPurchaseSubmissions")


def validate_plan(plan: dict) -> List[str]:
    """Structural validation of every request body (offline, used by dry-run and the gate)."""
    errors = []
    for op in plan["operations"]:
        where = f"{op['kind']} ({op['key']})"
        if op["path"].startswith(FORBIDDEN_PATHS):
            errors.append(f"{where}: sync plans must never submit for review or release")
        body = op.get("body")
        if op["method"] == "DELETE":
            if body is not None:
                errors.append(f"{where}: DELETE must not have a body")
            continue
        if not isinstance(body, dict) or "data" not in body:
            errors.append(f"{where}: body.data missing")
            continue
        data = body["data"]
        if isinstance(data, list):  # relationship replacement
            if not all(isinstance(d, dict) and set(d) == {"type", "id"} for d in data):
                errors.append(f"{where}: relationship linkage must be [{{type,id}}]")
            continue
        spec = REQUEST_SPECS.get(data.get("type"))
        if spec is None:
            errors.append(f"{where}: unknown resource type {data.get('type')}")
            continue
        extra = set(data.get("attributes", {})) - spec["attributes"]
        if extra:
            errors.append(f"{where}: unsupported attributes {sorted(extra)}")
        extra_rel = set(data.get("relationships", {})) - spec["relationships"]
        if extra_rel:
            errors.append(f"{where}: unsupported relationships {sorted(extra_rel)}")
        if op["method"] == "PATCH" and "id" not in data:
            errors.append(f"{where}: PATCH body requires data.id")
        if op["method"] in ("POST", "UPLOAD") and "id" in data:
            errors.append(f"{where}: create body must not set data.id")
        limits = IAP_LIMITS if data["type"] == "inAppPurchaseLocalizations" else LIMITS
        for k, lim in limits.items():
            v = data.get("attributes", {}).get(k)
            if isinstance(v, str) and len(v) > lim:
                errors.append(f"{where}: {k} is {len(v)} chars (max {lim})")
        if data.get("attributes", {}).get("releaseType") not in (None, "MANUAL"):
            errors.append(f"{where}: releaseType must be MANUAL")
    keys = [o["key"] for o in plan["operations"]]
    if len(keys) != len(set(keys)):
        errors.append("duplicate operation keys")
    return errors
