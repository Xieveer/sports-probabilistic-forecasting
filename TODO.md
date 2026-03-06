# TODO — Sports Probabilistic Forecasting

> Актуальный список задач на развитие проекта.
> Обновлено: 2026-03-06

---

## 🟡 Отложено (требует внешних зависимостей)

### 1. Feature Store v2
- [ ] Централизованное хранилище фичей (Feast / custom)
- [ ] Offline: parquet → feature store для training
- [ ] Online: кеш последних значений для inference
- **Статус:** текущая архитектура (offline parquet + FeaturePipeline) покрывает потребности. Внедрение Feast целесообразно при увеличении количества турниров и фичей.

### 2. Мониторинг — расширения
- [ ] Alertmanager: Slack / Telegram уведомления при срабатывании alert rules
- [ ] Grafana: дополнительные dashboards (per-tournament, per-model)
- [ ] P&L мониторинг: tracking реальных ставок и прибыли
- **Статус:** базовый мониторинг (Prometheus + Grafana + alert rules) реализован. Интеграция с мессенджерами требует настройки Alertmanager.

### 3. CI/CD
- [ ] GitHub Actions pipeline (lint → test → build → deploy)
- [ ] Автоматический DVC repro при пуше в main
- [ ] Kubernetes манифесты для production deployment

---

## ✅ Недавно завершено (2026-03-06)

### Low Priority — всё завершено

- [x] **Документация**
  - `docs/CURRENT_TRAINING_STATUS.md` — статус обучения, метрики, алгоритмы
  - `docs/HOW_TO_ADD_NEW_TOURNAMENT.md` — пошаговый гайд по добавлению турнира
  - `docs/HOW_TO_ADD_NEW_MARKET.md` — пошаговый гайд по добавлению маркета
  - `README.md` — полностью обновлён с актуальной архитектурой

- [x] **DVC стадии v2.0**
  - Добавлена стадия `validate` (Pandera validation)
  - Добавлена стадия `train_prod` (production training, параметризована через params.yaml)
  - Добавлена стадия `materialize` (batch prediction → DB)
  - `params.yaml` расширен секцией `prod.*` для production конфигурации

- [x] **Data Quality — улучшения**
  - `check_schema_drift()` — обнаружение изменений в схеме данных
  - `save_schema_snapshot()` — сохранение snapshot схемы в JSON
  - `report_duplicate_ids()` — детальный отчёт о дублях ID (top-5, %)
  - Schema drift + duplicate reporting интегрированы в `run_validation.py`
  - `.schema_snapshots/` — автоматическое создание snapshots при первой валидации
  - 10 новых unit-тестов (SchemaDrift, DuplicateIds)

- [x] **Inference pipeline — улучшения**
  - `GET /predict/cached/{match_id}` — LRU кеш с TTL (5 мин, 512 записей)
  - `POST /predict/cache/clear` — ручной сброс кеша
  - `GET /predict/cache/stats` — статистика кеша (hits, misses, size)
  - `GET /predict/stale` — список устаревших предсказаний для batch scheduling
  - `get_stale_predictions()` в PredictionRepository
  - `StaleInfo` Pydantic schema

---

## ✅ Ранее завершено (Medium Priority, 2026-03-06)

- [x] **Мониторинг деградации (Prometheus/Grafana)**
  - Prometheus custom gauges: AUC, LogLoss, ECE, ROI, drift score
  - Prometheus `/metrics` endpoint в FastAPI
  - Alert rules: ModelAUCDegraded, ModelLogLossHigh, DataDriftSignificant
  - Grafana dashboard + auto-provisioning
  - `sports_forecast/monitoring/drift.py`: PSI + KS drift detection
  - `sports_forecast/monitoring/performance.py`: degradation detection
  - 13 unit-тестов

- [x] **Feature Selection Service**
  - `ModelImportanceRanker`, `MutualInfoRanker`, `ShapRanker`
  - `FeatureSelector` оркестратор (union, intersection, vote, rank_average)
  - Hydra конфиги: `default.yaml`, `aggressive.yaml`
  - Интеграция в trainer + MLflow logging
  - 22 unit-теста

- [x] **A/B тестирование моделей**
  - `ModelComparator`: prod vs shadow
  - `model_tag` в Prediction Store
  - 8 unit-тестов

---

## ✅ Ранее завершено (High Priority)

- [x] **Airflow DAGs**: 5 DAGs для полного ML lifecycle
- [x] **Airflow Docker Compose**: LocalExecutor, PostgreSQL backend
- [x] **Data Validation (Pandera)**: 5 схем, quality gates, 16 тестов
- [x] **Data Leakage Audit**: все генераторы проверены
- [x] **DVC repro**: полный pipeline up to date
- [x] **E2E test**: CatBoost, все метрики в MLflow
- [x] **MLflow Model Registry**: pyfunc log_model + register
- [x] **Stacking Ensemble**: CatBoost + LGBM + LogReg
- [x] **Optuna оптимизация**: Bayesian, SQLite storage
- [x] **Калибровка**: Isotonic regression, ECE 0.074 → 0.018
- [x] **Formula-based targets**: FormulaTargetBuilder + 14 тестов

## ✅ Ранее завершено (Infrastructure)

- [x] **FastAPI сервис**: /predict, /upcoming, /health, /metrics
- [x] **Prediction Store**: SQLAlchemy + SQLite/PostgreSQL
- [x] **Batch Prediction**: materialize.py → DB + parquet
- [x] **Docker stack**: PostgreSQL + FastAPI + MLflow + Worker + Prometheus + Grafana
- [x] **Odds passthrough**: raw odds через все слои
- [x] **TimeFeatureGenerator**: weekday/hour в FeaturePipeline
- [x] **MLflow метрики v2**: ML + betting, threshold sweep, odds bins
- [x] **DVC параметризация**: basic/advanced через params.yaml
- [x] **Bookmaker config**: динамический маппинг из fonbet.yaml
