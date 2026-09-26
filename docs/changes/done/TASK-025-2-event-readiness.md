# TASK-025-2 — Отчёт о срезе readiness API

> **Статус среза:** базовая версия и failed-attempt extension прошли review
> **Статус TASK:** `done`
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
provider `market.last_update` для h2h; store `fetched_at` считается временем
сохранения и не доказывает freshness линии. Legacy OddsStore строки без provider
timestamp не попадают в readiness projection. Для профиля `has_draw=False`
извлечение отклоняет h2h с исходом Draw; sidecar timestamp сохраняется только
для подтверждённого 2-way рынка. Строки привязываются по нормализованным участникам
и точному UTC kickoff, только если найден ровно один canonical event. Совпадение
только по дате, несколько одинаковых кандидатов и несовпавший старый kickoff
не создают привязку. UPSERT не заменяет более свежее observation старым, поэтому
повтор bridge безопасен. Odds values хранятся отдельно от `Prediction.odds_raw`.
Observation также сохраняет snapshot kickoff и участников canonical event,
которому была сопоставлена линия. Если время или участники события меняются,
evaluation сразу переводит старое observation в `stale`, даже пока его
`fetched_at` находится внутри TTL. Новая линия требует нового однозначного
source observation.

Migration `0011_event_odds_observations` создаёт odds projection. TASK-025-6
добавил migration `0013_future_odds_acquisition` для batch attempts и provider
timestamp provenance. Каждая попытка хранит run ID, результат, safe failure code,
quota snapshot и UTC request window. Runtime grants дают API read для attempt
history и refresh writer право записи.

Calendar API теперь возвращает odds `last_success_at` и `last_attempt_at`.
`odds.failed` выставляется, когда последняя применимая попытка завершилась
ошибкой внутри request window уже после preparation deadline и новее успешного
наблюдения/ответа. Более поздний успешный batch без линии оставляет `missing`;
старое observation не удаляется.

## Изменённые границы

- API календаря и его схемы;
- чистые readiness rules и турнирные policy;
- OddsStore→DB projection bridge и DB repository/model;
- Alembic migration и database role grants;
- целевые API/unit/migration tests, README и API architecture docs.

Формулы odds/value, Telegram handlers и service deployment не менялись. Production
migration или production smoke не запускались.

## Непокрытые зависимости и риски

- Production API key/quota и фактический coverage подтверждаются Operations;
  в этой задаче использовались fake provider fixtures без реальных odds запросов.
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
  Отдельные проверки закрепили отказ legacy строки без market timestamp и
  3-way h2h с Draw при требуемом `winner_withOT`. В следующем review-cycle
  red-тесты воспроизвели смешение close odds с open kickoff при переносе и
  пропуск Draw outcome, у которого отсутствовала числовая цена.
- **Green:** linker, projection таблица, readiness evaluator/API поля и football
  fixture реализованы; ошибка prediction остаётся `failed`, а несовпадение
  event identity snapshot немедленно делает odds `stale`. Подтверждённый 2-way
  h2h использует `market.last_update`; retrieval timestamp OddsStore не заменяет
  provider time. Close snapshot выбирается только при равенстве нормализованных
  команд и точного kickoff; наличие Draw/Tie распознаётся независимо от цены.
- **Failed-attempt extension:** red-тесты до implementation падали на отсутствующем
  future odds adapter; затем API/unit tests проверили окно события, preparation
  deadline, более поздний success без линии, сохранённый старый observation и
  `last_attempt_at`. Конкретные команды для extension приведены в отчёте TASK-025-6.
- **Refactor:** DB grants ограничены необходимыми API read/worker write правами;
  API загружает readiness rows пакетно, а не выполняет запрос на компонент для
  каждого события.

## Проверки

- `uv run pytest -q tests/test_event_readiness.py tests/test_calendar_api.py tests/test_odds_refresh.py tests/test_readiness_and_migrations.py tests/test_prediction_repository_upcoming.py tests/test_prediction_publication.py` — 47 passed после correction cycle.
- `uv run pytest -q tests/test_event_readiness.py tests/test_calendar_api.py tests/test_odds_refresh.py tests/test_readiness_and_migrations.py tests/test_prediction_repository_upcoming.py tests/test_prediction_publication.py tests/test_odds_enrichment.py tests/test_odds_store.py` — 92 passed после odds provenance correction.
- `uv run pytest -q tests/test_event_readiness.py tests/test_calendar_api.py tests/test_odds_refresh.py tests/test_readiness_and_migrations.py tests/test_prediction_repository_upcoming.py tests/test_prediction_publication.py tests/test_odds_enrichment.py tests/test_odds_store.py tests/test_odds_pipeline_v2_integration.py` — 95 passed после snapshot/Draw correction.
- `make lint` — passed.
- `uv run pre-commit run mypy --files sports_forecast/service/event_readiness.py sports_forecast/service/odds_projection.py sports_forecast/service/db/models.py sports_forecast/service/db/repository.py sports_forecast/service/routers/calendar.py sports_forecast/service/schemas.py` — passed.
- `uv run alembic heads` — на момент этого среза единственный head
  `0011_event_odds_observations`; следующий срез добавил `0012`.
- `git diff --check` — passed.
- Во время параллельного TASK-025-3 общий lint и targeted mypy временно
  блокировались его незавершённым diff; после исправления TASK-025-3 повторный
  `make lint` прошёл. `ruff check` по odds/readiness файлам, pre-commit для
  correction commit и `git diff --check` также прошли.

Независимый Reviewer нашёл два P1: свежий `Prediction.status=error` ошибочно
становился `ready`, а odds observation после переноса оставался `ready` до TTL.
Оба сценария воспроизведены regression tests и исправлены. Повторный review
проверил identity matching, migration/grants, API semantics, football fixture
и идемпотентный sync; блокирующих findings для реализованного среза нет.

Расширение failed acquisition в TASK-025-6 реализовано и прошло повторное
независимое review без блокирующих findings.
