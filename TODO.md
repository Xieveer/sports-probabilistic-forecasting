# TODO — Sports Probabilistic Forecasting

> Актуальный список задач на развитие проекта.
> Обновлено: 2026-03-06

---

## 🔴 High Priority

### 1. Airflow DAGs (A–E)
- [ ] DAG A: Data Ingestion (парсеры → raw layer)
- [ ] DAG B: Data Processing (clean → interim → features → processed)
- [ ] DAG C: Training Pipeline (per tournament / per market)
- [ ] DAG D: Prediction Materialization (model → predictions DB)
- [ ] DAG E: Model Monitoring & Retraining triggers
- [ ] Все DAGs запускаются через CLI, без airflow-логики в ML-коде
- [ ] Docker Compose: Airflow как отдельный контейнер

### 2. Data Validation (Pandera)
- [ ] Определить Pandera-схемы для raw → clean → processed слоёв
- [ ] Quality Gate: блокировать pipeline при невалидных данных
- [ ] Алерты при schema drift

---

## 🟡 Medium Priority

### 3. Мониторинг деградации (Prometheus/Grafana)
- [ ] Отслеживание prod метрик на новых данных
- [ ] Алерты при падении AUC/LogLoss
- [ ] Grafana дашборд с ключевыми метриками

### 4. Feature Selection Service
- [ ] Автоматический отбор фичей (Boruta / SHAP / mutual_info)
- [ ] Сравнение basic vs advanced наборов
- [ ] Интеграция с MLflow (логирование набора фичей для каждого эксперимента)

### 5. A/B тестирование моделей
- [ ] Split traffic между Shadow/Prod
- [ ] Логирование реальных результатов
- [ ] Автоматическое переключение на лучшую модель

### 6. Feature Store
- [ ] Централизованное хранилище фичей
- [ ] Offline: для training
- [ ] Online: для inference

---

## 🟢 Low Priority

### 7. Документация
- [ ] Обновить `docs/CURRENT_TRAINING_STATUS.md`
- [ ] Создать `docs/HOW_TO_ADD_NEW_TOURNAMENT.md`
- [ ] Создать `docs/HOW_TO_ADD_NEW_MARKET.md`
- [ ] Обновить README с актуальной архитектурой

### 8. DVC стадии для v2.0
- [ ] Обновить `dvc.yaml` для новых стадий (train → materialize → deploy)
- [ ] Интеграция с Airflow DAGs

---

## ✅ Недавно завершено (2026-03-06)

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
