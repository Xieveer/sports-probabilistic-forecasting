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

### 2026-05-10 — R31 Feature Selection UX (ревью)

- **Задача:** `backlog/R31.md` → `done_task/R31.md`
- **Ограничения и компромиссы:**
  - Старые ключи MLflow `*_fs_fit_*` / `feature_importance_fs_fit.csv` заменены на `*_full_*` / `feature_importance_full.csv`; дашборды и скрипты сравнения по старым именам нужно обновить. Тег `primary_feature_set=selected` отделяет новые прогоны.
  - `fs_round` пока всегда `1`; многораундовый FS не реализован.
- **Возможные улучшения / техдолг:**
  - Итеративный / automated multi-round FS — **отложен**, целесообразность под вопросом; см. `backlog/R32.md`.
  - Опционально: временное дублирование метрик под legacy-именами `*_fs_fit_*` для переходного периода (не делалось).

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

- **Задача:** `done_task/R20.md` (подзадача R20.1, отмечена как выполненная)
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

- **Задача:** `done_task/R20.md` (подзадача R20.9, отмечена как выполненная)
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

- **Задача:** `done_task/R20.md` (подзадача R20.3) → `done_task/R20.3.md`
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

- **Задача:** `done_task/R20.md` (подзадача R20.2) → `done_task/R20.2.md`
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

- **Задача:** `done_task/R20.md` (подзадачи R20.5/6/7 → `done_task/R20.5.md`, `done_task/R20.6.md`, `done_task/R20.7.md`)
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

- **Задача:** `done_task/R20.md` (подзадача R20.4 → отмечена `[x]` внутри R20.md)
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

- **Задача:** `done_task/R21.md` (sub-task R21.2) → `done_task/R21.2.md`
- **Ограничения и компромиссы:**
  - Секция `output_columns` (legacy V1: `pinnacle_home_open`, `pinnacle_total_open`, …) и новая `bookmaker_profiles` сосуществуют в одном YAML. Это допустимо как промежуточное состояние, но создаёт два конкурирующих источника истины по именам колонок до замены в R21.3/R21.6.
  - `test_nhl_odds_includes_configured_bookmakers` жёстко проверяет `bms == ["pinnacle", "onexbet"]`. При добавлении нового букмекера тест придётся обновить вручную — нет параметризации через `bookmaker_profiles` из самого конфига.
  - Нет проверки, что значения `winner_semantics` / `total_semantics` в профилях соответствуют именам колонок в `ODDS_STORE_COLUMNS_V2` (R21.1). Несоответствие можно внести в YAML без теста. Кросс-валидация будет возможна после R21.3.
- **Возможные улучшения / техдолг:**
  - R21.3/R21.6: удалить или явно пометить `output_columns` как `deprecated` после перехода enrichment и merge на `bookmaker_profiles`-генерацию колонок.
  - Добавить тест-фикстуру, которая кросс-валидирует `{bm}_{winner_semantics}_*` колонки из профилей с `ODDS_STORE_COLUMNS_V2` (например, через `startswith`-check).
  - Параметризовать `test_nhl_odds_includes_configured_bookmakers` через загрузку профилей из `the_odds_api.yaml` вместо hardcode-списка.

### 2026-04-25 — R21.3: Enrichment multi-bookmaker + total line + V2 naming

- **Задача:** `done_task/R21.md` (sub-task R21.3) → `done_task/R21.3.md`
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

- **Задача:** `done_task/R21.md` (sub-task R21.1, файл остаётся в backlog до завершения R21.2–R21.9)
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

- **Задача:** `done_task/R21.md` (подзадача R21.4) → `done_task/R21.4.md`
- **Ограничения и компромиссы:**
  - Seed-запрос (`legacy_open_time_utc`) делается всегда, даже если `ref_dt` будет найден и open-probe даст другой ISO. При probe-попадании seed payload отбрасывается и не возвращается как `p_open` — минорный overhead (1 extra API call / cached miss). В R21.5 можно реиспользовать seed как `p_open` если он совпадает с выбранным open.
  - `used_legacy_timestamps=True` устанавливается как при полном legacy-fallback (нет `ref_dt`), так и при частичном (close динамический, open из legacy). R21.5 при интеграции должен учесть эту семантику (флаг означает «open из legacy», не «оба из legacy»).
  - `_legacy_isos`: если `legacy_open_time_utc` передать как `"12:00:00Z"` (без `T`, но с `Z`) — вернётся строка без даты. Патологичный ввод, в практике не встречается (всегда `"HH:MM:SS"`), но стоит добавить guard при дальнейшем рефакторинге.
  - Тест-моки не реализуют полную сигнатуру `HistoricalOddsClient` Protocol (опущены `markets`, `odds_format`) → `# type: ignore[arg-type]`. При желании можно унифицировать через `**kwargs` в Protocol-сигнатуре или общий базовый mock-класс в conftest.
- **Возможные улучшения / техдолг:**
  - R21.5: реиспользовать seed payload как `p_open` если выбранный open-ISO совпадает с seed-ISO.
  - Добавить тест на патологичный ввод `_legacy_isos` (`"12:00:00Z"` без даты).
  - Вынести тест-моки клиента в `conftest.py` как reusable fixture (`FakeOddsClient`) — облегчит R21.8 тесты.

### 2026-04-25 — R21.8 Тесты: unit + integration для V2 odds pipeline

- **Задача:** `done_task/R21.md` (подзадача R21.8) → `done_task/R21.8.md`
- **Ограничения и компромиссы:**
  - Мок-клиенты API (`class C`) определяются inline в каждом тесте snapshot_discovery; предложенный в tech-debt R21.5 reusable `FakeOddsClient` в `conftest.py` не реализован — inline-подход гибче для per-test ветвления, но добавляет дублирование.
  - Integration-тест (`test_end_to_end_mock_backfill_store_v2_merge_source_csv`) использует `events_to_odds_frame` напрямую, а не полный `backfill_day_frames` с mock-клиентом. Это упрощение: `backfill_day_frames` покрыт отдельным unit-тестом с monkeypatch. Полный e2e (client → discover → backfill_day_frames → store → merge) через один тест отсутствует.
  - Покрытие измерено структурно (каждый публичный путь), но не через `coverage.py` — формальный отчёт по строкам отсутствует. Рекомендуется добавить `make test-cov` / CI coverage gate после R21.9.
  - `test_backfill_day_frames_discover_adds_timing_and_uses_config` проверяет, что `"bookmaker_profiles" in last_book_cfg`, используя side-effect в mock `_eto`. Если сигнатура `events_to_odds_frame` изменится (переименование параметра), тест не упадёт, но `last_book_cfg` останется пустым — молчаливое false-negative.
- **Возможные улучшения / техдолг:**
  - Добавить `conftest.py` с `FakeOddsClient` fixture, переиспользуемой в test_snapshot_discovery и test_odds_backfill (устраняет дублирование inline-классов).
  - Добавить `make test-cov` / `pytest --cov` в CI с gate ≥ 80% по модулям `sports_forecast/data/providers/odds/`.
  - Расширить integration-тест до полного пути `backfill_day_frames(mock_client, ...)` → `upsert_odds_store_file` → `merge_odds_into_source_csv` в одном fixture-пространстве (после R21.9 когда V1-fallback путей станет меньше).

