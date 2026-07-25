"""
Regression test for JOB-91: init_db() must not crash on a brand-new,
empty SQLite file.

Root cause: _EVIDENCE_RECORDS_DDL (raw SQL in _migrate_confidence_matrix)
had drifted from EvidenceRecordRow (the ORM class) — 11 columns vs. 13,
missing tenant_id and is_ai_assisted. Migration 003's staleness check
("negative_flag" not in the stored CREATE TABLE SQL) always misfires on a
freshly ORM-created table (the ORM never emits a CHECK constraint), so it
unconditionally rebuilt evidence_records via the drifted DDL and then
crashed on `INSERT INTO evidence_records SELECT * FROM evidence_records_old`
(13 source columns into 11 destination columns).

Running
-------
    backend/.venv/bin/pytest backend/tests/test_init_db_fresh_deployment.py -v
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def _fresh_sqlite_path() -> Path:
    """A path to a SQLite file guaranteed not to exist yet."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="job91_fresh_db_"))
    db_path = tmp_dir / "fresh_jobs.db"
    if db_path.exists():
        db_path.unlink()
    return db_path


class TestInitDbFreshDeployment:
    def test_init_db_does_not_crash_on_fresh_sqlite_file(self, monkeypatch):
        """
        The core JOB-91 regression check: init_db() against a database file
        that has never existed before must not raise sqlite3.OperationalError
        (or anything else).
        """
        import backend.core.migrations as db_module

        db_path = _fresh_sqlite_path()
        assert not db_path.exists()

        fresh_engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        monkeypatch.setattr(db_module, "ENGINE", fresh_engine)

        # Must not raise.
        db_module.init_db()

        assert db_path.exists()

        # The evidence_records table must end up with the full ORM column
        # set (13 columns) — proves the DDL/ORM reconciliation actually
        # took effect, not just that no exception was raised.
        with fresh_engine.connect() as conn:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(evidence_records)"))}
        expected = {
            "evidence_id", "entity_id", "user_id", "tenant_id", "source_type",
            "base_weight", "raw_content", "verified_at", "hard_expires_at",
            "session_id", "event_id", "extra_metadata", "is_ai_assisted",
        }
        assert expected <= cols

        fresh_engine.dispose()

    def test_init_db_is_idempotent_on_fresh_file(self, monkeypatch):
        """Calling init_db() twice against the same fresh file must not raise
        the second time either, and must leave the schema unchanged."""
        import backend.core.migrations as db_module

        db_path = _fresh_sqlite_path()
        fresh_engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        monkeypatch.setattr(db_module, "ENGINE", fresh_engine)

        db_module.init_db()
        db_module.init_db()  # must not raise

        with fresh_engine.connect() as conn:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(evidence_records)"))}
        assert "tenant_id" in cols
        assert "is_ai_assisted" in cols

        fresh_engine.dispose()

    def test_init_db_preserves_data_on_a_db_it_already_initialized(self, monkeypatch):
        """
        Simulates an app restart against an existing (already-migrated)
        jobs.db: data inserted after the first init_db() call must survive
        a second init_db() call untouched (JOB-91 requirement #4 — no
        breakage of existing, incrementally-ALTERed databases).
        """
        import backend.core.migrations as db_module
        from backend.models.profile import EvidenceRecordRow

        db_path = _fresh_sqlite_path()
        fresh_engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        monkeypatch.setattr(db_module, "ENGINE", fresh_engine)

        db_module.init_db()

        with Session(fresh_engine) as session:
            session.add(EvidenceRecordRow(
                evidence_id="ev-1", entity_id="ent-1", user_id="user-1",
                source_type="cv_parse", base_weight=1.0,
                verified_at="2026-01-01T00:00:00Z",
            ))
            session.commit()

        # Simulate the app restarting and calling init_db() again.
        db_module.init_db()

        with Session(fresh_engine) as session:
            row = session.get(EvidenceRecordRow, "ev-1")
            assert row is not None
            assert row.user_id == "user-1"
            assert row.source_type == "cv_parse"

        fresh_engine.dispose()