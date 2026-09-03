"""Immutable initial bootstrap canonical NHL history без обращения к provider API."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from sports_forecast.deploy.serving_data import ArchiveArtifact, archive_snapshot, verify_archive
from sports_forecast.service.db.engine import get_session
from sports_forecast.service.db.models import (
    BootstrapImport,
    CanonicalEvent,
    CanonicalEventRevision,
    RefreshWatermark,
)
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

_BOOTSTRAP_METADATA = "bootstrap.json"
_EVENTS_FILE = "canonical_events.jsonl"
_SCHEMA_VERSION = 1
_NHL_REQUIRED_COLUMNS = frozenset({"id", "datetime", "match_is_end"})
_NHL_RESULT_COLUMNS = (
    "home_score_ft",
    "away_score_ft",
    "match_end",
    "home_score_mt",
    "away_score_mt",
)


class CanonicalBootstrapError(ValueError):
    """Bootstrap bundle не соответствует canonical NHL contract."""


@dataclass(frozen=True)
class BootstrapImportResult:
    """Безопасный итог attempted bootstrap import."""

    artifact_id: str
    events_count: int
    imported: bool


def _canonical_json(value: object) -> str:
    """Сериализовать значение стабильно для manifest/revision identity."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _revision_sha256(payload: dict[str, Any], result: dict[str, str | None]) -> str:
    """Построить content hash provider record без времени локального import."""
    digest = hashlib.sha256()
    digest.update(_canonical_json({"payload": payload, "result": result}).encode("utf-8"))
    return digest.hexdigest()


