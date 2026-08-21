"""
Regression test for the CRM/Applications status-enum mismatch (2026-08-20).

Deliberately does NOT use the db_available fixture. `ApplicationRow` is a
plain SQLAlchemy model — constructing one in memory and passing it through
`_from_row()` exercises the exact line that crashed
(`ApplicationStatus(row.status)`) with zero DB connection, so this runs on
every CI push instead of being gated behind live Postgres like most of this
module's other tests.
"""
from __future__ import annotations

import pytest

from backend.models.application import ApplicationRow
from backend.repositories.application_repository import _from_row
from backend.schemas.application import ApplicationStatus


def _row(status: str) -> ApplicationRow:
    return ApplicationRow(
        application_id="app-1",
        user_id="user-1",
        job_id="job-1",
        title="Product Manager",
        company="Acme",
        # ats has a SQLAlchemy-level default("Direct"), but that only applies
        # on INSERT — a bare in-memory instantiation like this one leaves it
        # None, which Application's non-Optional `ats: str` then rejects.
        # Set explicitly so this test's failures are about the status enum,
        # not an unrelated fixture gap.
        ats="Direct",
        status=status,
        submitted_at="Today 09:14",
        last_update="2h ago",
        score=0.0,
    )


# Every stage backend/api/routes/crm.py's _STAGES lets a card be dragged
# into. If ApplicationStatus is ever missing one of these, this test names
# exactly which one — rather than a live user discovering it as a 500 on
# their next page load.
_CRM_MOVABLE_STAGES = ("submitted", "phone screen", "technical", "interview", "offer", "rejected")


@pytest.mark.parametrize("stage", _CRM_MOVABLE_STAGES)
def test_from_row_accepts_every_crm_movable_stage(stage):
    result = _from_row(_row(stage))
    assert result.status == ApplicationStatus(stage)


def test_phone_screen_and_technical_are_valid_members():
    # The two that were missing outright — asserted individually so a future
    # revert of just this enum change fails here, not only in the
    # parametrized sweep above.
    assert ApplicationStatus("phone screen") is ApplicationStatus.PHONE_SCREEN
    assert ApplicationStatus("technical") is ApplicationStatus.TECHNICAL