### 2026-04-25 — R21.6 Merge/refresh pipeline V2: no-suffix merge, per-bookmaker coverage

- **Задача:** `done_task/R21.md` (подзадача R21.6; R21 не перенесён в done_task до закрытия всех подзадач)
- **Ограничения и компромиссы:**
  - `_ODDS_JOIN_KEYS` в `enrichment.py` дублирует `ODDS_DEDUP_KEYS` из `store.py` (одинаковые тройки). Не импортирован напрямую, чтобы избежать циклической зависимости между enrichment и store. При рефакторинге: вынести в отдельный `constants.py` модуль.
  - `_log_source_odds_metrics` читает `source.csv` с диска при каждом refresh. На больших файлах — лишний I/O. Можно принимать DataFrame как опциональный аргумент или передавать кэш из вызывающего кода (отложить до R21.9 или при появлении проблем производительности).
  - Primary coverage-колонка выбирается по приоритету V1 > V2-Pinnacle > onexbet: если source содержит и V1, и V2 одновременно (переходный период до R21.9), priority отдаётся V1. Это может скрыть ухудшение V2 coverage. Пересмотреть после R21.9 (full migration).
- **Возможные улучшения / техдолг:**
  - После R21.9 (миграция store V1→V2): удалить V1-fallback в `_log_source_odds_metrics` и упростить приоритет до V2 Pinnacle → onexbet.
  - Добавить тест для сценария «source содержит и V1, и V2 колонки одновременно» — убедиться, что `drop_from_left` корректно заменяет обе группы без суффиксов.

### 2026-04-25 — R21.7 Pandera V2 validation + observability hooks

- **Задача:** `done_task/R21.md` (подзадача R21.7) → `done_task/R21.7.md`
- **Ограничения и компромиссы:**
  - `_OddsDecimalColumn`, `_OddsTotalLineColumn`, `_OddsMinutesColumn` — singleton Column-объекты, разделяемые между несколькими схемами через `dict.fromkeys`. Pandera не мутирует Column при добавлении в схему (всё тесты проходят), однако при смене мажорной версии Pandera поведение может измениться. При следующем upgrade Pandera стоит проверить, что singleton-шаринг остаётся безопасным.
  - `open_minutes_before` / `close_minutes_before` валидируются как `float` (а не `int`). Логически значения — целые минуты, но хранятся как float (деление datetime), что приводит к типу `float64` в pandas. Проверка `>= 0` корректна, но нет верхней границы (теоретически возможны значения вроде 1e9 при некорректных данных).
  - Валидация в `refresh.run_odds_refresh` — post-store sanity-check (после загрузки уже сохранённого store), а не перед upsert. Сам pre-upsert fail-fast реализован в `backfill._upsert_if_non_empty`. Это двухуровневая защита, но пропуск данных через refresh без прохождения через backfill (если вызов `run_backfill_fn` возвращает что-то неожиданное) не поймается до записи.
- **Возможные улучшения / техдолг:**
  - Добавить верхнюю границу для `minutes_before` (например `<= 20_000`, ~14 дней) — защита от аномальных данных.
  - Рассмотреть `int` / nullable int dtype для `minutes_before` колонок в V2 store (сейчас `float64`), если Pandas 2.x + Arrow-backend станет стандартом.
  - После R21.9 (миграция V1→V2): удалить V1-ветку из `_ODDS_DECIMAL_COLS` (union больше не нужен — все данные в V2) и упростить до `_ODDS_V2_DECIMAL_COLS`.

### 2026-04-25 — R21.5 Backfill: dynamic snapshot discovery integration

- **Задача:** `done_task/R21.md` (подзадача R21.5) → `done_task/R21.5.md`
- **Ограничения и компромиссы:**
  - В legacy-режиме `open_minutes_before = 0` и `close_minutes_before = 0` — семантически неточно (0 означает «ровно в момент игры», тогда как legacy-timestamp произвольный). Правильнее было бы хранить `None` / sentinel, но это потребует nullable int в V2-схеме (R21.1). Принято как временный компромисс до R21.7 (Pandera V2 валидация).
  - `validate_pinnacle_odds_float_columns` вызывается в `_upsert_if_non_empty` — устаревшее V1-имя, не охватывает V2-колонки (1xBet, total_line). Не вызывает ошибок (V2-колонки просто не проверяются), устраняется в R21.7.
  - Флаг `used_legacy_timestamps=True` в `SnapshotPlan` устанавливается при обоих вариантах legacy: полном (оба ISO фиксированы) и частичном (только open из legacy). Семантика зафиксирована в tech-debt R21.4; R21.5 следует той же конвенции.
- **Возможные улучшения / техдолг:**
  - CLI `--bookmakers pinnacle,onexbet`: override списка букмекеров из командной строки (пропущен в R21.5; функционально покрывается YAML `bookmaker_profiles`). Добавить в R21.8 или отдельной подзадачей.
  - `quota_budget_per_run` default: при dynamic discovery 3–5 probe-запросов/день вместо 2 — дефолт следует пересмотреть (R21.9 или операционная настройка).
  - Нет теста для `use_open_close=False` + `legacy_timestamps=False` (dynamic single-snapshot ветка). Добавить в R21.8.
  - `_snapshot_discovery_params` не тестируется изолированно для edge-cases (пустой список offsets, нечисловые значения). Добавить юнит-тест в R21.8.

### 2026-04-25 — R21.10 Schema V3: close-only, миграции V1/V2→V3, enrichment close-only

- **Задача:** `done_task/R21.md` (подзадача R21.10) → `done_task/R21.10.md`
- **Ограничения и компромиссы:**
  - `extract_bookmaker_row_from_event` сохранил ветки `snapshot_role="open"` и `"single"` для обратной совместимости V2-тестов (R21.1–R21.8). До R21.14 legacy-тесты могут опираться на эти пути; после R21.14 ветки `"open"`/`"single"` стоит помечать deprecated или убирать.
  - `_events_to_odds_frame_v2` переименована семантически (V3 close-only), но имя функции ещё содержит `_v2`. До R21.14 достаточно; после — рекомендуется переименовать в `_events_to_odds_frame_v3` для ясности.
  - `write_unmatched_odds_teams_report` принимает `key_date_col` (новый параметр), но существующие вызывающие код (`refresh.py`) по умолчанию использует `"game_date"`. При переходе к V3 store с `commence_time_utc`-based key-date нужно убедиться, что вызов обновлён (R21.14 или R21.9).
  - Pandera `_ODDS_MINUTES_BEFORE_COLS` содержит `"open_minutes_before"`, которая в V3 store отсутствует — включена для V2/V1 backward-compat; в R21.14 можно убрать `"open_minutes_before"` из проверки Pandera, если V1/V2 store больше не используются.
