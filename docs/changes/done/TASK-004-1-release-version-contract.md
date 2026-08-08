# TASK-004-1 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-08
> **Задача:** [TASK-004-1](../../backlog/tasks/TASK-004-1-release-version-contract.md)

## Реализованный результат

Установлена единая версия поставки `1.0.0`: package metadata, FastAPI OpenAPI,
health response и Sphinx используют один accessor package metadata. Проект стал
явно устанавливаемым Python-пакетом, чтобы metadata была доступна и в контейнере.

Docker workflow продолжает собирать образы на `main`, а также принимает release
Git-тег формата `v*.*.*`. Для release-тега он проверяет совпадение с версией из
`pyproject.toml` и передаёт `docker/metadata-action` SemVer-тег вместе с
существующим SHA-тегом. Production env-template использует `:1.0.0`, а не
изменяемый `:latest`.

Git-тег, публикация образов и deployment не выполнялись.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `pyproject.toml`, `uv.lock`, `sports_forecast/version.py` | Package metadata `1.0.0` и устанавливаемый пакет с одним accessor версии |
| `sports_forecast/service/app.py`, `sports_forecast/service/schemas.py` | Версия OpenAPI и health без расходящихся литералов |
| `.github/workflows/docker.yml` | Tag-trigger, проверка `v<version>` и Docker SemVer-tag |
| `.env.example`, `docker-compose.prod.yml`, `docs/source/conf.py`, `docs/deploy/secrets.md` | Immutable production image tags и единая версия документации |
| `tests/test_release_version_contract.py` | Контракт metadata/API/workflow |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_release_version_contract.py -q` — `2 failed`:
  metadata была `0.1.0`, workflow не содержал tag trigger.
- **Green:** после реализации и `uv sync` та же команда — `2 passed`.
- **Refactor:** package-version извлекается одним `get_service_version()`;
  устаревшие литералы `2.0.0` и `3.0.0` удалены из runtime/docs конфигурации.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv sync` | Пакет собран и установлен как `sports-probabilistic-forecasting==1.0.0` |
| `uv run pytest tests/test_release_version_contract.py -q` | 2 passed, 2 warnings |
| `make lint` | Успешно |
| `uv run pre-commit run mypy --files sports_forecast/version.py sports_forecast/service/app.py sports_forecast/service/schemas.py tests/test_release_version_contract.py` | Успешно |
| `uv run pre-commit run mypy --all-files` | Неуспешно: 22 ранее существовавшие ошибки в 11 незатронутых файлах |
| `make docs` | Успешно; 155 существующих предупреждений Sphinx |
| `git diff --check` | Успешно |

## Документация, review и follow-up

- Документация: [secrets.md](../../deploy/secrets.md),
  [.env.example](../../../.env.example) и [docker-compose.prod.yml](../../../docker-compose.prod.yml).
- Review / security: не выполнялось; требуется перед release handoff.
- Follow-up: [TASK-004-2](../../backlog/tasks/TASK-004-2-odds-api-key-ring.md).

## Остаточные риски

- Реальный GitHub Actions/GHCR run не выполнялся: remote tag/push требует
  отдельной авторизации владельца.
- Полный mypy baseline красный вне изменённой области; исправление не включалось
  в TASK-004-1.
- `make docs` завершается успешно, но содержит существующие предупреждения
  автодокументации, не вызванные этой задачей.
