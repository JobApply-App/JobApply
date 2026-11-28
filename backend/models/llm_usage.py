"""ORM model for the LLM usage log — one row per successful AI call.

Before this table the only record of what the AI cost was a stdout log line
per call, readable on Render 100 lines at a time, so there was no daily total
anywhere (docs/research/09-companies-and-costs.md, decision 1). Every row is
written by backend/services/llm_client.py, the single place calls go through.

cost_usd is an estimate, computed at write time from the price table in
llm_client (Anthropic's published per-token rates). It is what the daily
per-user spend ceiling (backend/api/deps.py, daily_ai_spend_limit) sums, so
that check is one indexed SUM rather than a price lookup per row.

Metadata only: never the prompt, never the response.
"""
from __future__ import annotations

from sqlalchemy import Column, Float, Index, Integer, String

from backend.core.database import Base


class LlmUsageRow(Base):
    __tablename__ = "llm_usage"

    id                 = Column(String, primary_key=True)
    created_at         = Column(String, nullable=False)   # ISO-8601 UTC
    purpose            = Column(String, nullable=False)
    provider           = Column(String, nullable=False)   # "anthropic" | "gemini"
    model              = Column(String, nullable=False)
    # Text, not an FK: anonymous callers (Eliya's public chat) and
    # process-level work have no user, and a log must never fail a call.
    user_id            = Column(String, nullable=True)
    job_id             = Column(String, nullable=True)
    input_tokens       = Column(Integer, nullable=True)
    output_tokens      = Column(Integer, nullable=True)
    cache_read_tokens  = Column(Integer, nullable=True)
    cache_write_tokens = Column(Integer, nullable=True)
    latency_ms         = Column(Integer, nullable=True)
    cost_usd           = Column(Float, nullable=True)     # null when the model has no known price

    __table_args__ = (
        # The spend ceiling is "sum cost for user_id since UTC midnight".
        Index("ix_llm_usage_user_created", "user_id", "created_at"),
        # The cost report is "group by purpose/model over a date range".
        Index("ix_llm_usage_created", "created_at"),
    )
