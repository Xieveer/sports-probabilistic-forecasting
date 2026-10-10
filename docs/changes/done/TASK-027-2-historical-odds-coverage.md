# TASK-027-2 — Покрытие истории и итоговая проверка Pinnacle

> **Статус:** реализация готова; итоговый real acceptance ожидает подтверждения второго registry mapping
> **Ветка:** `initiative/epic-027-historical-odds`
> **Требование:** [REQ-027](../../product/requirements/REQ-027-historical-odds.md)
> **Решение:** [ADR-031](../../architecture/adr/ADR-031-historical-odds.md)
> **Задача:** [TASK-027-2](../../backlog/tasks/TASK-027-2-historical-odds-coverage.md)

## Реализация

Добавлен offline отчёт по expected NHL universe из pinned `ir1` registry и UTC
kickoff окну `[from, to)`. Новый локальный CLI `historical_cli coverage`
принимает общий provider-as-of момент `T`, выводит числитель/знаменатель,
fingerprint импортированного набора, ошибки/диагностики импорта, timestamp
conflicts, unknown/late retrieval, unmapped source event count и пояснения строк.
Категории `covered`, `no_line`, `no_snapshot`, `mapping_error` взаимно
исключаются; current OddsStore/API/бот не используются.

Диагностика сохраняет разницу между отсутствием source evidence, отсутствующей
Pinnacle/`h2h` линией, отсутствием подходящего snapshot к `T`, некорректным
envelope timestamp, неверным рынком и конфликтным/неразрешённым event mapping.
Import diagnostics детализированы кодами; фатальная ошибка импорта прерывает CLI
и не включается в последующий отчёт.

## Red → green → refactor

- Red: `uv run pytest -q tests/test_historical_odds.py::test_coverage_counts_pinned_universe_and_reports_absent_line_separately` завершился ожидаемым `ModuleNotFoundError` отсутствующего `historical_coverage`.
- Green: добавлены expected-universe aggregation и coverage CLI; новые сценарии включают `covered`, `no_line`, отсутствующий source evidence, snapshot позже `T`, invalid timestamp, mapping error, unmapped event, import diagnostics/conflict и нулевое покрытие.
- Refactor: Ruff lint/format чистые; проверен минимальный JSON результат CLI на реальном pinned registry и локальных cache файлах.

## Реальные данные и acceptance

Owner-confirmed mapping из TASK-027-1: NHL API game `2023020180` ↔ The Odds API
event `b42367c52f8c596d01199dd31258cc62`, CAR–BUF, kickoff
`2023-11-08T00:00:00Z`, pinned snapshot
`ir1:ef9cc3818aeb73dcbe68dbebd1bd912ea30b68a30ea898167676f4cd8dcce210`.
Импорт двух локальных файлов дал 24 source event rows и 21 Pinnacle observation,
0 diagnostics. Coverage для окна `[2023-11-07T00:00:00Z,
2023-11-09T00:00:00Z)` к `2023-11-07T11:55:43Z`: **1/1 covered**, 0 `no_line`,
0 `no_snapshot`, 0 `mapping_error`, 2 файла, 0 conflicts, 2 receipts с unknown
retrieval, 13 unmapped source event IDs. Fingerprint набора:
`sha256:8f4673bbf009d8a1e30e05cdfe577d0d2e3c20d0377dbb99e6105e5ac8715c09`.

Повторный import тех же файлов вставил 0 observations. Реальные query для
`2023-11-06T23:00:00Z`, `2023-11-07T00:00:00Z` и
`2023-11-07T11:55:43Z` вернули null, ранний observation
`ho1:25b7a255202c6bd699f59784ce07e5a4c48a4a47e3743af06e660d22e9ca601f`
и поздний `ho1:b980b881373b6756af38f54e6a09952ba4348467eccc445a4cf71e302a3b5fe0`.
Retrieval остался unknown, `locally_known_at_t=false`. SHA-256 обоих исходных
cache файлов совпали с зафиксированным в TASK-027-1 evidence.

Реальный `no_line` control найден, но ещё не включён в pinned registry:
The Odds API event `c4e420f552d6ffa6f1a1e5dec5a0db3e` ↔ NHL API game
`2023020271`, Anaheim Ducks — St Louis Blues, kickoff `2023-11-20T01:00:00Z`.
Четыре локальных historical envelope показывают отсутствие Pinnacle/`h2h`.
Их file SHA-256: `c6485f0b2712660322e08800bb5766647743c171e10b8ab660b06d139bf0223e`,
`7e2697acbd8f78c9e75e0080a399a740a2bf9e0e8624a5ec2461206ed65d9819`,
`13ee307326e9f3ba7a713eb0acac6b5acee9a5d0aff9eca8240f53cb56a8fa49`,
`f44d735492892dc7f87b078c84f81b30e85044c7d00326672c00a1d6cf0ed3be`.
Указанная NHL API связь проверена по официальному schedule endpoint за
`2023-11-19`; confirmation от владельца ожидается. До решения владельца второй
mapping не добавлять и итоговый real acceptance не объявлять.

## Проверки

- `uv run pytest -q tests/test_historical_odds.py tests/test_registry_snapshot.py tests/test_event_identity.py tests/test_odds_store.py tests/test_odds_backfill.py tests/test_odds_client.py` — **104 passed**, 6 сторонних warnings.
- `uv run ruff check sports_forecast/data/providers/odds/historical_coverage.py sports_forecast/data/providers/odds/historical_cli.py tests/test_historical_odds.py` — passed.
- `uv run ruff format --check sports_forecast/data/providers/odds/historical_coverage.py sports_forecast/data/providers/odds/historical_cli.py tests/test_historical_odds.py` — passed.
- `uv run python -m sports_forecast.data.providers.odds.historical_cli --help` и `... coverage --help` — passed; команда использует только локальные SQLite/cache/registry и не делает network calls.
- Реальный `import` двух cache files и `coverage` CLI выполнены на локальном registry package; результаты указаны выше. Исходный cache не изменён, raw responses/SQLite/evidence bundle в Git не добавлены.

## Остаточный gate и handoff

Синтетические сценарии и старые OddsStore/backfill/client/identity regression
зелёные. Для завершения TASK требуется подтверждение владельца mapping второго
матча и повторный real coverage CLI, где `no_line=1` стоит отдельно от
CAR–BUF `covered=1`. После этого обновить этот отчёт и TASK до `done`, затем
передать Product Owner для независимого review. PR не создавался, production
release не выполнялся.
