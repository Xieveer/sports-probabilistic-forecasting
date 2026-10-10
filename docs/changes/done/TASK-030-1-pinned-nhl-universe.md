# Выполнение TASK-030-1 — Закреплённый NHL universe

## Результат

Добавлен локальный offline CLI `sports_forecast.research.nhl_universe`. Он
закрепляет NHL model universe как проверенный `ir1` snapshot, выводит manifest
с fingerprints и диагностикой, а также сохраняет однозначно разрешённые
The Odds API event designations в отдельной research registry до экспорта.
Confirmation основан на точном UTC kickoff, подтверждённых NHL/team UUID и
batch reverse uniqueness; конфликтные и неоднозначные refs автоматически не
подтверждаются. Матчи без линии остаются в universe.

Universe ограничен `regular` и `playoffs`, как в существующем NHL preprocessing.
Остальные game types отражены до odds coverage и не считаются betting
исключениями. Код читает только `id`, `nhl_id`, `datetime`, `home_team`,
`away_team`, `game_type`; исходы матчей в manifest не включаются.

## Проверки

Red: новый focused test до реализации завершился ожидаемым
`ModuleNotFoundError` для отсутствующего research модуля.

После реализации выполнено:

```text
uv run pytest -q tests/test_research_nhl_universe.py tests/test_event_identity.py tests/test_registry_snapshot.py tests/test_historical_odds.py
59 passed, 1 warning

uv run ruff check sports_forecast/research/nhl_universe.py tests/test_research_nhl_universe.py
All checks passed

git diff --check
passed
```

На дополнительном review найден сценарий, где CLI мог получить один файл как
`registry_database` и `historical_database`: registry initialization меняла бы
источник до основного path guard. Red regression воспроизвёл отсутствие отказа.
Теперь CLI и прямой API отклоняют одинаковые файлы, symlink и hardlink до
инициализации; тест сверяет исходные bytes до и после. Финальные проверки после
этой правки:

```text
uv run pytest -q tests/test_research_nhl_universe.py tests/test_event_identity.py tests/test_registry_snapshot.py tests/test_historical_odds.py
66 passed, 1 warning

uv run ruff check sports_forecast/research/nhl_universe.py tests/test_research_nhl_universe.py
All checks passed

git diff --check
passed
```

После исправлений real smoke повторно запущен на тех же локальных файлах и
research registry. Команда осталась той же, что приведена выше; завершилась
кодом 0 примерно за 40 секунд. Run ID, snapshot ID, fingerprints и все
счётчики совпали с исходным smoke: run
`13afa80adc3d80b91ee7463b8dfbb31f2e5b3a62c36c2b1e290f1c36cffdb5b5`, snapshot
`ir1:65ba2acd9aa49921f27912be924b272e4f0e9c2ebd63db165c3633bcce783498`,
historical fingerprint `sha256:0755bcc3f8453b75a9b2a7ebe5c912920683429c562614dd4b05e4ad4cc48a10`.

Реальный offline smoke выполнен на текущих локальных входах:

```bash
uv run python -m sports_forecast.research.nhl_universe \
  --matches ../../data/raw/nhl/matches.parquet \
  --historical-database /tmp/epic-030-nhl-history.sqlite3 \
  --registry-database /tmp/epic-030-nhl-universe-final/registry/master.sqlite3 \
  --team-seed conf/bookmaker/team_name_registry/nhl.yaml \
  --output /tmp/epic-030-nhl-universe-final \
  --start 2023-10-01T00:00:00Z \
  --end 2026-05-01T00:00:00Z
```

Импорт исторического кэша в SQLite перед smoke был идемпотентным: 1790 файлов,
19933 observations, 0 новых observations, 0 diagnostics. Smoke занял около 94
секунд, завершился кодом 0 и записал артефакты только в `/tmp`.

## Фактические счётчики smoke

- NHL raw rows в окне: 4450.
- Не входят в model universe по game type: 300 (259 `preseason`; ещё 41:
  `12` — 1, `19` — 6, `20` — 1, `4` — 3, `9` — 30).
- Expected NHL universe: 4150 (`regular` / `playoffs`); NHL mapping resolved:
  4150, unresolved: 0.
- Historical source-event resolutions: resolved 2788, unresolved 755,
  conflict 610, ambiguous 0. Это все импортированные historical source event
  IDs в окне, а не только Pinnacle h2h events. Соответствующие residual причины
  включают неподтверждённые home/away team designation, отсутствие точного
  совпадения и несовместимые факты под одним historical source ID.
- Snapshot: `ir1:65ba2acd9aa49921f27912be924b272e4f0e9c2ebd63db165c3633bcce783498`.
- Run: `13afa80adc3d80b91ee7463b8dfbb31f2e5b3a62c36c2b1e290f1c36cffdb5b5`.
- NHL parquet fingerprint:
  `sha256:b6eaed0092a8d7dad4d6fd070b0f71d64493003b4fc6d7c55095a01dd7bb8fb3`.
- Historical files fingerprint:
  `sha256:0755bcc3f8453b75a9b2a7ebe5c912920683429c562614dd4b05e4ad4cc48a10`.
- Полный manifest:
  `/tmp/epic-030-nhl-universe-final/runs/13afa80adc3d80b91ee7463b8dfbb31f2e5b3a62c36c2b1e290f1c36cffdb5b5/manifest.json`.

Предварительные 3294 точных совпадения считались для Pinnacle h2h среза и не
являются порогом приёмки. Они и приведённые выше resolution counts используют
разные denominators: smoke обрабатывает весь импортированный historical
source-event universe. TASK завершена; dataset и evaluator относятся к
следующим задачам. Независимый Reviewer принял код без P0–P2 findings после
финального запуска 66 адресных тестов; commit/PR на этом этапе не выполнены.

## Дополнительные исправления по результатам review

1. Уже закреплённый The Odds API source ID мог разрешиться по alias, даже если
   новый historical import задавал другой kickoff. Red test сначала показал
   `resolved=1` вместо ожидаемого `conflict=1`. Теперь перед designation
   сравниваются kickoff и точная project event relation; несовпадение даёт
   `pinned_source_kickoff_conflict`, confirmed list пуст, новая designation не
   записывается. Общий resolver не менялся.
2. CLI раньше создавал registry до проверки его расположения. Regression test
   моделировал прежний порядок и обнаружил созданный файл в `data/registry`.
   Теперь path guard вызывается до `EntityRegistry.initialize()` и запрещает
   project `data/registry/**` и `data/entity-registry*`; отдельные `/tmp` и
   worktree research outputs допустимы.
3. Historical fingerprint раньше не замечал импортированные файлы без event
   rows. Red regression с двумя разными пустыми cache imports дала одинаковый
   `run_id`. Теперь fingerprint строится по всем `historical_cache_files`;
   smoke SQLite содержит 1609 файлов, и fingerprint остался прежним:
   `sha256:0755bcc3f8453b75a9b2a7ebe5c912920683429c562614dd4b05e4ad4cc48a10`.
4. Research reader раньше вызывал общий historical reader, который выполняет
   schema initialization и мог писать в источник на невалидной БД. Red
   regression с partial SQLite зафиксировал изменение bytes при ошибке. Оба
   необходимых чтения теперь идут по SQLite URI `mode=ro`; тест подтверждает,
   что partial input остаётся побайтно неизменным.

5. Дополнительный review обнаружил совпадение файлов historical input и
   research registry через обычный путь, symlink или hardlink. Проверка до
   открытия registry отклоняет все три случая; red regression и финальный
   запуск 66 тестов указаны в разделе «Проверки».
