"""
Long institution names were cut at 35 characters in the CV (production log,
2026-10-28: "IDF School of Compute..."). The limit is 60 now, in the schema,
the tailor's clamp and the PDF builder alike.
"""
from backend.models.cv import LIMITS

NAME = "The Interdisciplinary Center (IDC) Herzliya"   # 43 characters


def test_schema_accepts_a_long_institution_name():
    from backend.models.cv import CVDataSchema
    assert LIMITS["edu_inst"] >= len(NAME)
    cv = CVDataSchema.model_validate({"education": [{"degree": "B.A.", "institution": NAME, "dates": "2019"}]})
    assert cv.education[0].institution == NAME


def test_pdf_shows_the_whole_name():
    from backend.services.pdf_builder import _build_education
    assert NAME in _build_education([{"degree": "B.A.", "institution": NAME, "dates": "2019"}])


def test_tailor_clamp_keeps_the_whole_name():
    from backend.agents.tailor import _LIM
    assert _LIM["edu_inst"] == LIMITS["edu_inst"]
