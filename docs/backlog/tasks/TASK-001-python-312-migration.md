# TASK-001 — Перевести контракт runtime на Python 3.12

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** не требуется: один согласованный вертикальный срез
> **Требование:** [REQ-001](../../product/requirements/REQ-001-python-312.md)
> **ADR:** [ADR-001](../../architecture/adr/ADR-001-python-312-runtime.md)

## Результат и границы

Python 3.12 — единственный поддерживаемый runtime проекта. Не изменяются прикладная логика,
версии зависимостей без необходимости разрешения lockfile и production deployment.

## Критерии приёмки

- [x] Контракт пакета, CI и Docker используют Python 3.12.
- [x] Lockfile обновлён командой `uv`, а документация синхронизирована.
- [x] Проверки миграции зафиксированы в отчёте.

## План реализации

1. Обновить version pins и документацию.
2. Пересобрать lockfile через `uv` с Python 3.12.
3. Выполнить проверки конфигурации и релевантные тесты.

## Затрагиваемые области и зависимости

- `pyproject.toml`, `uv.lock`, `.python-version`, GitHub Actions, Dockerfile, Airflow Dockerfile,
  README и docs.
- Airflow 2.10.4 поддерживает Python 3.12 согласно ADR-001.

## Проверка

- `uv lock --check`
- `uv sync --frozen --python 3.12 --group dev`
- `make ai-validate`, `make test-unit`
- Docker build API и Airflow image.

## Handoff и отчёт

- Отчёт выполнения: [TASK-001 report](../../changes/done/TASK-001-python-312-migration.md).
- Follow-up / findings: проверочная Docker-сборка требует повторения в среде с устойчивым
  доступом к Docker Hub.
