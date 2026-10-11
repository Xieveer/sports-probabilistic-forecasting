"""Idempotent least-privilege grants after Alembic migration."""

from __future__ import annotations

from sqlalchemy import text

from sports_forecast.service.db.engine import get_engine


RUNTIME_GRANTS = (
    "GRANT USAGE ON SCHEMA public TO sf_api_reader, sf_refresh_writer, sf_control_api, sf_registry_sync, sf_registry_feedback",
    "GRANT SELECT ON TABLE predictions, tournament_publication_states, canonical_events, canonical_event_revisions, calendar_coverages, odds_observations, odds_acquisition_attempts, data_cycle_stage_results TO sf_api_reader",
    "GRANT SELECT ON TABLE registry_identity_snapshots, registry_snapshot_records, registry_event_resolver_projections, registry_publications, active_registry_installation, registry_canonical_event_mappings TO sf_api_reader",
    "GRANT SELECT (run_id, tournament) ON TABLE data_cycle_runs TO sf_api_reader",
    "GRANT SELECT ON TABLE data_cycle_runs, data_cycle_stage_results, pipeline_schedules, data_cycle_control_requests, data_cycle_dispatcher_state TO sf_control_api",
    "GRANT SELECT ON TABLE data_cycle_notification_outbox TO sf_control_api",
    "GRANT SELECT ON TABLE bet_card_contexts, real_bets, real_bet_audit TO sf_control_api",
    "GRANT SELECT (revision_id, tournament, source_namespace, source_event_id, market, market_spec, outcomes_json, probabilities_json) ON TABLE prediction_revisions TO sf_control_api",
    "GRANT INSERT ON TABLE bet_card_contexts, real_bets, real_bet_audit TO sf_control_api",
    "GRANT UPDATE (status, result, payout, settled_at, revision, updated_at, placed_at, stake, decimal_odds, funding, outcome) ON TABLE real_bets TO sf_control_api",
    "GRANT UPDATE (status, attempts, available_at, lease_token, lease_until, last_error_code, delivered_at) ON TABLE data_cycle_notification_outbox TO sf_control_api",
    "GRANT INSERT, UPDATE ON TABLE pipeline_schedules, data_cycle_dispatcher_state TO sf_control_api",
    "GRANT EXECUTE ON FUNCTION public.mark_data_cycle_executor_stalled(text) TO sf_control_api",
    "GRANT INSERT (run_id, tournament, reason, requested_at, scheduled_for, executor_generation) ON TABLE data_cycle_runs TO sf_control_api",
    "GRANT INSERT (run_id, stage) ON TABLE data_cycle_stage_results TO sf_control_api",
    "GRANT INSERT ON TABLE data_cycle_control_requests TO sf_control_api",
    "GRANT USAGE, SELECT ON SEQUENCE pipeline_schedules_id_seq, data_cycle_control_requests_id_seq, data_cycle_dispatcher_state_id_seq, data_cycle_runs_id_seq, data_cycle_stage_results_id_seq TO sf_control_api",
    "GRANT SELECT ON TABLE registry_identity_snapshots, registry_snapshot_records, registry_event_resolver_projections, registry_publications, active_registry_installation, registry_installation_locks, registry_canonical_event_mappings TO sf_refresh_writer",
    "GRANT INSERT ON TABLE registry_canonical_event_mappings TO sf_refresh_writer",
    "GRANT UPDATE (lock_version) ON TABLE registry_installation_locks TO sf_refresh_writer",
    "GRANT INSERT ON TABLE registry_candidate_outbox TO sf_refresh_writer",
    "GRANT USAGE, SELECT ON SEQUENCE registry_candidate_outbox_id_seq TO sf_refresh_writer",
    "GRANT SELECT, INSERT ON TABLE prediction_revisions TO sf_refresh_writer",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE predictions, tournament_publication_states, worker_executions, model_deployments, refresh_locks, canonical_events, canonical_event_revisions, calendar_coverages, refresh_watermarks, bootstrap_imports, odds_observations, odds_acquisition_attempts, data_cycle_runs, data_cycle_stage_results TO sf_refresh_writer",
    "GRANT SELECT, INSERT ON TABLE data_cycle_notification_outbox TO sf_refresh_writer",
    "GRANT USAGE, SELECT ON SEQUENCE data_cycle_notification_outbox_id_seq TO sf_refresh_writer",
    "GRANT USAGE, SELECT ON SEQUENCE predictions_id_seq, tournament_publication_states_id_seq, worker_executions_id_seq, model_deployments_id_seq, refresh_locks_id_seq, canonical_events_id_seq, canonical_event_revisions_id_seq, calendar_coverages_id_seq, refresh_watermarks_id_seq, bootstrap_imports_id_seq, odds_observations_id_seq, odds_acquisition_attempts_id_seq, data_cycle_runs_id_seq, data_cycle_stage_results_id_seq TO sf_refresh_writer",
    "REVOKE ALL ON TABLE alembic_version FROM sf_api_reader, sf_control_api, sf_refresh_writer, sf_registry_sync, sf_registry_feedback",
)

REGISTRY_SYNC_GRANTS = (
    "GRANT SELECT ON TABLE canonical_events, registry_identity_snapshots, registry_snapshot_records, registry_event_resolver_projections, registry_publications, active_registry_installation, registry_installation_locks, registry_canonical_event_mappings TO sf_registry_sync",
    "GRANT INSERT ON TABLE registry_identity_snapshots, registry_snapshot_records, registry_event_resolver_projections, registry_publications, registry_canonical_event_mappings, active_registry_installation TO sf_registry_sync",
    "GRANT UPDATE (publication_sequence, publication_id, snapshot_id) ON TABLE active_registry_installation TO sf_registry_sync",
    "GRANT UPDATE (lock_version) ON TABLE registry_installation_locks TO sf_registry_sync",
)

REGISTRY_FEEDBACK_GRANTS = (
    "GRANT SELECT ON TABLE registry_candidate_outbox, registry_candidate_batch_sequences TO sf_registry_feedback",
    "GRANT INSERT, UPDATE (last_sequence) ON TABLE registry_candidate_batch_sequences TO sf_registry_feedback",
    "GRANT UPDATE (status, batch_id, attempts, last_error_code, published_at, acknowledged_at) ON TABLE registry_candidate_outbox TO sf_registry_feedback",
)


def grant_runtime_roles() -> None:
    """Выдать runtime identities и registry processes только необходимые grants.

    Команда должна выполняться migration identity после `alembic upgrade head`.
    Она безопасна при повторе и не читает/не логирует credentials.
    """
    with get_engine().begin() as connection:
        for statement in RUNTIME_GRANTS:
            connection.execute(text(statement))
        for statement in REGISTRY_SYNC_GRANTS:
            connection.execute(text(statement))
        for statement in REGISTRY_FEEDBACK_GRANTS:
            connection.execute(text(statement))


def main() -> None:
    """Запустить grant bootstrap без вывода credential данных."""
    grant_runtime_roles()


if __name__ == "__main__":
    main()
