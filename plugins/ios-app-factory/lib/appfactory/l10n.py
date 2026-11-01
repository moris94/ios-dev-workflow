"""String Catalog (.xcstrings) analysis for en (development language) + ja."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

from .jsonio import read_json

FORMAT_RE = re.compile(r"%(?:\d+\$)?[-+ #0]*\d*(?:\.\d+)?(?:hh|h|ll|l|z|t|j|L)?[@dDuUxXoOfeEgGcCsSpaA]")
JA_RE = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]")

# SwiftUI initialisers whose first string literal is a LocalizedStringKey.
LITERAL_KEY_RE = re.compile(
    r"(?:\b(?:Text|Button|Label|Toggle|Section|NavigationLink|TextField|SecureField|Picker|Stepper|Link|LabeledContent|"
    r"ContentUnavailableView|navigationTitle|alert|confirmationDialog|accessibilityLabel|accessibilityHint|"
    r"LocalizedStringKey|LocalizedStringResource)\(\s*|String\(localized:\s*)\"((?:[^\"\\]|\\.)*)\""
)


def _units(entry: dict) -> Iterator[Tuple[str, str, str]]:
    """Yield (path, state, value) for every stringUnit in a localization, incl. plural/device variations."""
    def walk(node, path):
        if not isinstance(node, dict):
            return
        if "stringUnit" in node:
            unit = node["stringUnit"]
            yield path, unit.get("state", ""), unit.get("value", "")
        for kind in ("variations",):
            for vkind, cases in node.get(kind, {}).items():
                for case, sub in cases.items():
                    yield from walk(sub, f"{path}/{vkind}.{case}")
        for i, sub in enumerate(node.get("substitutions", {}).values() if isinstance(node.get("substitutions"), dict) else []):
            yield from walk(sub, f"{path}/sub{i}")
    yield from walk(entry, "")


def analyse_catalog(path: Path, required_locales=("en", "ja")) -> Dict[str, List]:
    data = read_json(path)
    result = {"errors": [], "warnings": [], "keys": []}
    if data is None:
        result["errors"].append(f"{path.name}: missing")
        return result
    if data.get("sourceLanguage") != "en":
        result["errors"].append(f"{path.name}: sourceLanguage must be 'en' (English is the default)")
    for key, entry in data.get("strings", {}).items():
        if entry.get("shouldTranslate") is False or key.strip() == "":
            continue
        result["keys"].append(key)
        if entry.get("extractionState") == "stale":
            result["warnings"].append(f"{key!r}: stale (no longer used in code)")
        locs = entry.get("localizations", {})
        en_values = [v for _, _, v in _units(locs.get("en", {}))] or [key]
        for loc in required_locales:
            if loc == "en" and "en" not in locs:
                continue  # key itself is the English source string
            units = list(_units(locs.get(loc, {})))
            if not units:
                result["errors"].append(f"{key!r}: missing '{loc}' translation")
                continue
            for upath, state, value in units:
                if state not in ("translated",):
                    result["errors"].append(f"{key!r}[{loc}{upath}]: state={state or 'missing'} (must be 'translated')")
                if not value.strip():
                    result["errors"].append(f"{key!r}[{loc}{upath}]: empty value")
        en_fmt = sorted(FORMAT_RE.findall(en_values[0])) if en_values else []
        for upath, _, value in _units(locs.get("ja", {})):
            if "variations" not in locs.get("ja", {}) and sorted(FORMAT_RE.findall(value)) != en_fmt:
                result["errors"].append(f"{key!r}[ja{upath}]: format specifiers {FORMAT_RE.findall(value)} != en {en_fmt}")
            if value and not JA_RE.search(value) and re.search(r"[A-Za-z]{4,}", value) and value != key:
                result["warnings"].append(f"{key!r}[ja]: looks untranslated ({value!r})")
    return result


def literal_keys_in_code(sources: Dict[Path, str]) -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {}
    for path, text in sources.items():
        for m in LITERAL_KEY_RE.finditer(text):
            key = m.group(1)
            if "\\(" in key or not key.strip():
                continue  # interpolated keys are verified by Xcode's extraction
            key = key.replace('\\"', '"').replace("\\n", "\n")
            found.setdefault(key, []).append(path.name)
    return found
