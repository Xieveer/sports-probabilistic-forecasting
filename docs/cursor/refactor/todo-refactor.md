# TODO Refactor — Sports Probabilistic Forecasting

> Задачи рефакторинга по результатам полного аудита проекта.
> Создано: 2026-03-07

---

## Приоритизация

| Задача | Критичность | Сложность | Статус | Рекомендуемый порядок |
|--------|-------------|-----------|--------|----------------------|
| R1     | 🔴 High     | Medium    | ✅     | 1-й ✅               |
| R3     | 🟢 Low      | Trivial   | ✅     | 2-й ✅               |
| R7     | 🟢 Low      | Trivial   | ✅     | 3-й ✅               |
| R6     | 🟢 Low      | Low       | ✅     | 4-й ✅               |
| R8     | 🔴 High     | Trivial   | ✅     | 5-й ✅               |
| R9     | 🟡 Medium   | Medium    | ✅     | 6-й ✅ (R9.1-3 fix, R9.4 verified no-change)|
| R2     | 🟡 Medium   | Medium    | ✅     | 7-й ✅               |
| R10    | 🟡 Medium   | Medium    | ✅     | 8-й ✅                    |
| R11    | 🟢 Low      | Trivial   | ✅     | 11-й ✅               |
| R12    | 🟡 Medium   | Medium    | ✅     | 12-й ✅ (winner full cycle) |
| R13    | 🔴 High     | Medium    | ✅     | 13-й ✅ (архитектурное выравнивание, все R13.1–R13.7) |
| R5     | 🟡 Medium   | High      | 🟡     | 9-й (объёмный)       |
| R4     | 🟡 Medium   | High      | 🟡     | 10-й (зависит от R5) |
| R14    | 🔴 High     | Medium    | ✅     | 14-й ✅ (source-адаптеры, SourceProvider pattern) |
| R15    | 🟡 Medium   | Low       | 🟡     | 15-й (операционное руководство) |
| R16    | 🟡 Medium   | Medium    | 🟡     | 16-й (MLflow сравнительная визуализация) |
| R17    | 🔴 High     | High      | ✅     | 17-й ✅ (NHL Web API провайдер данных) |
| R18    | 🔴 High     | Medium    | ✅     | 18-й ✅ (lp_eu_a18: Optuna reg + feature selection) |
| R19    | 🔴 High     | High      | ✅     | 19-й ✅ (NHL production + Odds API + Telegram-бот; R19.11-R19.12 — операционно; stretch R19.17-R19.20 отложены) |
| R20    | 🔴 High     | High      | ✅     | 20-й ✅ (Pinnacle odds: backfill 3 сезонов + инкрементальный автоапдейт) |
| R21    | 🔴 High     | High      | ✅     | 21-й ✅ (Multi-bookmaker V3 + логи; R21.13 реестр — частично по unmatched) |
| R22    | 🔴 High     | Medium    | 🟡     | 22-й (NHL baseline + OT + фичи ✅; R22.7 открыта — откат `pinnacle_holdout`, см. R26) |
| R23    | 🔴 High     | High      | ✅     | 23-й ✅ (CI/CD, секреты, prod deploy, observability, refresh) |
| R24    | 🟡 Medium   | Medium    | 🟡     | 24-й (Telegram UX: меню, подписки, admin, polish) |
| R25    | 🟡 Medium   | High      | 🟡     | 25-й (NHL: team stats, player props, lineup-driven inference; после R22 baseline) |
| R26    | 🟡 Medium   | High      | ✅     | 26-й ✅ (единый контракт odds → беттинг-метрики в train; NHL + merge-источники) |
| R27    | 🔴 High     | High      | ✅     | 27-й ✅ (NHL FE v2: goals/stats EWM, streaks, lineup continuity/seniority) |
| R28    | 🟡 Medium   | Medium    | ✅     | 28-й ✅ (семантические алиасы колонок в rolling-контекстах; параллельно R27) |

---

## Задачи

### Выполненные ✅

