"""
CV Optimization models.

CVImprovement  — one rewritten section with its rationale and added placeholders.
OptimizationReport — the full output of a single OptimizationEngine.generate_suggestions() call.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CVImprovement(BaseModel):
    """A single before/after CV rewrite with full rationale."""

    original_section: str = Field(...,
        description="The exact original bullet point or paragraph from the CV being rewritten.")
    improved_section: str = Field(...,
        description="The rewritten version — active ownership language, metric placeholders "
                    "where real numbers are unknown, no fabricated facts.")
    logic_behind_change: str = Field(...,
        description="Concise explanation of what was weak (passive voice, vague scope, "
                    "missing outcome) and why the rewrite addresses the specific red_flag or weakness.")
    added_metrics: list[str] = Field(...,
        description="Every placeholder inserted in improved_section, e.g. '[X%]', '[N users]', "
                    "'[Feature Name]'. Empty list if the rewrite added no placeholders.")


class OptimizationReport(BaseModel):
    """Complete output of a single OptimizationEngine.generate_suggestions() call."""

    executive_summary: str = Field(...,
        description="2-3 sentence summary: the biggest CV gaps found and the overall rewrite strategy.")
    priority_order: list[str] = Field(...,
        description="Short labels for the areas to fix first, ordered by impact on score, "
                    "e.g. ['add_ownership_language', 'insert_metrics', 'remove_passive_verbs'].")
    improvements: list[CVImprovement] = Field(...,
        description="One CVImprovement per rewritten section, ordered by priority (highest impact first).")
    model_used: str = Field(default="",
        description="The Anthropic model ID that produced this report.")
