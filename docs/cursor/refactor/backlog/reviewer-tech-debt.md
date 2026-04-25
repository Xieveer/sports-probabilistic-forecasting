# Технический долг и отложенные улучшения (после ревью)

Накопительный журнал: после **успешного** ревью Reviewer переносит сюда ограничения принятого решения, компромиссы и идеи будущих доработок, которые **не** требуют Rework и не блокируют закрытие задачи.

**Не дублировать сюда:** пункты, по которым код должен быть исправлен до приёмки — они остаются в секции **Rework** и в цикле Worker → Reviewer.

**Связь с задачами:** для задач из бэклога указывайте идентификатор (`R5`, `R13.2`, …) и при наличии путь к записи в `done_task/`.

---

## Формат записи

Каждая запись — блок с датой и контекстом:

```markdown
### YYYY-MM-DD — <краткий заголовок / ID задачи>

- **Задача:** `backlog/Rx.md` → `done_task/Rx.md` (или «вне бэклога», если одноразовая работа)
- **Ограничения и компромиссы:** …
- **Возможные улучшения / техдолг:** …
```

При отсутствии отложенных пунктов по итогам ревью новую секцию не добавлять (достаточно не писать «пустые» заголовки).

---

## Записи

<!-- Новые блоки `### YYYY-MM-DD` добавляйте в конец этого раздела (хронология от старых к новым сверху вниз). -->

### 2026-04-04 — R14 Source-адаптеры / SourceProvider

- **Задача:** `backlog/R14.md` → `done_task/R14.md`
- **Ограничения и компромиссы:**
  - `ProviderRegistry.create()` содержит жёстко прописанный if/elif вместо self-registration через декоратор — добавление провайдера требует правки реестра вручную (задокументировано в инструкции).
  - `HttpApiSourceProvider` — PoC: нет поддержки аутентификации, пагинации, потоковой загрузки, rate-limiting. Сохраняет весь ответ в память (`response.content`).
  - `FileSourceProvider` не принимает альтернативное имя файла (хардкод `source.csv`). Если провайдер нужен для Parquet, потребует расширения.
  - `ingest.process_tournament` загружает `paths_cfg` при `None`, что добавляет лишний Hydra I/O при batch-прогоне если уже передан.
- **Возможные улучшения / техдолг:**
  - Заменить if/elif в `ProviderRegistry.create()` на `register`-декоратор или явный `_registry` dict с авторегистрацией.
  - Добавить streaming download в `HttpApiSourceProvider` (`stream=True`, write chunk by chunk).
  - Поддержка аутентификации (Bearer token, Basic) через секреты (env vars / Vault).
  - Расширить `FileSourceProvider`: принимать имя файла (не только `source.csv`) и тип (CSV/Parquet).
  - Интеграционный тест `process_tournament` с мок-провайдером (на уровне ingest, не только unit).

### 2026-04-05 — R17 NHL Web API провайдер

- **Задача:** `backlog/R17.md` → `done_task/R17.md`
- **Ограничения и компромиссы:**
  - Этап `features` в `dvc.yaml` по умолчанию не включает `tournament=nhl` в multirun (иначе `dvc repro` может ломаться без interim-данных); в ingest добавлен комментарий, расширение multirun — вручную при готовых данных.
  - Травмы в `source.csv`: поле `injured` пустое; отдельного стабильного injury endpoint в разобранном Web API нет.
  - Standings для «до игры»: запрос `standings/{gameDate − 1}`; внутри одного `gameDate` порядок матчей и учёт ранних игр дня не моделируется (нет среза по `startTimeUTC`).
  - MT-метрики из PBP (`sog_mt`, хиты, FOW, …) остаются событийными; редкий дубль «goal»+«shot-on-goal» в фиде может завысить SOG.
  - Строки предстоящих матчей без ростеров и boxscore; полная таблица при перевыгрузке опирается на слияние с предыдущим `source.csv` и чекпоинт только для завершённых игр.
  - Тесты R17.9 используют компактные инлайновые JSON-фрагменты, а не отдельные файлы `tests/fixtures/nhl/*.json`.
  - Полная историческая загрузка остаётся долгой (десятки тысяч запросов); опора на `max_games` (лимит новых обогащений OFF), `checkpoint_file`, узкий `date_from`/`date_to`.