- **Возможные улучшения / техдолг:**
  - R21.14: переименовать `_events_to_odds_frame_v2` → `_events_to_odds_frame_v3`, убрать `"open"`/`"single"` ветку из `extract_bookmaker_row_from_event` как deprecated.
  - R21.14: убрать `"open_minutes_before"` из `_ODDS_MINUTES_BEFORE_COLS` в Pandera schemas (V3 store не имеет `open_minutes_before`).
  - После R21.9 (full V3 backfill): удалить V1 + V2-только ветки из union `_ODDS_DECIMAL_COLS` — упростить до V3-only или V3 + V1 legacy.
  - Покрыть тестом сценарий `load_odds_store` на реальный V2 parquet (V2→V3 migration at load). Сейчас тест `test_migrate_v2_to_v3_drops_open_and_draw_pinnacle` проверяет функцию напрямую, но не через `load_odds_store`.

### 2026-04-25 — R21.12 Подробное логирование API-вызовов

- **Задача:** `done_task/R21.md` (подзадача R21.12) → `done_task/R21.12.md`
- **Ограничения и компромиссы:**
  - ~~`snapshot_discovery.py` по-прежнему логирует полный URL с `apiKey` в WARNING-сообщениях при `seed fetch failed`.~~ **Исправлено в R21.14** (2026-04-25): `_safe_fetch_exception_detail()` — WARNING выводит только тип исключения + HTTP status; URL в логи не попадает.
  - Cache-hit логирует `x-requests-remaining` из `last_quota()`, а не из реального заголовка HTTP (заголовок недоступен при кеш-хите). Логически корректно, но значение может устареть, если кеш-хиты идут до первого реального HTTP-запроса.
  - `_log_backfill_close_payload` логирует INFO на каждый день вне зависимости от того, пуст ли ответ (0 events). При массовом backfill это создаёт шум «events_found=0» для дней без матчей. Функционально безвредно.
- **Возможные улучшения / техдолг:**
  - ~~`snapshot_discovery.py`: заменить URL на path в WARNING.~~ **Закрыто R21.14** (2026-04-25).
  - В `_log_backfill_close_payload`: добавить guard `if not evs: return` для подавления INFO при 0 events (или понизить до DEBUG).

### 2026-04-25 — R21.14 Тесты + конфиг V3, apiKey fix

- **Задача:** `done_task/R21.md` (подзадача R21.14) → `done_task/R21.14.md`
- **Ограничения и компромиссы:**
  - `_ODDS_MINUTES_BEFORE_COLS` в Pandera по-прежнему содержит `"open_minutes_before"` для backward-compat V1/V2 store. В V3 store колонка отсутствует, Pandera её пропускает (`strict=False`). Убрать безопасно только после R21.9 (full V3 backfill), когда V1/V2 parquet больше не загружаются.
  - `_events_to_odds_frame_v2` в `enrichment.py` — имя функции содержит `_v2`, хотя обрабатывает V3-поток (close-only). До R21.9 функциональных последствий нет.
  - `test_v3_positive_sample` покрывает только positive path. Negative path (невалидные V3-данные) покрыт существующими V1/V2 тестами в `TestValidateOddsFloatColumnsV2`.
- **Возможные улучшения / техдолг:**
  - После R21.9: убрать `"open_minutes_before"` из `_ODDS_MINUTES_BEFORE_COLS` (Pandera cleanup).
  - После R21.9: переименовать `_events_to_odds_frame_v2` → `_events_to_odds_frame_v3` в `enrichment.py`.
  - Добавить negative test V3 в `TestValidateOddsFloatColumnsV3` (decimal < 1.0, line < 0).

### 2026-05-03 — R22.8 OT-рынки NHL (winner_withOT / total_withOT)

- **Задача:** `done_task/R22.md` (подзадача R22.8, Phase C) — OT-inclusive markets, NHL
- **Ограничения и компромиссы:**
  - `home_goals_full` / `away_goals_full` — это копия `home_points` / `away_points` (transform `copy` в `nhl.yaml` `derived_columns`). Семантически правильно для текущего NHL boxscore (где `*_ft` уже включает OT). Если в будущем появится источник, где `*_ft` не включает буллит-гол победителя, контракт потребует пересмотра — сейчас это явно задокументировано в `ice_hockey.yaml` и `HOW_TO_ADD_NEW_MARKET.md`.
  - Трансформация `copy` в `_apply_derived_columns` (`clean.py`) применяется только тогда, когда в YAML прописан `transform: copy`; другие турниры не затронуты — проверено grep'ом по всем `conf/tournament/*.yaml`.
  - Фактические прогоны `make train-sweep-nhl-ot-winner` / `make train-sweep-nhl-ot-total` — операционные и не покрыты автотестами (требуют NHL interim parquet с колонками `*_goals_full` / `*_goals_reg` после пересборки features).
  - `allowed_market_specs` в `ice_hockey.yaml` для `winner_withOT` не содержит поля `lines` (линии не применимы для winner); для `total_withOT` линии прописаны, но не валидируются автоматически на соответствие фактической line из market_spec. Это принятый компромисс (аналогично существующему `total`).
  - `market_key: "total"` в `prematch_line` для `total_over_withOT` / `total_under_withOT` — условный; реальный ключ OddsAPI для тотала с OT может отличаться у разных букмекеров. Предупреждение оставлено в комментарии YAML.
- **Возможные улучшения / техдолг:**
  - После первого реального `make train-sweep-nhl-ot-winner`: зафиксировать MLflow experiment name и promoted model path.
  - При интеграции OddsAPI для `total_withOT`: уточнить `market_key` (возможно, потребуется отдельный ключ вроде `total_full` или специфичный для букмекера); зафиксировать контракт в конфиге и `HOW_TO_ADD_NEW_MARKET.md`.
  - Рассмотреть интеграционный тест: NHL interim parquet (минимальный срез) → `_apply_derived_columns` → проверка наличия `home_goals_full`/`away_goals_full` в выводе (сейчас покрыто юнит-тестами `targets.py`, но не сквозным clean-пайплайном).
  - Если понадобится различать «OT без буллит-гола» vs «включая буллит-гол у победителя» — потребуется отдельная derived-колонка и контракт в assembler; текущая схема считает финальный счёт с +1 победителю при победе в буллитах (NHL boxscore семантика).

### 2026-05-03 — R22 Phase A (R22.1–R22.3): NHL training config, season-holdout split, Makefile, docs

