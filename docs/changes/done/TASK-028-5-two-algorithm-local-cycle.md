# TASK-028-5 — Локальный цикл двух алгоритмов и rollback

> **Статус:** done; независимое review завершено, P0–P2 findings отсутствуют
> **Ветка:** `initiative/epic-028-production-model-contract`
> **TASK:** [TASK-028-5](../../backlog/tasks/TASK-028-5-two-algorithm-local-cycle.md)

## Что выполнено

Проверен локальный цикл для будущей игры NHL `2026020084` SEA@WSH, scheduled
2026-10-11 21:00 UTC. Official NHL API retrieval зафиксирован в
`2026-10-10T11:11:44Z`; собраны 51 FUT строки, без checkpoints и записи в
основной `source.csv`. Штатные clean и advanced feature stages записывали
результаты только в временный каталог. В long inference 110 строк, 489
признаков. Для двух строк события 170 значений NaN; это ожидаемые missing values
до составов и исторических игровых признаков. Подстановки нулями не было.

Одобренный CatBoost v1 проверен на исходной версии 1.2.12. Его исходный bundle
`sha256:a94173608d42bc69363be243527c1bdd893e2eee81c98f6615c01232aed1f64a`
не менялся; model SHA-256 —
`4042e85367a9d3c493a15ef45d0d9dcba9c78004833761224e379c360b0b5cda`.
По решению PO локально построен отдельный managed v2 для app 1.2.15 из тех же
байтов. Сохранено происхождение v1. Второй candidate — локальный LightGBM
fixture на 2 500 строках read-only NHL training history, с target
`pl_goals_full > opp_goals_full`.

Полный путь `bundle → Worker → materialize → PostgreSQL → API` выполнил
CatBoost A → LightGBM B → rollback CatBoost A. В базе созданы три разные
immutable revisions; каждый `PredictionRevision.run_id` совпадает с
соответствующим успешным `WorkerExecution.run_id`. API отдаёт probabilities
последней A revision. Повтор того же завершённого Worker run не создал новую
revision. Повреждённый candidate и NaN probability run отклонены; active pointer
и current revision остались прежними.

Обнаружены и исправлены два дефекта, подтверждённые тестами:

- LightGBM 4.6.0 sklearn wrapper после reload считал модель необученной. Adapter
  теперь выставляет `fitted_` при загрузке.
- Worker не передавал свой стабильный run ID в materialize, поэтому revision
  получала случайный `materialize-...` ID. Worker теперь записывает
  `cfg.refresh_run_id = run_id` перед materialize.

## Evidence

- Feature parquet SHA-256:
  `433d5980935555498cbc5e3e29391bcd43371dea54913298c5645fc9704500dd`.
- Managed CatBoost bundle:
  `sha256:bd15a687b5c6439fce296d7c5a29351a90fbf952304e12f6bb1eb41052a55d24`.
- Managed LightGBM fixture bundle:
  `sha256:3814e77c1f0fc0ad0eabf04838134cd73ae7cc9b7782736c1a1b7d184dac46a6`.
- Runtime: app 1.2.15, CatBoost 1.2.8, LightGBM 4.6.0, PostgreSQL 16.
- CatBoost probability rows: `[0.2903, 0.7097]`, `[0.6546, 0.3454]`.
- LightGBM probability rows: `[0.4634, 0.5366]`, `[0.6441, 0.3559]`.
- Revision bundle sequence: `A → B → A`; all values finite, in range `[0,1]`,
  each row sums to 1.
- PostgreSQL disposable container used tmpfs storage and was removed after the
  gate. Source/training data stayed read-only. Temporary bundles and features
  were not added to Git.

## Проверки

- `uv run pytest -q tests/test_task_028_5_local_cycle.py::test_lgbm_adapter_can_predict_after_save_and_reload` — passed.
- `DATABASE_URL='postgresql://<temporary-local-dsn>' uv run alembic upgrade head` — passed on disposable PostgreSQL, migrations 0001–0024.
- `SF_TASK_028_5_DATABASE_URL=... uv run pytest -q --tb=short --log-level=ERROR tests/test_task_028_5_local_cycle.py` — passed: 2 tests, including fresh NHL API fetch, feature build, managed A→B→A Worker cycle, PostgreSQL, API and negative gates.
- `make lint` — passed.
- `make test-unit` — 1 508 passed, 16 deselected.
- Независимое review TASK-028-5: P0–P2 findings отсутствуют.

## Ограничения

Это локальный engineering gate, не оценка качества и не финансовая проверка
LightGBM fixture. Он не менял production pointer и ничего не публиковал в бота.
Публичный API не раскрывает revision ID/source namespace; соответствие API
последней revision проверено по совпадению probabilities с DB current pointer.
Адресный integration gate опирается на доступность live NHL API, конкретный
future event и подготовленные локальные approved model/data artifacts; он
воспроизводим в подготовленном контуре. Historic as-of replay не проверялся.
