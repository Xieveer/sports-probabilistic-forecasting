# TASK-027-2 — Покрытие истории и итоговая проверка Pinnacle

> **Статус:** done, передан на финальный независимый review
> **Ветка:** `initiative/epic-027-historical-odds`
> **Требование:** [REQ-027](../../product/requirements/REQ-027-historical-odds.md)
> **Решение:** [ADR-031](../../architecture/adr/ADR-031-historical-odds.md)
> **Задача:** [TASK-027-2](../../backlog/tasks/TASK-027-2-historical-odds-coverage.md)

## Реализация

Добавлен offline отчёт по expected NHL universe из pinned `ir1` registry и UTC
kickoff окну `[from, to)`. Новый локальный CLI `historical_cli coverage`
принимает общий provider-as-of момент `T`, выводит числитель/знаменатель,
fingerprint импортированного набора, ошибки/диагностики импорта, timestamp
conflicts, unknown/late retrieval, unmapped source event count и распределение
уникальных source IDs по resolver причинам `missing`, `mismatch`, `ambiguous`,
`conflict`.
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
- Reviewer P2 red: тесты ожидали поля resolver-reason aggregation и упали из-за его отсутствия; также зафиксировали, что реальный pinned report считает 13 unmapped IDs без breakdown.
- Reviewer P2 green: добавлено `unmapped_source_event_reasons`; unresolved source IDs классифицируются из `EventResolution.status` и `.reason`, один стабильный reason bucket выбирается на source ID. Focused regression подтверждает missing/mismatch раздельно.

## Реальные данные и acceptance

Owner-confirmed mapping из TASK-027-1: NHL API game `2023020180` ↔ The Odds API
event `b42367c52f8c596d01199dd31258cc62`, CAR–BUF, kickoff
`2023-11-08T00:00:00Z`, pinned snapshot
`ir1:ef9cc3818aeb73dcbe68dbebd1bd912ea30b68a30ea898167676f4cd8dcce210`.
Импорт двух локальных файлов дал 24 source event rows и 21 Pinnacle observation,
0 diagnostics. Coverage для окна `[2023-11-07T00:00:00Z,
2023-11-09T00:00:00Z)` к `2023-11-07T11:55:43Z`: **1/1 covered**, 0 `no_line`,
0 `no_snapshot`, 0 `mapping_error`, 2 файла, 0 conflicts, 2 receipts с unknown
retrieval, 13 unmapped source event IDs: 12 `mismatch`, 1 `missing`.
Пересчитанный fingerprint набора:
`sha256:8f4673bbf009d8a1e30e05cdfe577d0d2e3c20d0377dbb99e6105e5ac8715c09`.

Повторный import тех же файлов вставил 0 observations. Реальные query для
`2023-11-06T23:00:00Z`, `2023-11-07T00:00:00Z` и
`2023-11-07T11:55:43Z` вернули null, ранний observation
`ho1:25b7a255202c6bd699f59784ce07e5a4c48a4a47e3743af06e660d22e9ca601f`
и поздний `ho1:b980b881373b6756af38f54e6a09952ba4348467eccc445a4cf71e302a3b5fe0`.
Retrieval остался unknown, `locally_known_at_t=false`. SHA-256 обоих исходных
cache файлов совпали с зафиксированным в TASK-027-1 evidence.

Владелец подтвердил mapping для no-line контроля: NHL API game `2023020271` ↔
The Odds API event `c4e420f552d6ffa6f1a1e5dec5a0db3e`, Anaheim Ducks — St Louis
Blues, kickoff `2023-11-20T01:00:00Z`. В изолированный локальный registry вне
Git добавлено событие с `ANA`/`STL` participant entities и confirmed source
designation по этому решению. Полученный pinned snapshot:
`ir1:7f6ee9a8004c00dde23e42017de491f44dbccf6150a75ec9ca01d65773e7c9c9`.

Для полного acceptance импортированы четыре source snapshots без
Pinnacle/`h2h` для ANA–STL и оба исходных CAR–BUF snapshots. SHA-256 всех шести
файлов (время envelope, полный source ID и локальная cache path соответствуют
записям ниже; cache paths опущены для краткости):

