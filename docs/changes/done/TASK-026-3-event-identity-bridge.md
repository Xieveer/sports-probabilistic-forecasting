# TASK-026-3 — Project event identity и canonical bridge

> **Статус:** выполнено, независимое review пройдено
> **Требование:** [REQ-026](../../product/requirements/REQ-026-entity-registry.md)
> **Решение:** [ADR-027](../../architecture/adr/ADR-027-local-entity-registry-and-snapshots.md)
> **Задача:** [TASK-026-3](../../backlog/tasks/TASK-026-3-event-identity-bridge.md)

## Реализовано

- Локальный registry schema обновлён до v8. `event_relations` хранит project
  event UUID, турнир, home/away team UUID и плановое время; каждое создание или
  исправление защищено expected revision и записывает actor/reason/audit.
  Перенос расписания меняет relation revision, но сохраняет UUID события.
- `EventIdentitySnapshot.from_registry()` строит неизменяемую проекцию только из
  активных project events, relations и designation заданного снимка. Source event
  ID принимается только при confirmed designation в tournament scope.
- `RegistryEventResolver` сначала использует точный подтверждённый source event
  ID. Он сохраняет UUID при переносе времени, но возвращает `conflict`, если
  известные confirmed tournament/team IDs противоречат связи. Неизвестная raw
  строка сама по себе не считается подтверждённым противоречием.
- Повторные canonical references с уже confirmed source key остаются resolved.
  Batch resolver проверяет reverse uniqueness только для same-source/sport/
  tournament scope: разные source IDs, которые автоматически претендуют на один
  project event по точным участникам и времени, получают `ambiguous`; confirmed
  source-key history сохраняется. При повторном backfill уже записанные mappings
  остаются неизменными и участвуют как occupied claims; поздний конкурент получает
  `ambiguous`.
- Fallback разрешает событие только при подтверждённых tournament/home/away,
  точном UTC времени и единственном результате. Он не использует fuzzy, nearest,
  одно имя или time window. Отсутствие времени и designation остаётся unresolved;
  несколько точных событий — ambiguous.
- Snapshot ID вычисляется как `ev1:<sha256>` от canonical JSON projection,
  считанного в одной SQLite read transaction. Projection включает events,
  relations, внешние designations и их интервалы, conflict overlays, schema и
  resolver policy versions и `nfkc-casefold-alnum-v1` normalization version;
  порядок строк не влияет на hash. Reader отвергает неподдерживаемые
  normalization/projection schema versions.
- `registry_identity_snapshots` хранит kind, SHA-256, projection schema,
  normalization/policy versions и
  полный frozen projection JSON. `registry_canonical_event_mappings` ссылается
  на header и хранит resolved/unresolved/ambiguous/conflict для пары
  `(snapshot_id, canonical_event_id)`. Проверка header и запись mapping атомарны;
  forged object или повторное использование ID для другого содержимого
  отклоняются до записи. Frozen projection загружается повторно без доступа к
  изменяемому локальному registry.
- `put_event_mapping` отвергает resolved UUID вне frozen projection и неизвестные
  статусы.
- Resolver применяет tournament, team и source-event designations и conflict
  overlays на `scheduled_at` canonical event с полуоткрытыми интервалами
  `[valid_from, valid_until)`. Open overlay блокирует только пересекающийся
  интервал; resolved overlay выбирает target только в своём интервале; dismissed
  overlay не влияет на разрешение. Pending/deferred designation сама по себе не
  отменяет существующую confirmed привязку; открытый overlay или несколько
  противоречащих confirmed ID блокируют разрешение. Истёкшие aliases не
  связываются. Если дата отсутствует и выбор зависит от временных
  confirmed aliases/overlays, результат `ambiguous`.
- `backfill_event_bridge()` по умолчанию строит dry-run для всех фактических
  `CanonicalEvent` rows. Явный `apply=True` пишет version-pinned bridge в
  транзакции; legacy rows без подтверждённых участников сохраняются как
  unresolved mapping. Старые event integer IDs и canonical rows не изменяются.
- `conf/identity_event.yaml` выключает новый reader по умолчанию. Production
  matcher, календарный ingest/API и production routes не переключались.

## Red → green → refactor

- Red: `uv run pytest tests/test_event_identity.py -q` завершился ожидаемой
  ошибкой импорта отсутствующего `sports_forecast.identity.events`.
- Green/refactor: тесты подтверждают source-ID при переносе расписания,
  противоречащие подтверждённые team IDs, неоднозначные точные матчи,
  отсутствие auto-resolution без подтверждённых участников/времени,
  snapshot-pinned mappings и unresolved legacy row, dry-run по умолчанию,
  owner audit/revision при reschedule и выключенный compatibility switch.
- Red для review findings: до реализации batch reverse uniqueness и frozen
  snapshot loader новые regressions завершились collection error из-за
  отсутствующего `load_event_snapshot`; затем они проверили ambiguous конкурирующие
  source IDs, сохранение confirmed historical references, content-derived ID,
  отказ forged reuse и reload старого projection после локального изменения.
- Red для последних findings: regressions воспроизвели конфликт immutable mapping
  после появления поздней canonical row, принятие UUID вне projection и отсутствие
  normalization version в объекте snapshot. Исправление сохраняет прежний mapping,
  создаёт ambiguous запись для нового конкурента и отказывает forged UUID/unsupported
  normalizer.
- Red → green для temporal finding: regressions проверяют смену tournament/team/
  source-event aliases по датам, истечение алиаса, отсутствие даты при временном
  выборе, а также open/resolved/dismissed overlays в пределах их интервалов.
  Resolver теперь использует `scheduled_at` как дату выбора designation и overlay.
- Red → green для pending candidate finding: регрессия сначала падала, потому
  что pending designation для уже подтверждённого alias переводил event mapping
  в conflict. Resolver теперь учитывает pending/deferred только через явно
  открытый overlay и сохраняет действующий confirmed target.

## Проверки

- `uv run pytest tests/test_event_identity.py tests/test_entity_registry.py tests/test_calendar_api.py tests/test_live_odds_enrichment.py tests/test_readiness_and_migrations.py -q` — **68 passed, 3 warnings**.
- `uv run ruff check sports_forecast/identity/events.py sports_forecast/identity/registry.py sports_forecast/service/db/models.py tests/test_event_identity.py tests/test_entity_registry.py migrations/versions/0018_registry_canonical_event_mappings.py` — **All checks passed**.
- `uv run ruff format --check sports_forecast/identity/events.py sports_forecast/identity/registry.py sports_forecast/service/db/models.py tests/test_event_identity.py tests/test_entity_registry.py migrations/versions/0018_registry_canonical_event_mappings.py` — **6 files already formatted**.
- `uv run pre-commit run mypy --files sports_forecast/identity/events.py sports_forecast/identity/registry.py sports_forecast/service/db/models.py tests/test_event_identity.py` — **Passed**.
- `git diff --check` — пройдено.

## Границы

Server snapshot export/install, server-first feedback transport и переключение
matcher остаются в TASK-026-4/5/6. Никакие production routes не добавлялись.
Независимый Reviewer проверил полный diff и повторил целевой pytest
(**68 passed, 3 warnings**), Ruff, mypy и `git diff --check`.
Блокирующих P0–P2 замечаний нет.
