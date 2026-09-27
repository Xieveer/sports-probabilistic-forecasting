"""Сервисные команды durable lifecycle Data Cycle."""

from __future__ import annotations

from datetime import UTC, datetime

from omegaconf import ListConfig

from sports_forecast.config.loaders import load_tournament_config
from sports_forecast.orchestration.data_cycle_recovery import HostStopEvidence
from sports_forecast.service.db.engine import get_session
from sports_forecast.service.db.repository import DataCycleRunRepository


def load_required_stages(tournament: str) -> frozenset[str]:
    """Загрузить policy обязательных Data Cycle stages из tournament Hydra config."""
    tournament_config = load_tournament_config(tournament)
    policy = tournament_config.get("data_cycle")
    required = policy.get("required_stages") if policy is not None else None
    if not isinstance(required, (list, tuple, ListConfig)) or not required:
        raise ValueError("Для pipeline не настроены обязательные стадии Data Cycle")
    if any(not isinstance(stage, str) for stage in required):
        raise ValueError("Pipeline policy содержит некорректный список обязательных стадий")
    return frozenset(required)


def create_run(run_id: str, tournament: str, reason: str) -> None:
    """Зарезервировать run и результаты всех фиксированных стадий."""
    with get_session() as session:
        DataCycleRunRepository(session).create(run_id=run_id, tournament=tournament, reason=reason)


def claim_executor(run_id: str, owner_id: str) -> int:
    """Принять waiting run от одного systemd invocation и вернуть generation."""
    with get_session() as session:
        return DataCycleRunRepository(session).claim_executor(run_id, owner_id=owner_id)


def heartbeat_executor(run_id: str, *, owner_generation: int, at: datetime | None = None) -> None:
    """Продлить живое владение run для текущей executor generation."""
    with get_session() as session:
        DataCycleRunRepository(session).heartbeat_executor(
            run_id, owner_generation=owner_generation, at=at
        )


def get_executor_owner(run_id: str) -> dict[str, object]:
    """Прочитать приватную owner identity для ограниченного host recovery adapter."""
    with get_session() as session:
        run = DataCycleRunRepository(session).get(run_id)
        if run is None or run.executor_owner_id is None or run.executor_generation < 1:
            raise ValueError("Data Cycle executor owner отсутствует")
        return {
            "run_id": run.run_id,
            "owner_id": run.executor_owner_id,
            "generation": run.executor_generation,
            "status": "stalled" if run.executor_stalled_at is not None else run.status,
            "stalled_at": run.executor_stalled_at,
        }


def recover_executor(run_id: str, evidence: HostStopEvidence) -> None:
    """Закрыть stalled run после проверки полного host evidence."""
    with get_session() as session:
        DataCycleRunRepository(session).recover_executor(
            run_id, recovery_evidence=evidence, at=datetime.now(UTC)
        )


def start_stage(run_id: str, stage: str) -> None:
    """Перевести одну стадию в running."""
    with get_session() as session:
        DataCycleRunRepository(session).start_stage(run_id, stage)


def finish_stage(
    run_id: str, stage: str, *, status: str, counts: dict[str, int] | None = None
) -> None:
    """Зафиксировать результат стадии и её агрегированные счётчики."""
    with get_session() as session:
        DataCycleRunRepository(session).finish_stage(run_id, stage, status=status, counts=counts)


def finish_run(run_id: str, *, status: str, summary: dict[str, int] | None = None) -> None:
    """Закрыть run вручную либо вывести итоговый статус из фактических стадий."""
    with get_session() as session:
        repository = DataCycleRunRepository(session)
        run = repository.get(run_id)
        if run is None:
            raise ValueError("Data Cycle run отсутствует")
        repository.finish_run(
            run_id,
            status=status,
            required_stages=load_required_stages(run.tournament),
            at=datetime.now(UTC),
            summary=summary,
        )


def fail_run(run_id: str, *, failure_code: str, tournament: str | None = None) -> None:
    """Закрыть run и, для NHL acquisition failure, старить попытку coverage."""
    with get_session() as session:
        repo = DataCycleRunRepository(session)
        run = repo.get(run_id)
        calendar_failed = bool(
            tournament is not None
            and run is not None
            and run.current_stage == "calendar"
            and any(stage.stage == "calendar" and stage.status == "running" for stage in run.stages)
        )
        repo.fail_run(run_id, failure_code=failure_code, at=datetime.now(UTC))
        if calendar_failed and tournament is not None:
            repo.record_calendar_failure(
                tournament=tournament,
                source="nhl_web_api",
                failure_code="source_fetch_failed",
                at=datetime.now(UTC),
            )
