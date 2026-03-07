# Текущий статус обучения моделей

**Обновлено:** 2026-03-06
**Версия архитектуры:** 3.0

---

## Поддерживаемые турниры

| Турнир | Спорт | Регион | Фичей (advanced) | Статус |
|--------|-------|--------|-------------------|--------|
| uel_kz_1 | Cyberhockey | Kazakhstan | 75 | ✅ Готов |
| uel_kz_2 | Cyberhockey | Kazakhstan | 60 | ✅ Готов |
| uel_cz | Cyberhockey | Czech Republic | 60 | ✅ Готов |
| lp_ru | Table Tennis | Russia | 52 | ✅ Готов |
| lp_eu | Table Tennis | Europe | 52 | ✅ Готов |
| lp_eu_a18 | Table Tennis | Europe (A18) | 52 | ✅ Готов |
| lp_by | Table Tennis | Belarus | 52 | ✅ Готов |

---

## Последний полный прогон (2026-03-06)

**Маркет:** winner, **Алгоритм:** CatBoost, **Фичи:** advanced

| Турнир | ROI | Bets | Sharpe | PF | ECE | Стабильность |
|--------|-----|------|--------|----|-----|--------------|
| uel_kz_1 | 5.19% | 1753 | 0.038 | 1.08 | 0.046 | high ✅ |
| uel_kz_2 | 6.33% | 1465 | 0.047 | 1.11 | 0.058 | high ✅ |
| uel_cz | 3.86% | 1507 | 0.031 | 1.07 | 0.056 | high ✅ |
| lp_ru | 17.07% | 9028 | 0.124 | 1.31 | 0.014 | high ✅ |
| lp_eu | 15.19% | 5522 | 0.118 | 1.28 | 0.022 | high ✅ |
| lp_eu_a18 | 8.26% | 1280 | 0.071 | 1.16 | 0.039 | high ✅ |
| lp_by | 9.04% | 1750 | 0.071 | 1.17 | 0.049 | high ✅ |

Все 7 моделей зарегистрированы в **MLflow Model Registry**.

---

## Поддерживаемые маркеты

| Маркет | Формат | Таргет | Спорт |
|--------|--------|--------|-------|
| winner (long) | long | pl_points > opp_points (cyberhockey), pl_sets > opp_sets (table tennis) | Все |
| winner_home (wide) | wide | home_points > away_points / home_sets > away_sets | Все |
| total_over | wide | (home_points + away_points) > line | Все |
| total_under | wide | (home_points + away_points) < line | Все |

---

## Поддерживаемые алгоритмы

| Алгоритм | Конфиг | Описание | Статус |
|----------|--------|----------|--------|
| DummyModel | `algorithm=dummy` | Baseline (частоты классов) | ✅ |
| LogisticRegression | `algorithm=logreg` | Линейная модель | ✅ |
| CatBoost | `algorithm=catboost` | Gradient boosting (Yandex) | ✅ |
| LightGBM | `algorithm=lgbm` | Gradient boosting (Microsoft) | ✅ |
| Stacking | `algorithm=stacking` | Мета-модель поверх base моделей | ✅ |

---

## Наборы фичей

| Набор | Конфиг | Описание | ~Фичей |
|-------|--------|----------|--------|
| basic | `features=basic` | ewm span=10, count global+h2h, form, time | 19–25 |
| advanced | `features=advanced` | ewm spans=[5,10,25], расширенные контексты, h2h | 52–75 |

Переключение через `params.yaml` → `features.config: basic|advanced`.

---

## Конвейер обучения

### Data Pipeline (DVC)

```
source → ingest → raw → clean → interim → features → processed
```

Управляется через `dvc repro`. Обучение **НЕ** входит в DVC.

### Training Pipeline (Hydra + MLflow)

1. **Загрузка данных** — `train_long.parquet` или `train_wide.parquet`
2. **Вычисление таргета** — через `target_sources` (FormulaTargetBuilder)
3. **Сортировка по времени** — `datetime`
4. **Фильтрация фичей** — `f_` prefix, исключая `exclude_cols`
5. **Train/Test split** — 90/10 (time-based)
6. **Shadow модель** — TSCV (4 фолда) на train
7. **Evaluation на test** — ML метрики
8. **Калибровка** — IsotonicRegression (если ECE > порог)
9. **Business метрики** — BettingSimulator, threshold sweep, odds bins
10. **Prod модель** — обучение на train + test
11. **MLflow** — метрики, артефакты, Model Registry