- [x] **R1** — Исправить именование участников в конфигах и long format
- [x] **R2** — Ревизия контекстных колонок и multi-metric EWM
- [x] **R3** — Унифицировать datetime API (utcnow → timezone-aware)
- [x] **R6** — Проверить и почистить stacking config
- [x] **R7** — Удалить устаревший `tournament/all.yaml`
- [x] **R8** — Исправить `fillna(0)` для int-колонок в `_apply_dtype_conversion`
- [x] **R9.1** — `ewm_generator.py` — `fillna(0.0)` в EWM-цепочке
- [x] **R9.2** — `mutual_info_ranker.py` — `X.fillna(0)` перед MI scoring
- [x] **R9.3** — `selector.py` — агрегация рангов/скоров с fillna
- [x] **R9.4** — `logreg.py` — `SimpleImputer(strategy="mean")` оставлено как есть (верификация, без изменений кода); см. `done_task/R9.4.md`
- [x] **R11** — Исправить PerformanceWarning о фрагментации DataFrame в long_to_wide
- [x] **R10** — Исправить порядок генераторов и расхождение в количестве фичей (R10.3 сводка, R10.5 проверка, R10.6 исследование; R10.4 пропущено)
- [x] **R12.4** — Обучение winner: uel_kz_1 + lp_ru, catboost/lgbm/logreg/stacking, features=advanced; MLflow; см. `done_task/R12.4.md`
- [x] **R12.5** — Выполнено в рамках R12.4 (lp_ru в том же multirun); см. `done_task/R12.5.md`
- [x] **R12** — Полный цикл winner (uel_kz_1 + lp_ru): данные → обучение → promote → materialize; см. `docs/cursor/refactor/done_task/R12.md`, `done_task/R12.*.md`
- [x] **R12.6** — Promote compare в MLflow (`{tournament}__winner__player`); см. `done_task/R12.6.md`
- [x] **R12.7** — Materialize logreg/advanced + миграция SQLite `model_tag`; см. `done_task/R12.7.md`
- [x] **R13.1** — Добавлен validate-этап в `data_refresh` DAG (`ingest → clean → features → validate`) и зафиксирован fail-fast контракт; см. `done_task/R13.1.md`
- [x] **R13.2** — Materialize переведён на promoted-контракт (`deploy.yaml`/метаданные) вместо DAG `algorithm/features`; см. `done_task/R13.2.md`
- [x] **R13.4** — Зафиксирован operational-контракт DVC по средам (`prod/dev/CI`) в архитектурной документации; см. `done_task/R13.4.md`
- [x] **R13.5** — Декомпозирован refresh-контур по турнирам (`source → ingest → clean → features → materialize`) с политикой конкуренции (`pool/lock/max_active_runs`) и контрактом source-stage; см. `done_task/R13.5.md`
- [x] **R13.6** — Разделён публичный (`/predict`, тег `predictions`) и операционный (`/internal/predict`, тег `operations`) слои FastAPI: контракт в коде и документации; см. `done_task/R13.6.md`
- [x] **R13.7** — Добавлены 7 smoke/integration acceptance тестов для оркестрационного контура (Makefile CLI chain, Hydra --help, DAG source contracts); см. `done_task/R13.7.md`
- [x] **R13** — Полное выравнивание реализации с Service & Orchestration Architecture (все R13.1–R13.7); см. `done_task/R13.md`
- [x] **R14** — Source-адаптеры: паттерн `SourceProvider` (R14.1–R14.7); см. `done_task/R14.md`
  - [x] R14.1 — ABC `SourceProvider` (контракт провайдера)
  - [x] R14.2 — `FileSourceProvider` (извлечь текущую CSV-логику)
  - [x] R14.3 — `ProviderRegistry` + фабрика `get_provider()`
  - [x] R14.4 — Адаптировать `ingest.py` под провайдерный интерфейс
  - [x] R14.5 — `HttpApiSourceProvider` (proof-of-concept)
  - [x] R14.6 — Обновить HOW_TO_ADD_NEW_TOURNAMENT.md (шаг 2а + кастомный провайдер)
  - [x] R14.7 — Unit-тесты для провайдеров (9 тестов)
