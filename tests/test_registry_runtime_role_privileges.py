"""Проверка границ production ролей registry на disposable PostgreSQL."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text


ROLE_URLS = {
    "sf_registry_sync": "SF_TEST_REGISTRY_SYNC_DATABASE_URL",
    "sf_registry_feedback": "SF_TEST_REGISTRY_FEEDBACK_DATABASE_URL",
    "sf_refresh_writer": "SF_TEST_REFRESH_WRITER_DATABASE_URL",
    "sf_api_reader": "SF_TEST_API_READER_DATABASE_URL",
}


@pytest.mark.integration
@pytest.mark.skipif(
    not all(os.environ.get(name) for name in ROLE_URLS.values()),
    reason="Нужны URL четырёх ролей на disposable PostgreSQL с Alembic head и grants",
)
def test_registry_roles_have_only_their_runtime_capabilities() -> None:
    """Проверить реальные PostgreSQL grants для sync, feedback, Worker и API."""
    expectations = {
        "sf_registry_sync": {
            ("table", "canonical_events", "SELECT"): True,
            ("table", "registry_identity_snapshots", "INSERT"): True,
            ("column", "active_registry_installation.snapshot_id", "UPDATE"): True,
            ("table", "predictions", "SELECT"): False,
            ("table", "registry_candidate_outbox", "SELECT"): False,
        },
        "sf_registry_feedback": {
            ("table", "registry_candidate_outbox", "SELECT"): True,
            ("column", "registry_candidate_outbox.status", "UPDATE"): True,
            ("table", "registry_candidate_batch_sequences", "INSERT"): True,
            ("table", "registry_candidate_outbox", "INSERT"): False,
            ("table", "canonical_events", "SELECT"): False,
            ("table", "predictions", "SELECT"): False,
        },
        "sf_refresh_writer": {
            ("table", "prediction_revisions", "SELECT"): True,
            ("table", "prediction_revisions", "INSERT"): True,
            ("table", "registry_candidate_outbox", "INSERT"): True,
            ("table", "registry_publications", "INSERT"): False,
            ("column", "active_registry_installation.snapshot_id", "UPDATE"): False,
        },
        "sf_api_reader": {
            ("table", "registry_identity_snapshots", "SELECT"): True,
            ("table", "registry_candidate_outbox", "SELECT"): False,
            ("table", "prediction_revisions", "INSERT"): False,
        },
    }
    for role, checks in expectations.items():
        engine = create_engine(os.environ[ROLE_URLS[role]])
        try:
            with engine.connect() as connection:
                assert connection.execute(text("SELECT current_user")).scalar_one() == role
                for (kind, target, privilege), expected in checks.items():
                    if kind == "column":
                        table, column = target.split(".", 1)
                        query = text(
                            "SELECT has_column_privilege(current_user, :table, :column, :privilege)"
                        )
                        values = {"table": table, "column": column, "privilege": privilege}
                    else:
                        query = text("SELECT has_table_privilege(current_user, :table, :privilege)")
                        values = {"table": target, "privilege": privilege}
                    assert connection.execute(query, values).scalar_one() is expected, (
                        role,
                        target,
                        privilege,
                    )
        finally:
            engine.dispose()
