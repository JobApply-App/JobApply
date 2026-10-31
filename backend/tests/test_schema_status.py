"""The database's migration revision is compared with the code's head, so a
deploy that skipped migrations is reported instead of failing silently."""
from backend.core import migrations


class _Pg:
    name = "postgresql"


def _postgres(monkeypatch):
    monkeypatch.setattr(migrations.ENGINE, "dialect", _Pg(), raising=False)


def test_code_head_is_a_real_revision():
    head = migrations._code_head()
    assert head and len(head) == 12


def test_at_head_is_ok(monkeypatch):
    _postgres(monkeypatch)
    monkeypatch.setattr(migrations, "_db_revision", lambda: "abc123def456")
    monkeypatch.setattr(migrations, "_code_head", lambda: "abc123def456")
    assert migrations.schema_status() == "ok"


def test_behind_names_both_revisions(monkeypatch):
    _postgres(monkeypatch)
    monkeypatch.setattr(migrations, "_db_revision", lambda: "c5a91b3e7d02")
    monkeypatch.setattr(migrations, "_code_head", lambda: "e4b8c2a7f915")
    assert migrations.schema_status() == "behind (database c5a91b3e7d02, code e4b8c2a7f915)"


def test_a_failed_check_never_raises(monkeypatch):
    _postgres(monkeypatch)
    def boom():
        raise RuntimeError("no table")
    monkeypatch.setattr(migrations, "_db_revision", boom)
    assert migrations.schema_status() == "unknown (RuntimeError)"
