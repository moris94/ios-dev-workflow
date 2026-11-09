"""Gates for research, proposal, charter, MVP and ASO artifacts."""
from __future__ import annotations

import datetime as _dt
import re

from . import gate

RESEARCH = "factory/artifacts/research/research.json"
PROPOSAL = "factory/artifacts/proposal/proposal.json"
CHARTER = "factory/artifacts/charter/charter.json"
MVP = "factory/artifacts/mvp/mvp.json"
DESIGN = "factory/artifacts/design/design.json"
ASO = "factory/artifacts/aso/aso.json"


def _source_ids(research) -> set:
    return {s["id"] for s in (research or {}).get("sources", [])}


@gate("research")
def research_gate(ctx):
    data = ctx.load_artifact(RESEARCH, "research")
    ctx.require_text("factory/artifacts/research/research.md", 400)
    if not data:
        return
    cfg = ctx.config.get("research", {})
    min_comp = int(cfg.get("min_competitors", 5))
    min_src = int(cfg.get("min_sources", 8))
    ids = [s["id"] for s in data["sources"]]
    urls = [s["url"] for s in data["sources"]]
    ctx.check("sources.unique-ids", len(ids) == len(set(ids)), "source ids are unique")
    ctx.check("sources.unique-urls", len(urls) == len(set(urls)), "source URLs are unique")
    ctx.check("sources.count", len(ids) >= min_src, f"{len(ids)} sources (>= {min_src} required)")
    today = _dt.date.today()
    future = [s["id"] for s in data["sources"] if _dt.date.fromisoformat(s["retrieved_at"]) > today]
    ctx.check("sources.retrieved_at", not future, "no source retrieved in the future", details=future or None)
    known = set(ids)
    dangling = []
    for section in ("competitors", "demand_signals", "user_pain_points", "market_gaps"):
        for i, item in enumerate(data[section]):
            missing = [sid for sid in item["source_ids"] if sid not in known]
            if missing:
                dangling.append(f"{section}[{i}] -> {missing}")
    ctx.check("citations.resolve", not dangling, "every claim cites an existing source", details=dangling or None)
    comps = data["competitors"]
    ctx.check("competitors.count", len(comps) >= min_comp, f"{len(comps)} competitors analysed (>= {min_comp})")
    app_store = [c for c in comps if "apps.apple.com" in c["app_store_url"]]
    ctx.check("competitors.app-store-links", len(app_store) >= min(3, min_comp),
              f"{len(app_store)} competitors link to apps.apple.com")
    names = [c["name"].strip().lower() for c in comps]
    ctx.check("competitors.unique", len(names) == len(set(names)), "competitor names unique")
    signals = data["demand_signals"]
    ctx.check("demand.count", len(signals) >= 3, f"{len(signals)} demand signals (>= 3)")
    signal_sources = {sid for s in signals for sid in s["source_ids"]}
    ctx.check("demand.independent-sources", len(signal_sources) >= 3,
              f"demand evidence from {len(signal_sources)} distinct sources (>= 3)")
    ctx.check("demand.not-all-weak", any(s["strength"] != "weak" for s in signals),
              "at least one moderate/strong demand signal")
    ctx.check("search-log", len(data["search_log"]) >= 5, f"{len(data['search_log'])} searches logged (>= 5)")
    ctx.check("verdict.go", data["verdict"]["go"],
              "research verdict is GO" if data["verdict"]["go"] else
              "research verdict is NO-GO: stop and ask the human whether to pivot the idea")


@gate("proposal")
def proposal_gate(ctx):
    data = ctx.load_artifact(PROPOSAL, "proposal")
    ctx.require_text("factory/artifacts/proposal/proposal.md", 400)
    research = ctx.load_json(RESEARCH)
    if not data or not research:
        return
    known = _source_ids(research)
    bad = [d["point"] for d in data["differentiation"] if not set(d["evidence_source_ids"]) <= known]
    ctx.check("differentiation.evidence", not bad, "differentiation points cite research sources", details=bad or None)
    must = [f for f in data["key_features"] if f["priority"] == "must"]
    ctx.check("features.must", 1 <= len(must) <= 7, f"{len(must)} must-have features (1..7)")
    ctx.check("monetization.not-free", data["monetization_hypothesis"]["model"] != "free",
              "monetization model defined (first release ships with payments)")
    comp_names = {c["name"].lower() for c in research["competitors"]}
    mentioned = [n for n in comp_names if any(n in d["vs_competitors"].lower() for d in data["differentiation"])]
    ctx.warn("differentiation.names-competitors", bool(mentioned), "differentiation references competitors by name")