---

## Метрики

### ML метрики (test set)

| Метрика | Описание |
|---------|----------|
| test_logloss | Log Loss |
| test_brier | Brier Score |
| test_accuracy | Accuracy |
| test_auc | AUC-ROC |
| test_ece | Expected Calibration Error |
| test_mce | Max Calibration Error |

### Betting метрики (selected bets)

| Метрика | Описание |
|---------|----------|
| bet_n_bets | Количество ставок |
| bet_roi | Return on Investment |
| bet_profit_units | Прибыль в юнитах |
| bet_avg_edge | Средний edge (p_model - p_implied) |
| bet_avg_ev | Средний EV |
| bet_max_drawdown_units | Максимальная просадка |
| bet_sharpe_like | mean_return / std_return |
| bet_profit_factor | sum(wins) / abs(sum(losses)) |
| bet_ev_realization | profit_units / ev_sum_units |
| bet_hit_rate | Win rate |

### Артефакты MLflow

- `equity_curve.csv` — кривая эквити
- `threshold_sweep.csv` — метрики по порогам (0–30%, шаг 0.01)
- `per_bet_df.parquet` — DataFrame каждой ставки
- `feature_ranking.csv` — ранжирование фичей
- `experiment_config.yaml` — конфиг эксперимента

---

## Калибровка

| Метод | Описание | Триггер |
|-------|----------|---------|
| isotonic | Isotonic Regression | ECE > threshold (по умолчанию) |
| sigmoid | Platt Scaling (Logistic Regression) | ECE > threshold |

ECE обычно снижается с ~0.07 до ~0.02.

---

## Feature Selection

| Ранкер | Описание |
|--------|----------|
| model_importance | native feature_importances_ (CatBoost/LGBM) |
| mutual_info | sklearn mutual_info_classif |
| shap | SHAP TreeExplainer / LinearExplainer |

Стратегии агрегации: `union`, `intersection`, `vote`, `rank_average`.
Конфиги: `conf/feature_selection/default.yaml`, `conf/feature_selection/aggressive.yaml`.

---

## Гиперпараметры

| Метод | Конфиг | Описание |
|-------|--------|----------|
| none | `hyper=none` | Дефолтные параметры |
| grid_small | `hyper=grid_small` | Небольшой grid search |
| optuna | `hyper=optuna` | Optuna (Bayesian) |

---

## Команды запуска

```bash
# Одиночный эксперимент
uv run python -m sports_forecast.train \
    tournament=uel_kz_1 market=winner market_spec=winner \
    algorithm=catboost features=advanced

# Multirun по всем турнирам
uv run python -m sports_forecast.train --multirun \
    tournament=uel_kz_1,uel_kz_2,uel_cz,lp_ru,lp_eu,lp_eu_a18,lp_by \
    market=winner market_spec=winner algorithm=catboost features=advanced

# Через Makefile
make train TOURNAMENT=uel_kz_1 MARKET=winner SPEC=winner ALG=catboost FEAT=advanced

# DVC pipeline (только данные)
make dvc-repro

# MLflow UI
make mlflow-ui
```

---

## Инфраструктура

| Компонент | Статус |
|-----------|--------|
| DVC pipeline (ingest → clean → features) | ✅ |
| MLflow tracking + Model Registry | ✅ |
| Pandera data validation | ✅ |
| FastAPI prediction API | ✅ |
| Docker Compose (postgres, mlflow, api, worker) | ✅ |
| Airflow DAGs (data refresh, training, materialization, monitoring) | ✅ |
| Prometheus + Grafana monitoring | ✅ |
| A/B testing (shadow vs prod) | ✅ |
| Feature selection service | ✅ |
| Schema drift detection | ✅ |

---

## Известные ограничения

1. **Odds данные** — не все матчи имеют `odds_raw`, betting метрики вычисляются только на матчах с коэффициентами
2. **Малый edge** — при AUC ~0.53 ROI сильно зависит от порога и выборки
3. **Cyberhockey** — короткие матчи, высокая вариативность, больше фичей (h2h draw)
4. **Table Tennis** — двойная система счёта (sets для winner, points для total)
