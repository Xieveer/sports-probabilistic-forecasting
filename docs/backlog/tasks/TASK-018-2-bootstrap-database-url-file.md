# TASK-018-2 — File-backed DB URL для canonical bootstrap

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-018](../EPIC-018-post-rollout-runtime-corrections.md)
> **Требование:** [REQ-020](../../product/requirements/REQ-020-post-rollout-runtime-corrections.md)
> **ADR:** не требуется

## Результат и границы

Единый DB URL resolver читает `DATABASE_URL_FILE` перед `DATABASE_URL`; canonical
bootstrap через `get_session()` получает URL из файла. SQLite fallback сохраняется, если
обе переменные отсутствуют. Compose/entrypoint не меняются.

## Критерии приёмки

- [ ] File value применяется к `get_database_url()` и, следовательно, CLI import.
- [ ] Нечитаемый или пустой file завершает процесс безопасно, без раскрытия содержимого.

## План реализации

1. Добавить failing unit tests resolver для priority/file failures.
2. Минимально реализовать resolver в DB boundary и проверить bootstrap suite.

## Проверка

- `uv run pytest tests/test_database_url_file.py tests/test_canonical_bootstrap.py`

## Handoff и отчёт

- Отчёт выполнения: [TASK-018-2](../../changes/done/TASK-018-2-bootstrap-database-url-file.md).
- Follow-up / findings: нет.
- Review: ожидает независимого reviewer.
- Commit/push: ожидает reviewer.