- **Возможные улучшения / техдолг:**
  - Вынести крупные ответы API в файловые фикстуры + тесты на OT/SO/пустой boxscore.
  - Источник травм и букмекерских коэффициентов вне NHL Web API; слияние с `nhl_id` / временем.
  - Опциональный fallback `club-schedule-season` при дырках в schedule для архива.
  - Точный pre-game standings по времени начала (симуляция или иной API).

### 2026-04-05 — NHL assembler: промежуточная запись `source.csv` без обрезки

- **Задача:** вне бэклога — восстановление корректности частичного прогона ingest (flush + финал через `_snapshot_csv_rows`).
- **Ограничения и компромиссы:**
  - Снимок = для каждого `stub` из расписания: строка из текущего прохода, иначе из прошлого `source.csv`; если в прошлом файле не было строки для id (потерянный/первый прогон), до обработки матча в этом запуске в снимке «дыра» нет — полная длина достигается только когда есть данные в `prev` или после обхода stub.
  - При коллизии дублей `id` в `rows_from_current_pass` побеждает последняя запись в dict-сборке (нетипично для пайплайна).
  - Запись по-прежнему не атомарная: обрыв процесса во время `to_csv` может оставить повреждённый файл на диске.
- **Возможные улучшения / техдолг:**
  - Писать во временный файл и `rename` для атомарной подмены.
  - Опционально: ротация бэкапа `source.csv` перед полной перезаписью (конфигом).

### 2026-04-12 — R18 lp_eu_a18: Optuna reg, feature selection, fs_fit

- **Задача:** `backlog/R18.md` → `done_task/R18.md`
- **Ограничения и компромиссы:**
  - Переобучение после отбора использует те же гиперпараметры, что и полный прогон (Optuna не перезапускается на подмножестве фичей).
  - `PermutationImportanceRanker` по-прежнему на полной матрице train без сабсэмпла — дорого на больших `n` и многих фичах.
  - Каталог `optuna/` в `.gitignore`: локальные studies не версионируются; воспроизводимость — через MLflow params / повторный sweep.
- **Возможные улучшения / техдолг:**
  - Опциональный Optuna-pass только на колонках после `apply_selected_to_fit`.
  - Сабсэмпл строк для permutation importance или лимит фичей в конфиге.
  - Единый CLI-скрипт «экспорт лучших params из MLflow → hydra overrides».

---

### 2026-04-25 — R20.1: OddsStore (Parquet-хранилище линий Pinnacle)

- **Задача:** `backlog/R20.md` (подзадача R20.1, отмечена как выполненная)
- **Ограничения и компромиссы:**
  - Атомарность гарантирована только для операции записи (`to_parquet` + `rename`); полный цикл load–merge–save не является атомарным — при одновременном вызове `upsert_odds_store_file` из двух процессов возможен race condition на фазе load (последний writer перезапишет данные первого). Для текущего однопроцессного pipeline это некритично.
  - Паттерн `.gitignore` `data/source/*/odds/` технически избыточен, поскольку `/data/source` уже покрывает весь каталог. Оставлен как явный self-documenting комментарий для будущих контрибьюторов.
  - Нет Pandera-валидации типов/диапазонов odds-колонок на входе в `save`/`upsert` — отложено до R20.6.
- **Возможные улучшения / техдолг:**
  - Добавить межпроцессный file-lock (например `filelock`) вокруг `upsert_odds_store_file`, если в будущем refresh и backfill смогут запускаться параллельно.
  - Опциональная Pandera-валидация на входе в `upsert_odds_store` (диапазон odds 1.01–100.0, nullable float) — R20.6.
  - Рассмотреть партиционирование parquet по `game_date` (year/month) при объёме > 100k строк для ускорения point-lookup.

---

### 2026-04-25 — R20.9: TeamNameRegistry + unmatched report

