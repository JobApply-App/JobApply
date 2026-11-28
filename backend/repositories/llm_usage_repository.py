"""Repository for llm_usage — the per-call AI usage log.

See backend/models/llm_usage.py for what a row is and who writes it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.core.database import ENGINE
from backend.models.llm_usage import LlmUsageRow


def _today_start_utc() -> str:
    # Same clock and string format as cv_generation_repository: ISO-8601 UTC
    # strings sort chronologically, so no date parsing on either side.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")


def record(
    *,
    purpose: str,
    provider: str,
    model: str,
    user_id: Optional[str],
    job_id: Optional[str],
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    cache_read_tokens: Optional[int],
    cache_write_tokens: Optional[int],
    latency_ms: Optional[float],
    cost_usd: Optional[float],
) -> None:
    with Session(ENGINE) as session:
        session.add(LlmUsageRow(
            id=uuid.uuid4().hex,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            purpose=purpose,
            provider=provider,
            model=model,
            user_id=str(user_id) if user_id else None,
            job_id=str(job_id) if job_id else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            latency_ms=int(latency_ms) if latency_ms is not None else None,
            cost_usd=cost_usd,
        ))
        session.commit()


def spend_today(user_id: str) -> float:
    """Estimated USD spent on user_id's behalf since UTC midnight."""
    with Session(ENGINE) as session:
        total = (
            session.query(func.sum(LlmUsageRow.cost_usd))
            .filter(
                LlmUsageRow.user_id == str(user_id),
                LlmUsageRow.created_at >= _today_start_utc(),
            )
            .scalar()
        )
    return float(total or 0.0)
