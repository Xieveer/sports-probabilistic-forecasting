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
| R13    | 🔴 High     | Medium    | 🟡     | 13-й (архитектурное выравнивание) |
| R5     | 🟡 Medium   | High      | 🟡     | 9-й (объёмный)       |
| R4     | 🟡 Medium   | High      | 🟡     | 10-й (зависит от R5) |

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

### В работе / Backlog 🟡

- [ ] **R13** — Выравнивание реализации с Service & Orchestration Architecture
  - [x] R13.1 — Добавить validate-этап в `data_refresh` DAG и fail-fast контракт
  - [x] R13.2 — Перевести materialize на явный promoted-контракт (`deploy.yaml`/метаданные)
  - [x] R13.3 — Исправить promote в `training_sweep` для мульти-турнирного режима
  - [x] R13.4 — Зафиксировать operational-контракт DVC по средам (prod/dev/CI)
  - [x] R13.5 — Ввести инкрементальную декомпозицию по турнирам + политику конкуренции
  - [ ] R13.6 — Разделить read-only API и операционные endpoint-ы на уровне контракта
  - [ ] R13.7 — Добавить smoke/integration acceptance для оркестрационного контура

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

---

## Ссылки на детали

Детальное описание каждой задачи находится в:
- **Backlog:** `docs/cursor/refactor/backlog/R*.md` — незавершенные задачи
- **Done:** `docs/cursor/refactor/done_task/R*.md` — завершенные задачи
