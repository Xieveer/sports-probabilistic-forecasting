"""Контракт immutable evidence bundle для production release."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_release_evidence import validate_evidence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "a" * 40
IMAGE_DIGEST = "b" * 64


def _manifest() -> dict[str, object]:
    """Вернуть минимальный корректный release manifest."""
    return {
        "service": "sports-probabilistic-forecasting",
        "version": "1.1.14",
        "source_commit": SOURCE_COMMIT,
        "source_tag": "v1.1.14",
        "evidence_tag": "v1.1.14-evidence.1",
        "images": {
            "postgres": f"postgres@sha256:{IMAGE_DIGEST}",
            "api": f"ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:{IMAGE_DIGEST}",
            "worker": f"ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:{IMAGE_DIGEST}",
            "telegram_bot": f"ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:{IMAGE_DIGEST}",
            "archive_sync": f"ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:{IMAGE_DIGEST}",
        },
    }


def _candidate_handoff(manifest: dict[str, object]) -> str:
    """Вернуть минимальный полный candidate handoff для evidence gate."""
    images = manifest["images"]
    assert isinstance(images, dict)
    application_evidence = "\n".join(
        f"- {name}: published; linux/amd64; image scan; provenance; {images[name]}"
        for name in ("api", "worker", "telegram_bot", "archive_sync")
    )
    return "\n".join(
        [
            "- Статус подготовки: `candidate`",
            f"source_tag: {manifest['source_tag']}",
            f"source_commit: {manifest['source_commit']}",
            f"evidence_tag: {manifest['evidence_tag']}",
            f"- postgres: {images['postgres']}",
            application_evidence,
            "- CI: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/1",
            "- Security: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/2",
            "- Docker: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/3",
            "- first-rollout: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/4",
        ]
    )


def test_evidence_manifest_validates_release_identity_and_rendered_compose(tmp_path: Path) -> None:
    """Evidence связывает source tag, commit и только допустимые runtime images."""
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")

    errors = validate_evidence(
        manifest_path,
        expected_version="1.1.14",
        expected_source_commit=SOURCE_COMMIT,
        rendered_compose_path=PROJECT_ROOT / "tests" / "fixtures" / "release-evidence-compose.yml",
    )

    assert errors == []


def test_evidence_requires_candidate_handoff_with_source_binding(tmp_path: Path) -> None:
    """Evidence handoff не может заменить candidate или скрыть source identity."""
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    handoff = tmp_path / "production-handoff.md"
    handoff.write_text("- Статус подготовки: `draft`", encoding="utf-8")

    errors = validate_evidence(
        manifest_path,
        expected_version="1.1.14",
        expected_source_commit=SOURCE_COMMIT,
        rendered_compose_path=PROJECT_ROOT / "tests" / "fixtures" / "release-evidence-compose.yml",
        handoff_path=handoff,
    )

    assert any("ожидается candidate" in error for error in errors)
    assert sum("production handoff: отсутствует" in error for error in errors) >= 3


def test_evidence_rejects_wrong_repository_versioned_tag_and_incomplete_handoff(
    tmp_path: Path,
) -> None:
    """Evidence не принимает attacker registry, другой version tag или неполный package."""
    manifest = _manifest()
    images = manifest["images"]
    assert isinstance(images, dict)
    images["api"] = f"ghcr.io/attacker/api@sha256:{IMAGE_DIGEST}"
    manifest["evidence_tag"] = "v9.9.9-evidence.1"
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    handoff = tmp_path / "production-handoff.md"
    handoff.write_text(_candidate_handoff(manifest).replace("provenance;", ""), encoding="utf-8")

    errors = validate_evidence(
        manifest_path,
        expected_version="1.1.14",
        expected_source_commit=SOURCE_COMMIT,
        rendered_compose_path=PROJECT_ROOT / "tests" / "fixtures" / "release-evidence-compose.yml",
        handoff_path=handoff,
    )

    assert any("api должен ссылаться на canonical repository" in error for error in errors)
    assert any("evidence_tag не совпадает с version" in error for error in errors)
    assert any("application evidence api неполон" in error for error in errors)


def test_evidence_manifest_rejects_extra_image_and_secret_like_value(tmp_path: Path) -> None:
    """Manifest не допускает расширение runtime perimeter или credentials."""
    manifest = _manifest()
    images = manifest["images"]
    assert isinstance(images, dict)
    images["caddy"] = f"ghcr.io/xieveer/caddy@sha256:{IMAGE_DIGEST}"
    images["api"] = "https://token@example.invalid/api@sha256:" + IMAGE_DIGEST
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    errors = validate_evidence(
        manifest_path,
        expected_version="1.1.14",
        expected_source_commit=SOURCE_COMMIT,
        rendered_compose_path=PROJECT_ROOT / "tests" / "fixtures" / "release-evidence-compose.yml",
    )

    assert any("точно пять runtime images" in error for error in errors)
    assert any("credentials" in error for error in errors)


def test_evidence_rejects_port_root_service_and_ddl_outside_migrator(tmp_path: Path) -> None:
    """Evidence gate fail-closed проверяет private и migration boundaries."""
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    rendered = tmp_path / "compose.yml"
    rendered.write_text(
        (PROJECT_ROOT / "tests" / "fixtures" / "release-evidence-compose.yml")
        .read_text(encoding="utf-8")
        .replace('user: "10001:10001"', 'user: "root"', 1)
        .replace("    image:", '    ports: ["8000:8000"]\n    image:', 1)
        .replace('command: ["api"]', 'command: ["alembic", "upgrade", "head"]'),
        encoding="utf-8",
    )

    errors = validate_evidence(
        manifest_path,
        expected_version="1.1.14",
        expected_source_commit=SOURCE_COMMIT,
        rendered_compose_path=rendered,
    )

    assert any("host ports запрещены" in error for error in errors)
    assert any("UID/GID 10001:10001" in error for error in errors)
    assert any("DDL разрешён только migrator" in error for error in errors)