- **Задача:** `done_task/R22.md` (Phase A завершена; Phase B/C — в работе)
- **Ограничения и компромиссы:**
  - R22.2 и R22.3 реализованы как Makefile-цели и операционная документация (`HOW_TO_ADD_NEW_TOURNAMENT.md`); фактический прогон `make train-sweep-nhl`, `make promote`, `make materialize` — операционный шаг, не покрытый автотестами (зависит от наличия NHL parquet-данных в `data/processed/nhl`).
  - `subset_frame_for_season_holdout` вызывается в `trainer.py` **дважды**: один раз до выбора фичей (для фильтрации датафрейма), второй раз при train/test-split (повторная маскировка по `holdout_seasons`). Функционально корректно, но избыточно; при рефакторинге trainer можно объединить в одну точку.
  - `train_eval_split.holdout_seasons` в YAML поддерживает только один сезон в baseline-конфиге (`20242025`). Несколько сезонов поддерживается кодом, но не проверено на NHL-данных с несколькими holdout-сезонами.
  - Изменение в `backfill.py` (`load_dotenv` в `run_backfill`) добавлено вне явного scope R22 (минимальный bugfix для programmatic-вызовов без CLI). Логически относится к R20/R21 fix-up.
- **Возможные улучшения / техдолг:**
  - После первого реального прогона `make train-sweep-nhl`: зафиксировать MLflow experiment name и promoted model path в документации (README или HOW_TO_ADD_NEW_TOURNAMENT.md).
  - Добавить интеграционный smoke-тест: загрузить маленький NHL parquet-срез и проверить полный pipeline split → features → train на корректность (сейчас только unit-тесты на `train_eval_split.py`).
  - Рассмотреть вынос двойного вызова `subset_frame_for_season_holdout` в trainer в единую точку (до feature selection), убрав дублирование маскировки на этапе split.
  - При добавлении Phase C (R22.8, `winner_withOT`): валидировать, что `season_column` присутствует в NHL parquet с OT-данными.
  - **~~Паттерн конфигов (вернуться позже):~~** закрыто в **R38**: канонический slug `nhl`; `conf/tournament/nhl_train.yaml` — deprecated-алиас (`defaults: [nhl]`); см. `docs/cursor/context/nhl_single_tournament_slug.md`.

### 2026-05-03 — R22.4: расширенные NHL roster-фичи

- **Задача:** `done_task/R22.md` (R22.4 Phase B stretch)
- **Ограничения и компромиссы:**
  - **TOI:** сезонный `roster/{team}/{season}` Web API не отдаёт TOI; агрегаты по льду не считаем (без фиктивных значений). Возможное направление: per-game ``playerByGameStats`` или отдельный фид.
  - **Стартовый вратарь:** ``*_primary_goalie_sweater`` — эвристика «первый вратарь в порядке API», не объявленный стартёр на матч.
  - **Травмы:** ``*_injured_listed`` опирается на список ``injured`` в JSON; до R19.20 счётчики обычно 0.
- **Возможные улучшения / техдолг:**
  - Подключить TOI и/или реальный starter, когда появятся стабильные поля в данных (R19.20+).

### 2026-05-04 — R22.6 Motivation / playoff context (NHL standings)

- **Задача:** `done_task/R22.md` (R22.6 Phase B stretch; R22.7 снова открыта после отката `pinnacle_holdout`, см. R26)
- **Ограничения и компромиссы:**
  - **Межконференционный шум:** `standing_rank_gap` и `*_playoff_spots_out` вычисляются по `*_conference_standing` (ранг внутри конференции), но wide-CSV не содержит признака «обе команды в одной конференции». Для матчей регулярного сезона между командами разных конференций разница рангов информативна лишь косвенно — модель получает сигнал без различия «internal vs cross-conference».
  - **`same_conference_standing_pressure` не реализован:** для надёжного признака «одна конференция» нужны явные колонки `home_conference` / `away_conference` в `source.csv` / interim; без них вычисление non-trivial и может давать ложные срабатывания. Задокументировано в module docstring как tech-debt.
  - **`get_total_feature_count` vs опциональные мотивационные колонки:** `get_expected_feature_names()` всегда включает `motivation_playoffs_phase` и `motivation_extended_game` (два опциональных ключа), даже если во входном датафрейме нет колонок `game_type` / `match_end`. Реальные выходные фичи (`get_actual_feature_names(df)`) на 0–2 имени меньше — потребители, полагающиеся на `get_feature_names()` как на константу, должны учитывать это расхождение.
  - **`game_type` / `match_end` — постфактумный контекст:** для pre-game строк оба поля обычно пусты → `nan`. Признаки полезны только при аналитике завершённых матчей или если источник данных проставляет их заранее (например, `playoffs` по расписанию).
- **Возможные улучшения / техдолг:**
  - Добавить колонки `home_conference` / `away_conference` в NHL assembler (из API `franchises` или standings response) — это разблокирует `same_conference_standing_pressure` (бинарный признак «тот же дивизион/конференция → давление в гонке значимее»).
  - Рассмотреть более точный «division race density» proxy: например, разброс (std) очков команд top-4 в дивизионе на текущую дату. Требует расширения standings snapshot с дивизиональным срезом.
  - Унифицировать `get_expected_feature_names()` / `get_actual_feature_names()` через публичный метод `get_optional_feature_keys()` — явный контракт «эти колонки могут отсутствовать» снизит риск несоответствия для downstream.
  - Суммарные «очки позади 8-го места» как абсолютная величина (`points_behind_playoff`) дополнят rank-based `*_playoff_spots_out` и будут менее чувствительны к числу сыгранных матчей.

### 2026-05-04 — R22.5 Travel / rest (NHL schedule)

- **Задача:** `done_task/R22.md` (R22.5 Phase B stretch)
- **Ограничения и компромиссы:**
  - Координаты арен — статический справочник `NHL_ARENA_GEO` (центр города/арены), не геокодирование строки `location` из CSV; нейтральные площадки и смена арены команды не моделируются.
  - «Площадка матча» = домашняя команда строки (`home_team`); расстояние считается между ареной предыдущей игры команды и текущей — корректно для типичного NHL home/away.
  - **Часовой пояс:** одно целочисленное смещение ``utc_offset_std`` на команду (зимнее время), **без DST** и без учёта календарной даты матча — грубый индикатор смены пояса при перелётах.
  - Существующие фичи плотности расписания (дни отдыха, B2B) не менялись; travel включается через ``travel.enabled: true`` в ``conf/features/generators/schedule/nhl.yaml`` (для юнит-тестов с фиктивными командами — ``travel.enabled: false``).
- **Возможные улучшения / техдолг:**
  - При появлении точных координат арен в данных — подставлять из источника или обновлять справочник при переездах команд.
  - DST-aware сдвиг или локальное время старта матча из API для более точного «jet lag» признака.
  - Суммарные км за скользящее окно (7 дней) как отдельные фичи.

### 2026-05-03 — R26: Единый контракт odds (NHL BettingSimulator в train)

- **Задача:** `backlog/R26.md` → `done_task/R26.md`
- **Ограничения и компромиссы:**
  - `build_synthetic_odds_raw_series` итерирует по строкам (`iterrows`) — для типичных датасетов NHL (~2–3k строк в train_long) приемлемо; при росте до 100k+ может стать узким местом.
  - `apply_tournament_default_bookmaker` подменяет профиль только при `bookmaker.name == fonbet`; если корневой дефолт когда-либо изменится — нужно обновить условие.
  - Synthetic dict строит `str(d)` — Python-dict repr; `extract_odds_from_raw` парсит его через `ast.literal_eval`. Хрупкость при нестандартных float-значениях (NaN, Inf) не устранена (унаследовано от существующего контракта Fonbet/UEL).
  - `select_columns` в `nhl.yaml` теперь явно включает `odds_raw`; если clean пропустит этап synthetic (нет Pinnacle-колонок), строка будет `None` — тренер не упадёт (zero-coverage warning), но BettingSimulator не посчитается.
