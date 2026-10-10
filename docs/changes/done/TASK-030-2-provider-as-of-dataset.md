# Выполнение TASK-030-2 — Provider-as-of Pinnacle dataset

## Результат

Добавлены пакетный read-only query `query_provider_as_of_many`, общая функция
взаимоисключающей классификации coverage и CLI
`sports_forecast.research.provider_dataset`. Он проверяет canonical `run_id`,
policy/window и fingerprints NHL parquet, team seed и historical imports.
Повторно прочитанные identity-only NHL rows сверяются с полным набором resolved
и timed unresolved diagnostics; untimed diagnostics не входят в expected count.
Также сверяются `ir1`, project-event UUID/kickoff и source links. Один
индексируемый batch по подтверждённым source IDs обслуживает
все event-specific моменты `T = kickoff − 15 минут`; нет полного сканирования
observations на каждый матч. Существующий scalar query и старый coverage CLI
сохраняют поведение.

Каждая строка содержит ожидаемый NHL event, `decision_at`, причину категории и
пригодную цену. Цена включает observation/receipt/source-file provenance,
`ho1`, `ir1`, обе стороны полного `winner_withOT` вектора, `observed_at`, age и
nullable `retrieved_at`. `retrieved_at=null` отражается как unknown. Snapshot
старше суток хранится только как `price_candidate` с категорией `stale_price`;
он не считается пригодной ценой. В набор не включаются исходы, признаки,
прогнозы и ставки.

Окно по умолчанию равно полному pinned NHL universe. Пара `--start/--end`
ограничивает его вложенным полуоткрытым окном; границы входят в resolved config
и влияют на dataset ID. Dataset ID зависит от canonical manifest/content,
включая source fingerprints, но не от абсолютных путей и времени запуска.

## Проверки

Red: первый focused test завершился ожидаемым `ModuleNotFoundError` до создания
нового модуля.

Green/regression:

```text
.venv/bin/pytest -q tests/test_research_provider_dataset.py tests/test_historical_odds.py tests/test_research_nhl_universe.py
37 passed, 1 warning

.venv/bin/ruff check sports_forecast/data/providers/odds/historical.py sports_forecast/data/providers/odds/historical_coverage.py sports_forecast/research/provider_dataset.py tests/test_historical_odds.py tests/test_research_provider_dataset.py
All checks passed
```

Synthetic coverage включает no-line, повторный запуск, conflicting latest
timestamp без fallback, stale classification, batch/scalar parity и побайтную
неизменность SQLite при batch query. Тамpered manifest с удалённым no-line
match и уменьшенным expected count отклоняется по сравнению с raw parquet.
Существующие historical coverage/query и NHL universe regressions также прошли.

После review P2 добавлены red/green регрессии: входной fixture с неизвестной
командой сначала падал на ошибочном требовании `len(nhl_events) ==
expected_events`. Теперь проверяется `resolved + timed diagnostics`, а
unresolved event сохраняется как `mapping_error` с source key, kickoff и
decision time. Отдельный tamper test удаляет resolved match и уменьшает
`expected_events`; генератор отклоняет manifest при сверке с raw parquet. Отдельно
отклоняются altered status resolved→unresolved, удалённый confirmed odds link и
tampered `run_id`. Fingerprint файла universe фиксирует точные
входные bytes, тогда как `run_id` проверяется по входным fingerprints/window/policy
и не считается хешем содержимого manifest.

Финальная P2-регрессия переносит resolved матч без odds link из `nhl_events` в
`nhl_diagnostics`, сохраняя source ID/kickoff и все counts. Теперь TASK2
независимо восстанавливает resolved/unresolved partition из raw parquet и pinned
`ir1`: учитывает уникальность source ID и пары kickoff/команды, temporal NHL
team designations, UUID участников и точный NHL source key. Manifest должен
совпасть с вычисленным partition как мультимножество; изменение списка или
подмена статуса не меняет классификацию и отклоняется.

## Offline smoke

Входы TASK-030-1 использованы без чтения результатов игр или ROI:

- universe run `13afa80adc3d80b91ee7463b8dfbb31f2e5b3a62c36c2b1e290f1c36cffdb5b5`;
- registry snapshot `ir1:65ba2acd9aa49921f27912be924b272e4f0e9c2ebd63db165c3633bcce783498`;
- historical input fingerprint `sha256:0755bcc3f8453b75a9b2a7ebe5c912920683429c562614dd4b05e4ad4cc48a10`.

Полное окно `[2023-10-01, 2026-05-01)`:

