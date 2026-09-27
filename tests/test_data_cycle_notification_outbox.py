"""Transactional Data Cycle terminal outbox tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from os import environ
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from sports_forecast.orchestration.data_cycle_recovery import HostStopEvidence
from sports_forecast.service.db.models import (
    Base,
    DataCycleNotificationOutbox,
    DataCycleRun,
)
from sports_forecast.service.db.repository import (
    DATA_CYCLE_STAGES,
    DataCycleNotificationOutboxRepository,
    DataCycleRunRepository,
)


@pytest.fixture
def engine():
    value = create_engine("sqlite://")
    Base.metadata.create_all(value)
    yield value
    value.dispose()


def _complete_run(
    repository: DataCycleRunRepository,
    *,
    run_id: str,
    reason: str,
    terminal_status: str,
    now: datetime,
) -> None:
    repository.create(run_id=run_id, tournament="nhl", reason=reason, at=now)
    for stage in DATA_CYCLE_STAGES:
        repository.start_stage(run_id, stage, at=now)
        repository.finish_stage(
            run_id,
            stage,
            status="partial_success"
            if terminal_status == "partial_success" and stage == "archive_sync"
            else "success",
            counts={"events_found": 4} if stage == "calendar" else {},
            at=now,
        )
    repository.finish_run(
        run_id,
        status=terminal_status,
        required_stages=DATA_CYCLE_STAGES,
        at=now,
    )


def test_terminal_success_and_partial_create_one_row_per_alias(monkeypatch, engine) -> None:
    """Terminal summary and alias fanout are committed with either terminal status."""
    monkeypatch.setenv("SF_DATA_CYCLE_NOTIFICATION_ALIASES", "nhl_admins,nhl_ops")
    now = datetime(2026, 9, 27, 8, tzinfo=UTC)
    with Session(engine) as session:
        repository = DataCycleRunRepository(session)
        _complete_run(
            repository,
            run_id="run-success",
            reason="scheduled",
            terminal_status="success",
            now=now,
        )
        _complete_run(
            repository,
            run_id="run-partial",
            reason="manual",
            terminal_status="partial_success",
            now=now,
        )
        session.flush()
        rows = list(
            session.scalars(
                select(DataCycleNotificationOutbox).order_by(
                    DataCycleNotificationOutbox.run_id,
                    DataCycleNotificationOutbox.destination_alias,
                )
            )
        )

    assert [(row.run_id, row.destination_alias) for row in rows] == [
        ("run-partial", "nhl_admins"),
        ("run-partial", "nhl_ops"),
        ("run-success", "nhl_admins"),
        ("run-success", "nhl_ops"),
    ]


def test_fail_run_creates_outbox_rows_and_rollback_removes_both(monkeypatch, engine) -> None:
    """Failed terminal status and outbox rows share a single DB transaction."""
    monkeypatch.setenv("SF_DATA_CYCLE_NOTIFICATION_ALIASES", "nhl_admins")
    now = datetime(2026, 9, 27, 9, tzinfo=UTC)
    with Session(engine) as session:
        repository = DataCycleRunRepository(session)
        repository.create(run_id="run-failed", tournament="nhl", reason="scheduled", at=now)
        repository.start_stage("run-failed", "calendar", at=now)
        session.commit()

        with pytest.raises(RuntimeError, match="rollback probe"):
            repository.fail_run("run-failed", failure_code="source_fetch_failed", at=now)
            session.flush()
            raise RuntimeError("rollback probe")
        session.rollback()

        assert session.get(DataCycleRun, 1).status == "running"
        assert list(session.scalars(select(DataCycleNotificationOutbox))) == []

        repository.fail_run("run-failed", failure_code="source_fetch_failed", at=now)
        session.commit()
        rows = list(session.scalars(select(DataCycleNotificationOutbox)))
        run = session.scalar(select(DataCycleRun).where(DataCycleRun.run_id == "run-failed"))

    assert run is not None and run.status == "failed"
    assert run.failure_code == "source_fetch_failed"
    assert len(rows) == 1
    assert rows[0].run_id == "run-failed"
    assert rows[0].destination_alias == "nhl_admins"


def test_terminal_producer_rejects_invalid_alias_config_without_terminalizing(
    monkeypatch, engine
) -> None:
    """Некорректный safe alias откатывает terminal transition явно."""
    monkeypatch.setenv("SF_DATA_CYCLE_NOTIFICATION_ALIASES", "nhl-admins,../unsafe")
    now = datetime(2026, 9, 27, 10, tzinfo=UTC)
    with Session(engine) as session:
        repository = DataCycleRunRepository(session)
        repository.create(run_id="run-invalid-alias", tournament="nhl", reason="manual", at=now)
        repository.start_stage("run-invalid-alias", "calendar", at=now)
        session.commit()
        with pytest.raises(ValueError, match="alias"):
            repository.fail_run("run-invalid-alias", failure_code="source_fetch_failed", at=now)
        session.rollback()

    with Session(engine) as session:
        run = session.scalar(select(DataCycleRun).where(DataCycleRun.run_id == "run-invalid-alias"))
        assert run is not None and run.status == "running"
        assert list(session.scalars(select(DataCycleNotificationOutbox))) == []


def test_notification_lease_expiry_retry_backoff_and_idempotent_ack(monkeypatch, engine) -> None:
    """Retry delay grows, expired token is fenced, and ack for current token is idempotent."""
    monkeypatch.setenv("SF_DATA_CYCLE_NOTIFICATION_ALIASES", "nhl_admins")
    start = datetime(2026, 9, 27, 11, tzinfo=UTC)
    with Session(engine, expire_on_commit=False) as session:
        run_repository = DataCycleRunRepository(session)
        run_repository.create(run_id="run-lease", tournament="nhl", reason="manual", at=start)
        run_repository.start_stage("run-lease", "calendar", at=start)
        run_repository.fail_run("run-lease", failure_code="source_fetch_failed", at=start)
        session.commit()

        outbox = DataCycleNotificationOutboxRepository(session)
        first = outbox.claim_due(at=start)
        assert len(first) == 1 and first[0].attempts == 1
        first_token = first[0].lease_token
        session.commit()

        assert outbox.claim_due(at=start + timedelta(minutes=1)) == []
        assert not outbox.acknowledge(
            first[0].id, first_token or "", at=start + timedelta(minutes=2)
        )
        second = outbox.claim_due(at=start + timedelta(minutes=2))
        assert len(second) == 1 and second[0].attempts == 2
        second_token = second[0].lease_token
        assert second_token != first_token
        assert not outbox.acknowledge(second[0].id, first_token or "", at=start)
        assert outbox.retry(
            second[0].id,
            second_token or "",
            error_code="telegram_send_failed",
            at=start + timedelta(minutes=2),
        )
        session.commit()

        assert outbox.claim_due(at=start + timedelta(minutes=2, seconds=59)) == []
        third = outbox.claim_due(at=start + timedelta(minutes=3))
        assert len(third) == 1 and third[0].attempts == 3
        third_token = third[0].lease_token or ""
        assert outbox.acknowledge(third[0].id, third_token, at=start + timedelta(minutes=3))
        session.commit()
        assert outbox.acknowledge(third[0].id, third_token, at=start + timedelta(minutes=4))

        row = session.get(DataCycleNotificationOutbox, third[0].id)
        assert row is not None
        assert row.status == "delivered"
        assert row.delivered_at == datetime(2026, 9, 27, 11, 3)
        assert row.attempts == 3


def test_recovery_terminal_failure_produces_outbox_after_host_proof(monkeypatch, engine) -> None:
    """Recovery failure notification is inserted only in verified terminal transition."""
    alias = "nhl_admins"
    owner = "aabbccdd00112233aabbccdd00112233"
    monkeypatch.setenv("SF_DATA_CYCLE_NOTIFICATION_ALIASES", alias)
    monkeypatch.setenv("SF_DATA_CYCLE_OWNER_ID", owner)
    start = datetime(2026, 9, 27, 13, tzinfo=UTC)
    with Session(engine) as session:
        repository = DataCycleRunRepository(session)
        repository.create(run_id="run-recovered", tournament="nhl", reason="scheduled", at=start)
        repository.claim_executor("run-recovered", owner_id=owner, at=start)
        repository.start_stage("run-recovered", "calendar", owner_generation=1, at=start)
        assert repository.mark_executor_stalled(
            "run-recovered",
            before=start + timedelta(minutes=1),
            at=start + timedelta(minutes=2),
        )
        evidence = HostStopEvidence(
            run_id="run-recovered",
            owner_id=owner,
            owner_generation=1,
            systemd_active_state="inactive",
            systemd_invocation_id=owner,
            systemd_main_pid=0,
            discovered_container_ids=(),
            stopped_container_ids=(),
            remaining_container_ids=(),
            container_run_ids=(),
            container_generations=(),
            container_owner_ids=(),
            inventory_complete=True,
            verified_at=start + timedelta(minutes=2),
        )
        repository.recover_executor(
            "run-recovered", recovery_evidence=evidence, at=start + timedelta(minutes=3)
        )
        session.commit()
        run = repository.get("run-recovered")
        rows = list(session.scalars(select(DataCycleNotificationOutbox)))

    assert run is not None and run.status == "failed"
    assert run.owner_stop_verified_at == datetime(2026, 9, 27, 13, 2)
    assert len(rows) == 1 and rows[0].run_id == "run-recovered"


@pytest.mark.integration
@pytest.mark.skipif(
    not environ.get("SF_TEST_POSTGRES_URL"),
    reason="Задайте SF_TEST_POSTGRES_URL на disposable PostgreSQL для outbox lease race",
)
def test_postgresql_notification_claim_skips_concurrently_leased_rows(monkeypatch) -> None:
    """Параллельные bot pollers получают непересекающиеся row leases."""
    monkeypatch.setenv("SF_DATA_CYCLE_NOTIFICATION_ALIASES", "nhl_admins")
    engine_pg = create_engine(environ["SF_TEST_POSTGRES_URL"], pool_size=3, max_overflow=0)
    schema = f"test_outbox_{uuid4().hex}"
    with engine_pg.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine_pg.execution_options(schema_translate_map={None: schema})
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    try:
        Base.metadata.create_all(scoped)
        with Session(scoped) as session:
            repository = DataCycleRunRepository(session)
            repository.create(run_id="run-claim-race", tournament="nhl", reason="manual", at=now)
            repository.start_stage("run-claim-race", "calendar", at=now)
            repository.fail_run("run-claim-race", failure_code="source_fetch_failed", at=now)
            session.commit()

        barrier = Barrier(2)

        def claim() -> list[tuple[int, str | None]]:
            with Session(scoped, expire_on_commit=False) as session:
                barrier.wait(timeout=5)
                rows = DataCycleNotificationOutboxRepository(session).claim_due(at=now)
                claims = [(row.id, row.lease_token) for row in rows]
                barrier.wait(timeout=5)
                session.commit()
                return claims

        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(executor.map(lambda _index: claim(), range(2)))
        assert sum(len(result) for result in claims) == 1
        tokens = [token for result in claims for _, token in result]
        assert len(set(tokens)) == 1 and tokens[0]
    finally:
        with engine_pg.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine_pg.dispose()
