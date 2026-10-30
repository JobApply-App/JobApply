"""
JD keyword extraction counted regions, adverbs and soft adjectives as
keywords a CV was "missing" ("us", "apac", "clearly", "collaborative" in a
production panel), lowering every CV's keyword score for words no CV should
contain.
"""
from backend.services.match_score_service import _extract_jd_keywords

JD = (
    "We are hiring a Technical Implementation Specialist for US and APAC customers. "
    "You will clearly communicate, clearly document and clearly present. "
    "Collaborative mindset; collaborative work; collaborative teams. "
    "Experience with APIs, UAT and Jira. APIs integration, APIs troubleshooting, UAT planning, UAT sign-off."
)


def test_regions_adverbs_and_soft_words_are_not_keywords():
    kws = _extract_jd_keywords(JD)
    for noise in ("us", "apac", "clearly", "collaborative"):
        assert noise not in kws, noise


def test_real_skills_are_still_keywords():
    kws = _extract_jd_keywords(JD)
    assert "uat" in kws and "apis" in kws
