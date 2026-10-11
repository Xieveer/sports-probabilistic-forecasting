"""Создание и проверка immutable model bundles до их активации."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml


class BundleVerificationError(ValueError):
    """Model bundle повреждён или несовместим с приложением."""


@dataclass(frozen=True)
class ModelBundle:
    """Проверенный immutable bundle модели."""

    bundle_id: str
    path: Path
    model_identity: str


@dataclass(frozen=True)
class VerifiedModelBundle(ModelBundle):
    """Проверенный managed-контракт модели из manifest v2."""

    schema_version: int
    model_pool: str
    market_spec: str
    market_rules: dict[str, object]
    outcomes: tuple[str, ...]
    feature_contract_id: str
    features: tuple[dict[str, str], ...]
    transformations_version: str
    algorithm: str
    model_entrypoint: str


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


def build_managed_model_bundle(
    source: Path,
    bundle_root: Path,
    *,
    model_identity: str,
    app_version: str,
    model_pool: str,
    market_spec: str,
    market_rules: dict[str, object],
    outcomes: list[str],
    feature_contract_id: str,
    features: list[dict[str, str]],
    transformations_version: str,
    algorithm: str,
    model_entrypoint: str,
) -> VerifiedModelBundle:
    """Собрать content-addressed managed bundle с manifest schema v2."""
    contract: dict[str, object] = {
        "schema_version": 2,
        "model_identity": model_identity,
        "app_version": app_version,
        "model_pool": model_pool,
        "market_spec": market_spec,
        "market_rules": market_rules,
        "outcomes": outcomes,
        "feature_contract_id": feature_contract_id,
        "features": features,
        "transformations_version": transformations_version,
        "algorithm": algorithm,
        "model_entrypoint": model_entrypoint,
        "files": _files(source),
    }
    _validate_managed_contract(contract)
    bundle_id = _bundle_id(contract)
    destination = bundle_root / bundle_id
    if not destination.exists():
        shutil.copytree(source, destination)
        manifest = {"bundle_id": bundle_id, **contract}
        (destination / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    verified = verify_model_bundle(destination, app_version=app_version)
    if not isinstance(verified, VerifiedModelBundle):
        raise BundleVerificationError("managed bundle не прошёл проверку schema v2")
    return verified


def verify_model_bundle(path: Path, *, app_version: str) -> ModelBundle | VerifiedModelBundle:
    """Проверить manifest, compatibility и checksum до использования bundle."""
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleVerificationError("manifest недоступен") from exc
    if not isinstance(manifest, dict) or manifest.get("app_version") != app_version:
        raise BundleVerificationError("compatibility mismatch")
    if manifest.get("schema_version") == 2:
        return _verify_managed_model_bundle(path, manifest)
    bundle_id = manifest.get("bundle_id")
    files = manifest.get("files")
    required_text_fields = ("app_version", "model_identity", "source_commit", "release")
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
        try:
            if not candidate.is_file():
                raise BundleVerificationError("checksum mismatch")
            actual_checksum = hashlib.sha256(candidate.read_bytes()).hexdigest()
        except OSError as exc:
            raise BundleVerificationError("файл bundle недоступен") from exc
        if actual_checksum != checksum:
            raise BundleVerificationError("checksum mismatch")
    return ModelBundle(bundle_id=bundle_id, path=path, model_identity=manifest["model_identity"])


def _verify_managed_model_bundle(path: Path, manifest: dict[str, object]) -> VerifiedModelBundle:
    """Проверить все поля managed-контракта и целостность файлов v2."""
    _validate_managed_contract(manifest)
    files = manifest["files"]
    entrypoint = manifest["model_entrypoint"]
    rules = manifest["market_rules"]
    outcomes = manifest["outcomes"]
    features = manifest["features"]
    assert isinstance(files, list)
    assert isinstance(entrypoint, str)
    assert isinstance(rules, dict)
    assert isinstance(outcomes, list)
    assert isinstance(features, list)
    bundle_id = manifest.get("bundle_id")
    payload = {key: value for key, value in manifest.items() if key != "bundle_id"}
    if not isinstance(bundle_id, str) or bundle_id != _bundle_id(payload) or path.name != bundle_id:
        raise BundleVerificationError("bundle identity mismatch")
    paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise BundleVerificationError("manifest v2 files некорректен")
        relative = entry.get("path")
        checksum = entry.get("sha256")
        if not isinstance(relative, str) or not isinstance(checksum, str):
            raise BundleVerificationError("manifest v2 files некорректен")
        relative_path = Path(relative)
        candidate = path / relative_path
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or "\\" in relative
            or relative in paths
        ):
            raise BundleVerificationError("manifest v2 содержит небезопасный или повторный путь")
        paths.add(relative)
        try:
            if not candidate.is_file() or not candidate.resolve().is_relative_to(path.resolve()):
                raise BundleVerificationError("checksum mismatch")
            actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
        except OSError as exc:
            raise BundleVerificationError("файл bundle недоступен") from exc
        if actual != checksum:
            raise BundleVerificationError("checksum mismatch")
    actual_paths = {
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file() and item.name != "manifest.json"
    }
    if actual_paths != paths:
        raise BundleVerificationError("набор файлов bundle не соответствует manifest v2")
    _verify_compatibility_files(path, manifest)
    return VerifiedModelBundle(
        bundle_id=bundle_id,
        path=path,
        model_identity=cast(str, manifest["model_identity"]),
        schema_version=2,
        model_pool=cast(str, manifest["model_pool"]),
        market_spec=cast(str, manifest["market_spec"]),
        market_rules=dict(rules),
        outcomes=tuple(outcomes),
        feature_contract_id=cast(str, manifest["feature_contract_id"]),
        features=tuple(dict(item) for item in features),
        transformations_version=cast(str, manifest["transformations_version"]),
        algorithm=cast(str, manifest["algorithm"]),
        model_entrypoint=entrypoint,
    )


def _validate_managed_contract(manifest: dict[str, object]) -> None:
    """Проверить структуру v2 до записи bundle и при чтении manifest."""
    text_fields = (
        "model_identity",
        "app_version",
        "model_pool",
        "market_spec",
        "feature_contract_id",
        "transformations_version",
        "algorithm",
        "model_entrypoint",
    )
    for field in text_fields:
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            raise BundleVerificationError(
                "manifest v2 содержит пустое обязательное поле, включая algorithm"
            )
    algorithm = manifest.get("algorithm")
    if algorithm not in {"catboost", "catboost_reg", "lgbm", "lgbm_reg", "logreg"}:
        raise BundleVerificationError("algorithm неизвестен")
    outcomes = manifest.get("outcomes")
    rules = manifest.get("market_rules")
    features = manifest.get("features")
    files = manifest.get("files")
    entrypoint = manifest.get("model_entrypoint")
    if (
        not isinstance(rules, dict)
        or not isinstance(rules.get("overtime"), bool)
        or not isinstance(rules.get("shootout"), bool)
        or not isinstance(rules.get("draw"), bool)
    ):
        raise BundleVerificationError("market rules должны явно задавать overtime, shootout и draw")
    expected_outcomes = (
        ("home_win", "draw", "away_win") if rules["draw"] else ("home_win", "away_win")
    )
    if not isinstance(outcomes, list) or tuple(outcomes) != expected_outcomes:
        raise BundleVerificationError("outcomes не соответствуют market rules")
    if manifest["market_spec"] == "winner_withOT" and (
        not rules["overtime"]
        or not rules["shootout"]
        or rules["draw"]
        or tuple(outcomes) != ("home_win", "away_win")
    ):
        raise BundleVerificationError(
            "winner_withOT требует overtime, shootout, отсутствие ничьей и два исхода"
        )
    if (
        not isinstance(features, list)
        or not features
        or any(
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not item["name"].strip()
            or not isinstance(item.get("type"), str)
            or not item["type"].strip()
            for item in features
        )
    ):
        raise BundleVerificationError("описание features некорректно")
    if not isinstance(files, list):
        raise BundleVerificationError("manifest v2 files некорректен")
    paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise BundleVerificationError("manifest v2 files некорректен")
        relative = entry.get("path")
        checksum = entry.get("sha256")
        if not isinstance(relative, str) or not isinstance(checksum, str):
            raise BundleVerificationError("manifest v2 files некорректен")
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or "\\" in relative
            or relative in paths
        ):
            raise BundleVerificationError("manifest v2 содержит небезопасный или повторный путь")
        paths.add(relative)
    model_path = Path(cast(str, entrypoint))
    if model_path.is_absolute() or ".." in model_path.parts or entrypoint not in paths:
        raise BundleVerificationError("model entrypoint должен указывать на один файл bundle")


def _verify_compatibility_files(path: Path, manifest: dict[str, object]) -> None:
    """Если legacy deploy.yaml/features.txt присутствуют, сверить их с v2."""
    deploy_path = path / "deploy.yaml"
    if deploy_path.is_file():
        try:
            deploy = yaml.safe_load(deploy_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise BundleVerificationError("deploy.yaml недоступен или некорректен") from exc
        model = deploy.get("model") if isinstance(deploy, dict) else None
        if not isinstance(model, dict) or model.get("algorithm") != manifest["algorithm"]:
            raise BundleVerificationError("deploy.yaml не соответствует manifest v2")
        configured_entrypoint = model.get("model_entrypoint", model.get("model_path"))
        if (
            configured_entrypoint is not None
            and configured_entrypoint != manifest["model_entrypoint"]
        ):
            raise BundleVerificationError("deploy.yaml не соответствует manifest v2")
    features_path = path / "features.txt"
    if features_path.is_file():
        try:
            listed = [
                line.strip()
                for line in features_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except OSError as exc:
            raise BundleVerificationError("features.txt недоступен") from exc
        features = cast(list[dict[str, str]], manifest["features"])
        expected = [item["name"] for item in features]
        if listed != expected:
            raise BundleVerificationError("features.txt не соответствует manifest v2")


def _verify_model_bundle_integrity(path: Path) -> ModelBundle:
    """Проверить immutable bundle без compatibility с будущим runtime release."""
    try:
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleVerificationError("manifest недоступен") from exc
    app_version = manifest.get("app_version") if isinstance(manifest, dict) else None
    if not isinstance(app_version, str) or not app_version.strip():
        raise BundleVerificationError("manifest некорректен")
    return verify_model_bundle(path, app_version=app_version)


def _set_pointer(pointer: Path, target: Path) -> None:
    """Атомарно заменить локальный symbolic pointer на verified bundle."""
    temporary = pointer.with_name(f".{pointer.name}.tmp")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(os.path.relpath(target, start=pointer.parent))
    temporary.replace(pointer)


def install_model_bundle(bundle_path: Path, runtime_root: Path, *, app_version: str) -> ModelBundle:
    """Проверить bundle до активации и сохранить current как previous для rollback."""
    bundle = verify_model_bundle(bundle_path, app_version=app_version)
    runtime_root.mkdir(parents=True, exist_ok=True)
    current = runtime_root / "current"
    previous = runtime_root / "previous"
    if current.is_symlink():
        active = _verify_model_bundle_integrity(current.resolve())
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
