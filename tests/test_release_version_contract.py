"""Контракт единой версии поставки и release-образов."""

from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path

import yaml

from sports_forecast.service.app import app
from sports_forecast.service.schemas import HealthResponse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_VERSION = "1.1.0"


def test_package_and_fastapi_publish_same_release_version() -> None:
    """Package metadata и OpenAPI должны публиковать версию релиза 1.1.0."""
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]

    assert project["version"] == RELEASE_VERSION
    assert app.version == RELEASE_VERSION
    assert app.openapi()["info"]["version"] == RELEASE_VERSION
    assert HealthResponse(timestamp=datetime.now()).version == RELEASE_VERSION


def test_release_workflow_publishes_only_exact_semver_image_tag() -> None:
    """Release публикует только exact SemVer tag, а runtime identity — digest."""
    workflow_path = PROJECT_ROOT / ".github" / "workflows" / "docker.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    assert "v*.*.*" in workflow[True]["push"]["tags"]
    steps = workflow["jobs"]["build-push"]["steps"]
    validation_step = next(
        step for step in steps if step.get("name") == "Validate release tag matches package version"
    )
    assert validation_step["if"] == "github.ref_type == 'tag'"
    assert "pyproject.toml" in validation_step["run"]

    metadata_step = next(step for step in steps if step.get("id") == "meta")
    tags = metadata_step["with"]["tags"]
    assert "type=semver,pattern={{version}}" in tags
    assert "type=sha,prefix=" not in tags
    assert "type=raw,value=latest" not in tags


def test_docker_publish_waits_for_security_gates_and_attests_digest() -> None:
    """Публикация образа выполняется после gates и создаёт provenance по digest."""
    workflow_path = PROJECT_ROOT / ".github" / "workflows" / "docker.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    verify = workflow["jobs"]["verify"]
    verify_steps = verify["steps"]
    verify_commands = "\n".join(step.get("run", "") for step in verify_steps)
    assert "make lint" in verify_commands
    assert "make test-unit" in verify_commands
    assert "make security" in verify_commands
    assert any(step.get("with", {}).get("scan-type") == "fs" for step in verify_steps)

    build_push = workflow["jobs"]["build-push"]
    assert build_push["needs"] == ["verify"]
    step_names = {step.get("name") for step in build_push["steps"]}
    assert "Scan pushed image" in step_names
    assert "Attest build provenance" in step_names
    assert workflow["permissions"]["attestations"] == "write"
    assert workflow["permissions"]["id-token"] == "write"


def test_release_dependency_audit_uses_an_absolute_requirements_path() -> None:
    """CI audit не теряет exported requirements при создании временного venv."""
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "pip-audit --requirement $(CURDIR)/requirements-audit.txt" in makefile


def test_docker_workflow_normalizes_ghcr_image_owner_for_all_release_steps() -> None:
    """GHCR reference всегда lowercase для build, scan, attestation и evidence."""
    workflow_path = PROJECT_ROOT / ".github" / "workflows" / "docker.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["build-push"]["steps"]

    image_name_step = next(step for step in steps if step.get("id") == "image-name")
    assert "${GITHUB_REPOSITORY_OWNER,,}" in image_name_step["run"]

    image_name = "${{ steps.image-name.outputs.value }}"
    metadata_step = next(step for step in steps if step.get("id") == "meta")
    scan_step = next(step for step in steps if step.get("name") == "Scan pushed image")
    attestation_step = next(step for step in steps if step.get("name") == "Attest build provenance")
    evidence_step = next(step for step in steps if step.get("name") == "Publish release evidence")

    assert image_name in metadata_step["with"]["images"]
    assert image_name in scan_step["with"]["image-ref"]
    assert image_name in attestation_step["with"]["subject-name"]
    assert image_name in evidence_step["env"]["IMAGE_NAME"]