- [x] **R17** — NHL Web API: провайдер `nhl_web_api`, конфиги ice_hockey/source/tournament, тесты; см. `done_task/R17.md`
  - [x] R17.1 — `NhlApiClient`
  - [x] R17.2 — Schedule scanner
  - [x] R17.3 — Boxscore / PBP
  - [x] R17.4 — Standings по дате
  - [x] R17.5 — Roster (травмы — заглушка)
  - [x] R17.6 — `NhlDataAssembler` + checkpoint
  - [x] R17.7 — `NhlWebApiSourceProvider` + registry
  - [x] R17.8 — Конфигурация + комментарий в `dvc.yaml`
  - [x] R17.9 — Unit-тесты
- [x] **R18** — lp_eu_a18: Optuna (регуляризация), feature selection, `apply_selected_to_fit`; см. `done_task/R18.md`
  - [x] R18.1 — Конфиги `catboost_reg` / `lgbm_reg`
  - [x] R18.2 — MLflow flavor для `*_reg`
  - [x] R18.3 — Прогон train + Optuna (операционно)
  - [x] R18.4 — Прогон feature selection (операционно)
  - [x] R18.5 — Prod на подмножестве: `apply_selected_to_fit`
- [x] **R19** — NHL production + Odds API + Telegram-бот; см. `done_task/R19.md`
  - [x] R19.1 — Инкрементальный режим NhlDataAssembler
  - [x] R19.2 — Source-refresh NHL в Airflow DAG
  - [x] R19.3 — Расширены clean-колонки NHL + Pandera-схема
  - [x] R19.4 — NHL в DVC features multirun
  - [x] R19.5 — OddsApiClient (quota, retry, кэш)
  - [x] R19.6 — Odds backfill (идемпотентно, 2–3 сезона)
  - [x] R19.7 — Odds enrichment → source.csv (не в фичи)
  - [x] R19.8 — NhlScheduleFeatureGenerator (schedule density, fatigue)
  - [x] R19.9 — NhlStandingsFeatureGenerator (standings, form)
  - [x] R19.10 — NhlRosterFeatureGenerator (MVP)
  - [ ] R19.11 — *(операционно)* NHL baseline training sweep + promote → **R22.2**
  - [ ] R19.12 — *(операционно)* NHL materialize + API verification → **R22.3**
  - [x] R19.13 — Bot scaffolding (aiogram 3, auth middleware, /start /help)
  - [x] R19.14 — Бот: /predict, /upcoming (inline keyboard)
  - [x] R19.15 — Бот: /status, /refresh, /models (admin guard)
  - [x] R19.16 — Бот: systemd unit, make bot-dev/bot-up
  - [ ] R19.17 — *(stretch)* Travel-фичи → **R22.5**
  - [ ] R19.18 — *(stretch)* Motivation/playoff context → **R22.6**
  - [ ] R19.19 — *(stretch)* Оценка vs Pinnacle на holdout → **R22.7**
  - [ ] R19.20 — *(stretch)* Injury report → по возможности в **R22.4**

- [x] **R20** — Pinnacle odds: историческая загрузка + инкрементальный refresh; операционный backfill 3 сезонов ✅ 2026-04-26; см. `docs/cursor/refactor/done_task/R20.md`, `done_task/R20.8.md`
- [x] **R21** — Multi-bookmaker V3 (R21.10–R21.14) + операционный re-backfill ✅ 2026-04-26; см. `docs/cursor/refactor/done_task/R21.md`, `done_task/R21.9.md` (R21.13: реестр + док; доразметка по `unmatched` — по мере необходимости)
- [x] **R26** — Единый контракт odds для беттинг-метрик в `train` (как UEL/LP), NHL через реестр + merge + конфиг букмекера ✅ 2026-05-03; см. `done_task/R26.md`
  - [x] R26.1 — YAML-контракт: `the_odds_api` / synthetic `odds_raw` vs `wide_columns` + обоснование в эпике
  - [x] R26.2 — Данные: `select_columns` / clean — odds в processed long + вне фич
  - [x] R26.3 — `betting/odds.py`: `winner_withOT` long + общий entrypoint; тесты (в т.ч. long decimal, wide transport)
  - [x] R26.4 — Hydra: `nhl` / `nhl_train` defaults `bookmaker` ≠ fonbet (`apply_tournament_default_bookmaker`)
  - [x] R26.5 — `trainer.py`: вызов общего извлечения odds, логи покрытия, zero-coverage warn
  - [x] R26.6 — `HOW_TO_ADD_NEW_TOURNAMENT.md` раздел Odds (dict vs merge wide)
