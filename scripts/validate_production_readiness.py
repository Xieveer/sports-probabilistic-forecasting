"""Проверка контракта передачи приложения в эксплуатацию."""

from __future__ import annotations

import re
from pathlib import Path


HANDOFF_PATH = Path("docs/operations/production-handoff.md")
REQUIRED_PATHS = (
    Path(".env.example"),
    Path(".github/workflows/ci.yml"),
    Path(".github/workflows/docker.yml"),
    Path(".github/workflows/security.yml"),
    Path("Dockerfile"),
    Path("pyproject.toml"),
    Path("uv.lock"),
    Path("scripts/acceptance_check.py"),
    HANDOFF_PATH,
)
REQUIRED_SECTIONS = (
    "Идентификация и ответственность",
    "Runtime и конфигурация",
    "Healthcheck и smoke-проверка",
    "Данные и совместимость",
    "Наблюдаемость",
    "Артефакт и откат",
    "Нерешённые вопросы",
)
STATUS_PATTERN = re.compile(r"^- Статус подготовки: `(?P<status>draft|candidate)`$", re.MULTILINE)
ENTRYPOINT_PATTERN = re.compile(r"^\s*(?:CMD|ENTRYPOINT)\s+", re.MULTILINE)
NON_ROOT_USER_PATTERN = re.compile(r"^\s*USER\s+(?!root(?:\s|$))\S+", re.MULTILINE)


def validate(root: Path) -> list[str]:
    """Проверить наличие и заполненность production-контракта.

    Args:
        root: Корень проверяемого проекта.

    Returns:
        Список ошибок. Пустой список означает успешную проверку.
    """
    errors = [
        f"{path.as_posix()}: обязательный файл отсутствует"
        for path in REQUIRED_PATHS
        if not (root / path).is_file()
    ]
    if errors:
        return errors

    handoff = (root / HANDOFF_PATH).read_text(encoding="utf-8")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    for section in REQUIRED_SECTIONS:
        if f"## {section}" not in handoff:
            errors.append(f"production-handoff.md: отсутствует раздел «{section}»")

    status_match = STATUS_PATTERN.search(handoff)
    if status_match is None:
        errors.append("production-handoff.md: статус должен быть draft или candidate")
        return errors

    status = status_match.group("status")
    if status == "draft":
        return errors

    has_project_placeholders = "project-name" in pyproject or "project_name" in pyproject
    if "ЗАПОЛНИТЬ" in handoff:
        errors.append("production-handoff.md: для candidate остались плейсхолдеры")
    if has_project_placeholders:
        errors.append("pyproject.toml: не заменены project-name/project_name")
    if "make acceptance-check" not in handoff:
        errors.append("production-handoff.md: для candidate обязательна acceptance-команда")
    if ENTRYPOINT_PATTERN.search(dockerfile) is None:
        errors.append("Dockerfile: для candidate требуется CMD или ENTRYPOINT")
    if NON_ROOT_USER_PATTERN.search(dockerfile) is None:
        errors.append("Dockerfile: runtime должен запускаться не от root")

    return errors


def main() -> int:
    """Запустить проверку и вернуть shell exit code."""
    root = Path(__file__).resolve().parent.parent
    errors = validate(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")  # noqa: T201
        return 1
    print("Production handoff is valid.")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
