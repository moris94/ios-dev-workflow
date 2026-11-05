"""In-memory App Store Connect simulator.

Implements the subset of endpoints the factory uses, with the same JSON:API
shapes, so plan → apply → verify → submit can be exercised end-to-end
offline (``--simulate``) and in the test-suite. It is *not* a substitute for
Apple's validation; it exists to prove idempotency, crash recovery and the
approval guard without credentials.
"""
from __future__ import annotations

import itertools
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from .client import Response

TERRITORIES = ["USA", "JPN", "GBR", "DEU", "FRA", "CAN", "AUS"]
PRICE_TIERS = ["0.00", "0.99", "1.99", "2.99", "3.99", "4.99", "5.99", "6.99", "7.99", "8.99", "9.99", "14.99", "19.99"]


class FakeASC:
    def __init__(self, state_path: Optional[Path] = None, bundle_id: str = "com.example.app", fail_after: Optional[int] = None,
                 uncertain_after: Optional[int] = None, shared: bool = False):
        self.state_path = Path(state_path) if state_path else None
        self.shared = shared  # re-read state before every request: several processes act on one "service"
        self.fail_after = fail_after
        self.uncertain_after = uncertain_after
        self.calls = []
        self.writes = 0
        if self.state_path and self.state_path.exists():
            raw = json.loads(self.state_path.read_text())
            self.db, seq = raw["db"], raw["seq"]
        else:
            self.db, seq = {}, 1
            self._put("apps", "app1", {"bundleId": bundle_id, "name": "Placeholder", "primaryLocale": "en-US"}, {})
            self._put("appInfos", "info1", {"state": "PREPARE_FOR_SUBMISSION"}, {"app": "app1", "primaryCategory": None})
            self._put("appInfoLocalizations", "infoloc1", {"locale": "en-US", "name": "Placeholder", "subtitle": None,
                                                           "privacyPolicyUrl": None}, {"appInfo": "info1"})
            for t in TERRITORIES:
                self._put("territories", t, {"currency": "USD" if t == "USA" else "XXX"}, {})
        self._seq = itertools.count(seq)

    # ----------------------------------------------------------- storage
    def _put(self, type_, id_, attrs, rels):
        self.db.setdefault(type_, {})[id_] = {"type": type_, "id": id_, "attributes": dict(attrs), "relationships": dict(rels)}
        return self.db[type_][id_]

    def _new_id(self, prefix):
        return f"{prefix}{next(self._seq)}"

    def save(self):
        if self.state_path:
            seq = next(self._seq)
            self._seq = itertools.count(seq)
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps({"db": self.db, "seq": seq}, indent=1))

    def _out(self, r: dict) -> dict:
        rels = {k: {"data": ({"type": "x", "id": v} if isinstance(v, str) else
                             [{"type": "x", "id": i} for i in v] if isinstance(v, list) else None)}
                for k, v in r["relationships"].items()}
        return {"type": r["type"], "id": r["id"], "attributes": r["attributes"], "relationships": rels}

    def _children(self, type_, rel, parent_id):
        return [r for r in self.db.get(type_, {}).values() if r["relationships"].get(rel) == parent_id]

    @staticmethod
    def _list(items):
        return Response(200, {"data": items, "links": {}})

    # ---------------------------------------------------------- transport
    def upload(self, url, method, headers, data):
        self.calls.append(("PUT", url))
        m = re.match(r"fake://upload/(\w+)/(\w+)", url)
        r = self.db[m.group(1)][m.group(2)]
        r["attributes"]["_bytes"] = r["attributes"].get("_bytes", 0) + len(data)
        return Response(200)

    def request(self, method: str, path: str, body: Any = None, params: Optional[dict] = None) -> Response:
        if self.shared and self.state_path and self.state_path.exists():
            raw = json.loads(self.state_path.read_text())
            self.db = raw["db"]
            self._seq = itertools.count(raw["seq"])
        parsed = urlparse(path)
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        q.update(params or {})
        p = parsed.path
        self.calls.append((method, p))
        if method != "GET":
            self.writes += 1
            if self.fail_after is not None and self.writes > self.fail_after:
                return Response(500, {"errors": [{"code": "SIMULATED_CRASH", "detail": "simulated outage"}]})
            if self.uncertain_after is not None and method == "POST" and self.writes > self.uncertain_after:
                self._dispatch(method, p, body, q)  # applied server-side, but the client never hears back
                self.save()
                return Response(503, {"errors": [{"code": "UNAVAILABLE"}]})
        resp = self._dispatch(method, p, body, q)
        if method != "GET":
            self.save()
        return resp

    # ---------------------------------------------------------- routing
    def _dispatch(self, method, p, body, q) -> Response:  # noqa: C901 – explicit route table
        d = (body or {}).get("data") if isinstance(body, dict) else None
        m = lambda pattern: re.fullmatch(pattern, p)  # noqa: E731

        if method == "GET":
            if p == "/v1/apps":
                return self._list([self._out(a) for a in self.db["apps"].values() if a["attributes"]["bundleId"] == q.get("filter[bundleId]")])
            if (r := m(r"/v1/apps/(\w+)")):
                a = self.db["apps"].get(r.group(1))
                return Response(200, {"data": self._out(a)}) if a else Response(404, {"errors": [{"code": "NOT_FOUND"}]})
            if (r := m(r"/v1/apps/(\w+)/appInfos")):
                infos = self._children("appInfos", "app", r.group(1))
                out = []
                for i in infos:
                    o = self._out(i)
                    cat = i["relationships"].get("primaryCategory")
                    o["relationships"]["primaryCategory"] = {"data": {"type": "appCategories", "id": cat} if cat else None}
                    out.append(o)
                return self._list(out)
            if (r := m(r"/v1/appInfos/(\w+)/appInfoLocalizations")):
                return self._list([self._out(x) for x in self._children("appInfoLocalizations", "appInfo", r.group(1))])
            if (r := m(r"/v1/apps/(\w+)/appStoreVersions")):
                vs = [v for v in self._children("appStoreVersions", "app", r.group(1))
                      if v["attributes"]["versionString"] == q.get("filter[versionString]", v["attributes"]["versionString"])]
                out = []
                for v in vs:
                    o = self._out(v)
                    b = v["relationships"].get("build")
                    o["relationships"]["build"] = {"data": {"type": "builds", "id": b} if b else None}
                    out.append(o)
                return self._list(out)
            if (r := m(r"/v1/appStoreVersions/(\w+)")):
                v = self.db.get("appStoreVersions", {}).get(r.group(1))
                return Response(200, {"data": self._out(v)}) if v else Response(404, {})
            if (r := m(r"/v1/appStoreVersions/(\w+)/appStoreVersionLocalizations")):
                return self._list([self._out(x) for x in self._children("appStoreVersionLocalizations", "appStoreVersion", r.group(1))])
            if (r := m(r"/v1/appStoreVersionLocalizations/(\w+)/appScreenshotSets")):
                return self._list([self._out(x) for x in self._children("appScreenshotSets", "appStoreVersionLocalization", r.group(1))])
            if (r := m(r"/v1/appScreenshotSets/(\w+)/appScreenshots")):
                s = self.db["appScreenshotSets"][r.group(1)]
                order = s["relationships"].get("appScreenshots") or []
                shots = {x["id"]: x for x in self._children("appScreenshots", "appScreenshotSet", r.group(1))}
                ids = [i for i in order if i in shots] + [i for i in shots if i not in order]
                return self._list([self._out(shots[i]) for i in ids])
            if (r := m(r"/v1/apps/(\w+)/inAppPurchasesV2")):
                items = self._children("inAppPurchases", "app", r.group(1))
                if q.get("filter[productId]"):
                    items = [i for i in items if i["attributes"]["productId"] == q["filter[productId]"]]
                return self._list([self._out(i) for i in items])
            if (r := m(r"/v2/inAppPurchases/(\w+)/inAppPurchaseLocalizations")):
                return self._list([self._out(x) for x in self._children("inAppPurchaseLocalizations", "inAppPurchaseV2", r.group(1))])
            if (r := m(r"/v2/inAppPurchases/(\w+)/pricePoints")):
                return self._list([{"type": "inAppPurchasePricePoints", "id": f"pp-{r.group(1)}-{q.get('filter[territory]')}-{t}",
                                    "attributes": {"customerPrice": t}} for t in PRICE_TIERS])
            if (r := m(r"/v2/inAppPurchases/(\w+)/iapPriceSchedule")):
                s = self.db.get("inAppPurchasePriceSchedules", {}).get(r.group(1))
                return Response(200, {"data": self._out(s)}) if s else Response(404, {})
            if (r := m(r"/v1/inAppPurchasePriceSchedules/(\w+)/manualPrices")):
                s = self.db["inAppPurchasePriceSchedules"][r.group(1)]
                pp = s["attributes"]["_price_point"]
                price = pp.rsplit("-", 1)[1]
                return Response(200, {"data": [{"type": "inAppPurchasePrices", "id": "p1",
                                                "relationships": {"inAppPurchasePricePoint": {"data": {"type": "inAppPurchasePricePoints", "id": pp}}}}],
                                      "included": [{"type": "inAppPurchasePricePoints", "id": pp, "attributes": {"customerPrice": price}}],
                                      "links": {}})
            if (r := m(r"/v2/inAppPurchases/(\w+)/inAppPurchaseAvailability")):
                a = self.db.get("inAppPurchaseAvailabilities", {}).get(r.group(1))
                return Response(200, {"data": self._out(a)}) if a else Response(404, {})
            if (r := m(r"/v2/inAppPurchases/(\w+)/appStoreReviewScreenshot")):
                shots = self._children("inAppPurchaseAppStoreReviewScreenshots", "inAppPurchaseV2", r.group(1))
                return Response(200, {"data": self._out(shots[0])}) if shots else Response(404, {})
            if p == "/v1/territories":
                return self._list([self._out(t) for t in self.db["territories"].values()])
            if (r := m(r"/v1/apps/(\w+)/appPriceSchedule")):
                s = self.db.get("appPriceSchedules", {}).get(r.group(1))
                return Response(200, {"data": self._out(s)}) if s else Response(404, {})
            if (r := m(r"/v1/appPriceSchedules/(\w+)/manualPrices")):
                s = self.db["appPriceSchedules"][r.group(1)]
                pp = s["attributes"]["_price_point"]
                return Response(200, {"data": [{"type": "appPrices", "id": "ap1",
                                                "relationships": {"appPricePoint": {"data": {"type": "appPricePoints", "id": pp}}}}],
                                      "included": [{"type": "appPricePoints", "id": pp, "attributes": {"customerPrice": pp.rsplit("-", 1)[1]}}],
                                      "links": {}})
            if (r := m(r"/v1/apps/(\w+)/appPricePoints")):
                return self._list([{"type": "appPricePoints", "id": f"app-pp-{q.get('filter[territory]')}-{t}",
                                    "attributes": {"customerPrice": t}} for t in PRICE_TIERS])
            if p == "/v1/builds":
                return self._list([self._out(b) for b in self.db.get("builds", {}).values()
                                   if b["attributes"]["version"] == str(q.get("filter[version]", b["attributes"]["version"]))])
            if (r := m(r"/v1/reviewSubmissions/(\w+)")):
                s = self.db.get("reviewSubmissions", {}).get(r.group(1))
                return Response(200, {"data": self._out(s)}) if s else Response(404, {})
            return Response(404, {"errors": [{"code": "NOT_FOUND", "detail": f"fake: no route GET {p}"}]})

        if method == "PATCH":
            if (r := m(r"/v1/appScreenshotSets/(\w+)/relationships/appScreenshots")):
                self.db["appScreenshotSets"][r.group(1)]["relationships"]["appScreenshots"] = [x["id"] for x in d]
                return Response(204)
            if (r := m(r"/v[12]/(\w+)/(\w+)")):
                type_, id_ = r.group(1), r.group(2)
                res = self.db.get(type_, {}).get(id_)
                if not res:
                    return Response(404, {"errors": [{"code": "NOT_FOUND"}]})
                res["attributes"].update(d.get("attributes", {}))
                for k, v in (d.get("relationships") or {}).items():
                    res["relationships"][k] = (v.get("data") or {}).get("id")
                if type_ in ("appScreenshots", "inAppPurchaseAppStoreReviewScreenshots") and d.get("attributes", {}).get("uploaded"):
                    res["attributes"]["assetDeliveryState"] = {"state": "COMPLETE"}
                if type_ == "reviewSubmissions" and d.get("attributes", {}).get("submitted"):
                    res["attributes"]["state"] = "WAITING_FOR_REVIEW"
                    for v in self.db.get("appStoreVersions", {}).values():
                        v["attributes"]["appStoreState"] = "WAITING_FOR_REVIEW"
                return Response(200, {"data": self._out(res)})

        if method == "DELETE":
            if (r := m(r"/v1/(\w+)/(\w+)")):
                if self.db.get(r.group(1), {}).pop(r.group(2), None) is None:
                    return Response(404, {"errors": [{"code": "NOT_FOUND"}]})
                return Response(204)

        if method == "POST":
            type_ = p.rsplit("/", 1)[1]
            attrs = dict(d.get("attributes") or {})
            rels = {k: (v.get("data") or {}).get("id") if isinstance(v.get("data"), dict) else v.get("data")
                    for k, v in (d.get("relationships") or {}).items()}
            if type_ == "appStoreVersions":
                if any(v["attributes"]["versionString"] == attrs["versionString"] for v in self._children("appStoreVersions", "app", rels["app"])):
                    return Response(409, {"errors": [{"code": "ENTITY_ERROR.DUPLICATE"}]})
                attrs["appStoreState"] = "PREPARE_FOR_SUBMISSION"
                v = self._put(type_, self._new_id("ver"), attrs, rels)
                self._put("appStoreVersionLocalizations", self._new_id("vloc"), {"locale": "en-US"}, {"appStoreVersion": v["id"]})
                return Response(201, {"data": self._out(v)})
            if type_ in ("appStoreVersionLocalizations", "appInfoLocalizations", "inAppPurchaseLocalizations"):
                parent_rel = {"appStoreVersionLocalizations": "appStoreVersion", "appInfoLocalizations": "appInfo",
                              "inAppPurchaseLocalizations": "inAppPurchaseV2"}[type_]
                if any(x["attributes"]["locale"] == attrs["locale"] for x in self._children(type_, parent_rel, rels[parent_rel])):
                    return Response(409, {"errors": [{"code": "ENTITY_ERROR.DUPLICATE", "detail": "locale exists"}]})
            if type_ == "inAppPurchases":
                attrs["state"] = "READY_TO_SUBMIT"
            if type_ in ("appScreenshots", "inAppPurchaseAppStoreReviewScreenshots"):
                new_id = self._new_id("asset")
                size = attrs["fileSize"]
                attrs["uploadOperations"] = [{"method": "PUT", "url": f"fake://upload/{type_}/{new_id}", "offset": 0,
                                              "length": size, "requestHeaders": [{"name": "Content-Type", "value": "image/png"}]}]
                res = self._put(type_, new_id, attrs, rels)
                return Response(201, {"data": self._out(res)})
            if type_ == "inAppPurchasePriceSchedules":
                iap = rels["inAppPurchase"]
                inc = (body.get("included") or [{}])[0]
                pp = inc["relationships"]["inAppPurchasePricePoint"]["data"]["id"]
                res = self._put(type_, iap, {"_price_point": pp}, {"inAppPurchase": iap})
                return Response(201, {"data": self._out(res)})
            if type_ == "appPriceSchedules":
                app = rels["app"]
                pp = body["included"][0]["relationships"]["appPricePoint"]["data"]["id"]
                return Response(201, {"data": self._out(self._put(type_, app, {"_price_point": pp}, {"app": app}))})
            if type_ == "inAppPurchaseAvailabilities":
                iap = rels["inAppPurchase"]
                res = self._put(type_, iap, attrs, {"inAppPurchase": iap})
                return Response(201, {"data": self._out(res)})
            if type_ == "reviewSubmissions":
                attrs["state"] = "READY_FOR_REVIEW"
            if type_ == "appStoreVersionReleaseRequests":
                ver = self.db["appStoreVersions"][rels["appStoreVersion"]]
                if ver["attributes"].get("appStoreState") != "PENDING_DEVELOPER_RELEASE":
                    return Response(409, {"errors": [{"code": "STATE_ERROR", "detail": "version not pending developer release"}]})
                ver["attributes"]["appStoreState"] = "READY_FOR_SALE"
            res = self._put(type_, self._new_id(type_[:4]), attrs, rels)
            return Response(201, {"data": self._out(res)})
        return Response(405, {"errors": [{"code": "METHOD_NOT_ALLOWED", "detail": f"fake: {method} {p}"}]})

    # ------------------------------------------------------------ helpers
    def add_build(self, version: str, build_number: str, state: str = "VALID") -> str:
        bid = self._new_id("build")
        self._put("builds", bid, {"version": str(build_number), "processingState": state,
                                   "usesNonExemptEncryption": False}, {"preReleaseVersion": version})
        self.save()
        return bid

    def set_version_state(self, state: str) -> None:
        for v in self.db.get("appStoreVersions", {}).values():
            v["attributes"]["appStoreState"] = state
        self.save()
