"""Quality profiles.

* ``mvp`` (default): delivery first. Checks about polish, depth or thoroughness become
  warnings — they are still evaluated and reported, but no longer block the pipeline.
* ``strict``: every check blocks (previous behaviour).

Never relaxed in any profile: schemas, build success, zero failing tests, App Store hard
limits and formats, StoreKit correctness, localisation completeness, human approvals,
secrets, freshness/consistency of generated artifacts and reports.
"""
from __future__ import annotations

import re

PROFILES = ("mvp", "strict")

RELAXED_IN_MVP = [re.compile(p) for p in (
    # documents / research depth
    r"^doc:", r"^sources\.count$", r"^competitors\.(count|app-store-links)$", r"^demand\.", r"^search-log$",
    r"^differentiation\.", r"^features\.must$",
    # MVP shaping
    r"^scope\.must-count$", r"^monetization\.prefer-non-consumable$", r"^product\..*\.ja$", r"^scenes\.paywall$",
    # design polish
    r"^anti-generic\.", r"^references\.(skill|hig)$", r"^dark-mode\.distinct$", r"^concept\.",
    r"^contrast\.(light|dark)\.accent/background", r"^screenshot\.caption-contrast-all-stops$",
    # UX review depth (the human approval itself is never relaxed)
    r"^coverage\.(screens|first-run|must-features)$", r"^trace\.principles$", r"^steps\.", r"^copy\.ja$",
    # app icon craft
    r"^aso\.(name|keywords)$", r"^palette\.from-design$", r"^layers\.simple$", r"^legibility\.coverage$",
    r"^glyph\.(present|contrast)$",
    # ASO polish (hard App Store limits stay errors)
    r"\.keywords\.(format|unique)$", r"\.description\.min$", r"\.captions\.length$", r"^names\.distinct-from-competitors$",
    # implementation / tests thoroughness (build and failures stay errors)
    r"^tests\.unit-present$", r"^tests\.(unit|ui)\.count$", r"^trace\.screens$", r"^code\.no-placeholders$",
    r"^uitests\.use-cases$", r"^catalog\.non-trivial$",
    # screenshots / support page niceties
    r"^reproducible\.", r"^page\.data-type:",
)]


def profile_of(config: dict) -> str:
    value = (config.get("quality") or {}).get("profile", "mvp")
    return value if value in PROFILES else "mvp"


def relaxed(check_id: str, profile: str) -> bool:
    return profile == "mvp" and any(p.search(check_id) for p in RELAXED_IN_MVP)