def _parse_datetime(value: str) -> datetime:
    """Проверить и нормализовать provider timestamp к UTC."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanonicalBootstrapError("NHL record содержит неверный datetime") from exc
    if parsed.tzinfo is None:
        raise CanonicalBootstrapError("NHL record datetime должен содержать timezone")
    return parsed.astimezone(UTC)


def _event_from_nhl_row(row: dict[str, str]) -> dict[str, Any]:
    """Преобразовать документированный NHL source row в canonical envelope."""
    missing = [column for column in _NHL_REQUIRED_COLUMNS if not row.get(column)]
    if missing:
        raise CanonicalBootstrapError(
            f"NHL source row не содержит обязательные поля: {sorted(missing)}"
        )
    scheduled_at = _parse_datetime(str(row["datetime"]))
    result = {column: row.get(column) or None for column in _NHL_RESULT_COLUMNS}
    payload = {key: value for key, value in row.items() if key is not None}
    is_finished = str(row["match_is_end"]) == "1"
    return {
        "schema_version": _SCHEMA_VERSION,
        "sport": "ice_hockey",
        "tournament": "nhl",
        "source": "nhl_web_api",
        "source_event_id": str(row["id"]),
        "scheduled_at": scheduled_at.isoformat().replace("+00:00", "Z"),
        "status": "finished" if is_finished else "upcoming",
        "result": result,
        "payload": payload,
        "revision_sha256": _revision_sha256(payload, result),
    }


def build_nhl_bootstrap_bundle(source_csv: Path, bundle_root: Path) -> ArchiveArtifact:
    """Собрать immutable initial NHL bundle из существующего локального source.csv.

    Args:
        source_csv: Полная локальная NHL история документированного source contract.
        bundle_root: Локальный root content-addressed immutable bundles.

    Returns:
        Проверенный bundle, который можно безопасно передать на VPS.
    """
    try:
        with source_csv.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise CanonicalBootstrapError("NHL source.csv не содержит заголовок")
            missing_columns = _NHL_REQUIRED_COLUMNS.difference(reader.fieldnames)
            if missing_columns:
                raise CanonicalBootstrapError(
                    f"NHL source.csv не содержит колонки: {sorted(missing_columns)}"
                )
            events = [_event_from_nhl_row(dict(row)) for row in reader]
    except OSError as exc:
        raise CanonicalBootstrapError(f"NHL source.csv недоступен: {source_csv}") from exc
    if not events:
        raise CanonicalBootstrapError("NHL source.csv не содержит событий")
    event_ids = [str(event["source_event_id"]) for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise CanonicalBootstrapError("NHL source.csv содержит duplicate id")

    stage = Path(tempfile.mkdtemp(prefix="nhl-bootstrap-"))
    try:
        events_path = stage / _EVENTS_FILE
        events_path.write_text(
            "".join(_canonical_json(event) + "\n" for event in events), encoding="utf-8"
        )
        (stage / _BOOTSTRAP_METADATA).write_text(
            _canonical_json(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "kind": "canonical_initial_bootstrap",
                    "sport": "ice_hockey",
                    "tournament": "nhl",
                    "source": "nhl_web_api",
                    "events_file": _EVENTS_FILE,
                    "events_count": len(events),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return archive_snapshot(stage, bundle_root)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _load_verified_events(bundle_path: Path) -> tuple[ArchiveArtifact, list[dict[str, Any]]]:
    """Проверить bundle до чтения и DB mutation, затем загрузить event envelopes."""
    artifact = verify_archive(bundle_path)
    try:
        metadata = json.loads((bundle_path / _BOOTSTRAP_METADATA).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalBootstrapError("Bootstrap metadata недоступен или невалиден") from exc
    expected_metadata = {
        "schema_version": _SCHEMA_VERSION,
        "kind": "canonical_initial_bootstrap",
        "sport": "ice_hockey",
        "tournament": "nhl",
        "source": "nhl_web_api",
        "events_file": _EVENTS_FILE,
    }
    if not isinstance(metadata, dict) or any(
        metadata.get(key) != value for key, value in expected_metadata.items()
    ):
        raise CanonicalBootstrapError("Bootstrap metadata не соответствует NHL canonical contract")
    try:
        events = [
            json.loads(line)
            for line in (bundle_path / _EVENTS_FILE).read_text(encoding="utf-8").splitlines()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalBootstrapError("Bootstrap events недоступны или невалидны") from exc
    if not events or metadata.get("events_count") != len(events):
        raise CanonicalBootstrapError("Bootstrap events count не соответствует metadata")
    if not all(isinstance(event, dict) for event in events):
        raise CanonicalBootstrapError("Bootstrap содержит невалидное событие")
    return artifact, events


def verify_nhl_bootstrap_bundle(bundle_path: Path) -> ArchiveArtifact:
    """Проверить immutable NHL canonical bootstrap без записи в БД.

    Args:
        bundle_path: Content-addressed каталог bootstrap bundle.

    Returns:
        Проверенный archive artifact.
    """
    artifact, _events = _load_verified_events(bundle_path)
    return artifact


def import_nhl_bootstrap_bundle(bundle_path: Path, session: Session) -> BootstrapImportResult:
    """Импортировать проверенный NHL bundle одной DB-транзакцией.

    Повтор verified immutable artifact не меняет event history и возвращает
    ``imported=False``. Любая ошибка до либо во время записи откатывает session.
    """
    artifact, events = _load_verified_events(bundle_path)
    existing_import = session.scalar(
        select(BootstrapImport).where(BootstrapImport.artifact_id == artifact.artifact_id)
    )
    if existing_import is not None:
        return BootstrapImportResult(
            artifact_id=artifact.artifact_id,
            events_count=existing_import.events_count,
            imported=False,
        )

    observed_at = _parse_datetime(artifact.created_at)
    try:
        for event_data in events:
            _import_event(session, event_data, source_observed_at=observed_at)
        session.add(
            BootstrapImport(
                artifact_id=artifact.artifact_id,
                tournament="nhl",
                source="nhl_web_api",
                status="succeeded",
                events_count=len(events),
            )
        )
        watermark = session.scalar(
            select(RefreshWatermark).where(RefreshWatermark.tournament == "nhl")
        )
        if watermark is None:
            session.add(
                RefreshWatermark(
                    tournament="nhl", source="nhl_web_api", snapshot_id=artifact.artifact_id
                )
            )
        else:
            watermark.source = "nhl_web_api"
            watermark.snapshot_id = artifact.artifact_id
        session.commit()
    except Exception:
        session.rollback()
        raise

    logger.info(
        "NHL bootstrap импортирован artifact_id=%s events=%d", artifact.artifact_id, len(events)
    )
    return BootstrapImportResult(
        artifact_id=artifact.artifact_id, events_count=len(events), imported=True
    )


def refresh_nhl_canonical_from_csv(source_csv: Path, session: Session) -> int:
    """Применить очередной NHL provider snapshot к canonical store одной транзакцией.

    Функция не вызывает provider API и не выбирает период загрузки: она принимает
    уже полученный incremental ``source.csv`` и фиксирует только changed revisions.
    """
    try:
        with source_csv.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise CanonicalBootstrapError("NHL source.csv не содержит заголовок")
            events = [_event_from_nhl_row(dict(row)) for row in reader]
    except OSError as exc:
        raise CanonicalBootstrapError(f"NHL source.csv недоступен: {source_csv}") from exc
    if not events:
        raise CanonicalBootstrapError("NHL source.csv не содержит событий")
    observed_at = datetime.now(UTC)
    try:
        for event in events:
            _import_event(session, event, source_observed_at=observed_at)
        session.commit()
    except Exception:
        session.rollback()
        raise
    logger.info("NHL canonical refresh применён events=%d", len(events))
    return len(events)


def _import_event(
    session: Session,
    event_data: dict[str, Any],
    *,
    source_observed_at: datetime,
) -> None:
    """Создать canonical event и immutable revision из одного verified envelope."""
    required = {
        "sport",
        "tournament",
        "source",
        "source_event_id",
        "scheduled_at",
        "status",
        "result",
        "payload",
        "revision_sha256",
    }
    if set(event_data).intersection(required) != required:
        raise CanonicalBootstrapError("Bootstrap event не соответствует canonical contract")
    if (
        event_data["sport"] != "ice_hockey"
        or event_data["tournament"] != "nhl"
        or event_data["source"] != "nhl_web_api"
        or event_data["status"] not in {"finished", "upcoming"}
        or not isinstance(event_data["payload"], dict)
        or not isinstance(event_data["result"], dict)
        or not isinstance(event_data["revision_sha256"], str)
    ):
        raise CanonicalBootstrapError("Bootstrap event содержит недопустимые значения")
    payload = event_data["payload"]
    result = event_data["result"]
    if event_data["revision_sha256"] != _revision_sha256(payload, result):
        raise CanonicalBootstrapError("Bootstrap event содержит неверный revision hash")
    scheduled_at = _parse_datetime(str(event_data["scheduled_at"]))
    event = session.scalar(
        select(CanonicalEvent).where(
            CanonicalEvent.tournament == "nhl",
            CanonicalEvent.source == "nhl_web_api",
            CanonicalEvent.source_event_id == str(event_data["source_event_id"]),
        )
    )
    if event is None:
        event = CanonicalEvent(
            sport="ice_hockey",
            tournament="nhl",
            source="nhl_web_api",
            source_event_id=str(event_data["source_event_id"]),
            scheduled_at=scheduled_at,
            status=str(event_data["status"]),
            current_revision_sha256=str(event_data["revision_sha256"]),
        )
        session.add(event)
        session.flush()
    else:
        event.scheduled_at = scheduled_at
        event.status = str(event_data["status"])
        event.current_revision_sha256 = str(event_data["revision_sha256"])

    revision = session.scalar(
        select(CanonicalEventRevision).where(
            CanonicalEventRevision.canonical_event_id == event.id,
            CanonicalEventRevision.revision_sha256 == str(event_data["revision_sha256"]),
        )
    )
    if revision is None:
        session.add(
            CanonicalEventRevision(
                canonical_event_id=event.id,
                revision_sha256=str(event_data["revision_sha256"]),
                payload_json=_canonical_json(payload),
                result_json=_canonical_json(result),
                source_observed_at=source_observed_at,
            )
        )


def _parser() -> argparse.ArgumentParser:
    """Создать CLI initial bootstrap без provider API calls."""
    parser = argparse.ArgumentParser(description="Immutable NHL canonical bootstrap.")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build-nhl")
    build.add_argument("--source-csv", required=True)
    build.add_argument("--bundle-root", required=True)
    import_bundle = commands.add_parser("import-nhl")
    import_bundle.add_argument("--bundle", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Выполнить local bundle build либо VPS DB import после migration."""
    args = _parser().parse_args(argv)
    try:
        if args.command == "build-nhl":
            artifact = build_nhl_bootstrap_bundle(Path(args.source_csv), Path(args.bundle_root))
            print(artifact.artifact_id)
        else:
            with get_session() as session:
                result = import_nhl_bootstrap_bundle(Path(args.bundle), session)
            print(f"{result.artifact_id} imported={str(result.imported).lower()}")
    except (CanonicalBootstrapError, OSError, ValueError) as exc:
        logger.error("Canonical bootstrap не выполнен: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
