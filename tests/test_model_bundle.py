"""Контракт immutable production model bundle."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sports_forecast.deploy.model_bundle import (
    BundleVerificationError,
    build_model_bundle,
    install_model_bundle,
    load_current_model_bundle,
    rollback_model_bundle,
    verify_model_bundle,
)


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
