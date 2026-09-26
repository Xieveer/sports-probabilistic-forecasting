"""Idempotent least-privilege grants after Alembic migration."""

from __future__ import annotations

from sqlalchemy import text

from sports_forecast.service.db.engine import get_engine


RUNTIME_GRANTS = (
    "GRANT USAGE ON SCHEMA public TO sf_api_reader, sf_refresh_writer",
    "GRANT SELECT ON TABLE predictions, tournament_publication_states, canonical_events, canonical_event_revisions, calendar_coverages, odds_observations, odds_acquisition_attempts TO sf_api_reader",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE predictions, tournament_publication_states, worker_executions, model_deployments, refresh_locks, canonical_events, canonical_event_revisions, calendar_coverages, refresh_watermarks, bootstrap_imports, odds_observations, odds_acquisition_attempts, data_cycle_runs, data_cycle_stage_results TO sf_refresh_writer",
    "GRANT USAGE, SELECT ON SEQUENCE predictions_id_seq, tournament_publication_states_id_seq, worker_executions_id_seq, model_deployments_id_seq, refresh_locks_id_seq, canonical_events_id_seq, canonical_event_revisions_id_seq, calendar_coverages_id_seq, refresh_watermarks_id_seq, bootstrap_imports_id_seq, odds_observations_id_seq, odds_acquisition_attempts_id_seq, data_cycle_runs_id_seq, data_cycle_stage_results_id_seq TO sf_refresh_writer",
    "REVOKE ALL ON TABLE alembic_version FROM sf_api_reader, sf_refresh_writer",
)


def grant_runtime_roles() -> None:
    """Выдать API reader и Worker writer только необходимые grants.

    Команда должна выполняться migration identity после `alembic upgrade head`.
    Она безопасна при повторе и не читает/не логирует credentials.
    """
    with get_engine().begin() as connection:
        for statement in RUNTIME_GRANTS:
            connection.execute(text(statement))


def main() -> None:
    """Запустить grant bootstrap без вывода credential данных."""
    grant_runtime_roles()


if __name__ == "__main__":
    main()
