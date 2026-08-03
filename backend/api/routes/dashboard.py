"""
Aggregated Overview-page endpoint — streamed.

GET /api/dashboard/overview computes the 4 datasets the Overview page (and
its embedded TrustDashboard) needs — daily KPIs, LinkedIn scraper status,
confidence matrix, and trust score — from ONE shared AUTOCOMMIT connection
(same efficiency work as before: one connection, one LEFT JOIN for
profile_entities + evidence instead of two queries — see
profile_entity_repository.get_all_with_evidence_for_user()), but STREAMS each
section to the client as newline-delimited JSON (NDJSON) the instant it's
computed, instead of buffering all 4 into one JSON object.

Why streaming, not 4 separate requests: splitting this back into 4 HTTP
calls (the pre-aggregation design) would reintroduce the duplicate entity/
evidence loads and per-request connection overhead this endpoint exists to
eliminate — measured and eliminated earlier in this project's history.
Streaming keeps the exact same one-connection, one-JOIN backend work and
only changes DELIVERY: overview and scraper_status (one query each) reach
the browser as soon as their own query resolves — measured ~400-850ms,
roughly 600-1000ms earlier than the old buffered response. confidence_matrix
and trust_score both then arrive together, right after the entities+evidence
JOIN resolves (~1.3-1.5s) — they're tied, not staggered: both are pure
Python computation from the same already-loaded entity_rows/evidence, with
zero further DB access (compute_profile_familiarity_from_entities() removed
trust_score's separate familiarity query earlier in this project's history —
see ProfileUpdateService). The JOIN itself, not any one section's own
compute, is the real remaining sequential cost.

Each section's computation is wrapped in its own try/except: one section
failing emits an {"error": ...} line for JUST that section and the stream
continues — it does not abort sections that already succeeded or would
still succeed after it.

Correctness-first design: still NO server-side cache. Every request reads
the current committed database state — streaming only changes when each
already-fresh section reaches the client, not what data it contains.

The 4 existing endpoints (GET /api/analytics/overview, GET
/api/settings/scraper-status, GET /api/profile/{user_id}/trust-score, GET
/api/profile/{user_id}/confidence-matrix) are unchanged and still work —
this is an addition, not a replacement.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Iterator, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.api.deps import CurrentUser, get_current_user, standard_rate_limit
from backend.api.routes.profile import build_trust_score_response
from backend.api.routes.settings import SCRAPER_STATUS_KEYS, build_scraper_status
from backend.core.database import ENGINE
from backend.repositories import kv_repository, profile_entity_repository
from backend.services.analytics_service import compute_overview
from backend.services.confidence_matrix_service import (
    compute_breakdown,
    compute_radar,
    entities_from_profile_entities,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(standard_rate_limit)])

# Section names, in the order the frontend can expect them to arrive (not
# guaranteed — a slow network could reorder chunks at the transport level in
# theory, so the frontend keys off each line's own "section" field rather
# than assuming position — but under normal operation this is the emission
# order, fastest-to-compute first).
SECTION_OVERVIEW          = "overview"
SECTION_SCRAPER_STATUS    = "scraper_status"
SECTION_CONFIDENCE_MATRIX = "confidence_matrix"
SECTION_TRUST_SCORE       = "trust_score"


def _line(section: str, data: Optional[dict] = None, error: Optional[str] = None) -> bytes:
    payload: dict = {"section": section}
    if error is not None:
        payload["error"] = error
    else:
        payload["data"] = data
    return (json.dumps(payload) + "\n").encode("utf-8")


def _stream_dashboard_overview(user_id: str) -> Iterator[bytes]:
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── One shared connection for the fast, independent sections ──────────
    # Same AUTOCOMMIT + one-connection reasoning as before (see prior
    # revision's docstring in git history for the full measured rationale):
    # no write/flush/commit anywhere on this path, so there's nothing an
    # implicit transaction would need to roll back, and no cross-statement
    # snapshot requirement — these 3 reads are logically independent facets
    # of the dashboard, not a set of values that must match to the millisecond.
    entity_rows = None
    evidence_by_entity = None

    with ENGINE.connect().execution_options(isolation_level="AUTOCOMMIT") as conn, \
            Session(bind=conn) as db:
        try:
            overview_kpis = compute_overview(user_id, session=db)
            yield _line(SECTION_OVERVIEW, data=overview_kpis)
        except Exception as exc:
            logger.exception("[dashboard/overview-stream] overview KPI section failed for user=%s", user_id)
            yield _line(SECTION_OVERVIEW, error=str(exc) or "Failed to load KPIs.")

        try:
            scraper_entries = kv_repository.get_many(SCRAPER_STATUS_KEYS, session=db)
            scraper_status = build_scraper_status(scraper_entries)
            yield _line(SECTION_SCRAPER_STATUS, data=scraper_status.model_dump())
        except Exception as exc:
            logger.exception("[dashboard/overview-stream] scraper-status section failed for user=%s", user_id)
            yield _line(SECTION_SCRAPER_STATUS, error=str(exc) or "Failed to load scraper status.")

        try:
            entity_rows, evidence_by_entity = profile_entity_repository.get_all_with_evidence_for_user(
                user_id, now_iso, session=db
            )
        except Exception as exc:
            logger.exception(
                "[dashboard/overview-stream] entity+evidence load failed for user=%s", user_id
            )
            err = str(exc) or "Failed to load profile data."
            yield _line(SECTION_CONFIDENCE_MATRIX, error=err)
            yield _line(SECTION_TRUST_SCORE, error=err)
            return

    # ── confidence_matrix and trust_score: both pure Python from the data
    # just loaded — neither needs any further DB access
    # (compute_profile_familiarity_from_entities() computes the Holistic
    # Familiarity score from entity_rows directly, no separate query), so
    # both arrive within milliseconds of each other, right after the JOIN.
    try:
        cm_entity_rows, cm_evidence_by_entity = entities_from_profile_entities(entity_rows, evidence_by_entity)
        radar_data = compute_radar(cm_entity_rows, cm_evidence_by_entity, user_id)
        entity_breakdown = compute_breakdown(cm_entity_rows, cm_evidence_by_entity)
        confidence_matrix = {
            "user_id":          user_id,
            "radar_data":       radar_data,
            "entity_breakdown": entity_breakdown,
            "computed_at":      datetime.now(timezone.utc).isoformat(),
        }
        yield _line(SECTION_CONFIDENCE_MATRIX, data=confidence_matrix)
    except Exception as exc:
        logger.exception("[dashboard/overview-stream] confidence-matrix section failed for user=%s", user_id)
        yield _line(SECTION_CONFIDENCE_MATRIX, error=str(exc) or "Failed to compute confidence matrix.")

    try:
        trust_score = build_trust_score_response(user_id, entity_rows, evidence_by_entity, now_iso)
        yield _line(SECTION_TRUST_SCORE, data=trust_score)
    except Exception as exc:
        logger.exception("[dashboard/overview-stream] trust-score section failed for user=%s", user_id)
        yield _line(SECTION_TRUST_SCORE, error=str(exc) or "Failed to compute trust score.")


@router.get("/overview")
def get_dashboard_overview(user: CurrentUser = Depends(get_current_user)) -> StreamingResponse:
    """
    Streams the Overview page's 4 sections as newline-delimited JSON
    (NDJSON), one line per section, as soon as each is computed — instead of
    buffering all 4 into one JSON object and waiting for the slowest
    (trust_score) before sending anything.

    Each line has the shape:
        {"section": "overview" | "scraper_status" | "confidence_matrix" | "trust_score",
         "data": <same shape as the corresponding standalone endpoint>}
    or, if that section's computation failed:
        {"section": "...", "error": "<message>"}

    Always computed fresh from the current committed database state on every
    request — no caching layer. Streaming only changes WHEN each
    already-fresh section reaches the client, never what data it contains.
    """
    return StreamingResponse(
        _stream_dashboard_overview(user.user_id),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-store",
            # Disabling any downstream proxy buffering (nginx-style) so the
            # stream isn't accidentally coalesced back into one write.
            "X-Accel-Buffering": "no",
        },
    )
