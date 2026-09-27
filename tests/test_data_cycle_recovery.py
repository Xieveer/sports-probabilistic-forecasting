"""Fault-oriented tests for safe Data Cycle executor recovery."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from sports_forecast.orchestration.data_cycle_recovery import HostStopEvidence
from sports_forecast.service.data_cycle_control import dispatch_due_run
from sports_forecast.service.data_cycle_history import serialize_run
from sports_forecast.service.db.models import Base
from sports_forecast.service.db.repository import DataCycleRunRepository


OWNER_A = "aabbccdd00112233aabbccdd00112233"


@pytest.fixture
def session() -> Session:
    """Создать изолированную БД для проверки executor ownership."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def test_stalled_run_is_terminalized_only_after_verified_owner_stop(
    session: Session, monkeypatch
) -> None:
    """Recovery сохраняет прерванную стадию и закрывает run после host proof."""
    now = datetime(2026, 9, 26, 10, tzinfo=UTC)
    repository = DataCycleRunRepository(session)
    repository.create(run_id="run-fenced", tournament="nhl", reason="scheduled", at=now)

    first_fence = repository.claim_executor("run-fenced", owner_id=OWNER_A, at=now)
    assert first_fence == 1
    monkeypatch.setenv("SF_DATA_CYCLE_OWNER_ID", OWNER_A)
    monkeypatch.setenv("SF_DATA_CYCLE_GENERATION", str(first_fence))
    repository.start_stage("run-fenced", "calendar", owner_generation=first_fence, at=now)
    assert repository.mark_executor_stalled(
        "run-fenced",
        before=datetime(2026, 9, 26, 10, 30),
        at=datetime(2026, 9, 26, 11),
    )
    repository.recover_executor(
        "run-fenced",
        recovery_evidence=_verified_stop_evidence(),
        at=datetime(2026, 9, 26, 12),
    )

    recovered = repository.get("run-fenced")
    assert recovered is not None and recovered.status == "failed"
    assert recovered.owner_stop_verified_at == datetime(2026, 9, 26, 11)
    assert recovered.stopped_container_count == 3
    calendar_stage = next(stage for stage in recovered.stages if stage.stage == "calendar")
    assert calendar_stage.status == "failed"
    assert calendar_stage.failure_code == "source_fetch_failed"
    odds_stage = next(stage for stage in recovered.stages if stage.stage == "data_odds")
    assert odds_stage.status == "skipped"
    with pytest.raises(RuntimeError, match="fenc"):
        repository.start_stage("run-fenced", "data_odds", owner_generation=first_fence, at=now)


