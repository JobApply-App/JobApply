"""
Hebrew acronyms (צה"ל, בע"מ) written with a bare double quote inside JSON
strings broke every Hebrew CV that mentioned the army (production,
2026-10-30: "TailorAgent JSON unrecoverable" twice for the same job).
"""
import json

from backend.utilities.json_repair import parse_json_robust


def test_bare_quote_in_hebrew_acronym_is_repaired():
    raw = (
        '{"type": "cv", "cv_data": {"summary": "מנהל מוצר בעל ניסיון", '
        '"military_service": {"role": "קצין מודיעין", "unit": "צה"ל"}, '
        '"experience": [{"company": "אקמה בע"מ", "bullets": ["דיווחתי למנכ"ל"]}]}}'
    )
    with_error = None
    try:
        json.loads(raw)
    except json.JSONDecodeError as exc:
        with_error = exc
    assert with_error is not None, "the fixture must reproduce the production failure"

    parsed = parse_json_robust(raw, context="test")
    assert parsed is not None
    cv = parsed["cv_data"]
    assert cv["military_service"]["unit"] == "צה״ל"
    assert cv["experience"][0]["company"] == "אקמה בע״מ"
    assert cv["experience"][0]["bullets"] == ["דיווחתי למנכ״ל"]


def test_quotes_next_to_hebrew_delimiters_are_untouched():
    data = {"a": "שלום", "b": ["א", "ב"], "c": "ציטוט: \"שלום\" כאן"}
    raw = json.dumps(data, ensure_ascii=False)
    assert parse_json_robust(raw) == data


def test_well_formed_gershayim_passes_through():
    data = {"unit": "צה״ל"}
    assert parse_json_robust(json.dumps(data, ensure_ascii=False)) == data