- **Возможные улучшения / техдолг:**
  - Заменить `iterrows` на vectorized-сборку dict: `pd.concat` + `apply` на уровне группы, или специализированный builder без Python-loop — для масштабирования на плотные long датасеты.
  - Унифицировать synthetic-сборку и fonbet-парсинг через общий объект `OddsDict` (датакласс), устранив хрупкость `ast.literal_eval`.
  - R22.7 (holdout eval vs Pinnacle) по-прежнему открыта: R26 покрывает train-time BettingSimulator, но не изолированный OOD holdout-отчёт — при необходимости сделать отдельной задачей.
  - Implied probability 2-way (market-benchmark) — упомянута в R26.3, юнит-тесты не добавлены; задел есть в `synthetic_odds_raw`, но вычисление vig/no-vig вероятности ещё не реализовано.

### 2026-05-03 — R23: CI/CD, секреты, production deploy на VPS

- **Задача:** `backlog/R23.md` → `done_task/R23.md`
- **Ограничения и компромиссы:**
  - **`!reset` в docker-compose.prod.yml:** тег `!reset` — расширение Docker Compose, не стандартный YAML. Pre-commit `check-yaml` добавлен exclude; при смене YAML-линтера исключение нужно повторить. Альтернатива — Compose `extends:` (но ломает `!reset` семантику для массивов).
  - **Deploy без healthcheck-барьера:** `deploy.yml` делает `up -d --remove-orphans`, но не дожидается healthcheck-прохождения новых контейнеров. Откат при ошибке — вручную. При CI-сбое `workflow_run` guard защищает, но partial-start сценарий не обрабатывается.
  - **docker.yml не зависит от ci.yml:** CI и Docker — независимые workflows. При merge в main Docker может запустить параллельно с CI; образ теоретически может быть push-нут при фейловых тестах, если CI запустился раньше и ещё не завершился. Полное решение — caching стратегия или `workflow_run` от CI.
  - **Cron без оркестратора:** `cron_refresh.py` — bash-уровень с `flock`; нет retry-политики, нет алертинга на cron-сбой напрямую (только через staleness-алерт). Airflow-DAG `dag_data_refresh.py` существует параллельно — два механизма рефреша.
  - **node-exporter без сетевой изоляции:** сервис объявлен в `docker-compose.prod.yml`, но не добавлен в `networks:` базового compose; видимость зависит от дефолтного compose-поведения.
  - **Caddy basic auth через env:** хэш пароля передаётся переменной окружения в контейнер Caddy; при утечке `.env` на сервере — раскрытие basic auth.
- **Возможные улучшения / техдолг:**
  - Добавить step `docker compose ps --filter health=healthy` или использовать `appleboy/ssh-action` с ожиданием healthcheck-порогов после деплоя.
  - Связать `docker.yml` с `ci.yml` через `workflow_run` для гарантии «образ пушится только при зелёных тестах».
  - Cron alerting: добавить `on_failure_command` или интеграцию healthchecks.io/Alertmanager для уведомления при падении cron-джобы.
  - Versionize Caddyfile: при появлении нескольких сервисов рассмотреть шаблонизацию через Caddyfile snippets или отдельный Caddyfile-фрагмент per-сервис.
  - Переработать `node-exporter` в именованную сеть (`networks: monitoring_net`) для изоляции scrape-трафика.

### 2026-05-04 — R28: rolling_column_aliases + inseason context

- **Задача:** `backlog/R28.md` → `done_task/R28.md`
- **Ограничения и компромиссы:**
  - **Глобальность алиасов:** `rolling_column_aliases` действует на все контексты разом — если одна и та же колонка в разных контекстах имеет разный смысл (и нужно маппить по-разному), текущий подход не покрывает этот случай. Риск — Low: таких ситуаций в проекте пока нет, но если появятся — нужен context-level override (Approach B из R28).
  - **`loaders.py` — вне скоупа R28:** баг-фикс `load_bookmaker_config` (замена Hydra compose на `OmegaConf.load`) попал в тот же коммит; он корректен и тесты проходят, но не является частью R28. При ревью архитектуры следует проверить, нет ли ещё мест с аналогичным паттерном `initialize_config_dir` внутри `@hydra.main`.
  - **`_ewm_compute_diff_for_generator` — новый API:** добавлен ключ `library_compute_diff` в конфиг генератора — нигде не задокументирован в конфигах (только в коде). При добавлении нового EWM-генератора разработчик должен знать об этом поле из кода, а не из конфига.
  - **Backward compat через name-suffix:** fallback `gen_key.endswith("_total") → compute_diff=False` зависит от именования генератора в YAML. Если кто-то назовёт новый EWM-генератор `ewm_total_advanced`, он автоматически получит `compute_diff=False` — неочевидное поведение.
- **Возможные улучшения / техдолг:**
  - Добавить context-level override (`contexts.<name>.keys_override: [...]`) как Approach B для случаев, когда один контекст в разных спортах нужно маппить по-разному без изменения всех ключей.
  - Задокументировать `library_compute_diff` в `standard.yaml` и/или в docstring `_ewm_compute_diff_for_generator` как явно поддерживаемый ключ конфига генератора.
  - Заменить fallback `endswith("_total")` на явный дефолт `compute_diff: true` в YAML конфиге — уберёт неявную зависимость от именования.
  - Проверить остальные места в `loaders.py` на аналогичный паттерн `initialize_config_dir` / `compose` внутри уже инициализированного Hydra-контекста (потенциальные GlobalHydra-конфликты).

### 2026-05-04 — R27 NHL Feature Engineering v2

- **Задача:** `backlog/R27.md` → `done_task/R27.md`
- **Follow-up (тот же день):** исправлен критический баг — `ewm_metrics` из Hydra приходит как **ListConfig**, `_tournament_ewm_metrics` возвращал `None`, sport EWM не инжектился в `materialize_features_config` при реальном `cfg.tournament`. Исправление: `OmegaConf.is_config` + `to_container`; добавлен CI smoke `tests/test_r27_nhl_advanced_pipeline_smoke.py` (R27.10 без parquet в репо).
- **Ограничения и компромиссы:**
  - **Полный операционный прогон на NHL interim parquet** по-прежнему не зафиксирован в CI (в репозитории нет `data/`); локально: `features_build` + `train` на `nhl` при наличии данных.
  - **Roster seniority считается по всему датафрейму батча.** Функция `_add_lineup_features` обходит строки в хронологическом порядке внутри переданного DataFrame, поэтому правильность результата зависит от того, что весь исторический ростер попадает в один батч. При инкрементальном вызове (только новые матчи) состояние сбросится.
  - **`_one_team` определена внутри цикла** — рефакторинг ради Ruff B023 привёл к передаче `row_idx` явным параметром; корректно, но архитектурно чище было бы вынести функцию на уровень метода.
  - **Streak на больших long (dvc-repro):** исправлено — индекс ``id → (home_pos, away_pos)`` за O(n) + запись фич в numpy-буферы без тысяч ``DataFrame.loc`` на матч (регрессия ``test_streak_many_matches_completes_quickly``).
  - **`inject_sport_ewm_generators` дублирует весь dict контекстов** (через `copy.deepcopy`). Для 7 метрик × N контекстов это нормально, но размер конфига растёт линейно.