def test_stale_heartbeat_alone_cannot_transfer_executor_ownership(
    session: Session, monkeypatch
) -> None:
    """Timeout наблюдения переводит run в stalled, но сам не открывает takeover."""
    now = datetime(2026, 9, 26, 10, tzinfo=UTC)
    repository = DataCycleRunRepository(session)
    repository.create(run_id="run-stalled", tournament="nhl", reason="scheduled", at=now)
    repository.claim_executor("run-stalled", owner_id=OWNER_A, at=now)
    monkeypatch.setenv("SF_DATA_CYCLE_OWNER_ID", OWNER_A)
    monkeypatch.setenv("SF_DATA_CYCLE_GENERATION", "1")
    assert repository.mark_executor_stalled(
        "run-stalled",
        before=datetime(2026, 9, 26, 11, tzinfo=UTC),
        at=datetime(2026, 9, 26, 12, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="evidence|подтвержд"):
        repository.recover_executor(
            "run-stalled", recovery_evidence=None, at=datetime(2026, 9, 26, 13, tzinfo=UTC)
        )
    run = repository.get("run-stalled")
    assert run is not None
    assert run.status == "running"
    assert run.executor_owner_id == OWNER_A


def test_publication_guard_rejects_claimed_run_without_owner_environment(
    session: Session, monkeypatch
) -> None:
    """Worker без owner/generation не может пройти pre-publication guard."""
    repository = DataCycleRunRepository(session)
    repository.create(run_id="run-publication-fence", tournament="nhl", reason="scheduled")
    repository.claim_executor(
        "run-publication-fence", owner_id=OWNER_A, at=datetime(2026, 9, 26, 10, tzinfo=UTC)
    )
    monkeypatch.delenv("SF_DATA_CYCLE_OWNER_ID", raising=False)
    monkeypatch.delenv("SF_DATA_CYCLE_GENERATION", raising=False)

    with pytest.raises(RuntimeError, match="generation fenced"):
        repository.assert_executor_owner("run-publication-fence", owner_generation=1)


def test_dispatcher_marks_expired_executor_stalled_without_releasing_active_slot(
    session: Session,
) -> None:
    """Потеря heartbeat видна в DTO, но blocking active run сохраняется."""
    claimed_at = datetime(2026, 9, 26, 10, tzinfo=UTC)
    now = datetime(2026, 9, 26, 11, 36, tzinfo=UTC)
    repository = DataCycleRunRepository(session)
    repository.create(run_id="run-stalled-dto", tournament="nhl", reason="scheduled", at=claimed_at)
    repository.claim_executor("run-stalled-dto", owner_id=OWNER_A, at=claimed_at)

    active, _missed = dispatch_due_run(session, "nhl", "host-a", now=now)

    assert active is not None
    assert active.run_id == "run-stalled-dto"
    assert active.status == "running"
    assert active.executor_stalled_at is not None
    assert serialize_run(active)["status"] == "stalled"
    with pytest.raises(ValueError, match="Executor claim"):
        repository.claim_executor(
            "run-stalled-dto",
            owner_id="bbccddeeff001122bbccddeeff001122",
            at=now,
        )


def test_long_running_stage_heartbeat_prevents_stall_until_heartbeats_stop(
    session: Session, monkeypatch
) -> None:
    """Fake-clock stage past 95 minutes stays owned while periodic heartbeat arrives."""
    from contextlib import contextmanager

    from sports_forecast.orchestration import data_cycle

    started_at = datetime(2026, 9, 26, 10, tzinfo=UTC)
    repository = DataCycleRunRepository(session)
    repository.create(run_id="run-long-stage", tournament="nhl", reason="scheduled", at=started_at)
    repository.claim_executor("run-long-stage", owner_id=OWNER_A, at=started_at)
    monkeypatch.setenv("SF_DATA_CYCLE_OWNER_ID", OWNER_A)
    monkeypatch.setenv("SF_DATA_CYCLE_GENERATION", "1")

    @contextmanager
    def test_session():
        yield session

    monkeypatch.setattr(data_cycle, "get_session", test_session)
    latest = started_at
    for minute in (30, 60, 90, 120, 150):
        latest = started_at + timedelta(minutes=minute)
        data_cycle.heartbeat_executor("run-long-stage", owner_generation=1, at=latest)
        dispatch_due_run(session, "nhl", "host-a", now=latest)
        active = repository.get("run-long-stage")
        assert active is not None and active.status == "running"
        assert active.executor_stalled_at is None

    # Simulate an executor crash: once heartbeats stop beyond the threshold,
    # dispatcher marks the old owner stalled and retains the active slot.
    active, _missed = dispatch_due_run(session, "nhl", "host-a", now=latest + timedelta(minutes=96))
    assert active is not None
    assert active.executor_stalled_at is not None


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("SF_TEST_POSTGRES_URL"),
    reason="Задайте SF_TEST_POSTGRES_URL на disposable PostgreSQL для executor claim race",
)
def test_postgresql_claim_race_assigns_exactly_one_owner() -> None:
    """Concurrent systemd owners не могут получить одинаковый waiting run."""
    engine = create_engine(os.environ["SF_TEST_POSTGRES_URL"], pool_size=3, max_overflow=0)
    schema = f"test_executor_{uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_engine = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(scoped_engine)
        with Session(scoped_engine) as session:
            DataCycleRunRepository(session).create(
                run_id="run-claim-race", tournament="nhl", reason="scheduled"
            )
            session.commit()
        barrier = Barrier(2)

        def claim(owner_id: str) -> tuple[str, int | None]:
            with Session(scoped_engine) as session:
                barrier.wait(timeout=5)
                try:
                    generation = DataCycleRunRepository(session).claim_executor(
                        "run-claim-race", owner_id=owner_id
                    )
                    session.commit()
                    return owner_id, generation
                except ValueError:
                    session.rollback()
                    return owner_id, None

        owners = (OWNER_A, "bbccddeeff001122bbccddeeff001122")
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, owners))
        assert sum(generation is not None for _, generation in results) == 1
        with Session(scoped_engine) as session:
            run = DataCycleRunRepository(session).get("run-claim-race")
            assert run is not None
            assert run.executor_generation == 1
            assert run.executor_owner_id in owners
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()