- **Задача:** `backlog/R20.md` (подзадача R20.9, отмечена как выполненная)
- **Ограничения и компромиссы:**
  - `nhl.yaml` — реестр пустой (обе секции `{}`): алиасы появятся только после первого production backfill, когда `unmatched_teams.csv` покажет несовпадения. До тех пор `_team_key` всегда возвращает `normalize_team_key` — функционально корректно, но сопоставление NHL ↔ Odds API по-прежнему зависит от единообразия нормализации в двух источниках.
  - `write_unmatched_odds_teams_report` итерирует через `iterrows()` (O(n)) — для DataFrame ~10k строк незначительно, но при большом историческом backfill лучше векторизованный подход.
  - Сопутствующие изменения в `assembler.py` (`_merge_full_source_snapshot`) и `bot/__main__.py` / `backfill.py` (`load_dotenv`) выходят за формальный скоп R20.9, однако не вносят регрессий; добавление `python-dotenv` обосновано production-сценарием.
- **Возможные улучшения / техдолг:**
  - После первого backfill NHL: заполнить `nhl.yaml` реальными алиасами из `unmatched_teams.csv`; добавить CI-тест, проверяющий, что каждый canonical в реестре совпадает с одним из ключей в `source.csv`.
  - Заменить `iterrows()` в `write_unmatched_odds_teams_report` на set-based vectorized diff между `odds_df` и `source_match_keys`.
  - Добавить типизированный `TypeAlias` для `MatchKey = tuple[str, str, str]` для ясности сигнатур.
  - Рассмотреть автогенерацию скелета `nhl.yaml` командой CLI (из `unmatched_teams.csv` → YAML-шаблон с пустыми canonical для заполнения вручную).

### 2026-04-18 — R19: NHL production + Odds API + Telegram-бот

- **Задача:** `backlog/R19.md` → `done_task/R19.md`
- **Ограничения и компромиссы:**
  - R19.11 (training sweep) и R19.12 (materialize + API verify) — операционные прогоны, не реализованы в коде; инфраструктура полностью готова (`make train`, `make materialize`).
  - Stretch-цели R19.17–R19.20 (travel-фичи, motivation/clinch, injury report, оценка vs Pinnacle) отложены как отдельные задачи.
  - `AllowedUsersMiddleware` регистрируется отдельно на `dp.message` и `dp.callback_query`; другие типы событий (inline query, poll и т.д.) не проверяются по whitelist (пропускаются) — нет хендлеров для них, поэтому не блокирующий пробел.
  - `NhlRosterFeatureGenerator`: парсинг JSON-поля roster — если поле отсутствует или пустое, генератор gracefully возвращает NaN по всем roster-фичам.
  - Для EWM-зависимых генераторов (standings form) инкрементальный refresh всё равно пересчитывает весь history от первого матча в `interim` (stateful EWM — отдельный эпик).
  - pandas `df.at[i, col]` возвращает широкий union-тип; использованы `# type: ignore[arg-type/assignment/misc]` в standings/schedule генераторах — компромисс между строгостью типов и читаемостью кода.
- **Возможные улучшения / техдолг:**
  - Реализовать R19.11–R19.12: прогнать NHL baseline training sweep, promote, materialize, верифицировать API.
  - Webhook-режим бота вместо polling (R19.16 stretch); polling достаточен для MVP.
  - Stateful EWM для form-генераторов (избегать пересчёта всей истории при инкрементальном refresh).
  - `AllowedUsersMiddleware` расширить на `InlineQuery` / `Poll` если добавятся соответствующие хендлеры.
  - Автоматическое определение `BOT_TOURNAMENTS` из реестра promoted-моделей вместо env-var / хардкода по умолчанию.
  - Интеграционный тест для бота (mock FastAPI + aiogram test client).
  - R19.17–R19.20: travel-фичи (справочник арен), motivation/clinch context, injury report, оценка модели vs Pinnacle closing на holdout.

---

### 2026-04-25 — R20.3: incremental odds refresh + checkpoint/resume

