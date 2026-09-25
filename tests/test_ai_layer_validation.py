"""Контракты исполнимого процесса работы Codex-агентов."""

import tomllib
from pathlib import Path
from shutil import copy2, copytree

from scripts.validate_ai_layer import (
    _agent_model_error,
    _reviewer_profile_error,
    _workflow_contract_errors,
    validate,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_reviewer_profile_can_execute_assigned_commit_gate() -> None:
    """Reviewer имеет write-доступ, необходимый только для его commit/push gate."""
    profile = (PROJECT_ROOT / ".codex" / "agents" / "reviewer.toml").read_text(encoding="utf-8")

    assert 'sandbox_mode = "workspace-write"' in profile


def test_validator_rejects_read_only_reviewer_profile() -> None:
    """Read-only профиль не может выполнять назначенный reviewer commit gate."""
    profile = tomllib.loads(
        'sandbox_mode = "read-only"\ncomment = "sandbox_mode = \\"workspace-write\\""\n'
    )

    assert _reviewer_profile_error(profile) == (
        "reviewer не может выполнить назначенный commit gate"
    )


def test_agent_model_contract_assigns_fixed_gpt_6_models() -> None:
    """Роли используют закреплённые модели GPT-6 без маршрутизации по сложности."""
    assert _agent_model_error("architect", "gpt-6-astra") is None
    assert _agent_model_error("business-analyst", "gpt-6-luna") is None
    assert _agent_model_error("developer", "gpt-6-luna") is None
    assert _agent_model_error("reviewer", "gpt-6-sol") is None
    assert _agent_model_error("operations-agent", "gpt-6-sol") is None


def test_validate_rejects_wrong_product_owner_root_model(tmp_path: Path) -> None:
    """Главный PO также закреплён за Sol, а не только его subagent-профиль."""
    root = _copy_ai_layer(tmp_path)
    config_path = root / ".codex" / "config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            'model = "gpt-6-sol"', 'model = "gpt-6-luna"', 1
        ),
        encoding="utf-8",
    )

    assert any("главный Product Owner" in error for error in validate(root))


def test_agent_model_contract_rejects_legacy_and_astra_outside_architect() -> None:
    """Старые GPT-5.6 и Astra вне роли Architect блокируют проверку AI-слоя."""
    assert _agent_model_error("reviewer", "gpt-5.6-sol") == ("разрешены только модели GPT-6")
    assert _agent_model_error("reviewer", "gpt-6-astra") == (
        "gpt-6-astra разрешена только для architect"
    )


def test_validate_rejects_role_outside_required_workflow(tmp_path: Path) -> None:
    """AI-слой принимает только восемь ролей из REQ-024."""
    root = _copy_ai_layer(tmp_path)
    (root / "agents" / "extra.md").write_text(
        "# Extra\n\n## Цель\n\nТест.\n\n## Scope\n\nТест.\n\n## Результат\n\nТест.\n\n## Composition\n\nТест.\n",
        encoding="utf-8",
    )
    (root / ".codex" / "agents" / "extra.toml").write_text(
        'name = "extra"\n'
        'description = "Тестовая роль."\n'
        'model = "gpt-6-sol"\n'
        'developer_instructions = "agents/extra.md"\n',
        encoding="utf-8",
    )

    assert any("ровно восемь ролей REQ-024" in error for error in validate(root))


def test_workflow_contract_requires_task_review_evidence_template(tmp_path: Path) -> None:
    """Потеря полей review/commit в TASK template блокирует AI validation."""
    docs = tmp_path / "docs"
    (docs / "development").mkdir(parents=True)
    (docs / "backlog" / "tasks").mkdir(parents=True)
    (docs / "changes" / "done").mkdir(parents=True)
    (docs / "development" / "agent-artifacts.md").write_text(
        "независимый TASK review\nитоговый EPIC evidence commit\nНа каждом handoff",
        encoding="utf-8",
    )
    (docs / "backlog" / "0000-epic-template.md").write_text(
        "Полное EPIC review\nHash проверенного коммита",
        encoding="utf-8",
    )
    (docs / "backlog" / "tasks" / "0000-task-template.md").write_text(
        "Commit/push:", encoding="utf-8"
    )
    (docs / "changes" / "done" / "0000-task-report-template.md").write_text(
        "Review / security:\nCommit/push:", encoding="utf-8"
    )

    errors = _workflow_contract_errors(tmp_path)

    assert any("0000-task-template.md" in error and "Review:" in error for error in errors)


