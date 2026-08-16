"""Контракты operational archive и безопасного retention runtime data."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sports_forecast.deploy.serving_data import (
    ArchiveVerificationError,
    archive_snapshot,
    build_serving_bundle,
    import_verified_archive,
    install_serving_bundle,
    main,
    prepare_training_input,
    prune_runtime_snapshots,
    verify_archive,
)


def _write_snapshot(root: Path, name: str, content: str) -> Path:
    snapshot = root / name
    snapshot.mkdir(parents=True)
    (snapshot / "schedule.json").write_text(content, encoding="utf-8")
    return snapshot


def test_archive_snapshot_has_immutable_id_timestamp_checksum_and_manifest(tmp_path: Path) -> None:
    """Каждый archive получает безопасный manifest и content-derived immutable ID."""
    snapshot = _write_snapshot(tmp_path, "snapshot", '{"game": "nhl-1"}')
    archive = archive_snapshot(
        snapshot,
        tmp_path / "archive",
        created_at=datetime(2026, 8, 9, 8, 0, tzinfo=UTC),
    )

    assert archive.artifact_id.startswith("sha256:")
    assert archive.created_at == "2026-08-09T08:00:00Z"
    assert (archive.path / "manifest.json").is_file()
    assert verify_archive(archive.path).artifact_id == archive.artifact_id


def test_archive_identity_includes_safe_snapshot_provenance(tmp_path: Path) -> None:
    """Разные run/config identities не могут выдать один immutable manifest."""
    snapshot = _write_snapshot(tmp_path, "snapshot", '{"game": "nhl-1"}')
    first = archive_snapshot(
        snapshot, tmp_path / "archive", provenance={"run_id": "run-1", "config_id": "cfg-a"}
    )
    second = archive_snapshot(
        snapshot, tmp_path / "archive", provenance={"run_id": "run-2", "config_id": "cfg-a"}
    )

    assert first.artifact_id != second.artifact_id


def test_archive_verification_rejects_tampered_file_without_importing(tmp_path: Path) -> None:
    """Проверка checksum останавливает дальнейший import повреждённого archive."""
    snapshot = _write_snapshot(tmp_path, "snapshot", '{"game": "nhl-1"}')
    archive = archive_snapshot(snapshot, tmp_path / "archive")
    (archive.path / "schedule.json").write_text('{"game": "nhl-2"}', encoding="utf-8")

    with pytest.raises(ArchiveVerificationError, match="checksum"):
        verify_archive(archive.path)


def test_retention_keeps_old_runtime_snapshot_until_archive_is_verified(tmp_path: Path) -> None:
    """Retention не удаляет старые runtime data без verified operational archive."""
    runtime_root = tmp_path / "runtime"
    old_snapshot = _write_snapshot(runtime_root, "snapshot-old", '{"game": "nhl-1"}')
    old_time = datetime.now(tz=UTC) - timedelta(days=8)
    old_timestamp = old_time.timestamp()
    for path in (old_snapshot, old_snapshot / "schedule.json"):
        path.touch(exist_ok=True)
        path.chmod(0o700 if path.is_dir() else 0o600)
        os.utime(path, (old_timestamp, old_timestamp))

    removed_without_archive = prune_runtime_snapshots(
        runtime_root,
        tmp_path / "archive",
        older_than_days=7,
    )

    assert removed_without_archive == []
    assert old_snapshot.exists()

    archive_snapshot(old_snapshot, tmp_path / "archive")
    removed_with_archive = prune_runtime_snapshots(
        runtime_root,
        tmp_path / "archive",
        older_than_days=7,
    )

    assert removed_with_archive == [old_snapshot]
    assert not old_snapshot.exists()


def test_import_validates_and_deduplicates_before_creating_local_staging(tmp_path: Path) -> None:
    """Local import не создаёт staging при checksum ошибке и повтор не дублирует artifact."""
    snapshot = _write_snapshot(tmp_path, "snapshot", '{"game": "nhl-1"}')
    archive = archive_snapshot(snapshot, tmp_path / "archive")
    import_root = tmp_path / "imports"

    first_import = import_verified_archive(archive.path, import_root)
    second_import = import_verified_archive(archive.path, import_root)

    assert first_import == second_import
    assert (first_import / "schedule.json").read_text(encoding="utf-8") == '{"game": "nhl-1"}'

    (archive.path / "schedule.json").write_text('{"game": "nhl-2"}', encoding="utf-8")
    with pytest.raises(ArchiveVerificationError):
        import_verified_archive(archive.path, import_root)
    assert list(import_root.iterdir()) == [first_import]


def test_training_input_descriptor_is_created_only_after_verified_import(tmp_path: Path) -> None:
    """Descriptor фиксирует immutable input, не вызывая DVC и не храня payload."""
    snapshot = _write_snapshot(tmp_path, "snapshot", '{"game": "nhl-1"}')
    archive = archive_snapshot(
        snapshot, tmp_path / "archive", provenance={"run_id": "run-1", "source": "nhl_web_api"}
    )
    descriptor = prepare_training_input(
        archive.path, tmp_path / "imports", tmp_path / "training" / "input.json"
    )

    payload = json.loads(descriptor.read_text(encoding="utf-8"))
    assert payload["artifact_id"] == archive.artifact_id
    assert payload["provenance"]["run_id"] == "run-1"


def test_training_input_cli_creates_descriptor(tmp_path: Path) -> None:
    """CLI не требует DVC и возвращает успех только после verified import."""
    snapshot = _write_snapshot(tmp_path, "snapshot", '{"game": "nhl-1"}')
    archive = archive_snapshot(snapshot, tmp_path / "archive")
    descriptor = tmp_path / "training" / "input.json"

    code = main(
        [
            "training-input",
            "--archive",
            str(archive.path),
            "--import-root",
            str(tmp_path / "imports"),
            "--descriptor",
            str(descriptor),
        ]
    )

    assert code == 0
    assert descriptor.is_file()


def test_serving_bundle_install_keeps_current_and_previous_verified_versions(
    tmp_path: Path,
) -> None:
    """Установка bundle переключает current и сохраняет предыдущую версию для rollback."""
    bundle_source = _write_snapshot(tmp_path, "bundle-source", '{"lookback": 10}')
    first_bundle = build_serving_bundle(bundle_source, tmp_path / "bundles")
    runtime_root = tmp_path / "runtime-bundles"
    first_installed = install_serving_bundle(first_bundle.path, runtime_root)

    (bundle_source / "schedule.json").write_text('{"lookback": 20}', encoding="utf-8")
    second_bundle = build_serving_bundle(bundle_source, tmp_path / "bundles")
    second_installed = install_serving_bundle(second_bundle.path, runtime_root)

    assert (runtime_root / "current").resolve() == second_installed
    assert (runtime_root / "previous").resolve() == first_installed
