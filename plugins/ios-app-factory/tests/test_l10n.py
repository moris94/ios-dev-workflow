import json
from pathlib import Path

from appfactory.l10n import analyse_catalog, literal_keys_in_code


def _cat(tmp_path, strings, source="en"):
    p = tmp_path / "Localizable.xcstrings"
    p.write_text(json.dumps({"sourceLanguage": source, "strings": strings, "version": "1.0"}))
    return p


def ja(v, state="translated"):
    return {"localizations": {"ja": {"stringUnit": {"state": state, "value": v}}}}


def test_complete_catalog(tmp_path):
    r = analyse_catalog(_cat(tmp_path, {"Save": ja("保存"), "%lld notes": ja("%lld件のメモ")}))
    assert r["errors"] == [] and set(r["keys"]) == {"Save", "%lld notes"}


def test_missing_untranslated_and_format_mismatch(tmp_path):
    r = analyse_catalog(_cat(tmp_path, {"Save": {}, "Cancel": ja("キャンセル", "needs_review"), "%@ items": ja("項目")}))
    joined = "\n".join(r["errors"])
    assert "'Save': missing 'ja'" in joined
    assert "state=needs_review" in joined
    assert "format specifiers" in joined


def test_plural_variations(tmp_path):
    entry = {"localizations": {"ja": {"variations": {"plural": {"other": {"stringUnit": {"state": "translated", "value": "%lld件"}}}}}}}
    assert analyse_catalog(_cat(tmp_path, {"%lld items": entry}))["errors"] == []


def test_source_language_must_be_english(tmp_path):
    r = analyse_catalog(_cat(tmp_path, {}, source="ja"))
    assert any("sourceLanguage" in e for e in r["errors"])


def test_literal_keys_extracted_from_swift():
    src = {Path("V.swift"): 'Text("Hello")\nButton("Save") {}\nText(verbatim: x)\nText("Hi \\(name)")\n'
                           'let s = String(localized: "Oops")\n.navigationTitle("Notes")\nImage(systemName: "plus")'}
    assert set(literal_keys_in_code(src)) == {"Hello", "Save", "Oops", "Notes"}
