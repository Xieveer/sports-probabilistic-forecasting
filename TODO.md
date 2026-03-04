# TODO — Sports Probabilistic Forecasting

> Актуальный список задач на развитие проекта.
> Обновлено: 2026-03-04

---

## 🔴 High Priority

### 1. Проверка утечек данных (Data Leakage Audit)
- [ ] Проанализировать top-10 важных фичей CatBoost/LGBM на предмет leakage
- [ ] Проверить корреляцию фичей с таргетом (EDA notebook)
- [ ] Убедиться что `shift=1` в EWM/Count генераторах работает корректно
- [ ] Проверить что `match_state` (form/fg/dp) вычисляется ДО матча, а не после
- [ ] На подозрительно хороших метриках (LogLoss ≈ 0.0, AUC = 1.0) разобраться с причиной

### 2. Re-run clean stage после изменений
- [ ] Перезапустить `data_clean` для всех турниров (weekday/hour удалены из derived_columns)
- [ ] Проверить что `odds_raw` корректно проходит через clean → interim → processed
- [ ] Убедиться что `TimeFeatureGenerator` генерирует weekday/hour в pipeline

### 3. Полный end-to-end тест обучения
- [ ] Запустить обучение на одном турнире (uel_kz_1 / lp_eu) с CatBoost
- [ ] Проверить MLflow: все ML + betting метрики логируются
- [ ] Проверить артефакты: equity_curve.csv, per_bet_df.parquet, threshold_sweep.csv
- [ ] Проверить что odds_raw → extract_odds_from_raw корректно работает в training pipeline

---

## 🟡 Medium Priority

### 4. Stacking Ensemble
- [ ] Протестировать ensemble конфиг (stacking CatBoost + LGBM + LogReg)
- [ ] Подключить к v2.0 архитектуре через ModelFactory
- [ ] Логирование в MLflow для ensemble

### 5. Optuna оптимизация
- [ ] Модуль готов (`sports_forecast/training/optimization/optuna_optimizer.py`)
- [ ] Протестировать с CatBoost: подбор depth, lr, l2
- [ ] Добавить конфиги для LGBM

### 6. Калибровка моделей
- [ ] Оценить baseline ECE/MCE по турнирам
- [ ] Включить `calibration.enabled: true` при ECE > 0.10
- [ ] Протестировать Isotonic vs Sigmoid

### 7. DVC интеграция
- [ ] Обновить `dvc.yaml` для текущей архитектуры (train.py v2.0)
- [ ] Убедиться что `dvc repro` воспроизводит full pipeline
- [ ] Добавить стадии: clean → features → train → deploy

### 8. Formula-based targets
- [ ] Реализовать `formula` в `utils/targets.py` (сейчас TODO в коде)
- [ ] Позволит определять таргет через формулу в конфиге (например, `home_sets > away_sets`)

---

## 🟢 Low Priority

### 9. FastAPI Inference Endpoint
- [ ] REST API для async predictions
- [ ] Роуты: `/predict/winner`, `/predict/total`
- [ ] Загрузка модели из MLflow Model Registry

### 10. Мониторинг деградации
- [ ] Отслеживание prod метрик на новых данных
- [ ] Алерты при падении AUC/LogLoss
- [ ] Автоматический ретрейн при drift

### 11. A/B тестирование моделей
- [ ] Split traffic между Shadow/Prod
- [ ] Логирование реальных результатов
- [ ] Автоматическое переключение на лучшую модель

### 12. Feature Store
- [ ] Централизованное хранилище фичей
- [ ] Offline: для training
- [ ] Online: для inference

### 13. Airflow оркестрация
- [ ] DAG для daily re-training
- [ ] DAG для inference
- [ ] Все через CLI, без airflow-логики в ML-коде

### 14. Документация
- [ ] Обновить `docs/CURRENT_TRAINING_STATUS.md`
- [ ] Создать `docs/HOW_TO_ADD_NEW_TOURNAMENT.md`
- [ ] Создать `docs/HOW_TO_ADD_NEW_MARKET.md`
- [ ] Обновить README с актуальной архитектурой

---

## ✅ Недавно завершено

- [x] **Odds passthrough**: raw odds проходят через все слои (clean → interim → features → trainer)
- [x] **extract_odds_from_raw**: парсинг dict-строки из odds_raw для BettingSimulator
- [x] **TimeFeatureGenerator**: weekday/hour генерируются в FeaturePipeline, убраны из clean
- [x] **MLflow метрики v2**: полный набор ML + betting метрик, threshold sweep, odds bins
- [x] **BettingResult dataclass**: расширенные метрики, per_bet_df, equity_curve
- [x] **MCE (Max Calibration Error)**: добавлен в metrics и trainer
- [x] **Hydra @package directives**: betting, calibration, split, metrics правильно изолированы
- [x] **MLflow tracking URI**: синхронизация train.py ↔ mlflow-ui через sqlite
