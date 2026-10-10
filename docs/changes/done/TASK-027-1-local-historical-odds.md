# TASK-027-1 — Локальный импорт и запрос истории Pinnacle

> **Статус:** done, ожидает независимый review
> **Ветка:** `initiative/epic-027-historical-odds`
> **Требование:** [REQ-027](../../product/requirements/REQ-027-historical-odds.md)
> **Решение:** [ADR-031](../../architecture/adr/ADR-031-historical-odds.md)
> **Задача:** [TASK-027-1](../../backlog/tasks/TASK-027-1-local-historical-odds.md)

## Результат

Добавлен offline import historical The Odds API cache в отдельную SQLite БД,
point-in-time запрос `provider_as_of` и CLI import/query. Импорт сохраняет
неизменяемые `ho1` факты, receipts с отдельными ID и hash исходного файла,
компактные NHL event facts,
включая отсутствие Pinnacle/h2h, и диагностические коды. Дубликат исходного
файла и изменение порядка outcomes не создают новые наблюдения. Изменившаяся
цена в том же provider timestamp остаётся конфликтом.

На запросе закрепляется проверенный `ir1`. Strict resolver применяется batch-ом,
а цена возвращается только при явном подтверждённом event designation в этом
snapshot. Envelope `timestamp` — единственный источник `observed_at`; provider
`last_update` хранится отдельно и не влияет на отбор. `retrieved_at` не выводится
из mtime/import time. Ответ включает receipt ID и hash файла, market rules, обе цены, возраст
snapshot, provenance и явную маркировку `provider_as_of`; `locally_known_at_t`
остаётся `false`.

Новый путь не использует API client или сеть. Старый OddsStore, service DB,
Alembic, runtime acquisition, close/T−15, API и бот не изменялись. Большие
cache responses и локальные SQLite/registry артефакты в Git не добавлялись.

## Red → green → refactor

- Red: `uv run pytest -q tests/test_historical_odds.py` завершился ожидаемым
  `ModuleNotFoundError` до реализации модуля.
- Red для хранения event facts: focused test завершился ожидаемым ImportError до
  добавления `list_imported_source_events`.
- Green: новые import/query, idempotency, outcome reorder, point-in-time,
  неизвестное и позднее retrieval, timezone-naive T, конфликт timestamp,
  нерешённый event mapping, transaction rollback, отсутствие target market и
  draw outcome покрыты focused integration tests.
- Refactor: форматирование и lint новых Python модулей; отдельный локальный
  registry snapshot подтвердил реальный Pinnacle пример через CLI.

## Реальное локальное evidence

Владелец подтвердил связь NHL API game `2023020180` ↔ The Odds API event
`b42367c52f8c596d01199dd31258cc62`, Carolina Hurricanes (home) — Buffalo
Sabres (away), kickoff `2023-11-08T00:00:00Z`.

Для этой связи создан временный локальный registry и проверенный snapshot вне
репозитория. Snapshot ID и manifest digest:
`ir1:ef9cc3818aeb73dcbe68dbebd1bd912ea30b68a30ea898167676f4cd8dcce210`.
Evidence bundle расположен в `/tmp/sports-forecast-epic-027-evidence-final2`;
production registry state не менялся.

Импортированы два существующих локальных cache файла, суммарно 24 provider
event rows: 21 наблюдение Pinnacle h2h сохранено, ошибок импорта нет.

| Envelope `timestamp` | SHA-256 файла | Provider `observed_at` | Pinnacle home / away |
| --- | --- | --- | --- |
| 2023-11-06T23:25:43Z | `64830ea162f6d8d0cf451a7b6ee4e488affd20019440778a81858a66c88f08df` | 2023-11-06T23:25:43Z | 1.51 / 2.70 |
| 2023-11-07T11:55:40Z | `09861cc7ef3936dc216cfd2a3d3d3e2398a4de52da2bedd303e871b5570593cf` | 2023-11-07T11:55:40Z | 1.51 / 2.73 |

Запрос к `2023-11-06T23:00:00Z` вернул `null`; к `2023-11-07T00:00:00Z`
вернул ранний observation `ho1:25b7a255202c6bd699f59784ce07e5a4c48a4a47e3743af06e660d22e9ca601f`;
к `2023-11-07T11:55:43Z` — поздний observation
`ho1:b980b881373b6756af38f54e6a09952ba4348467eccc445a4cf71e302a3b5fe0`.
У обоих `retrieved_at=null`, `retrieval_status=unknown`, `late_retrieval=null`,
`locally_known_at_t=false`. Повторно прочитанные после импорта SHA-256 совпали с
таблицей; cache не менялся.

## Проверки

Фактически выполнены:

- `uv run pytest -q tests/test_historical_odds.py tests/test_registry_snapshot.py` — 24 passed.
- `uv run ruff check sports_forecast/data/providers/odds/historical.py sports_forecast/data/providers/odds/historical_cli.py tests/test_historical_odds.py` — passed.
- `uv run ruff format sports_forecast/data/providers/odds/historical.py sports_forecast/data/providers/odds/historical_cli.py tests/test_historical_odds.py` — completed.
- `uv run python -m sports_forecast.data.providers.odds.historical_cli --help` — passed.
- `uv run python -m sports_forecast.data.providers.odds.historical_cli import --source '/home/xieveer/Документы/PyCharmProject/SportsProbabilisticForecasting/data/cache/the_odds_api/_historical_sports_icehockey_nhl_odds_h2h,totals_eu_2023-11-06T23:30:00Z.json' --database /tmp/sports-forecast-epic-027-evidence-final2/historical-final4.sqlite3` — 14 events seen, 11 observations inserted, 0 diagnostics.
- `uv run python -m sports_forecast.data.providers.odds.historical_cli import --source '/home/xieveer/Документы/PyCharmProject/SportsProbabilisticForecasting/data/cache/the_odds_api/_historical_sports_icehockey_nhl_odds_h2h,totals_eu_2023-11-07T12:00:00Z.json' --database /tmp/sports-forecast-epic-027-evidence-final2/historical-final4.sqlite3` — 10 events seen, 10 observations inserted, 0 diagnostics.
- `uv run python -m sports_forecast.data.providers.odds.historical_cli query --database /tmp/sports-forecast-epic-027-evidence-final2/historical-final4.sqlite3 --registry-snapshot /tmp/sports-forecast-epic-027-evidence-final2/registry/snapshots/ef9cc3818aeb73dcbe68dbebd1bd912ea30b68a30ea898167676f4cd8dcce210 --event-id 618af5aa-9786-485e-bfe5-6c61b61932eb --at 2023-11-06T23:00:00Z` — `null`.
- Та же `query` команда с `--at 2023-11-07T00:00:00Z` выбрала ранний observation; с `--at 2023-11-07T11:55:43Z` — поздний.
- Повторный `sha256sum` обоих исходных файлов подтвердил hashes из таблицы.

## Остаточные ограничения

- `retrieved_at` неизвестен для legacy cache. Для batch с разными доказанными
  временами получения импорт нужно вызывать отдельно для каждого такого времени.
- Поддержан только подтверждённый NHL/Pinnacle `h2h` → `winner_withOT`.
- Отчёт coverage, expected event universe и подсчёт категорий выполняет
  TASK-027-2; здесь сохранены source event facts и отсутствие target market.
- Проверка старых close/T−15/current odds и полный acceptance EPIC остаются в
  TASK-027-2. Production rollout не выполнялся.

## Handoff

Передать Product Owner для независимого review. Finding должен пройти новый
red→green цикл. PR не создавался; следующий engineering шаг — TASK-027-2 после
review этого среза.