- [x] **R28** — Унификация rolling-контекстов через семантические алиасы колонок ✅ 2026-05-04; см. `done_task/R28.md`
- [x] **R27** — NHL Feature Engineering v2: goals/stats EWM, streaks, lineup continuity/seniority ✅ 2026-05-04; см. `done_task/R27.md`
  - [x] R27.1 — Derived metric columns в `long_format.py` (goals_full_diff/total, sog/bs/hits/pim2/fow diff)
  - [x] R27.6 — Spans [5,25,100] → [5,15] в `standard.yaml`
  - [x] R27.2 — `ewm_metrics` + `ewm_spans` в `conf/sport/ice_hockey.yaml`
  - [x] R27.3 — `inject_sport_ewm_generators` в `rolling_contexts.py`
  - [x] R27.5 — `StreakFeatureGenerator` — серии + win rate
  - [x] R27.7 — Inseason context ✅ (в R28.2)
  - [x] R27.9 — Lineup continuity (Jaccard), seniority, stability
- [x] **R23** — CI/CD, секреты, prod deploy, observability, refresh ✅ 2026-05-03; см. `done_task/R23.md`
  - [x] R23.1 — GitHub Actions: lint + test on PR (ci.yml, Python 3.10/3.12, uv cache)
  - [x] R23.2 — GitHub Actions: Docker build + push ghcr.io (docker.yml, api/worker/telegram-bot)
  - [x] R23.3 — `.env.example` + `docs/deploy/secrets.md` (GitHub Secrets vs VPS .env)
  - [x] R23.4 — GitHub Actions: deploy hook SSH + workflow_dispatch (deploy.yml)
  - [x] R23.5 — `docker-compose.prod.yml`: limits, log rotation, node-exporter, caddy
  - [x] R23.6 — Reverse proxy + HTTPS: Caddy 2, Let's Encrypt, basicauth Grafana/MLflow
  - [x] R23.7 — Observability prod: prometheus.prod.yml, api_slo alerts, Grafana panels
  - [x] R23.8 — Scheduled data refresh: `cron_refresh.py` + shell wrapper + unit tests

### В работе / Backlog 🟡

- [ ] **R4** — Реализовать рабочий monitoring DAG
  - [ ] R4.1 — Изучить модули мониторинга
  - [ ] R4.2 — Реализовать полноценную `check_model_quality()`
  - [ ] R4.3 — Определить источник «фактических результатов»
  - [ ] R4.4 — Исправить `_decide_retrain`
  - [ ] R4.5 — Добавить интеграцию drift detection
  - [ ] R4.6 — Протестировать DAG в изоляции

- [ ] **R5** — Тесты: покрытие service layer + 90%+ coverage target
  - [ ] R5.1 — Unit-тесты для `PredictionRepository`
  - [ ] R5.2 — Unit-тесты для DB engine
  - [ ] R5.3 — Unit-тесты для Pydantic schemas
  - [ ] R5.4 — Тесты для `materialize.py`
  - [ ] R5.5 — Тесты для FastAPI endpoints
  - [ ] R5.6 — Измерить покрытие, довести до 90%+
  - [ ] R5.7 — Рассмотреть интеграционные / e2e тесты


- [ ] **R15** — Операционное руководство: запуск, обучение, деплой
  - [ ] R15.1 — Написать `docs/source/operations.rst` (полный гайд)
  - [ ] R15.2 — Добавить в toctree `index.rst`
  - [ ] R15.3 — Ревизия `quickstart.rst` на консистентность
  - [ ] R15.4 — Smoke-check сборки docs