- **Возможные улучшения / техдолг:**
  - При наличии данных: прогнать `features_build` на полном NHL interim и сравнить NaN-rate по фичам с порогом 30 %.
  - Вынести `_one_team` из `_add_lineup_features` в отдельный статический метод класса для улучшения читаемости и тестируемости.
  - Рассмотреть stateful-вариант roster seniority с сохранением `cum_app` / `last_sw` между инкрементальными вызовами (аналогично как EWM хранит состояние через GroupBy).
  - R27.8 (inseason EWM профиль с другими spans) остаётся открытым: после R27.7 `standard.yaml` автоматически генерирует inseason контекст с теми же spans [5,15]; если потребуется другой набор spans для inseason — создать `nhl_inseason.yaml`.

### 2026-05-04 — R29: спорт-осознанная композиция feature pipeline

- **Задача:** `backlog/R29.md` → `done_task/R29.md`
- **Ограничения и компромиссы:**
  - `_FALLBACK_SPORT_GROUPS` в `feature_pipeline_compose.py` дублирует данные из `conf/sport/*.yaml` как Python-словарь. При добавлении нового спорта нужно обновить как YAML, так и этот словарь — точка рассинхронизации. Принято сознательно, чтобы не читать YAML при каждом вызове и не завязываться на Hydra при вызове вне контекста compose.
  - Только две группы (`nhl_boxscore`, `streak`) покрыты механизмом групп R29. Добавление новой optional-группы (например, `injury_report`, `player_props`) потребует расширения констант `GROUP_*_KEYS`, путей YAML и логики `_effective_feature_groups`.
  - `compose_feature_pipeline` вызывается каждый раз при `materialize_features_config` (включая unit-тесты rolling/EWM) — защищено guard `_should_compose`, который возвращает `False` если `tournament_cfg` не содержит `sport`/`feature_pipeline`/`feature_pipeline_overrides`.
- **Возможные улучшения / техдолг:**
  - Загрузка групп через реестр YAML (читать `conf/sport/<sport>.yaml` напрямую), убрать `_FALLBACK_SPORT_GROUPS` — устранит дублирование, но потребует аккуратной интеграции с Hydra.
  - Расширить механизм групп: помимо `nhl_boxscore` / `streak` поддержать произвольные группы через конфиг (ключ → список YAML-фрагментов), без хардкода в коде.
  - Football и basketball YAML — пока заглушки без `form_params`, `rolling_context_names`, `target_sources`; при появлении данных потребуется полное заполнение по образцу `cyberhockey.yaml`.

### 2026-05-09 — R30: расхождение «y по голам» vs `y_true` (закрыто → `done_task/R30.md`)

- **Задача:** `backlog/R30.md` → `done_task/R30.md` (критический фикс выполнен; R30.1–R30.4 не делались — ниже как опциональный техдолг)
- **Ограничения и компромиссы:**
  - Корневая причина: в `trainer.py` после сортировки по времени таргет не переиндексировался по `sort_order` (`iloc[RangeIndex]`). Исправлено; регрессия `tests/test_trainer_target_sort_alignment.py`.
  - CSV `test_bet_trace.csv`, сгенерированный до фикса, исторически неверен относительно голов — перезапустить `train` для нового артефакта.
- **Возможные улучшения / техдолг (не блокируют закрытие R30):**
  - **R30.1** — колонка `target_from_goals` в trace + assert/флаг `betting.strict_trace_target_check`.
  - **R30.2** — отдельный тест на сэмпле parquet + hydra (частично перекрыто `test_trainer_target_sort_alignment` + существующими target-тестами).
  - **R30.3** — интеграция: прочитать сохранённый CSV и сравнить с голами.
  - **R30.4** — короткая заметка про Excel и строки вида `4-1` как даты.

### 2026-05-09 — Отбор ставок по edge вместо EV (беттинг-симулятор)

- **Задача:** вне бэклога — отбор ставок по `p_model - p_implied`, порог `min_edge_threshold`.
- **Ограничения и компромиссы:**
  - Значение по умолчанию `0.05` в конфиге раньше интерпретировалось как порог EV; теперь это порог edge в долях вероятности — сопоставимость с историческими прогонами MLflow нарушена без перекалибровки порога.
  - Прямой вызов `BettingSimulator(min_value_threshold=...)` больше не работает; в Hydra остаётся fallback в `trainer.py` на ключ `min_value_threshold`.
  - Имена MLflow-метрик sweep (`sweep_ev_real_thr_*` и т.д.) по-прежнему содержат «ev» в названии, хотя ось порога теперь edge.
- **Возможные улучшения / техдолг:**
  - Опциональный `selection_mode: edge | ev` в `conf/betting.yaml` для A/B без дублирования кода.
  - Deprecated-аргумент `min_value_threshold` в `BettingSimulator.__init__` с предупреждением в лог.
  - Переименовать sweep-метрики в MLflow при согласовании с потребителями дашбордов.

### 2026-05-10 — Optuna: имя SQLite-study, Hydra `pruner`/`sampler` = null, user_attrs по trial

- **Задача:** вне бэклога — накопление trials в одном study при смене train/holdout; падение на `hyper.pruner=null`; диагностика trial-level TSCV в MLflow.
- **Ограничения и компромиссы:**
  - Суффикс имени study строится из `train_eval_split`, `split`, `inner_train_rows`, `features.name`, `hyper.metric`, seed сэмплера и опционально `hyper.optuna_study_tag`. Если меняется только содержимое parquet при тех же сезонах и том же числе строк inner train, хэш не меняется — для принудительно нового study задать `hyper.optuna_study_tag` или изменить конфиг/объём выборки.
  - `MedianPruner` без пошагового `trial.report` по фолдам остаётся слабым; `pruner=null` отключает обрезку полностью.
  - Бизнес-метрики по-прежнему только на финальной модели, не на каждый Optuna trial.
- **Возможные улучшения / техдолг:**
  - В fingerprint опционально включать контрольную сумму/версию датасета (DVC `md5`, mtime), если нужно различать пересборку данных без смены `inner_train_rows`.
  - Реальный pruning: `trial.report` + `HyperbandPruner` или отчёт по фолдам TSCV.

### 2026-05-11 — R35: block bootstrap CI на bet trace

