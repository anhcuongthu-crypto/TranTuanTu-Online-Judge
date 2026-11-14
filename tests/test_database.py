"""Regression tests for PostgreSQL schema compatibility."""

import oj.database as database


class RecordingConnection:
    def __init__(self, statements):
        self.statements = statements

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, parameters=None):
        self.statements.append(" ".join(statement.split()))
        return None


def test_postgres_schema_preserves_fractional_scores(monkeypatch):
    statements = []

    monkeypatch.setattr(
        database,
        "connect",
        lambda path: RecordingConnection(statements)
    )

    database._init_postgres("postgresql://example.invalid/test")

    normalized = "\n".join(statements)
    assert "score DOUBLE PRECISION NOT NULL DEFAULT 0" in normalized
    assert "best_score DOUBLE PRECISION NOT NULL DEFAULT 0" in normalized
    assert (
        "ALTER TABLE solves ALTER COLUMN best_score TYPE DOUBLE PRECISION "
        "USING best_score::DOUBLE PRECISION"
    ) in normalized


def test_postgres_pools_close_before_interpreter_shutdown(monkeypatch):
    closed = []

    class FakePool:
        def close(self, timeout=None):
            closed.append(timeout)

    monkeypatch.setattr(
        database,
        "_POSTGRES_POOLS",
        {"postgresql://example.invalid/test": FakePool()}
    )
    database._close_postgres_pools()

    assert closed == [5.0]
    assert database._POSTGRES_POOLS == {}