- [ ] **R16** — MLflow: сравнительная визуализация метрик по запускам
  - [ ] R16.1 — Добавить теги `sweep_id` и `run_index` в trainer
  - [ ] R16.2 — Стандартизировать именование экспериментов (контракт)
  - [ ] R16.3 — Скрипт `scripts/mlflow_compare.py` (CLI + chart)
  - [ ] R16.4 — Makefile-цель `make compare`
  - [ ] R16.5 — Расширить скрипт: multi-metric subplots, best-run highlight
  - [ ] R16.6 — *(Опционально)* Grafana dashboard JSON
   - [ ] R16.7 — Документировать workflow сравнения

- [ ] **R22** — NHL: R22.1–R22.6, R22.8 ✅; **R22.7** открыта (откат `pinnacle_holdout`); см. `docs/cursor/refactor/done_task/R22.md`, план замены — **R26**
  - [x] R22.1 — Конфиг NHL training (split, target, алгоритм, features) ✅ 2026-05-03
  - [x] R22.2 — NHL baseline training sweep + promote (субсуммирует R19.11) ✅ 2026-05-03
  - [x] R22.3 — NHL materialize + API verification (субсуммирует R19.12) ✅ 2026-05-03
  - [x] R22.4 — *(stretch)* Расширенные roster-фичи (top-N агрегаты, goalie proxy, injury count; TOI отложен — нет в API) ✅ 2026-05-03
  - [x] R22.5 — *(stretch)* Travel / rest (км между аренами, сдвиг TZ; `NhlScheduleFeatureGenerator`) ✅ 2026-05-04
  - [x] R22.6 — *(stretch)* Motivation / playoff context ✅ 2026-05-04
  - [ ] R22.7 — *(stretch)* Оценка vs Pinnacle / betting на holdout *(откат standalone CLI; реализация — R26 или отдельное решение)*
  - [x] R22.8 — Рынки NHL: `winner_withOT`, `total_withOT` (параллельно основному времени) ✅ 2026-05-03

- [ ] **R24** — Telegram UX (меню, подписки, admin, polish); см. `backlog/R24.md`
  - [ ] R24.1 — Inline-меню и навигация
  - [ ] R24.2 — Уведомления по расписанию (subscribe / digest)
  - [ ] R24.3 — Safe admin boundaries (/retrain, /logs, /health)
  - [ ] R24.4 — Error handling + UX polish

- [ ] **R25** — NHL: team stats, player props, lineup-driven inference; см. `backlog/R25.md`
  - [ ] R25.1 — Аудит boxscore-колонок (PP goals и пр.)
  - [ ] R25.2 — Target sources для team stats в ice_hockey.yaml
  - [ ] R25.3 — Market family & spec configs для team stats
  - [ ] R25.4 — Training config для ≥2 team stat markets
  - [ ] R25.5 — Baseline sweep team stats + promote + materialize
  - [ ] R25.6 — Player prop data schema (player × game grain)
  - [ ] R25.7 — Player prop targets + market family/spec
  - [ ] R25.8 — PlayerRollingFeatureGenerator
  - [ ] R25.9 — Training config + baseline sweep для player props
  - [ ] R25.10 — Player prop materialize + API endpoint
  - [ ] R25.11 — ABC LineupProvider (контракт)
  - [ ] R25.12 — Реализация lineup provider (3rd-party сервис)
  - [ ] R25.13 — Protocol refresh job (T-60m)
  - [ ] R25.14 — Lineup diff + событие lineup_changed
  - [ ] R25.15 — Rematerialize policy (конфиг, пороги)
  - [ ] R25.16 — Delta materialize pipeline
  - [ ] R25.17 — API invalidation при re-materialize
  - [ ] R25.18 — Telegram hook «lineup locked» (контракт → R24)

---

## Ссылки на детали

Детальное описание каждой задачи находится в:
- **Backlog:** `docs/cursor/refactor/backlog/R*.md` — незавершенные задачи
- **Done:** `docs/cursor/refactor/done_task/R*.md` — завершенные задачи
- **Техдолг и идеи после ревью:** `docs/cursor/refactor/backlog/reviewer-tech-debt.md` — накопительный журнал (ограничения, компромиссы, возможные улучшения по итогам успешного ревью; не путать с Rework). Процесс: цикл Worker → Reviewer в `.cursor/skills/worker-reviewer-loop/SKILL.md` и роль Reviewer в `.cursor/agents/reviewer.md`.