| Event ID | Envelope `timestamp` | SHA-256 исходного файла | Pinnacle/h2h |
| --- | --- | --- | --- |
| `b42367c52f8c596d01199dd31258cc62` | `2023-11-06T23:25:43Z` | `64830ea162f6d8d0cf451a7b6ee4e488affd20019440778a81858a66c88f08df` | Есть |
| `b42367c52f8c596d01199dd31258cc62` | `2023-11-07T11:55:40Z` | `09861cc7ef3936dc216cfd2a3d3d3e2398a4de52da2bedd303e871b5570593cf` | Есть |
| `c4e420f552d6ffa6f1a1e5dec5a0db3e` | `2023-11-18T11:55:41Z` | `c6485f0b2712660322e08800bb5766647743c171e10b8ab660b06d139bf0223e` | Нет |
| `c4e420f552d6ffa6f1a1e5dec5a0db3e` | `2023-11-18T15:40:42Z` | `7e2697acbd8f78c9e75e0080a399a740a2bf9e0e8624a5ec2461206ed65d9819` | Нет |
| `c4e420f552d6ffa6f1a1e5dec5a0db3e` | `2023-11-19T11:55:40Z` | `13ee307326e9f3ba7a713eb0acac6b5acee9a5d0aff9eca8240f53cb56a8fa49` | Нет |
| `c4e420f552d6ffa6f1a1e5dec5a0db3e` | `2023-11-19T12:40:41Z` | `f44d735492892dc7f87b078c84f81b30e85044c7d00326672c00a1d6cf0ed3be` | Нет |

Coverage использовал `[from=2023-11-07T00:00:00Z,
to=2023-11-21T00:00:00Z)` и `T=2023-11-19T13:00:00Z`. Результат: **2 expected,
1 covered (CAR–BUF), 1 `no_line` (ANA–STL, subreason `no_pinnacle`), 0
`no_snapshot`, 0 `mapping_error`**; 6 imported files, 53 observations inserted
from 72 source event rows, 0 diagnostics/conflicts, 6 unknown retrieval, 0 late
retrieval, 32 unmapped IDs (30
`mismatch`, 2 `missing`). Imported-set fingerprint:
`sha256:20e0ff034f6a5c095d8910df1979acce11bada3ae8202534d70f88743956a962`.
Повторный импорт всех шести файлов вставил 0 observations на каждом файле.
Повторный sha256sum всех файлов совпал с первоначальным; cache не изменялся.
Локальный registry snapshot и SQLite хранятся в
`/tmp/sports-forecast-epic-027-evidence-final2`, в Git они не добавлены.

## Проверки

