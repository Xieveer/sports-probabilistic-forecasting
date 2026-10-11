# TASK-026-12 — Словари рынков и исходов

## Результат

Добавлены проектные сущности `market` и `outcome`, source aliases в заданном
sport/tournament/bookmaker scope и типизированные market rules с immutable
`UUID → home_win/away_win/draw` отображением. NHL/Pinnacle seed связывает
The Odds API `h2h` с `winner_withOT`, учитывающим овертайм и буллиты, с двумя
исходами home/away без ничьей. Seed идемпотентен и сохраняет owner remapping и
изменённые правила.

Локальный каталог показывает market alias, правила и историю изменений. Форма
позволяет изменить период, overtime/shootout/draw и набор исходов с семантическими
ключами; проверяются loopback, session, CSRF, размер тела и optimistic revision.

Локальные и установленные readers предоставляют `resolve_market(...)` и
`get_market_rule(...)`. Snapshot format v2 включает `market_rules.jsonl`; новый код
принимает v1/schema 11 и v2/schema 12. Publisher, downloader и installer сохраняют
старый v1 package читаемым. Проверено развертывание v2 и последующая publication
старого v1 package как более новой rollback sequence. Runbook требует сначала
вернуть v1 snapshot, затем старый бинарник. Event rows и прежние immutable packages
не удаляются.

## Изменённые файлы

- `sports_forecast/identity/registry.py` — schema 12, безопасная миграция entities,
  market rule API, revision и audit.
- `sports_forecast/identity/snapshot.py` — v2 market rules export/validation и dual read.
- `sports_forecast/identity/installation.py` — хранение и pinned read v1/v2 snapshots.
- `sports_forecast/identity/publication.py` — dual version publish/download/cache/verification.
- `sports_forecast/identity/review_app.py` — просмотр и audit-редактирование рынка.
- `sports_forecast/identity/nhl_market_seed.py` — повторяемый NHL/Pinnacle seed.
- `sports_forecast/identity/__init__.py` — экспорт типов правил и аудита.
- `tests/test_registry_market_rules.py`, `tests/test_registry_snapshot.py`,
  `tests/test_registry_installation.py`, `tests/test_registry_publication.py`,
  `tests/test_entity_registry.py` — доменный, UI, migration, snapshot, install и
  публикационный contracts.

## Red → green

- **Red:** до реализации `.venv/bin/pytest tests/test_registry_market_rules.py -q`
  остановился на ожидаемом `ModuleNotFoundError` для отсутствующего market seed.
- После первого green-цикла audit-тест выявил, что первичное сохранение правила также
  создаёт запись аудита; ожидание скорректировано на проверку начальной и изменяющей
  записей. Реализация оставляет обе записи.
- **Green:** целевой набор ниже прошёл после всех изменений.

## Проверки

- `.venv/bin/pytest tests/test_registry_market_rules.py tests/test_registry_snapshot.py tests/test_registry_installation.py tests/test_registry_publication.py tests/test_entity_registry.py tests/test_entity_review.py -q` — **124 passed**, 3 warnings.
- `.venv/bin/pre-commit run mypy --files sports_forecast/identity/registry.py sports_forecast/identity/snapshot.py sports_forecast/identity/installation.py sports_forecast/identity/publication.py sports_forecast/identity/review_app.py sports_forecast/identity/nhl_market_seed.py` — **passed**.
- `.venv/bin/ruff check sports_forecast/identity/registry.py sports_forecast/identity/snapshot.py sports_forecast/identity/installation.py sports_forecast/identity/publication.py sports_forecast/identity/review_app.py sports_forecast/identity/nhl_market_seed.py tests/test_registry_market_rules.py tests/test_registry_snapshot.py tests/test_registry_publication.py tests/test_entity_registry.py` — **passed**.
- `git diff --check` — **passed**.
- На объединённом EPIC-026 diff: `PYTHONPATH=. .venv/bin/pytest -m unit -q` —
  **1706 passed**, 17 deselected; `UV_OFFLINE=1 make lint` и
  `UV_OFFLINE=1 make type-check` — **passed**.
- Независимый review закрыл findings по сохранению owner remap, выбору
  confirmed alias и неизменности семантических outcome keys; новых P0–P2 нет.

`uv run pytest` не использовался для доказательства: uv не смог загрузить build
dependency `setuptools` из PyPI из-за DNS/network failure. Те же тесты запущены через
уже установленный `.venv/bin/pytest`.

## Границы и остаточные риски

- Срез реализует только NHL/Pinnacle `h2h`; другие источники, турниры и рынки не
  получили seed.
- `market_rules` и `market_rule_audit` добавлены в master schema; server projection
  хранит содержимое immutable snapshot, а не отдельные рабочие market-rule таблицы.
- Production migration/publication/sync не запускались. Перед бинарником без v2
  необходимо выполнить описанный rollback sequence: опубликовать и установить старый
  v1 snapshot, затем откатить приложение.
- Matcher реализован в TASK-026-13; реальный NHL forecast/odds cycle ещё требует
  итоговой интеграции и release gates EPIC-036.
