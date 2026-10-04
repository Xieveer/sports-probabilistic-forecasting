# TASK-026-2 — Локальная очередь подтверждения связей

**Проверенный коммит:** `e55aca4`.

**Результат:** локальный review-сервис, отдельное loopback FastAPI-приложение,
review entrypoint, миграции schema v5→v7 с evidence-кандидатами и их историей,
защита локальных файлов и runbook.

## Реализовано

- Кандидаты сохраняют designation, opaque `origin` (включая `server`), время
  наблюдения, ограниченные факты, предложенные project UUID, основание,
  idempotency key, revision и статус.
- Идентичный импорт остаётся no-op даже после отклонения/откладывания. Новые
  факты создают pending review revision с сохранённой предыдущей evidence
  историей. Если designation уже confirmed, base связь и resolver сохраняют
  подтверждённую project entity до явного owner correction.
- Все внешние строковые поля и коллекции валидируются на размер до обращения к
  SQLite. Очередь загружает не более пяти прошлых evidence revisions для preview;
  полная история читается отдельными страницами до 20 записей, оставаясь полностью
  сохранённой в SQLite.
- На странице доступны поиск, status/source/tournament фильтры, пагинация
  Next/Previous и поиск project entity по имени. У каждой выбранной строки свой
  target selector, поэтому batch может подтверждать разные UUID. До 20 решений
  выполняются атомарно; устаревшая candidate/designation revision отменяет batch.
- Создание tournament/team и подтверждение связи выполняются вместе с аудитом
  в одной SQLite `BEGIN IMMEDIATE` transaction. UI не создаёт event/player.
- Отдельная cookie session подписана HMAC и ограничена по времени; POST проверяет
  CSRF, точный loopback Host/Origin и размер тела. Secret читается только из файла
  с ограниченными правами. Внешние значения экранируются при HTML-выводе.
- Повтор ключа идемпотентности с изменённым scope/обозначением отклоняется;
  `.gitignore` покрывает secret и registry SQLite. POST body читается потоком
  с лимитом до form parsing.
- `sports_forecast.service.app` не импортирует и не регистрирует review UI.
  Транспорт server feedback остаётся в TASK-026-6; схема уже хранит его origin.
- Инструкция запуска, подготовки secret file и остановки: [локальный runbook](../../development/local-identity-review.md).

## Проверки

- RED: `uv run pytest tests/test_entity_review.py -q` до реализации завершился
  ожидаемой ошибкой `ModuleNotFoundError` для отсутствующего `review_service`.
- GREEN: `uv run pytest tests/test_entity_review.py tests/test_entity_registry.py -q`
  — **58 passed**, 3 предупреждения pytest/Starlette. Включены UI filters/pagination,
  per-row batch targets, confirmed-link preservation, scope checks,
  bounded input strings/history/request bodies, gitignore, audit, XSS/CSRF/Origin/session,
  rollback при stale revision, server origin и upgrade миграционной цепочки до schema v7.
- `uv run ruff check sports_forecast/identity/review_service.py sports_forecast/identity/review_app.py sports_forecast/identity/review_server.py sports_forecast/identity/registry.py tests/test_entity_review.py tests/test_entity_registry.py` — **All checks passed**.
- `uv run ruff format --check sports_forecast/identity/review_service.py sports_forecast/identity/review_app.py sports_forecast/identity/review_server.py sports_forecast/identity/registry.py tests/test_entity_review.py tests/test_entity_registry.py` — **6 files already formatted**.
- `uv run mypy sports_forecast/identity/review_service.py sports_forecast/identity/review_app.py sports_forecast/identity/review_server.py` — **Success: no issues found in 3 source files**.
- `uv run python -m sports_forecast.identity.review_server --help` — entrypoint успешно показывает CLI.
- Дополнительно запускался `uv run mypy tests/test_entity_review.py`; он завершился 347 ошибками в 19 файлах транзитивных production imports (включая существующие pandas stubs, service DB models, config/live odds). Для целевых production-модулей отдельный mypy выше чистый.

## Ограничения

- Интерфейс локален и однопользовательский; `actor` задаётся при запуске.
- Полная доставка server-first кандидатов до локального master будет реализована
  в TASK-026-6.
- Независимый Reviewer проверил полный diff и повторил целевой pytest
  (**58 passed, 3 warnings**), Ruff, mypy, `git diff --check` и `git check-ignore`.
  Блокирующих P0–P2 замечаний нет.
