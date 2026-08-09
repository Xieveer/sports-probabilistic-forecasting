"""Создание и проверка immutable model bundles до их активации."""

from __future__ import annotations

import hashlib
import json
import shutil
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path


class BundleVerificationError(ValueError):
    """Model bundle повреждён или несовместим с приложением."""


@dataclass(frozen=True)
class ModelBundle:
    """Проверенный immutable bundle модели."""

    bundle_id: str
    path: Path


def _files(source: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        if path.name == "manifest.json":
            continue
        entries.append(
            {
                "path": path.relative_to(source).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return entries


def _bundle_id(payload: dict[str, object]) -> str:
    """Вернуть content-addressed идентификатор неизменяемого manifest payload."""
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def build_model_bundle(
    source: Path,
    bundle_root: Path,
    *,
    model_identity: str,
    app_version: str,
    source_commit: str,
    release: str,
) -> ModelBundle:
    """Скопировать model files и сохранить content-addressed manifest."""
    entries = _files(source)
    manifest_payload = {
        "schema_version": 1,
        "model_identity": model_identity,
        "app_version": app_version,
        "source_commit": source_commit,
        "release": release,
        "files": entries,
    }
    bundle_id = _bundle_id(manifest_payload)
    destination = bundle_root / bundle_id
    if not destination.exists():
        shutil.copytree(source, destination)
        manifest = {"bundle_id": bundle_id, **manifest_payload}
        (destination / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    return verify_model_bundle(destination, app_version=app_version)


def verify_model_bundle(path: Path, *, app_version: str) -> ModelBundle:
    """Проверить manifest, compatibility и checksum до использования bundle."""
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleVerificationError("manifest недоступен") from exc
    if not isinstance(manifest, dict) or manifest.get("app_version") != app_version:
        raise BundleVerificationError("compatibility mismatch")
    bundle_id = manifest.get("bundle_id")
    files = manifest.get("files")
    required_text_fields = ("model_identity", "source_commit", "release")
    if (
        manifest.get("schema_version") != 1
        or not isinstance(bundle_id, str)
        or not isinstance(files, list)
        or any(
            not isinstance(manifest.get(field), str) or not manifest[field].strip()
            for field in required_text_fields
        )
    ):
        raise BundleVerificationError("manifest некорректен")
    expected_payload = {
        "schema_version": manifest["schema_version"],
        "model_identity": manifest["model_identity"],
        "app_version": manifest["app_version"],
        "source_commit": manifest["source_commit"],
        "release": manifest["release"],
        "files": files,
    }
    expected_id = _bundle_id(expected_payload)
    if bundle_id != expected_id or path.name != bundle_id:
        raise BundleVerificationError("bundle identity mismatch")
    for entry in files:
        if not isinstance(entry, dict):
            raise BundleVerificationError("manifest некорректен")
        relative = entry.get("path")
        checksum = entry.get("sha256")
        if (
            not isinstance(relative, str)
            or not isinstance(checksum, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise BundleVerificationError("manifest некорректен")
        candidate = path / relative
        if (
            not candidate.is_file()
            or hashlib.sha256(candidate.read_bytes()).hexdigest() != checksum
        ):
            raise BundleVerificationError("checksum mismatch")
    return ModelBundle(bundle_id=bundle_id, path=path)


def _set_pointer(pointer: Path, target: Path) -> None:
    """Атомарно заменить локальный symbolic pointer на verified bundle."""
    temporary = pointer.with_name(f".{pointer.name}.tmp")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    temporary.replace(pointer)


def install_model_bundle(bundle_path: Path, runtime_root: Path, *, app_version: str) -> ModelBundle:
    """Проверить bundle до активации и сохранить current как previous для rollback."""
    bundle = verify_model_bundle(bundle_path, app_version=app_version)
    runtime_root.mkdir(parents=True, exist_ok=True)
    current = runtime_root / "current"
    previous = runtime_root / "previous"
    if current.is_symlink():
        active = verify_model_bundle(current.resolve(), app_version=app_version)
        _set_pointer(previous, active.path)
    _set_pointer(current, bundle.path)
    return bundle


def rollback_model_bundle(runtime_root: Path, *, app_version: str) -> ModelBundle:
    """Проверить previous bundle и сделать его current без удаления артефактов."""
    current = runtime_root / "current"
    previous = runtime_root / "previous"
    if not previous.is_symlink():
        raise BundleVerificationError("previous bundle недоступен для rollback")
    bundle = verify_model_bundle(previous.resolve(), app_version=app_version)
    if current.is_symlink():
        _set_pointer(previous, current.resolve())
    _set_pointer(current, bundle.path)
    return bundle


def load_current_model_bundle(runtime_root: Path, *, app_version: str) -> ModelBundle:
    """Проверить активный bundle перед Worker/API inference."""
    current = runtime_root / "current"
    if not current.is_symlink():
        raise BundleVerificationError("current bundle недоступен")
    return verify_model_bundle(current.resolve(), app_version=app_version)


def main() -> None:
    """Выполнить явную promotion или rollback runtime model bundle."""
    parser = ArgumentParser(description="Управление immutable production model bundle")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install", help="Проверить и активировать bundle")
    install.add_argument("--bundle", type=Path, required=True)
    install.add_argument("--runtime-root", type=Path, required=True)
    install.add_argument("--app-version", required=True)
    rollback = commands.add_parser("rollback", help="Вернуть previous bundle")
    rollback.add_argument("--runtime-root", type=Path, required=True)
    rollback.add_argument("--app-version", required=True)
    args = parser.parse_args()
    if args.command == "install":
        install_model_bundle(args.bundle, args.runtime_root, app_version=args.app_version)
    else:
        rollback_model_bundle(args.runtime_root, app_version=args.app_version)


if __name__ == "__main__":
    main()
