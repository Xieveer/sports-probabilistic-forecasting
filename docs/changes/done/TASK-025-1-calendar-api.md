# TASK-025-1 — отчёт о выполнении

> **Статус задачи:** done, независимый review пройден
> **Дата:** 2026-09-26
> **Задача:** [TASK-025-1](../../backlog/tasks/TASK-025-1-calendar-api.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат

Добавлен `GET /calendar/{tournament}` для canonical source events независимо от
prediction store. Контракт возвращает opaque canonical event ID, участников,
статус, время, страницу событий и состояние покрытия. Периоды используют общие
букмекерские сутки `08:00 Europe/Moscow`; API поддерживает `today`, `tomorrow`,
3/7/14/30 суток, фиксирует верхнюю границу как исключающую и ограничивает начало
«Сегодня» текущим временем. Coverage старше 24 часов помечается как stale.

Добавлена additive migration `0010_calendar_coverage_and_participants` для
участников canonical event и таблицы `calendar_coverages`. NHL mapping сохраняет
переносы на прежней source identity, создаёт новую revision и не удаляет событие,
которое отсутствует в следующем снимке. Нормализуются scheduled/postponed/
cancelled/started/finished. NHL provider покрывает 30 суток и записывает manifest
только как полный после успешного обхода weekly anchors.

Malformed/пустой либо неполный weekly anchor теперь вызывает ошибку: проверяются
семь ожидаемых последовательных дат. Перед fetch старый manifest заменяется
состоянием `complete=false`, cached completed schedule progress очищается;
проверка фиксирует, что неудачный запрос не сохраняет прежний manifest как новый
успешный. Unknown NHL `gameState` получает `needs_review`. API фильтрует
`started`/`finished` независимо от scheduled time и выдаёт `confirmed_empty` только
при `total == 0`, включая pagination.

Проверен достижимый ручной entrypoint `canonical_bootstrap import-nhl`: повторный
импорт другого bundle ранее мог откатить свежие время/участников canonical event.
Bootstrap теперь добавляет immutable revisions, сохраняя существующую current
projection; отдельный регрессионный тест подтвердил это.

При сбое acquisition API DB пока не получает запись failed attempt:
последнее успешное DB coverage может отображаться до истечения 24-часового TTL.
Перед релизом Data Cycle должен передавать failed/partial coverage в БД; это
зафиксировано в TASK как follow-up и остаётся release blocker до реализации.

Футбольный production adapter не добавлялся. Fixture с другим турниром/source
проходит тот же календарный API контракт и pagination.

## TDD и проверки

- **Red:** исходный тест API был зафиксирован предыдущим Developer как падающий
  из-за отсутствующих `CanonicalEvent.home_participant`/`away_participant`.
  В correction cycle red выявил: started/finished попадали в календарь (3 вместо
  1), partial weekly anchor принимался, а второй import bundle откатывал время
  события с 03:00 на 00:00. Все три regression tests теперь green. Предыдущий цикл
  также зафиксировал red для начала периода и malformed anchor.
- `uv run pytest -q tests/test_calendar_api.py tests/test_canonical_bootstrap.py tests/test_nhl_provider.py tests/test_readiness_and_migrations.py tests/test_prediction_repository_upcoming.py tests/test_prediction_publication.py tests/test_canonical_full_refresh.py tests/test_canonical_snapshot.py` — 61 passed.
- `make lint` — успешно.
- `make docs` — успешно; итоговая инкрементальная сборка вывела 1 предупреждение
  о отсутствующем `docs/source/_static`; ошибок сборки нет. Предыдущая чистая
  сборка в этом сеансе вывела 24 предупреждения autodoc.
- `uv run alembic heads` — единственный head `0010_calendar_coverage_and_participants`.
- Migration integration test дважды применяет `upgrade head` и проверяет новую
  таблицу и participant columns.
- `git diff --check` — успешно.
- После commit gate failure SQLAlchemy typing исправлено без `type: ignore`:
  predicates/order используют typed table columns; coverage query использует
  `select`/`ScalarResult`, а `cast` ограничен legacy ORM boundary.
- `uv run pre-commit run mypy --files sports_forecast/service/db/repository.py` — passed.
- Повторный targeted/regression набор после исправления — 61 passed;
  `make lint` — passed.
- `uv run pre-commit run --files <изменённые файлы>` — все применимые hooks passed,
  включая ruff, ruff-format, mypy и AI roles/skills validation. Commit не выполнялся.

## Изменённые границы и неизменённое

Изменены NHL schedule/source mapping, canonical bootstrap, DB model/repository,
service schema/router, migration, targeted tests, README и API architecture docs.
Не менялись Telegram handlers, admin/control API, scheduler/Data Cycle, REQ/ADR,
production database, server timer и deployment.

## Review и follow-up

- Первое независимое review нашло ошибки пагинации, фильтра статусов,
  unknown NHL state, полноты недельного ответа и повторного bootstrap.
  После correction cycle Reviewer повторно проверил сценарии и выполнил
  `uv run pytest -q tests/test_calendar_api.py tests/test_canonical_bootstrap.py tests/test_nhl_provider.py`
  — 46 passed, блокирующих findings нет.
- Перед релизом реализовать передачу failed/partial acquisition attempt в
  persisted `calendar_coverages`, чтобы недавний успешный coverage не оставался
  видимым после новой ошибки. Это зафиксировано в
  [TASK-025-3](../../backlog/tasks/TASK-025-3-data-cycle-runs.md).
- Production migration, NHL runtime probe и выпуск версии не выполнялись.
