"""Контракт immutable production model bundle."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TypedDict, cast

import pytest

from sports_forecast.deploy.model_bundle import (
    BundleVerificationError,
    VerifiedModelBundle,
    build_managed_model_bundle,
    build_model_bundle,
    install_model_bundle,
    load_current_model_bundle,
    rollback_model_bundle,
    verify_model_bundle,
)


class ManagedContractFields(TypedDict):
    """Обязательные поля managed manifest для тестов."""

    model_pool: str
    market_spec: str
    market_rules: dict[str, object]
    outcomes: list[str]
    feature_contract_id: str
    features: list[dict[str, str]]
    transformations_version: str
    algorithm: str
    model_entrypoint: str


class ManagedBundleOptions(ManagedContractFields):
    """Аргументы сборщика managed bundle."""

    model_identity: str
    app_version: str


def test_model_bundle_import_does_not_require_mlflow() -> None:
    """Worker может загрузить verifier без зависимости local control plane."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(
                (
                    "import builtins",
                    "original_import = builtins.__import__",
                    "def deny_mlflow(name, *args, **kwargs):",
                    "    if name == 'mlflow' or name.startswith('mlflow.'):",
                    "        raise ModuleNotFoundError(\"No module named 'mlflow'\")",
                    "    return original_import(name, *args, **kwargs)",
                    "builtins.__import__ = deny_mlflow",
                    "from sports_forecast.deploy.model_bundle import verify_model_bundle",
                    "assert callable(verify_model_bundle)",
                )
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_model_bundle_has_immutable_id_and_rejects_tampered_model(tmp_path: Path) -> None:
    """Checksum повреждённой модели fail-fast до любой активации pointer."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.bin").write_bytes(b"model-v1")
    bundle = build_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="pool:football_winner:winner:abc",
        app_version="1.0.0",
        source_commit="a" * 40,
        release="v1.0.0",
    )

    assert bundle.bundle_id.startswith("sha256:")
    (bundle.path / "model.bin").write_bytes(b"tampered")

    with pytest.raises(BundleVerificationError, match="checksum"):
        verify_model_bundle(bundle.path, app_version="1.0.0")


def test_install_and_rollback_keep_verified_current_and_previous(tmp_path: Path) -> None:
    """Активация и rollback меняют только verified symbolic pointers."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.bin").write_bytes(b"model-v1")
    first = build_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="pool:x:winner:a",
        app_version="1",
        source_commit="a" * 40,
        release="v1",
    )
    (source / "model.bin").write_bytes(b"model-v2")
    second = build_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="pool:x:winner:b",
        app_version="1",
        source_commit="b" * 40,
        release="v1",
    )
    runtime = tmp_path / "runtime"

    install_model_bundle(first.path, runtime, app_version="1")
    install_model_bundle(second.path, runtime, app_version="1")
    rolled_back = rollback_model_bundle(runtime, app_version="1")

    assert rolled_back.bundle_id == first.bundle_id
    assert (runtime / "current").resolve().name == first.bundle_id
    assert not (runtime / "current").readlink().is_absolute()


def test_loader_fails_fast_when_current_bundle_is_missing_or_incompatible(tmp_path: Path) -> None:
    """Worker/API не получают путь модели без verified current bundle."""
    runtime = tmp_path / "runtime"
    with pytest.raises(BundleVerificationError, match="current bundle"):
        load_current_model_bundle(runtime, app_version="1")


def test_loader_rejects_tampered_active_bundle_without_replacing_pointer(tmp_path: Path) -> None:
    """Worker/API прекращают работу до prediction, сохраняя active pointer."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.bin").write_bytes(b"v1")
    bundle = build_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="pool:x:winner:a",
        app_version="1",
        source_commit="a" * 40,
        release="v1",
    )
    runtime = tmp_path / "runtime"
    install_model_bundle(bundle.path, runtime, app_version="1")
    current_target = (runtime / "current").resolve()
    (bundle.path / "model.bin").write_bytes(b"tampered")

    with pytest.raises(BundleVerificationError, match="checksum"):
        load_current_model_bundle(runtime, app_version="1")

    assert (runtime / "current").resolve() == current_target


def test_verifier_normalizes_artifact_read_io_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I/O ошибка при чтении проверяемого файла становится ошибкой верификации."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.bin").write_bytes(b"model")
    bundle = build_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="pool:x:winner:a",
        app_version="1",
        source_commit="a" * 40,
        release="v1",
    )
    original_read_bytes = Path.read_bytes

    def fail_model_read(path: Path) -> bytes:
        if path == bundle.path / "model.bin":
            raise OSError("simulated read failure")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_model_read)

    with pytest.raises(BundleVerificationError, match="недоступен"):
        verify_model_bundle(bundle.path, app_version="1")


def test_install_rejects_incompatible_bundle_without_changing_current(tmp_path: Path) -> None:
    """Не совместимый с app bundle не меняет уже активный pointer."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.bin").write_bytes(b"v1")
    first = build_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="pool:x:winner:a",
        app_version="1",
        source_commit="a" * 40,
        release="v1",
    )
    runtime = tmp_path / "runtime"
    install_model_bundle(first.path, runtime, app_version="1")
    (source / "model.bin").write_bytes(b"v2")
    incompatible = build_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="pool:x:winner:b",
        app_version="2",
        source_commit="b" * 40,
        release="v2",
    )

    with pytest.raises(BundleVerificationError, match="compatibility"):
        install_model_bundle(incompatible.path, runtime, app_version="1")

    assert load_current_model_bundle(runtime, app_version="1").bundle_id == first.bundle_id


