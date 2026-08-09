# TASK-001 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-07
> **Задача:** [TASK-001](../../backlog/tasks/TASK-001-python-312-migration.md)

## Реализованный результат

Проект поддерживает только Python 3.12. Контракт пакета ограничен `>=3.12,<3.13`, локальная
версия зафиксирована в `.python-version`, CI проверяет 3.12, а прикладной и Airflow Dockerfile
используют Python 3.12. Lockfile пересобран командой `uv lock --python 3.12`.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version` | Поддерживаемая версия и lockfile Python 3.12 |
| `.github/workflows/ci.yml` | Единственная CI-версия Python 3.12 |
| `Dockerfile`, `airflow/Dockerfile` | Runtime-образы Python 3.12 |
| `ruff.toml`, `sports_forecast/**`, `tests/**` | Target `py312` и 98 механических замен `timezone.utc` на `datetime.UTC` |
| `README.md`, `docs/source/index.rst`, `docs/dev-tooling.md` | Актуальные требования к Python |
| `docs/product/requirements/REQ-001-python-312.md` | Подтверждённые требования |
| `docs/architecture/adr/ADR-001-python-312-runtime.md` | Обоснование единого runtime |

## Доказательство TDD

- **Red:** не применимо: изменены версия runtime и конфигурация, без нового прикладного
  поведения.
- **Green:** `uv sync --frozen --python 3.12 --group dev` создал `.venv` на CPython 3.12.13.
- **Refactor:** не требовался.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv lock --python 3.12` | Успешно пересобрал `uv.lock`, 223 пакета |
| `uv run python --version` | `Python 3.12.13` |
| `uv lock --check` | Успешно |
| `make ai-validate` | Успешно |
| `make test-unit` | 725 passed на Python 3.12.13 |
| `make docs` | Успешно, 157 существующих предупреждений Sphinx |
| `uv run ruff check --fix sports_forecast tests` | 98 механических исправлений для target `py312` |
| `make lint` | Успешно |
| `docker compose … config --quiet` | Успешно для production и Airflow Compose с временными обязательными значениями |
| `docker build --target api ...` | Не завершилась: TLS handshake timeout при запросе Docker Hub |

## Документация, review и follow-up

- Документация: обновлены README и инженерные документы; требования и ADR сохранены.
- Review / security: не выполнялось.
- Follow-up: повторить API и Airflow Docker build в среде с устойчивым доступом к Docker Hub до
  production rollout.

## Остаточные риски

- Проверочная сборка Docker-образов не подтверждена локально из-за сетевого TLS timeout, хотя
  тег `apache/airflow:2.10.4-python3.12` проверен в Docker Hub.
- Локальные и внешние окружения на Python 3.10/3.11 должны быть пересозданы через `uv sync`.