- **Задача:** `backlog/R20.md` (подзадача R20.3) → `done_task/R20.3.md`
- **Ограничения и компромиссы:**
  - `quota_hit` жёстко захардкожен в `False`: `run_backfill` не возвращает флаг исчерпания квоты; поле зарезервировано для интеграции с R20.6. Оператор не узнает о частичной загрузке из поля результата до реализации R20.6.
  - При краше во время `backfill_call` следующий запуск повторяет весь сегмент целиком (с `seg.date_from`), а не с точки фактического сбоя. Безопасно из-за идемпотентного upsert, но при `max_days_per_refresh=30` это лишняя нагрузка на API-квоту.
  - `build_incremental_need_range`: если `state.last_successful_date` значительно старше `max_game_date`, `need_from` смещается ещё левее (консервативное перекрытие). При сильно рассинхронизированном state это может создавать широкое окно без реальной необходимости.
  - Тест `test_run_odds_refresh_mocked_backfill` проверяет assert на конкретную дату (`date_from == 2025-12-17`); если алгоритм расчёта изменится, тест сломается без явного описания намерения в assert-сообщении.
- **Возможные улучшения / техдолг:**
  - Интегрировать `quota_hit` через возврат из `run_backfill` или отдельный callback при реализации R20.6 (Pandera + observability).
  - Рассмотреть более гранулярный checkpoint: сохранять `last_successful_date` при обработке каждого дня внутри сегмента (требует изменения API `run_backfill` — отдельная задача).
  - Добавить тест для граничного случая, когда `state.last_successful_date` существенно отстаёт от `max_game_date` (проверить, что `need_from` не уходит за пределы сезона).
  - R20.4 (интеграция в `source_refresh.py`) должна использовать `run_odds_refresh` напрямую; убедиться, что lock-контур source_refresh охватывает и odds-шаг.

---

### 2026-04-25 — R20.2: season-aware backfill CLI + quota budget

- **Задача:** `backlog/R20.md` (подзадача R20.2) → `done_task/R20.2.md`
- **Ограничения и компромиссы:**
  - `run_backfill` переведён на keyword-only API — это ломает вызов с позиционными аргументами; внутри проекта других вызывающих нет, но при расширении к R20.3/R20.4 нужно иметь в виду.
  - `_read_quota_budget` использует `book_root.get(...)` вместо `OmegaConf.select(...)` — смешение API; работает корректно, но нарушает единообразие с остальным кодом `backfill.py`.
  - `assert date_from is not None and date_to is not None` (строка 335) защищает после валидации ValueError, но `assert` отключается при `-O`; лучше явный `if/raise`.
  - В режиме `--from/--to` факт достижения quota stop логируется только на уровне `warning` внутри `_backfill_date_range`; в `run_backfill` дополнительный лог для range-case отсутствует — для оператора может быть неочевидно.
  - `_backfill_date_range` — приватная функция, но тестируется напрямую в `test_backfill_stops_on_quota`; если внутренний контракт изменится, тест сломается.
- **Возможные улучшения / техдолг:**
  - Заменить `book_root.get(...)` на `OmegaConf.select(book_root, "quota_budget_per_run")` в `_read_quota_budget` для единообразия.
  - Добавить `if _hit_quota: logger.warning(...)` в ветке range-mode `run_backfill`, чтобы оператор явно видел факт частичной загрузки.
  - Добавить тест для `--store` без явного пути (default path через `default_odds_store_path`), чтобы покрыть ветку `args.store == ""` в `main`.
  - Заменить `assert` на `if date_from is None or date_to is None: raise AssertionError(...)` или добавить `# noqa: S101` с комментарием о том, что это second-guard после ValueError.

### 2026-04-25 — R20.5/R20.6/R20.7 Конфиг + валидация + наблюдаемость + тесты

- **Задача:** `backlog/R20.md` (подзадачи R20.5/6/7 → `done_task/R20.5.md`, `done_task/R20.6.md`, `done_task/R20.7.md`)
- **Ограничения и компромиссы:**
  - `match_rate_vs_source_pct` в `_log_source_odds_metrics` — это синоним `odds_coverage_pct` (доля строк source с непустым `pinnacle_home_close`). Настоящий match rate (matched events / total events, пришедших от API) требует сохранения счётчика ответа API на этапе backfill и передачи его в метрики merge. Сейчас оба числа совпадают; для промышленной наблюдаемости желательно разделить.
  - `validate_pinnacle_odds_float_columns` бросает `RuntimeError` (оборачивает `SchemaError/SchemaErrors`). При нарушении диапазона весь backfill/refresh прерывается. Это корректное fail-fast поведение, но для лёгких данных (единичные выбросы из-за парсинга) может быть избыточным. Альтернатива — `warn_only`-режим с log.warning и продолжением.
  - `_odds_runtime_from_source` читает весь `conf/source/{source}.yaml` при каждом вызове `run_odds_refresh`; при частых вызовах в тестах или Airflow это несущественно, но кеширование было бы чище.
  - Фикстура `pinnacle_odds.parquet` создаётся через `store_mod.save_odds_store()` в `tmp_path` — нет статического файла как артефакта для регрессионного тестирования формата parquet.