def test_cross_version_install_preserves_verified_current_for_release_recovery(
    tmp_path: Path,
) -> None:
    """Previous сохраняет old release bundle без проверки against target version."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.bin").write_bytes(b"v1")
    old_bundle = build_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="pool:x:winner:old",
        app_version="1",
        source_commit="a" * 40,
        release="v1",
    )
    runtime = tmp_path / "runtime"
    install_model_bundle(old_bundle.path, runtime, app_version="1")
    (source / "model.bin").write_bytes(b"v2")
    target_bundle = build_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="pool:x:winner:target",
        app_version="2",
        source_commit="b" * 40,
        release="v2",
    )

    installed = install_model_bundle(target_bundle.path, runtime, app_version="2")

    assert installed.bundle_id == target_bundle.bundle_id
    assert (runtime / "current").resolve() == target_bundle.path
    assert (runtime / "previous").resolve() == old_bundle.path


def test_install_does_not_preserve_unverified_current_as_previous(tmp_path: Path) -> None:
    """Следующая promotion не превращает повреждённый current в rollback target."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.bin").write_bytes(b"v1")
    first = build_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="pool:x:winner:a",
        app_version="1",
        source_commit="a" * 40,
        release="v1",
    )
    runtime = tmp_path / "runtime"
    install_model_bundle(first.path, runtime, app_version="1")
    (first.path / "model.bin").write_bytes(b"tampered")
    (source / "model.bin").write_bytes(b"v2")
    candidate = build_model_bundle(
        source,
        tmp_path / "bundles",
        model_identity="pool:x:winner:b",
        app_version="1",
        source_commit="b" * 40,
        release="v1",
    )

    with pytest.raises(BundleVerificationError, match="checksum"):
        install_model_bundle(candidate.path, runtime, app_version="1")

    assert (runtime / "current").resolve() == first.path
    assert not (runtime / "previous").exists()


def test_manifest_v2_roundtrip_and_content_hash_cover_managed_contract(tmp_path: Path) -> None:
    """V2 contract is typed, verified, and content-addressed with every field."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.cbm").write_bytes(b"approved-model")
    (source / "model-alt.cbm").write_bytes(b"alternate-model")
    contract: ManagedBundleOptions = {
        "model_identity": "nhl:winner_withOT:catboost",
        "app_version": "1.2.0",
        "model_pool": "nhl",
        "market_spec": "winner_withOT",
        "market_rules": {"overtime": True, "shootout": True, "draw": False},
        "outcomes": ["home_win", "away_win"],
        "feature_contract_id": "nhl-features-v1",
        "features": [{"name": "home_form", "type": "float"}],
        "transformations_version": "1",
        "algorithm": "catboost",
        "model_entrypoint": "model.cbm",
    }

    bundle = build_managed_model_bundle(source, tmp_path / "bundles", **contract)
    verified = verify_model_bundle(bundle.path, app_version="1.2.0")

    assert isinstance(verified, VerifiedModelBundle)
    assert verified.bundle_id == bundle.bundle_id
    assert verified.schema_version == 2
    assert verified.model_pool == "nhl"
    assert verified.market_spec == "winner_withOT"
    assert verified.outcomes == ("home_win", "away_win")
    assert verified.model_entrypoint == "model.cbm"

    variants = [
        ("model_pool", "nhl_alt"),
        ("market_spec", "winner_withOT_alt"),
        ("market_rules", {"overtime": False, "shootout": False, "draw": False}),
        ("outcomes", ["home_win", "draw", "away_win"]),
        ("feature_contract_id", "nhl-features-v2"),
        ("features", [{"name": "away_form", "type": "float"}]),
        ("transformations_version", "2"),
        ("algorithm", "lgbm"),
        ("model_entrypoint", "model-alt.cbm"),
    ]
    for field, value in variants:
        changed: dict[str, object] = dict(contract)
        changed[field] = value
        if field in {"market_rules", "outcomes"}:
            changed["market_spec"] = "winner"
        if field == "outcomes":
            changed["market_rules"] = {"overtime": False, "shootout": False, "draw": True}
        other = build_managed_model_bundle(
            source, tmp_path / "bundles", **cast(ManagedBundleOptions, changed)
        )
        assert other.bundle_id != bundle.bundle_id, field
    other_version_options = dict(contract, app_version="1.2.1")
    other_version = build_managed_model_bundle(
        source, tmp_path / "bundles", **cast(ManagedBundleOptions, other_version_options)
    )
    assert other_version.bundle_id != bundle.bundle_id
    (source / "model.cbm").write_bytes(b"different-model-bytes")
    other_file = build_managed_model_bundle(source, tmp_path / "bundles", **contract)
    assert other_file.bundle_id != bundle.bundle_id


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("algorithm", "", "algorithm"),
        ("algorithm", "unknown", "algorithm"),
        ("model_entrypoint", "../model.cbm", "entrypoint"),
        ("outcomes", ["home_win", "draw", "away_win"], "outcomes"),
    ],
)
def test_manifest_v2_rejects_invalid_managed_contract(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    """Невалидные алгоритм, путь или исходы блокируют сборку managed bundle."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.cbm").write_bytes(b"model")
    contract: dict[str, object] = {
        "model_pool": "nhl",
        "market_spec": "winner_withOT",
        "market_rules": {"overtime": True, "shootout": True, "draw": False},
        "outcomes": ["home_win", "away_win"],
        "feature_contract_id": "features-v1",
        "features": [{"name": "home_form", "type": "float"}],
        "transformations_version": "1",
        "algorithm": "catboost",
        "model_entrypoint": "model.cbm",
    }
    contract[field] = value

    with pytest.raises(BundleVerificationError, match=message):
        build_managed_model_bundle(
            source,
            tmp_path / "bundles",
            model_identity="nhl:winner_withOT:catboost",
            app_version="1.2.0",
            **cast(ManagedContractFields, contract),
        )


