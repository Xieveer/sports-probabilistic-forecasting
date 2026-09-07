"""Idempotent least-privilege grants after Alembic migration."""

from __future__ import annotations

from sqlalchemy import text

from sports_forecast.service.db.engine import get_engine


def grant_runtime_roles() -> None:
    """Выдать API reader и Worker writer только необходимые grants.

    Команда должна выполняться migration identity после `alembic upgrade head`.
    Она безопасна при повторе и не читает/не логирует credentials.
    """
    statements = (
        "GRANT USAGE ON SCHEMA public TO sf_api_reader, sf_refresh_writer",
        "GRANT SELECT ON TABLE predictions, tournament_publication_states TO sf_api_reader",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE predictions, tournament_publication_states, worker_executions, model_deployments, refresh_locks, canonical_events, canonical_event_revisions, refresh_watermarks, bootstrap_imports TO sf_refresh_writer",
        "GRANT USAGE, SELECT ON SEQUENCE predictions_id_seq, tournament_publication_states_id_seq, worker_executions_id_seq, model_deployments_id_seq, refresh_locks_id_seq, canonical_events_id_seq, canonical_event_revisions_id_seq, refresh_watermarks_id_seq, bootstrap_imports_id_seq TO sf_refresh_writer",
        "REVOKE ALL ON TABLE alembic_version FROM sf_api_reader, sf_refresh_writer",
    )
    with get_engine().begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def main() -> None:
    """Запустить grant bootstrap без вывода credential данных."""
    grant_runtime_roles()


if __name__ == "__main__":
    main()