- **Возможные улучшения / техдолг:**
  - Разделить `match_rate` и `coverage`: `match_rate = n_matched / n_api_events` (требует `BackfillRunResult.n_fetched_events`), `coverage = non_null_close / n_source_rows`.
  - Добавить `warn_only: bool` параметр в `validate_pinnacle_odds_float_columns` для мягкого режима при наличии outlier-данных.
  - Тест для `_log_source_odds_metrics` при отсутствующей колонке `pinnacle_home_close` (ветка `if col not in src.columns`).
  - Тест для `_log_unmatched_report_metrics` с непустым CSV-файлом.
  - Рассмотреть кеширование `load_source_config` через `functools.lru_cache` при `source_config_name` как аргументе (сейчас читается при каждом вызове `_odds_runtime_from_source`).

### 2026-04-25 — R20.4 Интеграция odds refresh в source_refresh pipeline

- **Задача:** `backlog/R20.md` (подзадача R20.4 → отмечена `[x]` внутри R20.md)
- **Ограничения и компромиссы:**
  - `ValueError` / `OSError` из `run_odds_refresh` не перехватываются в `main()` — при ошибке odds CLI завершается с трейсбеком вместо чистого `logger.error` + `return 1`. Поведение документировано в docstring как intentional fail-fast, но для операторов Airflow менее удобно, чем структурированный exit-код с логом.
  - `_DEFAULT_SPORT_KEY = "icehockey_nhl"` зашит как fallback в `source_refresh.py` — для любого нового турнира без явного `odds.sport_key` в конфиге этот дефолт будет семантически неверным.
  - `OmegaConf.select(odds, "enabled")` в `_odds_post_fetch_enabled` — избыточно; `odds.get("enabled")` на `DictConfig` возвращает то же значение. Работает корректно, но усложняет чтение.
  - Секция `odds` в `conf/source/nhl.yaml` получила `sport_key`, `incremental_buffer_days`, `max_days_per_refresh`, `auto_merge` — это частично перекрывает планируемый объём R20.5 (nhl.yaml часть). При выполнении R20.5 нужно проверить, что `conf/bookmaker/the_odds_api.yaml` ещё не обновлён, и избежать дублирования изменений.
- **Возможные улучшения / техдолг:**
  - Добавить в `main()` явный `except (ValueError, OSError) as e: logger.error("odds refresh failed: %s", e); return 1` для чистого CLI-поведения.
  - Убрать `_DEFAULT_SPORT_KEY` / `_DEFAULT_BOOKMAKER_KEY` из модуля; если `sport_key` не задан в конфиге — выбрасывать `ValueError` с понятным сообщением (конфиг всегда должен быть явным для реального турнира).
  - Добавить тест сценария `source_cfg=None` (когда `load_source_config` бросает `FileNotFoundError`): сейчас покрыт логикой кода, но явного теста нет.
  - При выполнении R20.5: синхронизировать и дополнить nhl.yaml-секцию (добавить `store_path`), а не дублировать правки.

### 2026-04-25 — R21.2: Конфигурация multi-bookmaker profiles + snapshot_discovery

- **Задача:** `backlog/R21.md` (sub-task R21.2) → `done_task/R21.2.md`
- **Ограничения и компромиссы:**
  - Секция `output_columns` (legacy V1: `pinnacle_home_open`, `pinnacle_total_open`, …) и новая `bookmaker_profiles` сосуществуют в одном YAML. Это допустимо как промежуточное состояние, но создаёт два конкурирующих источника истины по именам колонок до замены в R21.3/R21.6.
  - `test_nhl_odds_includes_configured_bookmakers` жёстко проверяет `bms == ["pinnacle", "onexbet"]`. При добавлении нового букмекера тест придётся обновить вручную — нет параметризации через `bookmaker_profiles` из самого конфига.
  - Нет проверки, что значения `winner_semantics` / `total_semantics` в профилях соответствуют именам колонок в `ODDS_STORE_COLUMNS_V2` (R21.1). Несоответствие можно внести в YAML без теста. Кросс-валидация будет возможна после R21.3.
