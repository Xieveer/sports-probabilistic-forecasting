# TODO — Sports Probabilistic Forecasting

> Актуальный список задач на развитие проекта.
> Обновлено: 2026-03-06

---

## 🟡 Medium Priority

### 1. Мониторинг деградации (Prometheus/Grafana)
- [ ] Отслеживание prod метрик на новых данных
- [ ] Алерты при падении AUC/LogLoss
- [ ] Grafana дашборд с ключевыми метриками

### 2. Feature Selection Service
- [ ] Автоматический отбор фичей (Boruta / SHAP / mutual_info)
- [ ] Сравнение basic vs advanced наборов
- [ ] Интеграция с MLflow (логирование набора фичей для каждого эксперимента)

### 3. A/B тестирование моделей
- [ ] Split traffic между Shadow/Prod
- [ ] Логирование реальных результатов
- [ ] Автоматическое переключение на лучшую модель

### 4. Feature Store
- [ ] Централизованное хранилище фичей
- [ ] Offline: для training
- [ ] Online: для inference

---

## 🟢 Low Priority

### 5. Документация
- [ ] Обновить `docs/CURRENT_TRAINING_STATUS.md`
- [ ] Создать `docs/HOW_TO_ADD_NEW_TOURNAMENT.md`
- [ ] Создать `docs/HOW_TO_ADD_NEW_MARKET.md`
- [ ] Обновить README с актуальной архитектурой

### 6. DVC стадии для v2.0
- [ ] Обновить `dvc.yaml` для новых стадий (train → materialize → deploy)
- [ ] Интеграция с Airflow DAGs

### 7. Data Quality — улучшения
- [ ] Дубли id в cyberhockey данных — расследовать root cause (OT матчи?)
- [ ] Pandera: добавить проверку schema drift (сравнение со snapshot)
- [ ] Pandera: алерты в Slack/Email при нарушении quality gates

### 8. Inference pipeline — улучшения
- [ ] On-demand inference endpoint (POST /predict) для single match
- [ ] Cache layer (Redis) для горячих предсказаний
- [ ] Batch scheduling: автоматическое обновление stale предсказаний

---

## ✅ Недавно завершено (2026-03-06)

- [x] **Airflow DAGs (A–E)**: 5 DAGs для полного ML lifecycle
  - DAG A: Data Refresh (ingest → clean → features)
  - DAG B/C: Training Sweep + Model Promotion
  - DAG D: Prediction Materialization
  - DAG E: Model Monitoring & Retraining triggers
- [x] **Airflow Docker Compose**: отдельный контейнер, LocalExecutor, PostgreSQL backend
- [x] **Data Validation (Pandera)**: схемы для raw/interim/processed слоёв
  - RawSchema, InterimSchema, ProcessedLongSchema, ProcessedWideSchema, PredictionSchema
  - Quality Gates интегрированы в clean.py и features_build.py
  - CLI: `make validate-data` — проверка 29 файлов, все OK
  - 16 unit-тестов для валидации
- [x] **Data Leakage Audit**: все генераторы (EWM, Count, Form, Time) проверены, утечек нет
- [x] **DVC repro**: полный pipeline up to date
- [x] **E2E test**: CatBoost на uel_kz_1, все метрики в MLflow
- [x] **MLflow Model Registry**: pyfunc log_model + register
- [x] **Stacking Ensemble**: CatBoost + LGBM + LogReg мета-модель (ROI 10.2%)
- [x] **Optuna оптимизация**: 5 trials CatBoost (ROI 10.81%), SQLite storage
- [x] **Калибровка модели**: Isotonic regression, ECE 0.074 → 0.018
- [x] **Formula-based targets**: FormulaTargetBuilder + 14 unit тестов

## ✅ Ранее завершено

- [x] **FastAPI сервис**: /predict/{match_id}, /upcoming/{tournament}, /health
- [x] **Prediction Store**: SQLAlchemy + SQLite/PostgreSQL
- [x] **Batch Prediction**: materialize.py → DB + parquet
- [x] **Docker stack**: PostgreSQL + FastAPI + MLflow + Worker
- [x] **Odds passthrough**: raw odds через все слои (clean → trainer)
- [x] **extract_odds_from_raw**: парсинг dict-строки для BettingSimulator
- [x] **TimeFeatureGenerator**: weekday/hour в FeaturePipeline
- [x] **MLflow метрики v2**: ML + betting метрики, threshold sweep, odds bins
- [x] **BettingResult dataclass**: расширенные метрики, per_bet_df, equity_curve
- [x] **MCE (Max Calibration Error)**: добавлен в metrics и trainer
- [x] **Hydra @package directives**: правильная изоляция конфигов
- [x] **MLflow tracking URI**: синхронизация train.py ↔ mlflow-ui через sqlite
- [x] **DVC параметризация**: basic/advanced feature sets через params.yaml
- [x] **Bookmaker config**: динамический маппинг odds ключей из fonbet.yaml