@pytest.mark.parametrize(
    ("rules", "outcomes"),
    [
        ({"overtime": False, "shootout": True, "draw": False}, ["home_win", "away_win"]),
        ({"overtime": True, "shootout": False, "draw": False}, ["home_win", "away_win"]),
        ({"overtime": True, "shootout": True, "draw": True}, ["home_win", "draw", "away_win"]),
    ],
)
def test_winner_with_ot_requires_full_match_rules_and_two_outcomes(
    tmp_path: Path, rules: dict[str, object], outcomes: list[str]
) -> None:
    """winner_withOT требует ОТ, буллиты, отсутствие ничьей и два исхода."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.cbm").write_bytes(b"model")
    with pytest.raises(BundleVerificationError, match="winner_withOT"):
        build_managed_model_bundle(
            source,
            tmp_path / "bundles",
            model_identity="nhl:winner_withOT:catboost",
            app_version="1.2.0",
            model_pool="nhl",
            market_spec="winner_withOT",
            market_rules=rules,
            outcomes=outcomes,
            feature_contract_id="features-v1",
            features=[{"name": "home_form", "type": "float"}],
            transformations_version="1",
            algorithm="catboost",
            model_entrypoint="model.cbm",
        )


def test_manifest_v2_rejects_tampering_and_inconsistent_compatibility_files(
    tmp_path: Path,
) -> None:
    """V2 проверяет checksum и согласованность legacy deploy.yaml/features.txt."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "model.cbm").write_bytes(b"model")
    (source / "deploy.yaml").write_text(
        "model:\n  algorithm: catboost\n  model_entrypoint: model.cbm\n",
        encoding="utf-8",
    )
    (source / "features.txt").write_text("home_form\n", encoding="utf-8")
    kwargs: ManagedBundleOptions = {
        "model_identity": "nhl:winner_withOT:catboost",
        "app_version": "1.2.0",
        "model_pool": "nhl",
        "market_spec": "winner_withOT",
        "market_rules": {"overtime": True, "shootout": True, "draw": False},
        "outcomes": ["home_win", "away_win"],
        "feature_contract_id": "features-v1",
        "features": [{"name": "home_form", "type": "float"}],
        "transformations_version": "1",
        "algorithm": "catboost",
        "model_entrypoint": "model.cbm",
    }
    bundle = build_managed_model_bundle(source, tmp_path / "bundles", **kwargs)
    assert bundle.schema_version == 2

    (bundle.path / "model.cbm").write_bytes(b"tampered")
    with pytest.raises(BundleVerificationError, match="checksum"):
        verify_model_bundle(bundle.path, app_version="1.2.0")

    (source / "deploy.yaml").write_text("model:\n  algorithm: lgbm\n", encoding="utf-8")
    with pytest.raises(BundleVerificationError, match="deploy.yaml"):
        build_managed_model_bundle(source, tmp_path / "bundles", **kwargs)
