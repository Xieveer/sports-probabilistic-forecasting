# Football nationals — feature engineering design (R44)

> **Статус:** defaults v1 (architect interview defaults; user may revise)
> **Турнир:** `football_nationals` · **Спорт:** `football` · **Профиль:** `features=advanced`

---

## ADR summary

Phase 2 добавляет слой фичей для сборных: рынки **winner** (1X2) и **total** (линии 1.5–4.5). Архитектура повторяет NHL R27/R28/R29: каркас `time` + `form` + `rolling` (EWM/Count), sport-level `ewm_metrics` через `inject_sport_ewm_generators`, без NHL pre-gen и без streak v1.

**Ключевые отличия от NHL:**

| Аспект | NHL (`ice_hockey`) | Football (`football`) |
|--------|-------------------|----------------------|
| EWM spans | `[5, 15]` | `[3, 10]` (редкие матчи сборных, `fg_trigger_minutes: 10080`) |
| Sport EWM metrics | goals_full, sog, bs, hits, pim2, fow | goals, xg, corners, possession, shotstarget (`*_all` period) |
| `inseason` key | колонка `season` | `season_id` via `rolling_column_aliases.season` |
| Pre-gen | schedule / standings / roster | нет |
| Streak | включён | **выключен** v1 |
| HT / 1h stats | N/A | **исключены** из фич (leakage) |
| Odds | pinnacle_* не в модель | `odd_*` не в генераторах; eval позже |
| Coach / referee | lineup continuity | **Phase 2 defer** |
| Similar matches API | — | **defer** |

---

## Interview defaults v1

| # | Решение |
|---|---------|
| 1 EWM | MVP: `goals`, `xg`, `corners`, `possession`, `shotstarget` — period **`all`**; spans **`[3, 10]`** |
| 2 Contexts | Полный набор из `football.yaml` + **`inseason`** / **`h2h_inseason`**; без `competition_importance` EWM |
| 3 xG | Включать; NaN → skip в EWM (без impute) |
| 4 Streak | `false` |
| 5 HT stats | Исключить `*_1h`, `home_score_ht` / `away_score_ht` из feature inputs |
| 6 Coach/referee | Defer Phase 2 |
| 7 Odds | Не в feature generators; historical odds epic позже |
| 8 Friendly | Единый EWM; фильтр friendly в train config |
| 9 Holdout | WC + EURO (`football_nationals.yaml`); без one-hot `competition_code`; `time_range` 2000+ |
| 10 Profile | Первый sweep **`advanced`**; `football_nationals` в DVC features multirun |
| 11 Similar | Defer `similar.json` neighbor features |
| 12 Markets | **winner** → total **2.5** → прочие линии |

---

## Derived metrics (long path)

После `wide_to_long` `create_player_metrics` строит diff/total для ST wide-колонок period=`all`:

| Metric | Source columns |
|--------|----------------|
| `goals_all_diff` / `goals_all_total` | `pl_goals_all`, `opp_goals_all` |
| `xg_all_diff` / `xg_all_total` | `pl_xg_all`, `opp_xg_all` |
| `corners_all_diff` / `corners_all_total` | `pl_corners_all`, `opp_corners_all` |
| `possession_all_diff` / `possession_all_total` | `pl_possession_all`, `opp_possession_all` |
| `shotstarget_all_diff` / `shotstarget_all_total` | `pl_shotstarget_all`, `opp_shotstarget_all` |

Базовые `diff_ps` / `total_ps` из `home_points` / `away_points` — как у других спортов.

Все derived метрики в `result_cols` (`conf/features/_common.yaml`) — защита от leakage.

---

## Generators (effective pipeline)

Пресет `features=advanced` + `compose_feature_pipeline` для `sport=football`:

| Generator | Role |
|-----------|------|
| `time` | weekday, hour, … |
| `form` | `pl_state`, `match_state` (`fg_trigger_minutes: 10080`) |
| `ewm_diff` / `ewm_total` | базовые EWM по `diff_ps` / `total_ps` |
| `count` | счётчики матчей по контекстам |
| `ewm_sport_*` | inject из `football.ewm_metrics` (10 генераторов: 5 метрик × diff/total) |

**Не включено v1:** `nhl_schedule`, `nhl_standings`, `nhl_roster`, `streak`.

---

## Rolling contexts

Активные имена (`conf/sport/football.yaml` → `rolling_context_names`):

`global`, `match_state`, `weekday`, `tour_side`, `form`, `team`, **`inseason`**, `h2h_global`, `h2h_match_state`, `h2h_side`, `h2h_form`, **`h2h_inseason`**, `h2h_team`

`inseason` / `h2h_inseason` используют ключ library `season` → фактическая колонка **`season_id`**:

```yaml
rolling_column_aliases:
  season: season_id
```

`competition_code` остаётся в long context для фильтрации train, **не** как EWM-группировка v1.

---

## Interim → processed contract

`conf/tournament/football_nationals.yaml` → `data_clean.select_columns`:

- Счёт FT, meta (`competition_code`, `season_id`, `match_importance`, `is_friendly`)
- ST stats `*_all` для MVP метрик
- **Без** `home_score_ht` / `away_score_ht` (v1)
- `odd_*` в interim для будущего betting eval; в `exclude_cols` для модели

Processed: `data/processed/football_nationals/train_long.parquet`, `train_wide.parquet`.

---

## DVC / smoke

```bash
uv run python -m sports_forecast.features.features_build \
  tournament=football_nationals features=advanced
# или
dvc repro features
```

CI: `tests/test_r44_football_advanced_pipeline_smoke.py` (synthetic wide, без parquet).

---

## Ссылки

- `conf/sport/football.yaml` — ewm, contexts, form
- `conf/tournament/football_nationals.yaml` — select_columns, holdout
- `docs/cursor/source_data/football.md` — колонки source/interim
- NHL refs: `done_task/R27.md`, `done_task/R28.md`, `done_task/R29.md`
