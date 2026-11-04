"""UI/UX gate: representative use cases are complete, traceable, rendered and human-approved."""
from __future__ import annotations

import re

from .. import approval
from .. import ux as ux_mod
from . import gate
from .planning import CHARTER, MVP

JA_RE = re.compile(r"[぀-ヿ一-鿿]")


@gate("ux_review")
def ux_gate(ctx):
    data = ctx.load_artifact(ux_mod.UX_JSON, "ux")
    ctx.require_text(f"{ux_mod.UX_DIR}/ux.md", 300)
    mvp, charter = ctx.load_json(MVP), ctx.load_json(CHARTER)
    if not (data and mvp and charter):
        return
    ucs = data["use_cases"]
    ids = [u["id"] for u in ucs]
    ctx.check("use-cases.unique", len(ids) == len(set(ids)), "use case ids unique")
    screens = {s["id"] for s in mvp["screens"]}
    fids = {f["id"] for f in mvp["features"]}
    pids = {p["id"] for p in charter["principles"]}
    bad_screens = sorted({f"{u['id']}:{s['screen']}" for u in ucs for s in u["steps"] if s["screen"] not in screens})
    ctx.check("trace.screens", not bad_screens, "every step uses an MVP screen", details=bad_screens or None)
    bad_f = sorted({f"{u['id']}:{f}" for u in ucs for f in u["features"] if f not in fids})
    ctx.check("trace.features", not bad_f, "use cases reference MVP features", details=bad_f or None)
    bad_p = sorted({f"{u['id']}:{p}" for u in ucs for p in u["principle_ids"] if p not in pids})
    ctx.check("trace.principles", not bad_p, "use cases reference charter principles", details=bad_p or None)
    must = {f["id"] for f in mvp["features"] if f["priority"] == "must"}
    covered = {f for u in ucs for f in u["features"]}
    ctx.check("coverage.must-features", must <= covered, "every must-have feature appears in a representative use case",
              details=sorted(must - covered) or None)
    kinds = {u["kind"] for u in ucs}
    ctx.check("coverage.core", "core" in kinds, "at least one core use case")
    ctx.check("coverage.first-run", "first_run" in kinds, "first-run / empty-state experience is designed")
    if mvp["monetization"].get("products"):
        paywall = [u for u in ucs if u["kind"] == "monetization"]
        ctx.check("coverage.monetization", bool(paywall), "purchase / restore flow is designed (monetization use case)")
        texts = " ".join(c.get("text", "") + " ".join(c.get("items", []))
                         for u in paywall for s in u["steps"] for c in s["wireframe"]["components"])
        ctx.check("monetization.restore", bool(re.search(r"restore", texts, re.I)),
                  "paywall wireframe shows Restore Purchases")
    unused = sorted(screens - {s["screen"] for u in ucs for s in u["steps"]})
    ctx.warn("coverage.screens", not unused, "every MVP screen is shown in some use case", details=unused or None)
    bad_ja = [u["id"] for u in ucs if not JA_RE.search(u["title"]["ja"])]
    bad_ja += [f"{u['id']} step {i + 1}" for u in ucs for i, s in enumerate(u["steps"])
               if s.get("copy") and not JA_RE.search(s["copy"]["ja"])]
    ctx.check("copy.ja", not bad_ja, "Japanese titles/copy are written in Japanese", details=bad_ja or None)
    def _tap_ok(w):
        t = w.get("tap")
        if t in ("leading", "trailing"):
            return bool((w.get("nav") or {}).get(t))
        return isinstance(t, int) and t < len(w["components"])

    bad_tap = [f"{u['id']} step {i + 1}" for u in ucs for i, s in enumerate(u["steps"][:-1]) if not _tap_ok(s["wireframe"])]
    ctx.check("steps.tap-targets", not bad_tap, "every step except the last marks the element the user acts on",
              details=bad_tap or None)
    long_core = [u["id"] for u in ucs if u["kind"] == "core" and len(u["steps"]) > 6]
    ctx.warn("steps.core-length", not long_core, "core use cases take <= 6 steps", details=long_core or None)

    expected = ux_mod.expected_files(ctx.project)
    stale = [rel for rel, blob in expected.items() if not ctx.path(rel).exists() or ctx.path(rel).read_bytes() != blob]
    extra = [ctx.project.rel(p) for p in ux_mod.board_paths(ctx.project) if ctx.project.rel(p) not in expected]
    ctx.check("storyboards.current", not stale and not extra, "storyboards match ux.json (run `app-factory ux render`)",
              details=(stale + extra) or None)

    ok, msg = approval.verify(ctx.project, "ux", ux_mod.ux_digest(ctx.project))
    ctx.check("approval.human", ok, msg if ok else
              f"{msg} — show the storyboards to the human and ask them to run `app-factory approve ux` in their own terminal")
