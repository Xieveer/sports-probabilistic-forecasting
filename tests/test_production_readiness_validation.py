"""Контракты строгой проверки production handoff."""

from __future__ import annotations

from pathlib import Path

from scripts.validate_production_readiness import validate


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_current_candidate_handoff_passes_production_gate() -> None:
    """Кандидат содержит проверяемые release-инварианты."""
    assert validate(PROJECT_ROOT) == []


def test_candidate_requires_acceptance_command(tmp_path: Path) -> None:
    """Нельзя передать candidate без non-mutating acceptance-команды."""
    for relative_path in (
        ".env.example",
        ".github/workflows/ci.yml",
        ".github/workflows/docker.yml",
        ".github/workflows/security.yml",
        "Dockerfile",
        "pyproject.toml",
        "scripts/acceptance_check.py",
        "uv.lock",
    ):
        source = PROJECT_ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    handoff = tmp_path / "docs/operations/production-handoff.md"
    handoff.parent.mkdir(parents=True)
    handoff.write_text(
        "\n".join(
            [
                "- Статус подготовки: `candidate`",
                *(
                    f"## {section}"
                    for section in (
                        "Идентификация и ответственность",
                        "Runtime и конфигурация",
                        "Healthcheck и smoke-проверка",
                        "Данные и совместимость",
                        "Наблюдаемость",
                        "Артефакт и откат",
                        "Нерешённые вопросы",
                    )
                ),
            ]
        ),
        encoding="utf-8",
    )

    errors = validate(tmp_path)

    assert "production-handoff.md: для candidate обязательна acceptance-команда" in errors