- **Задача:** `backlog/R35.md` → `done_task/R35.md`
- **Ограничения и компромиссы:**
  - `BootstrapResult.summary_dataframe()` вместо `summary()` как в pseudocode spec — незначительное расхождение имени метода, обратно совместимо.
  - Percentile bootstrap (не BCa): при малом числе ставок (<50) CI может быть смещён; BCa потребовал бы jack-knife pass (O(n·B) вместо O(B)).
  - `_compute_metrics_for_resample` полностью пересчитывает drawdown per-resample с O(n) loop — при B=5000, n=2000 это 10M итераций Python; для CI drawdown достаточно, но при B>10k стоит перейти на векторизованный cumsum.
  - Sharpe-like считается по прибыли в единицах стека (не в долях ROI) — соответствует spec, но не стандартному annualised Sharpe; сопоставимость с внешними источниками ограничена.
  - `n_bets` в bootstrap — это всегда `n` (размер resample = размер оригинала), поэтому CI для `n_bets` всегда вырождается в точку; метрика сохранена ради полноты API.
- **Возможные улучшения / техдолг:**
  - Добавить метод `result.summary()` как алиас `summary_dataframe()` для соответствия pseudocode spec.
  - BCa или студентизированный bootstrap для более корректных CI при малом n.
  - Векторизовать расчёт max_drawdown (numpy cumsum + running max) для ускорения при B>5000.
  - Опциональный `mode: parametric | block` в конфиге — параметрический бутстрап для конкретных распределений (Bernoulli win + Beta odds) как альтернатива.
  - Аннотировать MLflow metrics `_se` (стандартная ошибка) для сравнения разброса между экспериментами.

### 2026-05-11 — вне бэклога: fix betting_coverage для long-format

- **Задача:** вне бэклога — fix `BettingSimulator.coverage` для long-format (`rows_per_event=2`)
- **Ограничения и компромиссы:**
  - `coverage` при `coverage_rows_per_event=2` — аппроксимация: предполагается **фиксированное** количество строк на событие. Если для какого-то события в odd-фиде отсутствует одна из строк (например, нет коэффициента на одну сторону), знаменатель сместится и `coverage` окажется чуть завышен.
  - Симулятор не получает `event_id`; истинная доля «событий хотя бы с одной ставкой» была бы точнее, но потребовала бы изменения сигнатуры `simulate()` и всех вызывающих слоёв.
  - Константа `2` жёстко вшита в caller-код (`trainer.py`, `runner.py`) через тернарник; при появлении форматов с `rows_per_event ≠ 2` нужно будет расширить логику.
- **Возможные улучшения / техдолг:**
  - Вместо `coverage_rows_per_event: int` принимать `event_ids: np.ndarray | None` и считать `n_events_with_bet / n_unique_events` — точная метрика без допущения о равномерном распределении строк.
  - Вынести `rows_per_event` в конфиг (`features.long_rows_per_event: int = 1`) вместо жёсткого `2` в caller-коде; тогда добавление формата 3-way long не потребует правки trainer/runner.

### 2026-05-11 — R34: walk-forward simulation

- **Задача:** `backlog/R34.md` → `done_task/R34.md`
- **Ограничения и компромиссы:**
  - Реализована только частота `month`; `week` / day из черновика конфига не поддержаны кодом.
  - `WalkForwardConfig` — dataclass для документации; строгой регистрации в Hydra `ConfigStore` в репозитории нет (как и для других групп).
  - При `walk_forward.enabled` и `apply_selected_to_fit` снимок `metrics_full` (`*_full_*`) не логируется — осознанный компромисс против подмены статического holdout.
  - `_business_metrics_from_walk_forward` подгоняет словарь под контракт `_log_business_metrics_to_mlflow`: часть полей (например sweep/cal по ставкам) заполняется нулями/пустыми значениями, если их нет в агрегате cumulative trace.
  - Фичи на шагах WF не регенерируются; допущение «нет утечки» держится на том, что pipeline уже посчитал признаки только из прошлого относительно строки.
- **Возможные улучшения / техдолг:**
  - Добавить `frequency: week` (и при необходимости day) в slicer + конфиг.
  - Зарегистрировать `walk_forward` в `ConfigStore`, если проект перейдёт на единый struct для всех групп.
  - Богаче маппить cumulative betting → MLflow business block (sweep, cal-binning) без заглушек, если появятся требования к дашбордам.
  - Отдельный коммит для черновиков `R35.md`/`R36.md` и строк в `todo-refactor.md`, если эпики формализуются (в коммит R34 они не включались).

### 2026-05-11 — R36: experiment matrix (Hydra commands)

- **Задача:** `backlog/R36.md` → `done_task/R36.md`
- **Ограничения и компромиссы:**
  - Scheme B не запускалась в полном объёме по всем 8 турнирам (ресурсоёмко); верификация проведена только на `nhl` smoke с `n_resamples=100`. Команды для остальных турниров — незапущенные шаблоны; корректность их конфигов (наличие odds, нужных `market`/`market_spec`) не проверялась автоматически.
  - `dummy` в Scheme B (WF-путь) обозначен обязательным с оговоркой «при несовместимости смотреть лог»: поведение `DummyClassifier` внутри `WalkForwardRunner` зависит от реализации R34 и не покрыто отдельным тестом для WF-режима.
  - `stacking` вынесен как опциональный и не включён в матрицу; если он будет задействован, матрицу потребуется расширить.
- **Возможные улучшения / техдолг:**
  - Добавить Makefile-цели `make train-scheme-a` / `make train-scheme-b` с multirun по всем турнирам — чтобы матрица стала исполняемой, а не только документированной.
  - Smoke CI (GitHub Actions): выполнять `--cfg job --resolve` для Scheme A + Scheme B на `nhl` при каждом PR — гарантия, что overrides не сломались после изменений в `conf/`.
  - Зафиксировать допустимые значения `walk_forward.frequency` (сейчас только `month`) в таблице R36.1, чтобы при добавлении `week` было ясно, что команды в матрице устарели.

### 2026-05-13 — R37.1: локальный operational runbook (Sphinx)

- **Задача:** `backlog/R37.md` (подзадача **R37.1** выполнена) → см. `done_task/R37.1.md` (эпик R37 продолжается в бэклоге).
- **Ограничения и компромиссы:**
  - Заголовок раздела сфокусирован на NHL и общем стеке; при выполнении R15 возможна консолидация с более широким `operations.rst` без дублирования текстов.
  - Инструкция открыть `/docs` использует ``xdg-open`` (ориентир на типичный Linux desktop); macOS и Windows пользователям нужны эквиваленты (`open`, браузер вручную).
- **Возможные улучшения / техдолг:**
  - Одна строка «для macOS: `open http://127.0.0.1:8000/docs`» / «Windows: браузер вручную» — без усложняения RST.


### 2026-05-13 — R37.3: edge decision и `service_api.yaml`