- `uv run pytest -q tests/test_historical_odds.py tests/test_registry_snapshot.py tests/test_event_identity.py tests/test_odds_store.py tests/test_odds_backfill.py tests/test_odds_client.py` — **104 passed**, 6 сторонних warnings.
- `uv run ruff check sports_forecast/data/providers/odds/historical_coverage.py sports_forecast/data/providers/odds/historical_cli.py tests/test_historical_odds.py` — passed.
- `uv run ruff format --check sports_forecast/data/providers/odds/historical_coverage.py sports_forecast/data/providers/odds/historical_cli.py tests/test_historical_odds.py` — passed.
- `uv run pytest -q tests/test_historical_odds.py::test_coverage_zero_line_reports_no_snapshot_and_unmapped_source_event tests/test_historical_odds.py::test_coverage_separates_invalid_mapping_from_missing_snapshot` — **2 passed** после исправления P2; до исправления обе проверки завершились ожидаемо красным.
- `uv run python -m sports_forecast.data.providers.odds.historical_cli --help` и `uv run python -m sports_forecast.data.providers.odds.historical_cli coverage --help` — passed; CLI не обращается к сети и не требует API key.
- `uv run python -m sports_forecast.data.providers.odds.historical_cli coverage --database /tmp/sports-forecast-epic-027-evidence-final2/task2-final-acceptance.sqlite3 --registry-snapshot /tmp/sports-forecast-epic-027-evidence-final2/registry/snapshots/7f6ee9a8004c00dde23e42017de491f44dbccf6150a75ec9ca01d65773e7c9c9 --from 2023-11-07T00:00:00Z --to 2023-11-21T00:00:00Z --at 2023-11-19T13:00:00Z` — 2/2 categorized; `covered=1`, `no_line=1`.
- Выполнены следующие offline import команды; их точный повтор дал `observations_inserted=0` для каждого файла:

  ```bash
  uv run python -m sports_forecast.data.providers.odds.historical_cli import --source '/home/xieveer/Документы/PyCharmProject/SportsProbabilisticForecasting/data/cache/the_odds_api/_historical_sports_icehockey_nhl_odds_h2h,totals_eu_2023-11-06T23:30:00Z.json' --database /tmp/sports-forecast-epic-027-evidence-final2/task2-final-acceptance.sqlite3
  uv run python -m sports_forecast.data.providers.odds.historical_cli import --source '/home/xieveer/Документы/PyCharmProject/SportsProbabilisticForecasting/data/cache/the_odds_api/_historical_sports_icehockey_nhl_odds_h2h,totals_eu_2023-11-07T12:00:00Z.json' --database /tmp/sports-forecast-epic-027-evidence-final2/task2-final-acceptance.sqlite3
  uv run python -m sports_forecast.data.providers.odds.historical_cli import --source '/home/xieveer/Документы/PyCharmProject/SportsProbabilisticForecasting/data/cache/the_odds_api/_historical_sports_icehockey_nhl_odds_h2h,totals_eu_2023-11-18T12:00:00Z.json' --database /tmp/sports-forecast-epic-027-evidence-final2/task2-final-acceptance.sqlite3
  uv run python -m sports_forecast.data.providers.odds.historical_cli import --source '/home/xieveer/Документы/PyCharmProject/SportsProbabilisticForecasting/data/cache/the_odds_api/_historical_sports_icehockey_nhl_odds_h2h,totals_eu_2023-11-18T15:45:00Z.json' --database /tmp/sports-forecast-epic-027-evidence-final2/task2-final-acceptance.sqlite3
  uv run python -m sports_forecast.data.providers.odds.historical_cli import --source '/home/xieveer/Документы/PyCharmProject/SportsProbabilisticForecasting/data/cache/the_odds_api/_historical_sports_icehockey_nhl_odds_h2h,totals_eu_2023-11-19T12:00:00Z.json' --database /tmp/sports-forecast-epic-027-evidence-final2/task2-final-acceptance.sqlite3
  uv run python -m sports_forecast.data.providers.odds.historical_cli import --source '/home/xieveer/Документы/PyCharmProject/SportsProbabilisticForecasting/data/cache/the_odds_api/_historical_sports_icehockey_nhl_odds_h2h,totals_eu_2023-11-19T12:45:00Z.json' --database /tmp/sports-forecast-epic-027-evidence-final2/task2-final-acceptance.sqlite3
  ```

- CLI `query` на event `618af5aa-9786-485e-bfe5-6c61b61932eb` к `2023-11-06T23:00:00Z`, `2023-11-07T00:00:00Z`, `2023-11-07T11:55:43Z` прошли: null, ранний observation, поздний observation соответственно. Для воспроизводимости команда имеет вид:

  ```bash
  uv run python -m sports_forecast.data.providers.odds.historical_cli query --database /tmp/sports-forecast-epic-027-evidence-final2/task2-final-acceptance.sqlite3 --registry-snapshot /tmp/sports-forecast-epic-027-evidence-final2/registry/snapshots/7f6ee9a8004c00dde23e42017de491f44dbccf6150a75ec9ca01d65773e7c9c9 --event-id 618af5aa-9786-485e-bfe5-6c61b61932eb --at 2023-11-06T23:00:00Z
  uv run python -m sports_forecast.data.providers.odds.historical_cli query --database /tmp/sports-forecast-epic-027-evidence-final2/task2-final-acceptance.sqlite3 --registry-snapshot /tmp/sports-forecast-epic-027-evidence-final2/registry/snapshots/7f6ee9a8004c00dde23e42017de491f44dbccf6150a75ec9ca01d65773e7c9c9 --event-id 618af5aa-9786-485e-bfe5-6c61b61932eb --at 2023-11-07T00:00:00Z
  uv run python -m sports_forecast.data.providers.odds.historical_cli query --database /tmp/sports-forecast-epic-027-evidence-final2/task2-final-acceptance.sqlite3 --registry-snapshot /tmp/sports-forecast-epic-027-evidence-final2/registry/snapshots/7f6ee9a8004c00dde23e42017de491f44dbccf6150a75ec9ca01d65773e7c9c9 --event-id 618af5aa-9786-485e-bfe5-6c61b61932eb --at 2023-11-07T11:55:43Z
  ```
- Исходный cache не изменён; raw responses/SQLite/evidence bundle в Git не добавлены.

## Остаточный gate и handoff

Синтетические сценарии, real acceptance и старые
OddsStore/backfill/client/identity regression зелёные. TASK передан Product
Owner для финального независимого review. PR не создавался, production release
не выполнялся.