def test_workflow_templates_preserve_resume_context(tmp_path: Path) -> None:
    """EPIC и короткая TASK хранят контекст возобновления инициативы."""
    root = _copy_ai_layer(tmp_path)
    epic = root / "docs" / "backlog" / "0000-epic-template.md"
    task = root / "docs" / "backlog" / "tasks" / "0000-task-template.md"
    epic.write_text(
        epic.read_text(encoding="utf-8").replace("Следующая роль:", ""), encoding="utf-8"
    )
    task.write_text(
        task.read_text(encoding="utf-8").replace("Ветка инициативы:", ""), encoding="utf-8"
    )

    errors = _workflow_contract_errors(root)

    assert any("0000-epic-template.md" in error and "Следующая роль:" in error for error in errors)
    assert any(
        "0000-task-template.md" in error and "Ветка инициативы:" in error for error in errors
    )


def test_two_initiatives_resume_independently_from_persisted_epics(tmp_path: Path) -> None:
    """Два EPIC восстанавливают разные ветки и следующие роли без истории чата."""
    template = (PROJECT_ROOT / "docs/backlog/0000-epic-template.md").read_text(encoding="utf-8")
    for initiative_id, branch, stage, next_role in (
        ("EPIC-901", "initiative/epic-901-data", "research / data", "data-researcher"),
        ("EPIC-902", "initiative/epic-902-api", "engineering / review", "reviewer"),
    ):
        content = template.replace("EPIC-<id>", initiative_id)
        content = content.replace("initiative/epic-<id>-<slug>", branch)
        content = content.replace("<engineering | research | operations> / <текущий gate>", stage)
        content = content.replace("<роль и конкретное действие>", next_role)
        (tmp_path / f"{initiative_id}.md").write_text(content, encoding="utf-8")

    for initiative_id, branch, stage, next_role in (
        ("EPIC-901", "initiative/epic-901-data", "research / data", "data-researcher"),
        ("EPIC-902", "initiative/epic-902-api", "engineering / review", "reviewer"),
    ):
        restored = (tmp_path / f"{initiative_id}.md").read_text(encoding="utf-8")
        assert f"- Инициатива: `{initiative_id}`." in restored
        assert f"- Ветка инициативы: `{branch}`." in restored
        assert f"- Workflow / этап: `{stage}`." in restored
        assert f"- Следующая роль: {next_role}." in restored


def _copy_ai_layer(tmp_path: Path) -> Path:
    """Скопировать AI-слой в изолированный проект для проверки public validate."""
    destination = tmp_path / "project"
    for relative_path in (
        ".codex-plugin/plugin.json",
        ".agents/plugins/marketplace.json",
        "skills",
        "agents",
        ".codex",
        "evals",
        "docs/development/agent-artifacts.md",
        "docs/backlog/0000-epic-template.md",
        "docs/backlog/tasks/0000-task-template.md",
        "docs/changes/done/0000-task-report-template.md",
    ):
        source = PROJECT_ROOT / relative_path
        target = destination / relative_path
        if source.is_dir():
            copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            copy2(source, target)
    return destination


def test_validate_rejects_read_only_reviewer_profile(tmp_path: Path) -> None:
    """Public validate блокирует read-only профиль, даже с marker в comment."""
    root = _copy_ai_layer(tmp_path)
    profile_path = root / ".codex" / "agents" / "reviewer.toml"
    profile_path.write_text(
        profile_path.read_text(encoding="utf-8").replace(
            'sandbox_mode = "workspace-write"',
            'sandbox_mode = "read-only"\n# sandbox_mode = "workspace-write"',
            1,
        ),
        encoding="utf-8",
    )

    assert any("reviewer не может выполнить" in error for error in validate(root))


def test_validate_rejects_missing_task_and_report_evidence(tmp_path: Path) -> None:
    """Public validate блокирует потерю evidence в обоих task templates."""
    root = _copy_ai_layer(tmp_path)
    (root / "docs" / "backlog" / "tasks" / "0000-task-template.md").write_text(
        "Commit/push:", encoding="utf-8"
    )
    (root / "docs" / "changes" / "done" / "0000-task-report-template.md").write_text(
        "Review / security:", encoding="utf-8"
    )

    errors = validate(root)

    assert any("0000-task-template.md" in error and "Review:" in error for error in errors)
    assert any(
        "0000-task-report-template.md" in error and "Commit/push:" in error for error in errors
    )


def test_ai_layer_validator_accepts_agent_workflow_contract() -> None:
    """Проверка AI-слоя принимает только полный контракт передачи работы."""
    assert validate(PROJECT_ROOT) == []
