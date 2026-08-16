"""Контракты исполнимого процесса работы Codex-агентов."""

import tomllib
from pathlib import Path
from shutil import copy2, copytree

from scripts.validate_ai_layer import _reviewer_profile_error, _workflow_contract_errors, validate


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
