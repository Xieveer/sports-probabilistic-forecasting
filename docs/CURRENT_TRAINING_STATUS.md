# Текущий статус обучения моделей

**Обновлено:** 2026-03-06
**Версия архитектуры:** 2.0+

---

## Поддерживаемые турниры

| Турнир | Спорт | Регион | player_id_attr | Статус |
|--------|-------|--------|----------------|--------|
| uel_kz_1 | Cyberhockey | Kazakhstan | short_name_en | ✅ Готов |
| uel_kz_2 | Cyberhockey | Kazakhstan | short_name_en | ✅ Готов |
| uel_cz | Cyberhockey | Czech Republic | short_name_en | ✅ Готов |
| lp_ru | Table Tennis | Russia | name | ✅ Готов |
| lp_eu | Table Tennis | Europe | name | ✅ Готов |
| lp_eu_a18 | Table Tennis | Europe (A18) | name | ✅ Готов |
| lp_by | Table Tennis | Belarus | name | ✅ Готов |

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

| Набор | Конфиг | Описание | ~Кол-во фичей |
|-------|--------|----------|---------------|
| basic | `features=basic` | Минимальный: ewm span=10, count global+h2h, form, time | ~50 |
| advanced | `features=advanced` | Полный: ewm spans=[5,10,20], расширенные контексты | ~1000+ |

---

## Конвейер обучения

### Шаги

1. **Загрузка данных** — `train_long.parquet` или `train_wide.parquet`
2. **Вычисление таргета** — через `target_sources` из турнирного конфига
3. **Сортировка по времени** — `datetime` столбец
4. **Фильтрация фичей** — только столбцы с префиксом `f_`, исключая `exclude_cols`
5. **Train/Test split** — 90/10 по времени (time-based)
6. **Shadow модель** — TSCV (4 фолда) на train данных
7. **Калибровка** — IsotonicRegression на валидации (если ECE > порог)
8. **Prod модель** — обучение на train + test (полный датасет)
9. **Feature Selection** — ранжирование и отбор фичей
10. **Business метрики** — BettingSimulator, threshold sweep
11. **MLflow логирование** — метрики, артефакты, Model Registry

### Метрики

#### ML метрики (на test set)

| Метрика | Описание |
|---------|----------|
| test_logloss | Log Loss |
| test_brier | Brier Score |
| test_accuracy | Accuracy |
| test_auc | AUC-ROC |
| test_ece | Expected Calibration Error |
| test_mce | Max Calibration Error |

#### Betting метрики (на selected bets)

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

#### Артефакты MLflow

- `equity_curve.csv` — кривая эквити
- `threshold_sweep.csv` — метрики по порогам (0–30%, шаг 0.01)
- `per_bet_df.parquet` — DataFrame каждой ставки
- `feature_ranking.csv` — ранжирование фичей
- `experiment_config.yaml` — конфиг эксперимента

---

## Гиперпараметры

| Метод | Конфиг | Описание |
|-------|--------|----------|
| none | `hyper=none` | Без оптимизации, дефолтные параметры |
| grid_small | `hyper=grid_small` | Небольшой grid search |
| optuna | `hyper=optuna` | Optuna (Bayesian), настраиваемое число trials |

---

## Калибровка

| Метод | Описание | Триггер |
|-------|----------|---------|
| isotonic | Isotonic Regression | ECE > threshold (по умолчанию) |
| sigmoid | Platt Scaling (Logistic Regression) | ECE > threshold |

Результат: ECE обычно снижается с ~0.07 до ~0.02.

---

## Feature Selection

| Ранкер | Описание |
|--------|----------|
| model_importance | native feature_importances_ (CatBoost/LGBM) |
| mutual_info | sklearn mutual_info_classif |
| shap | SHAP TreeExplainer / LinearExplainer |

Стратегии агрегации: `union`, `intersection`, `vote`, `rank_average`.

---

## Команды запуска

```bash
# Одиночный эксперимент
make train TOURNAMENT=uel_kz_1 MARKET=winner SPEC=winner ALG=catboost FEAT=basic

# Sweep моделей
make train-sweep TOURNAMENT=uel_kz_1

# Sweep с расширенными фичами
make train-sweep-full TOURNAMENT=uel_kz_1

# Прямой вызов с параметрами
uv run python -m sports_forecast.train \
    tournament=uel_kz_1 \
    market=winner \
    market_spec=winner \
    algorithm=catboost \
    features=basic
```

---

## Последний E2E тест

**Дата:** 2026-03-06
**Турнир:** uel_kz_1, market=winner
**Результат:** ✅ Все метрики залогированы в MLflow

| Метрика | CatBoost |
|---------|----------|
| test_logloss | ~0.69 |
| test_auc | ~0.53 |
| test_ece | ~0.02 (после калибровки) |
| bet_roi | ~10% |

---

## Известные ограничения

1. **Odds данные** — не все матчи имеют odds_raw, betting метрики вычисляются только на матчах с коэффициентами
2. **Малый edge** — при низком AUC (~0.53) ROI сильно зависит от порога и выборки
3. **Cyberhockey специфика** — короткие матчи, высокая вариативность
4. **Table Tennis** — двойная система счёта (sets для winner, points для total)