def test_host_evidence_rejects_container_with_wrong_generation() -> None:
    """Неполная/чужая container inventory не становится доказательством stop."""
    from dataclasses import replace

    evidence = _verified_stop_evidence()
    with pytest.raises(ValueError, match="generation"):
        replace(evidence, container_generations=(1, 2, 1)).validate_for(
            run_id="run-fenced", owner_id=OWNER_A, owner_generation=1
        )
    with pytest.raises(ValueError, match="ещё работают"):
        replace(evidence, remaining_container_ids=("aabbccdd0011",)).validate_for(
            run_id="run-fenced", owner_id=OWNER_A, owner_generation=1
        )


def test_host_evidence_json_has_a_strict_round_trip() -> None:
    """Recovery CLI принимает только полный набор identity и systemd facts."""
    import json
    from dataclasses import asdict

    evidence = _verified_stop_evidence()
    value = asdict(evidence)
    value["verified_at"] = evidence.verified_at.isoformat()
    parsed = HostStopEvidence.from_json(json.dumps(value))

    assert parsed.validate_for(run_id="run-fenced", owner_id=OWNER_A, owner_generation=1) == 3
    with pytest.raises(ValueError, match="структура"):
        HostStopEvidence.from_json(json.dumps({**value, "untrusted": "field"}))


def test_live_labeled_container_keeps_stalled_run_active(session: Session, monkeypatch) -> None:
    """Inactive systemd plus live run container не освобождает право на новый claim."""
    from dataclasses import replace

    now = datetime(2026, 9, 26, 10, tzinfo=UTC)
    repository = DataCycleRunRepository(session)
    repository.create(run_id="run-live-container", tournament="nhl", reason="scheduled", at=now)
    repository.claim_executor("run-live-container", owner_id=OWNER_A, at=now)
    monkeypatch.setenv("SF_DATA_CYCLE_OWNER_ID", OWNER_A)
    monkeypatch.setenv("SF_DATA_CYCLE_GENERATION", "1")
    assert repository.mark_executor_stalled(
        "run-live-container",
        before=datetime(2026, 9, 26, 11, 35, tzinfo=UTC),
        at=datetime(2026, 9, 26, 12, tzinfo=UTC),
    )
    evidence = replace(
        _verified_stop_evidence(),
        run_id="run-live-container",
        remaining_container_ids=("aabbccdd0011",),
    )

    with pytest.raises(ValueError, match="ещё работают"):
        repository.recover_executor(
            "run-live-container", recovery_evidence=evidence, at=datetime(2026, 9, 26, 13)
        )
    with pytest.raises(ValueError, match="Executor claim"):
        repository.claim_executor(
            "run-live-container",
            owner_id="bbccddeeff001122bbccddeeff001122",
            at=datetime(2026, 9, 26, 13),
        )
    run = repository.get("run-live-container")
    assert run is not None
    assert run.status == "running"
    assert run.executor_stalled_at is not None
    assert run.owner_stop_verified_at is None


def _verified_stop_evidence() -> HostStopEvidence:
    """Fixture доказательства: run и все принадлежащие ему one-off containers остановлены."""
    return HostStopEvidence(
        run_id="run-fenced",
        owner_id=OWNER_A,
        owner_generation=1,
        systemd_active_state="inactive",
        systemd_invocation_id="aabbccdd00112233aabbccdd00112233",
        systemd_main_pid=0,
        discovered_container_ids=("aabbccdd0011", "bbccddeeff11", "ccddeeff0011"),
        stopped_container_ids=("aabbccdd0011", "bbccddeeff11", "ccddeeff0011"),
        remaining_container_ids=(),
        container_run_ids=("run-fenced", "run-fenced", "run-fenced"),
        container_generations=(1, 1, 1),
        container_owner_ids=(OWNER_A, OWNER_A, OWNER_A),
        inventory_complete=True,
        verified_at=datetime(2026, 9, 26, 11, tzinfo=UTC),
    )
