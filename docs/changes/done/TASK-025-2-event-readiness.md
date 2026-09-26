# TASK-025-2 — Отчёт о срезе readiness API

> **Статус среза:** реализован, повторное независимое review пройдено
> **Статус TASK:** `blocked` до добавления persisted failed-odds attempts в TASK-025-3
> **Дата:** 2026-09-26
> **Задача:** [TASK-025-2](../../backlog/tasks/TASK-025-2-event-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат

`GET /calendar/{tournament}` сохраняет календарное событие без prediction и
добавляет независимые `calendar_readiness`, `prediction_readiness`,
`odds_readiness` и агрегированное `readiness`. Компоненты содержат status,
reason code, требуемые/доступные markets и время последнего успешного обновления.
TTL, обязательные markets/bookmaker и preparation deadline читаются из
`conf/readiness/{tournament}.yaml`.

Prediction сопоставляется только по паре `(tournament, source_event_id == match_id)`.
Пустое/просроченное значение не считается готовым; prediction status `error`
виден как failed. Перенос UTC kickoff или изменение участника относительно
старого prediction переводит календарь в `changed`, а prediction — в
`partial` с кодом `event_identity_changed`. Существующая последняя prediction
строка не удаляется. `canonical_snapshot_id` с SHA revision не сравниваются:
это разные идентификаторы.

Добавлена `odds_observations` и мост из сохранённого OddsStore. Используется
реальный `fetched_at`; строки привязываются по нормализованным участникам и
точному UTC kickoff, только если найден ровно один canonical event. Совпадение
только по дате, несколько одинаковых кандидатов и несовпавший старый kickoff
не создают привязку. UPSERT не заменяет более свежее observation старым, поэтому
повтор bridge безопасен. Odds values хранятся отдельно от `Prediction.odds_raw`.
Observation также сохраняет snapshot kickoff и участников canonical event,
которому была сопоставлена линия. Если время или участники события меняются,
evaluation сразу переводит старое observation в `stale`, даже пока его
`fetched_at` находится внутри TTL. Новая линия требует нового однозначного
source observation.

DB migration `0011_event_odds_observations` additive. Runtime grants включают
API read для canonical calendar/coverage/revision и odds projection, а worker
write для odds observations. Ошибка DB sync после Parquet upsert возвращает
ошибку вызывающему Odds refresh; повторное выполнение синхронизирует persisted
store в БД.

## Изменённые границы

- API календаря и его схемы;
- чистые readiness rules и турнирные policy;
- OddsStore→DB projection bridge и DB repository/model;
- Alembic migration и database role grants;
- целевые API/unit/migration tests, README и API architecture docs.

Формулы odds/value, Telegram handlers, scheduler и service deployment не менялись.
Production migration или production smoke не запускались.

## Непокрытые зависимости и риски

- Odds observation отражает только реально сохранённые строки OddsStore. Текущий
  refresh ограничен `need_to=today`, а live poll выбирает существующие prediction
  rows; будущие календарные события без прогноза не получают линию автоматически.
  Calendar-first future odds acquisition добавлена в критерии TASK-025-3 и остаётся
  release gap до её выполнения.
- Persisted failed odds acquisition lifecycle и `odds_readiness=failed` зависят
  от TASK-025-3. До этого отсутствие/устаревание линии честно возвращает
  `missing`/`stale`; API не синтезирует failed из старого successful observation.
- Readiness policy defaults заданы конфигурацией и могут изменяться без API
  изменения: NHL prediction TTL 24h, odds TTL 6h, deadline 6h; EPL fixture
  prediction TTL 12h, odds TTL 3h, deadline 4h.
- Контрольный football fixture проверяет общий контракт, не подключение реального
  футбольного источника или production odds pipeline.

## Red → Green → Refactor

- **Red:** новый projection test сначала завершился ожидаемым collection error
  (`sports_forecast.service.odds_projection` отсутствовал). Затем scenario
  tests зафиксировали ожидаемую семантику уникальной привязки, fetched timestamp,
  неоднозначной пары и переноса kickoff. В correction cycle regression tests
  воспроизвели два дефекта: свежая prediction со статусом `error` считалась
  готовой, а сохранённая линия оставалась готовой после переноса события.
- **Green:** linker, projection таблица, readiness evaluator/API поля и football
  fixture реализованы; ошибка prediction остаётся `failed`, а несовпадение
  event identity snapshot немедленно делает odds `stale`.
- **Refactor:** DB grants ограничены необходимыми API read/worker write правами;
  API загружает readiness rows пакетно, а не выполняет запрос на компонент для
  каждого события.

## Проверки

- `uv run pytest -q tests/test_event_readiness.py tests/test_calendar_api.py tests/test_odds_refresh.py tests/test_readiness_and_migrations.py tests/test_prediction_repository_upcoming.py tests/test_prediction_publication.py` — 47 passed после correction cycle.
- `make lint` — passed.
- `uv run pre-commit run mypy --files sports_forecast/service/event_readiness.py sports_forecast/service/odds_projection.py sports_forecast/service/db/models.py sports_forecast/service/db/repository.py sports_forecast/service/routers/calendar.py sports_forecast/service/schemas.py` — passed.
- `uv run alembic heads` — единственный head `0011_event_odds_observations`.
- `git diff --check` — passed.

Независимый Reviewer нашёл два P1: свежий `Prediction.status=error` ошибочно
становился `ready`, а odds observation после переноса оставался `ready` до TTL.
Оба сценария воспроизведены regression tests и исправлены. Повторный review
проверил identity matching, migration/grants, API semantics, football fixture
и идемпотентный sync; блокирующих findings для реализованного среза нет.
