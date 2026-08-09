"""Immutable operational archive для production serving-data.

Модуль работает с локальным staging-каталогом. Его layout совпадает с key-prefix
Object Storage, поэтому оператор может синхронизировать только уже проверенные
immutable artifacts без смешивания с DVC cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

_ARCHIVE_DIRECTORY = "operational-archive"
_MANIFEST_NAME = "manifest.json"
_SCHEMA_VERSION = 1


class ArchiveVerificationError(ValueError):
    """Manifest или содержимое archive не прошли проверку целостности."""


@dataclass(frozen=True)
class ArchiveArtifact:
    """Проверенный immutable archive artifact.

    Attributes:
        artifact_id: Content-derived идентификатор с префиксом ``sha256:``.
        created_at: UTC timestamp создания manifest в ISO-8601.
        path: Локальный путь к immutable artifact.
    """

    artifact_id: str
    created_at: str
    path: Path


def _isoformat_utc(value: datetime) -> str:
    """Нормализовать timestamp к компактному UTC ISO-8601."""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    """Вычислить SHA-256 файла потоково."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_entries(source: Path) -> list[dict[str, str | int]]:
    """Собрать стабильный checksum-list обычных файлов source directory."""
    if not source.is_dir():
        raise ValueError(f"Ожидалась директория snapshot, получен: {source}")

    entries: list[dict[str, str | int]] = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink запрещён в archive: {path}")
        if path.is_file():
            entries.append(
                {
                    "path": path.relative_to(source).as_posix(),
                    "sha256": _sha256(path),
                    "size": path.stat().st_size,
                }
            )
    if not entries:
        raise ValueError(f"Snapshot не содержит файлов: {source}")
    return entries