- expected events: 4150;
- пригодная Pinnacle линия: 2785;
- подтверждённое source mapping отсутствует: 1362 (`mapping_error`);
- Pinnacle h2h отсутствует: 1 (`no_line`);
- snapshot просрочен более суток: 2 (`stale_price`);
- `no_snapshot` и timestamp conflict: 0;
- unknown retrieval: 2787 observations, late retrieval: 0.
- dataset ID: `pd1:53edba6acfdeeb1e1ccb20a024f8eeecc88c9dd792f7c90ce1cb580bfa5de64e`;
- events SHA-256: `sha256:1564a595c43fbd6314a973564f88e33dd5d3c804126fed3567ecce8a96b90e97`.

Закрытое тестовое окно `[2024-10-01, 2026-05-01)`:

- expected events: 2751;
- пригодная Pinnacle линия: 1568;
- подтверждённое source mapping отсутствует: 1181 (`mapping_error`);
- просроченный snapshot: 2 (`stale_price`);
- `no_line`, `no_snapshot` и timestamp conflict: 0;
- unknown retrieval: 1570 observations, late retrieval: 0;
- dataset ID: `pd1:4fd4501440a3054b69fdce5f2dce8c70c109c064132f023b2c5bf7725f37f5f6`;
- events SHA-256: `sha256:1a3f731655517f120f6e796d73ad3bac9ca8dc2b73eefb999024e32e5c1b2f11`.

Пример полного окна:

```bash
.venv/bin/python -m sports_forecast.research.provider_dataset \
  --universe-manifest /tmp/epic-030-nhl-universe-final/runs/13afa80adc3d80b91ee7463b8dfbb31f2e5b3a62c36c2b1e290f1c36cffdb5b5/manifest.json \
  --historical-database /tmp/epic-030-nhl-history.sqlite3 \
  --matches ../../data/raw/nhl/matches.parquet \
  --team-seed conf/bookmaker/team_name_registry/nhl.yaml \
  --snapshot /tmp/epic-030-nhl-universe-final/snapshots/65ba2acd9aa49921f27912be924b272e4f0e9c2ebd63db165c3633bcce783498 \
  --output /tmp/epic-030-provider-dataset
```

Команда для locked test:

```bash
.venv/bin/python -m sports_forecast.research.provider_dataset \
  --universe-manifest /tmp/epic-030-nhl-universe-final/runs/13afa80adc3d80b91ee7463b8dfbb31f2e5b3a62c36c2b1e290f1c36cffdb5b5/manifest.json \
  --historical-database /tmp/epic-030-nhl-history.sqlite3 \
  --matches ../../data/raw/nhl/matches.parquet \
  --team-seed conf/bookmaker/team_name_registry/nhl.yaml \
  --snapshot /tmp/epic-030-nhl-universe-final/snapshots/65ba2acd9aa49921f27912be924b272e4f0e9c2ebd63db165c3633bcce783498 \
  --output /tmp/epic-030-provider-dataset \
  --start 2024-10-01T00:00:00Z \
  --end 2026-05-01T00:00:00Z
```

Обе команды повторены: dataset ID, event SHA-256 и manifest совпали.
Полный manifest лежит в `/tmp/epic-030-provider-dataset/53edba6acfdeeb1e1ccb20a024f8eeecc88c9dd792f7c90ce1cb580bfa5de64e/manifest.json`, locked-test manifest — в `/tmp/epic-030-provider-dataset/4fd4501440a3054b69fdce5f2dce8c70c109c064132f023b2c5bf7725f37f5f6/manifest.json`.

Historical SQLite SHA-256 до и после smoke одинаков: `b96947d292f610b35300e8d8ab08c8a1a6faefb833051d610d3a244f687afa75`.
После partition проверки повторный полный smoke занял 34.77 секунды, locked test — 35.23 секунды; Python показал внешнее предупреждение
Pandera о будущем импорте pandas API, оно не влияло на результат.

## Интерпретация и ограничения

`mapping_error` означает, что для события полного NHL universe в закреплённом
snapshot нет подтверждённого The Odds API event mapping. Эти 1181 события
locked-test не считаются событиями с пригодной линией, ставочным знаменателем
или доказательством отсутствия Pinnacle рынка; source link требует дальнейшей
проверки/закрепления. Unknown retrieval у исторических receipts не доказывает,
что цена была доступна системе в момент T. Данный task не подтверждает
пригодность признаков, исходов, прогнозов или финансовый edge.

Ограничение целостности: historical fingerprint привязан к imported file hashes
из SQLite ledger и не доказывает побайтную неизменность observation rows при
ручной мутации SQLite. Это общий контракт EPIC-027; TASK2 использует неизменяемый
локальный import и read-only query, но не вводит отдельный signer/ledger format.

После последней P2-регрессии профильные тесты: 37 passed, 1 Pandera warning;
Ruff и `git diff --check` прошли. Повторный offline smoke подтвердил прежние
dataset IDs, event SHA-256 и счётчики, SQLite SHA-256 остался прежним.
Ожидается финальное независимое подтверждение Reviewer.
Commit/PR не создавались.
