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
| R9     | 🟡 Medium   | Medium    | ✅     | 6-й ✅ (R9.1-3 fix, R9.4 skip)|
| R2     | 🟡 Medium   | Medium    | ✅     | 7-й ✅               |
| R10    | 🟡 Medium   | Medium    | 🟡     | 8-й (порядок генераторов) |
| R11    | 🟢 Low      | Trivial   | ✅     | 11-й ✅               |
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
- [x] **R11** — Исправить PerformanceWarning о фрагментации DataFrame в long_to_wide

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

- [ ] **R9.4** — `logreg.py` — `SimpleImputer(strategy="mean")` — оставлено как есть
  - ⏭️ Решение: не требует изменений

- [ ] **R10** — Исправить порядок генераторов и расхождение в количестве фичей
  - [x] R10.1 — Изменить порядок генераторов: `form` должен быть ПЕРЕД `ewm` и `count` ✅
  - [x] R10.2 — Исправить `get_feature_names()`: get_expected / get_actual_feature_names, pipeline без warning ✅
  - [ ] R10.3 — Улучшить логирование пропущенных контекстов
  - [ ] R10.4 — Добавить валидацию порядка генераторов
  - [ ] R10.5 — Исправить подсчет фичей в `pipeline.py`
  - [ ] R10.6 — Исследовать проблему с фичами `h2h_match_num` (>50% null)

---

## Ссылки на детали

Детальное описание каждой задачи находится в:
- **Backlog:** `docs/refactor/backlog/R*.md` — незавершенные задачи
- **Done:** `docs/refactor/done_task/R*.md` — завершенные задачи