- **Возможные улучшения / техдолг:**
  - R21.3/R21.6: удалить или явно пометить `output_columns` как `deprecated` после перехода enrichment и merge на `bookmaker_profiles`-генерацию колонок.
  - Добавить тест-фикстуру, которая кросс-валидирует `{bm}_{winner_semantics}_*` колонки из профилей с `ODDS_STORE_COLUMNS_V2` (например, через `startswith`-check).
  - Параметризовать `test_nhl_odds_includes_configured_bookmakers` через загрузку профилей из `the_odds_api.yaml` вместо hardcode-списка.

### 2026-04-25 — R21.3: Enrichment multi-bookmaker + total line + V2 naming

- **Задача:** `backlog/R21.md` (sub-task R21.3) → `done_task/R21.3.md`
- **Ограничения и компромиссы:**
  - `has_draw` хранится в `BookmakerExtractionProfile`, но **не используется** для фильтрации draw-колонок: `_v2_row_keys_for_profile` всегда генерирует `{prefix}_{w}_draw_{open,close}` для всех профилей. Pinnacle (has_draw=False) имеет эти колонки в схеме, они просто остаются `None`. Поведение корректное, но немного несогласованное с семантикой поля.
  - `_totals_line_and_prices` берёт `point` из первого outcome с непустым `point`, а не строго из outcome `"Over"`. В реальных данных оба имеют одинаковый `point`, так что результат идентичен. При нестандартном ответе API (разные `point` у Over и Under) возьмётся тот, что встретился первым в JSON.
  - `mkt["point"]` (market-level) проверяется первым — это защитный fallback для API-версий, которые кладут `point` на уровне рынка, а не outcome. В текущих данных The Odds API используется outcome-level.
  - `_events_to_odds_frame_v2` строит close-индекс по ключу `hk|ak`. Если два события имеют одинаковые нормализованные названия команд (теоретически, при коллизии в `TeamNameRegistry`), второе перезапишет первое.
- **Возможные улучшения / техдолг:**
  - R21.7/R21.8: использовать `has_draw` для валидации — если у букмекера `has_draw=False`, а draw-колонка ненулевая, логировать аномалию.
  - R21.7/R21.8: добавить тест, что при `has_draw=False` (Pinnacle) в результирующем DataFrame draw-колонки содержат только `None`/NaN.
  - После завершения R21.6: вывести `output_columns` в YAML как `deprecated: true` и добавить предупреждение в `_extract_row_legacy_pinnacle`.
  - Кросс-валидация `winner_semantics` / `total_semantics` профиля против `ODDS_STORE_COLUMNS_V2` (отложена из R21.2) теперь возможна — добавить в R21.7 или R21.8.

### 2026-04-25 — R21.1: OddsStore V2 schema + V1→V2 migration

- **Задача:** `backlog/R21.md` (sub-task R21.1, файл остаётся в backlog до завершения R21.2–R21.9)
- **Ограничения и компромиссы:**
  - `validate_pinnacle_odds_float_columns` в `refresh.py` (R20) проверяет V1-имена колонок (`pinnacle_home_open`, …). После V2-миграции ни одна из них не попадёт в V2-store → валидация тихо пропускается (`have=[]`). Данные фактически не валидируются до выполнения R21.7.
  - `_log_source_odds_metrics` в `refresh.py` использует V1-имя `pinnacle_home_close` для метрики coverage. После merge V2-store в source.csv эта колонка отсутствует → лог выводит «нет колонки», метрика не считается до выполнения R21.6.
  - `migrate_v1_to_v2` имеет тип параметра `pd.DataFrame`, но внутри защищён от `None` — небольшая несогласованность type hint (безвредна).
  - Фактическое число колонок V2 — 33 (≈36 по задаче, использовалась «~»). Расхождение декларативное, функциональный контракт полный.