- **Задача:** `backlog/R37.md` (подзадача **R37.3**) → `done_task/R37.3.md` (эпик R37 остаётся 🟡 в `todo-refactor.md`).
- **Ограничения и компромиссы:**
  - Узел `conf/service_api.yaml` читается отдельным загрузчиком (`yaml.safe_load` + `lru_cache`), а не через основной Hydra `ConfigStore` сервиса; унификация с остальным `conf/` возможна позже вместе с R37.5.
  - Формула `p_implied = 1/odds` локализована в `edge_decision.py`; в `betting/odds.py` нет общей функции implied — дублирование идеи минимальное, парсинг raw сосредоточен в `odds.py` как и требовалось.
  - Тесты проверяют `load_edge_decision_params` с env-override; отдельного теста «значения строго из файла без env» нет.
- **Возможные улучшения / техдолг:**
  - При появлении единого FastAPI/Hydra контекста — подключить `service_api` к тому же механизму, что и прочие runtime-настройки.
  - Опционально экспортировать `implied_probability_from_decimal` из одного места (общий util), если появятся ещё потребители кроме симулятора и API.

### 2026-05-13 — R37.4: live Pinnacle NHL (`live_nhl_pinnacle`)

- **Задача:** `backlog/R37.md` (подзадача **R37.4**) → `done_task/R37.4.md` (эпик R37 остаётся 🟡 в `todo-refactor.md`).
- **Ограничения и компромиссы:**
  - Используются приватные хелперы `_find_bookmaker` и `_h2h_prices` из `enrichment.py`; сцепка с внутренним контрактом enrichment при рефакторинге потребует синхронизации или публичного API.
  - Live-снимок опирается на рынок API `h2h` (decimal двух исходов); связка с семантикой `winner_withOT` в train-контуре не проверяется отдельно — предполагается согласованность с профилем Pinnacle в конфиге.
  - Автомаппинг без `commence_utc` у референса разрешается только при единственном кандидате по командам; иначе возвращается `None`.
- **Возможные улучшения / техдолг:**
  - Вынести разбор Pinnacle h2h в публичную функцию слоя `enrichment` или общий util, чтобы не импортировать `_`-символы.
  - Добавить в `test_odds_config.py` явную валидацию схемы `live_inference` (типы ключей, неотрицательный tolerance).
  - Метрики/логирование unmatched `match_id` на уровне INFO при операционном использовании (без утечки секретов).

### 2026-05-13 — R37.5: публичный prediction payload + live enrichment в GET

- **Задача:** `backlog/R37.md` (подзадача **R37.5**) → `done_task/R37.5.md` (эпик R37 остаётся 🟡 в `todo-refactor.md`).
- **Ограничения и компромиссы:**
  - Обогащение завязано на `pred.market` в `("winner", "winner_withOT")`; если в витрине когда-либо окажется только `market_spec` с moneyline при другом `market`, строка может получить `skipped_unsupported_market`.
  - Внутренний кэшируемый путь `get_prediction_cached` не подмешивает live-поля (всегда `null`) — контракт типов совпадает, продуктовое обогащение только на публичных GET без кэша.
  - Покрытие тестами — уровень `live_odds_enrichment` и регрессия репозитория; отдельного ASGI-теста на OpenAPI query `live_pinnacle` нет.
- **Возможные улучшения / техдолг:**
  - Опциональная колонка БД / миграция для снапшота live-котировок на момент materialize (audit, отключение внешнего вызова на горячем GET).
  - E2E или роутер-тест с `TestClient` для smoke цепочки `/predict/...` + mock `batch_live_response_extras`.

### 2026-05-13 — R37.6: DAG `nhl_morning_refresh`

- **Задача:** `backlog/R37.md` (подзадача **R37.6**) → `done_task/R37.6.md` (эпик R37 остаётся 🟡 в `todo-refactor.md`).
- **Ограничения и компромиссы:**
  - `max_active_runs` / `max_active_tasks` читаются из `SF_NHL_MORNING_*`, а не из тех же имён, что `data_refresh` (`SF_REFRESH_MAX_ACTIVE_*`); значения по умолчанию совпадают (1), но в Airflow нужно помнять про два набора переменных при тюнинге.
  - Инкремент odds в цепочке зависит от `odds.enabled` в source-конфиге турнира; при выключенном post-step утренний контур не добавляет отдельной задачи odds.
- **Возможные улучшения / техдолг:**
  - По желанию унифицировать переменные параллелизма с `data_refresh` (один источник правды) или задокументировать политику в centralized ops-листе Variables.

### 2026-05-13 — R39.1: операционный e2e-контракт (runbook + env / секреты)

- **Задача:** `backlog/R39.md` (подзадача **R39.1**) → `done_task/R39.1.md` (эпик R39 остаётся 🟡 в `todo-refactor.md`).
- **Ограничения и компромиссы:**
  - Контракт digest (шаг после `validate` в DAG) описан как **целевой**; фактической задачи в коде DAG до **R39.5** ещё нет — документировано явно в `nhl_local_operations.rst`.
  - В `airflow/docker-compose.airflow.yml` переменные `ODDS_API_KEY` и `BOT_*` из хостового `.env` по умолчанию **не** проброшены в сервисы Airflow — для полной parity оператору понадобится ручное добавление (ожидается в R39.5/R39.6).
- **Возможные улучшения / техдолг:**
  - После появления digest: добавить `environment`/`env_file` для Airflow-сервисов (как в runbook), без логирования значений секретов.

### 2026-05-13 — R39.2: модуль live moneyline extras (betting vs FastAPI)

- **Задача:** `backlog/R39.md` (подзадача **R39.2**) → `done_task/R39.2.md` (эпик R39 остаётся 🟡 в `todo-refactor.md`).
- **Ограничения и компромиссы:**
  - `LiveMoneylinePredictionInput` задан как structural `Protocol`; статическая проверка совпадения с ORM `Prediction` отсутствует (duck typing).
  - Паритет с enrichment проверен unit-тестами на синтетических объектах и существующими тестами `live_odds_enrichment`, без отдельного golden-снимка полного HTTP-ответа.
- **Возможные улучшения / техдолг:**
  - При росте числа потребителей контракта — явный type alias `PredictionLike` рядом с ORM или runtime-валидатор минимального набора полей.

### 2026-05-13 — R39.3: модуль текста Telegram digest

- **Задача:** `backlog/R39.md` (подзадача **R39.3**) → `done_task/R39.3.md` (эпик R39 остаётся 🟡 в `todo-refactor.md`).
- **Ограничения и компромиссы:**
  - Лимит «краткого» перечисления матчей задан константой `brief_limit = 5` в `build_post_refresh_digest_text` без параметра конфигурации.
  - Golden-тесты покрывают `missing_api_key`, но не отдельный снимок для `fetch_failed` (текст ветки проще, дублирует структуру предупреждения).
- **Возможные улучшения / техдолг:**
  - Вынести `brief_limit` в аргумент с дефолтом 5 или в общий «telegram digest» config для согласования с лимитами сообщения.
  - При необходимости — один компактный golden на `fetch_failed` и/или на непустой `header`.
