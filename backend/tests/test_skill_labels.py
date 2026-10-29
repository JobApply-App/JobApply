"""
Skill category labels were cut at 20 characters (production log, 2026-10-29:
"Methodologies & Ope..."), items at 25. The schema, the tailor's clamp, its
prompt and the PDF builder now share one limit.
"""
from backend.models.cv import LIMITS

LABEL = "Methodologies & Operations"          # 26
ITEM = "Customer Journey Mapping & Design"     # 33


def test_limits_fit_real_labels():
    assert LIMITS["skill_label"] >= len(LABEL) and LIMITS["skill_item"] >= len(ITEM)


def test_pdf_shows_the_whole_label_and_item():
    from backend.services.pdf_builder import _build_skills
    html = _build_skills({"categories": [{"label": LABEL, "items": [ITEM]}]})
    assert "Methodologies &amp; Operations" in html and "Customer Journey Mapping &amp; Design" in html


def test_tailor_clamp_and_prompt_match_the_schema():
    from backend.agents import tailor
    assert tailor._LIM["skill_label"] == LIMITS["skill_label"]
    assert tailor._LIM["skill_item"] == LIMITS["skill_item"]
    src = open(tailor.__file__, encoding="utf-8").read()
    assert f"category <={LIMITS['skill_label']} chars" in src
    assert f"skill <={LIMITS['skill_item']} chars" in src
    assert f"<string <={LIMITS['edu_inst']} chars — copy exactly from profile>" in src
