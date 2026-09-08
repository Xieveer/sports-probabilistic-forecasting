"""Проверить immutable evidence bundle до создания evidence tag."""

from __future__ import annotations

import json
import re
import subprocess
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

import yaml


EXPECTED_IMAGE_KEYS = {"postgres", "api", "worker", "telegram_bot", "archive_sync"}
EXPECTED_IMAGE_REPOSITORIES = {
    "postgres": "postgres",
    "api": "ghcr.io/xieveer/sports-probabilistic-forecasting-api",
    "worker": "ghcr.io/xieveer/sports-probabilistic-forecasting-worker",
    "telegram_bot": "ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot",
    "archive_sync": "ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync",
}
EXPECTED_SERVICE_IMAGES = {
    "db": "postgres",
    "api": "api",
    "telegram-bot": "telegram_bot",
    "source-acquirer": "worker",
    "worker": "worker",
    "archive-sync": "archive_sync",
    "migrator": "api",
    "role-bootstrap": "postgres",
}
APPLICATION_SERVICES = {"api", "telegram-bot", "source-acquirer", "worker", "archive-sync"}
SHA256_REFERENCE = re.compile(r"^[a-z0-9.-]+(?:/[a-z0-9._-]+)*@sha256:[0-9a-f]{64}$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
EVIDENCE_TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+-evidence\.[1-9][0-9]*$")
DDL_PATTERN = re.compile(
    r"\b(?:alembic|create_all|create\s+table|alter\s+table|drop\s+table)\b", re.I
)


def _error_if(condition: bool, message: str, errors: list[str]) -> None:
    """Добавить ошибку, если условие истинно."""
    if condition:
        errors.append(message)


def _load_mapping(path: Path, loader: Any) -> dict[str, Any] | None:
    """Безопасно загрузить JSON/YAML mapping."""
    try:
        loaded = loader(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError):
        return None
    return loaded if isinstance(loaded, dict) else None


def validate_evidence(
    manifest_path: Path,
    *,
    expected_version: str,
    expected_source_commit: str,
    rendered_compose_path: Path,
    handoff_path: Path | None = None,
) -> list[str]:
    """Проверить release manifest и rendered production Compose.

    Args:
        manifest_path: Путь к JSON manifest из evidence commit.
        expected_version: Версия пакета из application tag.
        expected_source_commit: Commit, на который разворачивается source tag.
        rendered_compose_path: Compose, rendered с references из manifest.
        handoff_path: Candidate handoff из evidence commit, если он проверяется.

    Returns:
        Список fail-closed ошибок; пустой список означает валидный evidence bundle.
    """
    errors: list[str] = []
    manifest = _load_mapping(manifest_path, json.loads)
    if manifest is None:
        return ["release manifest: ожидается JSON object"]

    required_keys = {"service", "version", "source_commit", "source_tag", "evidence_tag", "images"}
    _error_if(set(manifest) != required_keys, "release manifest: недопустимая schema", errors)
    _error_if(
        manifest.get("service") != "sports-probabilistic-forecasting",
        "release manifest: неверный service",
        errors,
    )
    _error_if(
        manifest.get("version") != expected_version,
        "release manifest: version не совпадает с package",
        errors,
    )
    _error_if(
        manifest.get("source_tag") != f"v{expected_version}",
        "release manifest: source_tag не совпадает с version",
        errors,
    )
    _error_if(
        manifest.get("source_commit") != expected_source_commit,
        "release manifest: source_commit не совпадает с source tag",
        errors,
    )
    _error_if(
        not isinstance(manifest.get("source_commit"), str)
        or not COMMIT_SHA.fullmatch(manifest["source_commit"]),
        "release manifest: source_commit должен быть 40-hex",
        errors,
    )
    evidence_tag = manifest.get("evidence_tag")
    _error_if(
        not isinstance(evidence_tag, str) or not EVIDENCE_TAG.fullmatch(evidence_tag),
        "release manifest: неверный evidence_tag",
        errors,
    )
    _error_if(
        not isinstance(evidence_tag, str)
        or not re.fullmatch(rf"v{re.escape(expected_version)}-evidence\.[1-9][0-9]*", evidence_tag),
        "release manifest: evidence_tag не совпадает с version",
        errors,
    )

    raw_images = manifest.get("images")
    if not isinstance(raw_images, dict) or set(raw_images) != EXPECTED_IMAGE_KEYS:
        errors.append("release manifest: требуется точно пять runtime images без лишних entries")
    images = raw_images if isinstance(raw_images, dict) else {}
    for image_name, reference in images.items():
        if not isinstance(reference, str) or not SHA256_REFERENCE.fullmatch(reference):
            errors.append(f"release manifest: {image_name} должен быть exact @sha256 reference")
        elif reference.split("@", maxsplit=1)[0] != EXPECTED_IMAGE_REPOSITORIES.get(image_name):
            errors.append(
                f"release manifest: {image_name} должен ссылаться на canonical repository"
            )
        if isinstance(reference, str) and (
            "@" in reference.split("@sha256:", maxsplit=1)[0] or "://" in reference
        ):
            errors.append(f"release manifest: {image_name} не должен содержать credentials")

    rendered = _load_mapping(rendered_compose_path, yaml.safe_load)
    if rendered is None:
        return errors + ["rendered Compose: ожидается YAML object"]
    services = rendered.get("services")
    if not isinstance(services, dict):
        return errors + ["rendered Compose: services отсутствуют"]
    if set(services) != set(EXPECTED_SERVICE_IMAGES):
        errors.append("rendered Compose: недопустимый состав runtime services")

    for service_name, image_key in EXPECTED_SERVICE_IMAGES.items():
        service = services.get(service_name)
        if not isinstance(service, dict):
            continue
        _error_if("ports" in service, f"{service_name}: host ports запрещены", errors)
        _error_if(
            service.get("image") != images.get(image_key),
            f"{service_name}: image не совпадает с manifest",
            errors,
        )
        if service_name in APPLICATION_SERVICES:
            _error_if(
                service.get("user") != "10001:10001",
                f"{service_name}: обязателен UID/GID 10001:10001",
                errors,
            )
        command = service.get("command", [])
        command_text = " ".join(command) if isinstance(command, list) else str(command)
        if service_name != "migrator":
            _error_if(
                bool(DDL_PATTERN.search(command_text)),
                f"{service_name}: DDL разрешён только migrator",
                errors,
            )
    migrator = services.get("migrator")
    if isinstance(migrator, dict):
        command = migrator.get("command", [])
        command_text = " ".join(command) if isinstance(command, list) else str(command)
        _error_if("alembic" not in command_text, "migrator: должен выполнять migration", errors)
    if handoff_path is not None:
        try:
            handoff = handoff_path.read_text(encoding="utf-8")
        except OSError:
            errors.append("production handoff: файл отсутствует")
        else:
            _error_if(
                "- Статус подготовки: `candidate`" not in handoff,
                "production handoff: ожидается candidate",
                errors,
            )
            _error_if(
                "v1.1.12" in handoff,
                "production handoff: содержит stale v1.1.12 conclusion",
                errors,
            )
            for field, value in (
                ("source_tag", manifest.get("source_tag")),
                ("source_commit", manifest.get("source_commit")),
                ("evidence_tag", manifest.get("evidence_tag")),
            ):
                _error_if(
                    not isinstance(value, str) or value not in handoff,
                    f"production handoff: отсутствует {field}",
                    errors,
                )
            for evidence_name in ("CI", "Security", "Docker", "first-rollout"):
                _error_if(
                    f"- {evidence_name}: https://" not in handoff,
                    f"production handoff: отсутствует URL {evidence_name}",
                    errors,
                )
            for image_name in EXPECTED_IMAGE_KEYS:
                image_reference = images.get(image_name)
                _error_if(
                    not isinstance(image_reference, str) or image_reference not in handoff,
                    f"production handoff: отсутствует image {image_name}",
                    errors,
                )
            for image_name in ("api", "worker", "telegram_bot", "archive_sync"):
                matching_lines = [
                    line.lower() for line in handoff.splitlines() if image_name in line
                ]
                _error_if(
                    not any(
                        all(
                            marker in line
                            for marker in ("published", "linux/amd64", "scan", "provenance")
                        )
                        for line in matching_lines
                    ),
                    f"production handoff: application evidence {image_name} неполон",
                    errors,
                )
    return errors


def _source_tag_commit(repository_root: Path, source_tag: str) -> str:
    """Разрешить annotated/lightweight tag в его exact source commit."""
    result = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", f"{source_tag}^{{commit}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    """Запустить standalone gate evidence bundle."""
    parser = ArgumentParser(description="Проверка immutable release evidence")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--rendered-compose", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--source-tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    args = parser.parse_args()
    try:
        source_commit = _source_tag_commit(args.repository_root, args.source_tag)
    except subprocess.CalledProcessError:
        print(f"ERROR: source tag {args.source_tag} не разрешается в commit")  # noqa: T201
        return 1
    errors = validate_evidence(
        args.manifest,
        expected_version=args.version,
        expected_source_commit=source_commit,
        rendered_compose_path=args.rendered_compose,
        handoff_path=args.handoff,
    )
    for error in errors:
        print(f"ERROR: {error}")  # noqa: T201
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