def _artifact_id(entries: list[dict[str, str | int]]) -> str:
    """Построить content-derived immutable ID из списка файлов."""
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _manifest(entries: list[dict[str, str | int]], created_at: datetime) -> dict[str, Any]:
    """Сформировать безопасный serializable archive manifest."""
    return {
        "schema_version": _SCHEMA_VERSION,
        "artifact_id": _artifact_id(entries),
        "created_at": _isoformat_utc(created_at),
        "files": entries,
    }


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Записать manifest в каноническом формате."""
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def archive_snapshot(
    snapshot: Path,
    archive_root: Path,
    *,
    created_at: datetime | None = None,
) -> ArchiveArtifact:
    """Архивировать snapshot в immutable content-addressed layout.

    Args:
        snapshot: Директория production snapshot вне DVC cache.
        archive_root: Локальный root, соответствующий Object Storage prefix.
        created_at: Время manifest; по умолчанию текущее UTC.

    Returns:
        Проверенный immutable artifact. Повторный вызов с тем же содержимым
        возвращает существующий archive без перезаписи.
    """
    return _create_artifact(snapshot, archive_root, _ARCHIVE_DIRECTORY, created_at=created_at)


def _create_artifact(
    source: Path,
    root: Path,
    directory_name: str,
    *,
    created_at: datetime | None = None,
) -> ArchiveArtifact:
    """Создать immutable artifact в заданном верхнеуровневом layout-каталоге."""
    entries = _file_entries(source)
    manifest = _manifest(entries, created_at or datetime.now(tz=UTC))
    artifact_id = str(manifest["artifact_id"])
    destination = root / directory_name / artifact_id

    if destination.exists():
        verified = verify_archive(destination)
        if verified.artifact_id != artifact_id:
            raise ArchiveVerificationError(f"Существующий archive имеет другой ID: {destination}")
        return verified

    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="archive-", dir=destination.parent))
    try:
        shutil.copytree(source, stage, dirs_exist_ok=True, symlinks=False)
        _write_manifest(stage / _MANIFEST_NAME, manifest)
        stage.replace(destination)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    logger.info("Operational archive создан artifact_id=%s", artifact_id)
    return verify_archive(destination)


def import_verified_archive(archive_path: Path, import_root: Path) -> Path:
    """Импортировать проверенный archive в локальный staging без изменения DVC.

    После возврата оператор может передать этот staging в отдельную DVC-команду.
    Ошибка validation не создаёт и не изменяет локальный import.
    """
    artifact = verify_archive(archive_path)
    destination = import_root / artifact.artifact_id
    if destination.exists():
        verify_archive(destination)
        return destination

    import_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="archive-import-", dir=import_root))
    try:
        shutil.copytree(archive_path, stage, dirs_exist_ok=True, symlinks=False)
        verify_archive(stage, require_path_name=False)
        stage.replace(destination)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    logger.info("Archive подготовлен для локального import artifact_id=%s", artifact.artifact_id)
    return destination


def build_serving_bundle(
    source: Path,
    bundle_root: Path,
    *,
    created_at: datetime | None = None,
) -> ArchiveArtifact:
    """Собрать compact immutable serving-data bundle из явно выбранного source."""
    return _create_artifact(source, bundle_root, "serving-data-bundles", created_at=created_at)


def _replace_link(link: Path, target: str) -> None:
    """Атомарно заменить относительную symbolic link внутри runtime root."""
    temporary = link.with_name(f".{link.name}.new")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    temporary.replace(link)


def install_serving_bundle(bundle_path: Path, runtime_root: Path) -> Path:
    """Установить verified bundle, сохраняя current и previous для rollback.

    Установку выполняет оператор до runtime; контейнеры получают этот root только
    для чтения. Повторная установка текущего bundle не меняет rollback pointer.
    """
    bundle = verify_archive(bundle_path)
    versions_root = runtime_root / "versions"
    destination = versions_root / bundle.artifact_id
    runtime_root.mkdir(parents=True, exist_ok=True)
    versions_root.mkdir(parents=True, exist_ok=True)

    if not destination.exists():
        stage = Path(tempfile.mkdtemp(prefix="bundle-install-", dir=versions_root))
        try:
            shutil.copytree(bundle.path, stage, dirs_exist_ok=True, symlinks=False)
            verify_archive(stage, require_path_name=False)
            stage.replace(destination)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise

    current = runtime_root / "current"
    current_target = str(current.readlink()) if current.is_symlink() else None
    target = f"versions/{bundle.artifact_id}"
    if current_target == target:
        return destination
    if current_target is not None:
        _replace_link(runtime_root / "previous", current_target)
    _replace_link(current, target)
    logger.info("Serving-data bundle установлен artifact_id=%s", bundle.artifact_id)
    return destination


def verify_archive(archive_path: Path, *, require_path_name: bool = True) -> ArchiveArtifact:
    """Проверить manifest и checksums immutable archive.

    Args:
        archive_path: Каталог artifact c ``manifest.json``.
        require_path_name: Проверять, что имя каталога совпадает с immutable ID.

    Raises:
        ArchiveVerificationError: Если manifest или файл невалидны/повреждены.
    """
    manifest_path = archive_path / _MANIFEST_NAME
    try:
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchiveVerificationError(f"Manifest недоступен: {manifest_path}") from exc

    if not isinstance(raw_manifest, dict) or raw_manifest.get("schema_version") != _SCHEMA_VERSION:
        raise ArchiveVerificationError("Неподдерживаемый archive manifest")
    files = raw_manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ArchiveVerificationError("Manifest не содержит файлов")

    entries: list[dict[str, str | int]] = []
    for item in files:
        if not isinstance(item, dict):
            raise ArchiveVerificationError("Manifest содержит невалидную запись файла")
        relative = item.get("path")
        expected_checksum = item.get("sha256")
        expected_size = item.get("size")
        if (
            not isinstance(relative, str)
            or not isinstance(expected_checksum, str)
            or not isinstance(expected_size, int)
        ):
            raise ArchiveVerificationError("Manifest содержит неполные метаданные файла")
        file_path = archive_path / relative
        if (
            file_path.is_symlink()
            or not file_path.is_file()
            or file_path.stat().st_size != expected_size
        ):
            raise ArchiveVerificationError(
                f"Файл archive отсутствует или имеет другой размер: {relative}"
            )
        actual_checksum = _sha256(file_path)
        if actual_checksum != expected_checksum:
            raise ArchiveVerificationError(f"Неверный checksum файла: {relative}")
        entries.append({"path": relative, "sha256": expected_checksum, "size": expected_size})

    artifact_id = raw_manifest.get("artifact_id")
    created_at = raw_manifest.get("created_at")
    if artifact_id != _artifact_id(entries) or not isinstance(created_at, str):
        raise ArchiveVerificationError("Manifest содержит неверный immutable ID или timestamp")
    if require_path_name and archive_path.name != artifact_id:
        raise ArchiveVerificationError("Путь archive не соответствует immutable ID")
    return ArchiveArtifact(artifact_id=artifact_id, created_at=created_at, path=archive_path)


def prune_runtime_snapshots(
    runtime_root: Path,
    archive_root: Path,
    *,
    older_than_days: int,
    now: datetime | None = None,
) -> list[Path]:
    """Удалить старые runtime snapshots только после верификации archive.

    Args:
        runtime_root: Root одноразовых VPS snapshots.
        archive_root: Root immutable operational archive.
        older_than_days: Минимальный возраст удаления; должен быть положительным.
        now: Текущее UTC-время для детерминированной проверки.
    """
    if older_than_days <= 0:
        raise ValueError("Retention должен быть положительным числом дней")
    if not runtime_root.exists():
        return []

    cutoff = (now or datetime.now(tz=UTC)).timestamp() - timedelta_days(older_than_days)
    removed: list[Path] = []
    for snapshot in sorted(runtime_root.iterdir()):
        if snapshot.is_symlink() or not snapshot.is_dir() or snapshot.stat().st_mtime >= cutoff:
            continue
        try:
            artifact_id = _artifact_id(_file_entries(snapshot))
            verify_archive(archive_root / _ARCHIVE_DIRECTORY / artifact_id)
        except (ArchiveVerificationError, ValueError):
            logger.warning("Runtime snapshot сохранён: archive не верифицирован path=%s", snapshot)
            continue
        shutil.rmtree(snapshot)
        removed.append(snapshot)
        logger.info("Runtime snapshot удалён после archive verification path=%s", snapshot)
    return removed


def timedelta_days(days: int) -> float:
    """Вернуть количество секунд для retention interval в днях."""
    return days * 24 * 60 * 60


def _parser() -> argparse.ArgumentParser:
    """Создать CLI parser для локальных частей serving-data protocol."""
    parser = argparse.ArgumentParser(description="Immutable archive и serving-data bundle.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, positional, option in (
        ("archive", "source", "archive_root"),
        ("import", "archive", "import_root"),
        ("bundle", "source", "bundle_root"),
        ("install", "bundle", "runtime_root"),
    ):
        command = commands.add_parser(name)
        command.add_argument(f"--{positional.replace('_', '-')}", required=True)
        command.add_argument(f"--{option.replace('_', '-')}", required=True)
    prune = commands.add_parser("prune")
    prune.add_argument("--runtime-root", required=True)
    prune.add_argument("--archive-root", required=True)
    prune.add_argument("--older-than-days", type=int, default=7)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Выполнить одну безопасную локальную операцию serving-data protocol."""
    args = _parser().parse_args(argv)
    try:
        if args.command == "archive":
            artifact = archive_snapshot(Path(args.source), Path(args.archive_root))
            print(artifact.artifact_id)
        elif args.command == "import":
            print(import_verified_archive(Path(args.archive), Path(args.import_root)))
        elif args.command == "bundle":
            artifact = build_serving_bundle(Path(args.source), Path(args.bundle_root))
            print(artifact.artifact_id)
        elif args.command == "install":
            print(install_serving_bundle(Path(args.bundle), Path(args.runtime_root)))
        else:
            removed = prune_runtime_snapshots(
                Path(args.runtime_root),
                Path(args.archive_root),
                older_than_days=args.older_than_days,
            )
            print(len(removed))
    except (ArchiveVerificationError, OSError, ValueError) as exc:
        logger.error("Serving-data operation не выполнена: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