- **Возможные улучшения / техдолг:**
  - R21.7: обобщить `_PINNACLE_ODDS_FLOAT_COLS` → `_ODDS_FLOAT_COLS_V2` с покрытием всех decimal-полей обоих букмекеров + `total_line` range check.
  - R21.6: обновить `_log_source_odds_metrics` на V2-имена (`pinnacle_winner_withOT_home_close`, per-bookmaker coverage).
  - Добавить тип `pd.DataFrame | None` в сигнатуру `migrate_v1_to_v2` при ближайшем рефакторинге.

### 2026-04-25 — R21.4 Snapshot discovery

- **Задача:** `backlog/R21.md` (подзадача R21.4) → `done_task/R21.4.md`
- **Ограничения и компромиссы:**
  - Seed-запрос (`legacy_open_time_utc`) делается всегда, даже если `ref_dt` будет найден и open-probe даст другой ISO. При probe-попадании seed payload отбрасывается и не возвращается как `p_open` — минорный overhead (1 extra API call / cached miss). В R21.5 можно реиспользовать seed как `p_open` если он совпадает с выбранным open.
  - `used_legacy_timestamps=True` устанавливается как при полном legacy-fallback (нет `ref_dt`), так и при частичном (close динамический, open из legacy). R21.5 при интеграции должен учесть эту семантику (флаг означает «open из legacy», не «оба из legacy»).
  - `_legacy_isos`: если `legacy_open_time_utc` передать как `"12:00:00Z"` (без `T`, но с `Z`) — вернётся строка без даты. Патологичный ввод, в практике не встречается (всегда `"HH:MM:SS"`), но стоит добавить guard при дальнейшем рефакторинге.
  - Тест-моки не реализуют полную сигнатуру `HistoricalOddsClient` Protocol (опущены `markets`, `odds_format`) → `# type: ignore[arg-type]`. При желании можно унифицировать через `**kwargs` в Protocol-сигнатуре или общий базовый mock-класс в conftest.
- **Возможные улучшения / техдолг:**
  - R21.5: реиспользовать seed payload как `p_open` если выбранный open-ISO совпадает с seed-ISO.
  - Добавить тест на патологичный ввод `_legacy_isos` (`"12:00:00Z"` без даты).
  - Вынести тест-моки клиента в `conftest.py` как reusable fixture (`FakeOddsClient`) — облегчит R21.8 тесты.

### 2026-04-25 — R21.5 Backfill: dynamic snapshot discovery integration

- **Задача:** `backlog/R21.md` (подзадача R21.5) → `done_task/R21.5.md`
- **Ограничения и компромиссы:**
  - В legacy-режиме `open_minutes_before = 0` и `close_minutes_before = 0` — семантически неточно (0 означает «ровно в момент игры», тогда как legacy-timestamp произвольный). Правильнее было бы хранить `None` / sentinel, но это потребует nullable int в V2-схеме (R21.1). Принято как временный компромисс до R21.7 (Pandera V2 валидация).
  - `validate_pinnacle_odds_float_columns` вызывается в `_upsert_if_non_empty` — устаревшее V1-имя, не охватывает V2-колонки (1xBet, total_line). Не вызывает ошибок (V2-колонки просто не проверяются), устраняется в R21.7.
  - Флаг `used_legacy_timestamps=True` в `SnapshotPlan` устанавливается при обоих вариантах legacy: полном (оба ISO фиксированы) и частичном (только open из legacy). Семантика зафиксирована в tech-debt R21.4; R21.5 следует той же конвенции.
- **Возможные улучшения / техдолг:**
  - CLI `--bookmakers pinnacle,onexbet`: override списка букмекеров из командной строки (пропущен в R21.5; функционально покрывается YAML `bookmaker_profiles`). Добавить в R21.8 или отдельной подзадачей.
  - `quota_budget_per_run` default: при dynamic discovery 3–5 probe-запросов/день вместо 2 — дефолт следует пересмотреть (R21.9 или операционная настройка).
  - Нет теста для `use_open_close=False` + `legacy_timestamps=False` (dynamic single-snapshot ветка). Добавить в R21.8.
  - `_snapshot_discovery_params` не тестируется изолированно для edge-cases (пустой список offsets, нечисловые значения). Добавить юнит-тест в R21.8.