@gate("charter")
def charter_gate(ctx):
    data = ctx.load_artifact(CHARTER, "charter")
    ctx.require_text("factory/artifacts/charter/charter.md", 300)
    if not data:
        return
    pids = [p["id"] for p in data["principles"]]
    ctx.check("principles.unique", len(pids) == len(set(pids)), "principle ids unique")
    ctx.check("non-goals", len(data["non_goals"]) >= 2, "explicit non-goals")
    ja = data["tone_of_voice"]["ja"]
    ctx.check("tone.ja-is-japanese", bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", ja)), "Japanese tone of voice written in Japanese")


@gate("mvp")
def mvp_gate(ctx):
    data = ctx.load_artifact(MVP, "mvp")
    ctx.require_text("factory/artifacts/mvp/mvp.md", 300)
    charter = ctx.load_json(CHARTER)
    if not data or not charter:
        return
    cfg_app = ctx.config.get("app", {})
    pids = {p["id"] for p in charter["principles"]}
    fids = [f["id"] for f in data["features"]]
    sids = {s["id"] for s in data["screens"]}
    ctx.check("features.unique", len(fids) == len(set(fids)), "feature ids unique")
    bad_p = [f["id"] for f in data["features"] if not set(f["principle_ids"]) <= pids]
    ctx.check("features.trace-to-charter", not bad_p, "every feature traces to a charter principle", details=bad_p or None)
    bad_s = [f["id"] for f in data["features"] if not set(f["screens"]) <= sids]
    ctx.check("features.screens-defined", not bad_s, "feature screens are defined", details=bad_s or None)
    must = [f for f in data["features"] if f["priority"] == "must"]
    ctx.check("scope.must-count", 1 <= len(must) <= 8, f"{len(must)} must-have features (1..8) — keep the MVP small")
    ctx.check("version.matches-config", data["version"] == cfg_app.get("version"),
              f"mvp.version {data['version']} == config app.version {cfg_app.get('version')}")

    m = data["monetization"]
    waived = m["model"] == "none"
    if waived:
        ctx.check("monetization.required", bool(m.get("waiver")),
                  "no monetization requires an explicit human waiver (monetization.waiver)")
    else:
        ctx.check("monetization.products", len(m["products"]) >= 1, "at least one IAP product")
    if m["model"] != "non_consumable" and not waived:
        ctx.check("monetization.prefer-non-consumable", len(m.get("justification", "")) >= 40,
                  "non-consumable (買い切り) is preferred; other models need a >=40 char justification")
    bundle = cfg_app.get("bundle_id", "")
    for p in m["products"]:
        pid = p["product_id"]
        ctx.check(f"product.{pid}.prefix", pid.startswith(bundle + "."), f"product id starts with '{bundle}.'")
        ctx.check(f"product.{pid}.type-matches-model",
                  (m["model"] == "non_consumable") <= (p["type"] == "NON_CONSUMABLE"),
                  "NON_CONSUMABLE product for non_consumable model")
        unknown = [u for u in p["unlocks"] if u not in fids]
        ctx.check(f"product.{pid}.unlocks", not unknown, "unlocks reference existing features", details=unknown or None)
        ja = p["localizations"]["ja"]["description"]
        ctx.check(f"product.{pid}.ja", bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", ja)),
                  "Japanese product description is written in Japanese (name may be a brand)")
    pro_features = {u for p in m["products"] for u in p["unlocks"]}
    flagged = {f["id"] for f in data["features"] if f.get("requires_pro")}
    ctx.check("monetization.flags-consistent", waived or flagged == pro_features,
              "features with requires_pro == features unlocked by products",
              details=None if waived or flagged == pro_features else {"requires_pro": sorted(flagged), "unlocked": sorted(pro_features)})
    free_must = [f for f in must if not f.get("requires_pro")]
    ctx.check("monetization.free-value", bool(free_must) or waived, "free tier delivers at least one must-have feature")

    scenes = data["screenshot_scenes"]
    ids = [s["id"] for s in scenes]
    ctx.check("scenes.unique", len(ids) == len(set(ids)), "screenshot scene ids unique")
    bad_sc = [s["id"] for s in scenes if s["screen"] not in sids]
    ctx.check("scenes.screens", not bad_sc, "screenshot scenes use defined screens", details=bad_sc or None)
    ctx.check("scenes.paywall", any("paywall" in s["screen"].lower() or "pro" in s["id"] for s in scenes) or waived,
              "one screenshot scene shows the Pro/paywall value", severity="warning")


def _keyword_list(keywords: str):
    return [k for k in keywords.split(",")]


@gate("aso")
def aso_gate(ctx):
    data = ctx.load_artifact(ASO, "aso")
    mvp = ctx.load_json(MVP)
    if not data or not mvp:
        return
    scene_ids = [s["id"] for s in mvp["screenshot_scenes"]]
    caption_limits = {"en-US": 34, "ja": 18}
    for locale, meta in data["locales"].items():
        kws = _keyword_list(meta["keywords"])
        ctx.check(f"{locale}.keywords.format", all(k and k == k.strip() for k in kws),
                  "keywords are comma separated without spaces around commas")
        lowered = [k.lower() for k in kws]
        ctx.check(f"{locale}.keywords.unique", len(lowered) == len(set(lowered)), "no duplicate keywords")
        name_words = {w.lower() for w in re.split(r"[\s:\-–—]+", meta["name"]) if len(w) > 2}
        dup = sorted(name_words & set(lowered))
        ctx.warn(f"{locale}.keywords.no-name-repeat", not dup, "keywords do not repeat words from the app name", details=dup or None)
        ctx.check(f"{locale}.keywords.length", len(meta["keywords"]) <= 100, f"keywords {len(meta['keywords'])}/100 chars")
        ctx.check(f"{locale}.name.length", len(meta["name"]) <= 30, f"name {len(meta['name'])}/30")
        ctx.check(f"{locale}.subtitle.length", len(meta["subtitle"]) <= 30, f"subtitle {len(meta['subtitle'])}/30")
        ctx.check(f"{locale}.promo.length", len(meta["promotional_text"]) <= 170, f"promotional text {len(meta['promotional_text'])}/170")
        ctx.check(f"{locale}.description.max", len(meta["description"]) <= 4000,
                  f"description {len(meta['description'])}/4000 chars")
        ctx.check(f"{locale}.description.min", len(meta["description"]) >= 300,
                  f"description {len(meta['description'])} chars (>= 300 recommended)")
        if locale == "ja":
            ctx.check("ja.is-japanese", bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", meta["description"])),
                      "Japanese description is written in Japanese")
        caps = meta["screenshot_captions"]
        missing = [s for s in scene_ids if s not in caps]
        ctx.check(f"{locale}.captions.complete", not missing, "caption for every screenshot scene", details=missing or None)
        limit = caption_limits.get(locale, 34)
        long = [k for k, v in caps.items() if len(v["headline"]) > limit]
        ctx.check(f"{locale}.captions.length", not long, f"caption headlines <= {limit} chars", details=long or None)
        ctx.check(f"{locale}.no-price-in-metadata",
                  not re.search(r"(\$\d|¥\d|\d+円|free trial|無料トライアル)", meta["name"] + meta["subtitle"] + meta["keywords"], re.I),
                  "no prices in name/subtitle/keywords (App Review 2.3.7)")
    from ..codegen import PLACEHOLDER_HOST, app_links

    links = app_links(ctx.config)
    ctx.check("links.configured", PLACEHOLDER_HOST not in links["support"] + links["privacyPolicy"],
              "config app.links.support / privacy_policy set to real pages (ask the human if unknown)")
    for locale, meta in data["locales"].items():
        ctx.check(f"{locale}.links.match-app", meta["support_url"] == links["support"] and
                  meta["privacy_policy_url"] == links["privacyPolicy"],
                  "support/privacy URLs equal the in-app links (config app.links)")
    research = ctx.load_json(RESEARCH, required=False) or {}
    competitor_names = {c["name"].strip().lower() for c in research.get("competitors", [])}
    clash = [loc for loc, meta in data["locales"].items() if meta["name"].strip().lower() in competitor_names]
    ctx.check("names.distinct-from-competitors", not clash, "app name differs from every researched competitor",
              details=clash or None)
