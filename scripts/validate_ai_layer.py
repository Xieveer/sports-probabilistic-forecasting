"""Проверка структуры проектного AI-плагина."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

REQUIRED_SKILL_SECTIONS = {"Нельзя сокращать", "Red flags", "Проверка"}
REQUIRED_ROLE_SECTIONS = {"Цель", "Scope", "Результат", "Composition"}
REQUIRED_AGENT_FIELDS = {"name", "description", "developer_instructions", "model"}
SUPPORTED_AGENT_MODELS = {"gpt-5.6-sol", "gpt-5.6-terra"}
FRONTMATTER_PATTERN = re.compile(
    r"\A---\nname: ([a-z0-9-]+)\ndescription: (.+?)\n---\n",
    re.DOTALL,
)


def _read_json(path: Path) -> dict[str, Any]:
    """Прочитать JSON-объект.

    Args:
        path: Путь к JSON-файлу.

    Returns:
        Декодированный объект.

    Raises:
        ValueError: Если корневое значение не является объектом.
    """
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        msg = f"{path}: ожидается JSON object"
        raise TypeError(msg)
    return value


def _sections(text: str) -> set[str]:
    """Вернуть заголовки второго уровня."""
    return {
        line.removeprefix("## ").strip() for line in text.splitlines() if line.startswith("## ")
    }


def validate(root: Path) -> list[str]:
    """Проверить plugin manifest, skills, роли и eval cases.

    Args:
        root: Корень репозитория.

    Returns:
        Список обнаруженных ошибок.
    """
    errors: list[str] = []
    manifest = _read_json(root / ".codex-plugin" / "plugin.json")
    marketplace = _read_json(root / ".agents" / "plugins" / "marketplace.json")
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or len(plugins) != 1:
        errors.append(".agents/plugins/marketplace.json: ожидается ровно один plugin")
    elif plugins[0].get("name") != manifest.get("name"):
        errors.append("marketplace plugin name не совпадает с plugin manifest")

    skills_path = root / str(manifest.get("skills", "")).removeprefix("./")
    skill_names: set[str] = set()

    for directory in sorted(path for path in skills_path.iterdir() if path.is_dir()):
        skill_file = directory / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"{directory}: отсутствует SKILL.md")
            continue
        text = skill_file.read_text(encoding="utf-8")
        match = FRONTMATTER_PATTERN.match(text)
        if match is None:
            errors.append(f"{skill_file}: неверный frontmatter")
            continue
        name = match.group(1)
        skill_names.add(name)
        if name != directory.name:
            errors.append(f"{skill_file}: name не совпадает с каталогом")
        missing = REQUIRED_SKILL_SECTIONS - _sections(text)
        if missing:
            errors.append(f"{skill_file}: отсутствуют разделы {sorted(missing)}")
        if "[TODO" in text:
            errors.append(f"{skill_file}: остался TODO placeholder")

    role_names: set[str] = set()
    for role_file in sorted((root / "agents").glob("*.md")):
        if role_file.name == "README.md":
            continue
        role_names.add(role_file.stem)
        missing = REQUIRED_ROLE_SECTIONS - _sections(role_file.read_text(encoding="utf-8"))
        if missing:
            errors.append(f"{role_file}: отсутствуют разделы {sorted(missing)}")

    config_path = root / ".codex" / "config.toml"
    with config_path.open("rb") as config_file:
        config = tomllib.load(config_file)
    agents_config = config.get("agents")
    if not isinstance(agents_config, dict):
        errors.append(".codex/config.toml: отсутствует таблица agents")
    elif agents_config.get("default_subagent_model") not in SUPPORTED_AGENT_MODELS:
        errors.append(".codex/config.toml: неизвестная default_subagent_model")

    agent_names: set[str] = set()
    for agent_file in sorted((root / ".codex" / "agents").glob("*.toml")):
        with agent_file.open("rb") as source:
            agent = tomllib.load(source)
        missing_fields = REQUIRED_AGENT_FIELDS - agent.keys()
        if missing_fields:
            errors.append(f"{agent_file}: отсутствуют поля {sorted(missing_fields)}")
            continue
        name = str(agent["name"])
        agent_names.add(name)
        if name != agent_file.stem:
            errors.append(f"{agent_file}: name не совпадает с именем файла")
        if agent["model"] not in SUPPORTED_AGENT_MODELS:
            errors.append(f"{agent_file}: неизвестная model")
        if f"agents/{name}.md" not in str(agent["developer_instructions"]):
            errors.append(f"{agent_file}: developer_instructions не ссылается на роль")

    if agent_names != role_names:
        errors.append(".codex/agents: набор custom agents не совпадает с проектными ролями")

    evals = _read_json(root / "evals" / "cases.json")
    cases = evals.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("evals/cases.json: отсутствуют cases")
    else:
        ids: set[str] = set()
        for case in cases:
            if not isinstance(case, dict):
                errors.append("evals/cases.json: case должен быть object")
                continue
            case_id = str(case.get("id", ""))
            if not case_id or case_id in ids:
                errors.append(f"evals/cases.json: неверный или повторный id {case_id!r}")
            ids.add(case_id)
            if case.get("expected_skill") not in skill_names:
                errors.append(f"{case_id}: неизвестный expected_skill")
            for field in ("prompt", "must", "must_not"):
                if not case.get(field):
                    errors.append(f"{case_id}: пустое поле {field}")

    return errors


def main() -> int:
    """Запустить проверку и вернуть shell exit code."""
    root = Path(__file__).resolve().parent.parent
    errors = validate(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")  # noqa: T201
        return 1
    print("AI layer is valid.")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
