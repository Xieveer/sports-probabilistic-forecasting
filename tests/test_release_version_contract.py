"""Контракт единой версии поставки и release-образов."""

from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path

import yaml

from sports_forecast.service.app import app
from sports_forecast.service.schemas import HealthResponse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_VERSION = "1.0.0"


def test_package_and_fastapi_publish_same_release_version() -> None:
    """Package metadata и OpenAPI должны публиковать версию релиза 1.0.0."""
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)["project"]

    assert project["version"] == RELEASE_VERSION
    assert app.version == RELEASE_VERSION
    assert app.openapi()["info"]["version"] == RELEASE_VERSION
    assert HealthResponse(timestamp=datetime.now()).version == RELEASE_VERSION


def test_release_workflow_publishes_semver_and_sha_image_tags() -> None:
    """Release по Git-тегу публикует SemVer и traceable SHA теги всех образов."""
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
    assert "type=sha,prefix=" in tags
