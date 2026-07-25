"""
Matching analysis models for the Robust Matching Engine (V4.1).

ScoringBreakdown holds the four dimension scores; MatchAnalysis is the
complete output of a single engine.score() call.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ScoringBreakdown(BaseModel):
    """Four-axis breakdown. All values are floats in [0, 100]."""

    skills_match: float = Field(..., ge=0, le=100,
        description="Overlap between required/nice-to-have skills and candidate skills. "
                    "Proven (contextualised) skills count fully; declared-only skills count 20%.")
    experience_match: float = Field(..., ge=0, le=100,
        description="Years of relevant experience vs. job requirement, "
                    "weighted by function specificity (titled PM years > functional PM years > generic years).")
    domain_match: float = Field(..., ge=0, le=100,
        description="Industry/domain and customer-segment alignment "
                    "(e.g. B2B SaaS for a B2B SaaS role).")
    seniority_match: float = Field(..., ge=0, le=100,
        description="Alignment between claimed seniority, demonstrated responsibilities, "
                    "and the role's seniority expectations.")

    @property
    def weighted_average(self) -> float:
        """Canonical weighted score: skills 35 %, experience 30 %, domain 20 %, seniority 15 %."""
        return round(
            self.skills_match    * 0.35
            + self.experience_match * 0.30
            + self.domain_match     * 0.20
            + self.seniority_match  * 0.15,
            1,
        )


class MatchAnalysis(BaseModel):
    """Complete output of a single MatchingEngineAgent.score() call."""

    overall_score: int = Field(..., ge=0, le=100,
        description="Final composite score (should be close to breakdown.weighted_average).")
    breakdown: ScoringBreakdown
    strengths: list[str] = Field(...,
        description="Evidence-backed reasons the candidate is a strong fit.")
    weaknesses: list[str] = Field(...,
        description="Evidence-backed gaps or concerns.")
    red_flags: list[str] = Field(...,
        description="Critical issues that may disqualify or require direct mitigation.")
    recommendations: list[str] = Field(...,
        description="Specific, actionable steps to strengthen this application.")
    reasoning: str = Field(...,
        description="Comprehensive paragraph explaining the assessment and its key drivers.")
    model_used: str = Field(default="",
        description="The Anthropic model ID that produced this result.")
