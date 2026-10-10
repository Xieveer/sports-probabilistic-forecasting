# TASK-028-5 — Локальный цикл двух алгоритмов и rollback

> **Статус:** done — локальный integration gate и независимое review завершены
> **Владелец:** Developer
> **Эпик:** [EPIC-028](../EPIC-028-production-model-contract.md)
> **Требование:** [REQ-028](../../product/requirements/REQ-028-production-model-contract.md)
> **ADR:** [ADR-030](../../architecture/adr/ADR-030-production-model-contract.md), accepted

## Результат и границы

На изолированном локальном контуре один реальный путь `bundle → Worker →
materialize → DB → API` последовательно публикует NHL `winner_withOT` из
одобренного legacy CatBoost payload и локального LightGBM fixture, затем
ручной rollback возвращает проверенный CatBoost. Между активациями Worker и API
не меняются; production pointer, VPS и пользовательская рассылка не затрагиваются.

## Критерии приёмки

- [x] Локальный CatBoost payload сверен с documented approved bundle по SHA-256,
  загружается на совместимом runtime; его реальные feature order/types,
  market rules и `home_win / away_win` установлены по артефакту. Старые
  неизвестные training refs не заполняются догадками.
- [x] LightGBM fixture построен на совместимом входе для того же рынка и
  исходов, проходит тот же manifest v2 verifier и Loader/Worker/API без
  алгоритмических веток и без production promotion.
- [x] CatBoost → LightGBM → rollback CatBoost даёт три успешных локальных run;
  каждый сохраняет отдельную immutable revision с точным bundle ID, feature
  contract, временем и вероятностями. Старые revisions читаются по ID;
  актуальная витрина/API отражает последнюю активацию.
- [x] Повреждённый или несовместимый candidate, а также невалидный набор
  вероятностей не меняют active pointer или текущую публикацию.
- [x] Для `winner_withOT` до публикации проверены конечность, диапазон и
  сумма вероятностей `home_win / away_win`; при нарушении витрина и revisions
  остаются прежними.
- [x] Evidence содержит версии runtime, checksums и результаты теста без
  копирования model weights, внешних полных ответов или секретов в Git.

## План реализации

1. **Preflight:** только read-only сверить локальный NHL payload и staged
   v1.2.12 bundle; получить совместимый runtime и локальный вход с будущим
   матчем. Если достоверный feature/outcome contract не извлекается или
   app version несовместима, остановить реальный прогон и вернуть blocker PO.
2. **Red:** integration test с настоящими CatBoost/LightGBM адаптерами
   предъявляет общий путь и сохранение трёх revisions; отдельно проверяет
   повреждённый candidate и плохие вероятности.
3. **Green:** минимально дополнить fixture/adapter wiring и выполнить цикл
   на изолированной БД и bundle root; ручной rollback использует managed DB
   pointer. Не создавать новый scheduler или production deployment.
4. **Evidence:** проверить API текущей витрины, repository старых revisions и
   записать фактические команды/версии/checksums в done report.

## Затрагиваемые области и зависимости

- Ownership Developer: локальный integration fixture и тесты Worker,
  materialize, DB/API; при необходимости ограниченное исправление адаптеров
  `sports_forecast/predict.py` и `sports_forecast/training/models/`.
  Изменения иных модулей вернуть PO для проверки scope.
- Вход: reviewed [TASK-028-4](TASK-028-4-immutable-prediction-revisions.md).
  Локальный staged bundle v1.2.12 лежит вне Git в репозитории Operations Agent;
  точный путь и digest — в EPIC. Его наличие не доказывает совместимость с
  runtime, выбранным для TASK. LightGBM является локальным fixture.

## Проверка

- `uv run pytest -q tests/test_task_028_5_local_cycle.py::test_lgbm_adapter_can_predict_after_save_and_reload` — passed.
- Полный адресный integration gate на disposable PostgreSQL с миграцией до head — `2 passed`; сценарий получает NHL API расписание и строит признаки во временном каталоге.
- Проверены три `WorkerExecution.run_id`, совпадающие с `PredictionRevision.run_id`; повтор успешно завершённого Worker run не создаёт новую revision.
- API отдаёт probabilities последней revision после A→B→A. Повреждённый кандидат и NaN probabilities отклоняются без смены active pointer/current revision.
- `make lint` — passed; `make test-unit` — 1 508 passed, 16 deselected.
- Независимое review завершено: P0–P2 findings отсутствуют.

## Preflight 2026-10-10

- Staged bundle подтверждён по manifest как
  `sha256:a94173608d42bc69363be243527c1bdd893e2eee81c98f6615c01232aed1f64a`;
  SHA-256 файла CatBoost —
  `4042e85367a9d3c493a15ef45d0d9dcba9c78004833761224e379c360b0b5cda`.
- Read-only загрузка `CatBoostClassifier` на установленном CatBoost 1.2.8
  успешна: 489 уникальных имён `features.txt` совпадают по порядку с
  `model.feature_names_`, классы `[0, 1]`. `winner_withOT` target установлен
  конфигурацией как `player_win_full` — победа строки по полному счёту с ОТ и
  буллитами (`pl_goals_full > opp_goals_full`).
- Bundle manifest закрепляет `app_version=1.2.12`; checkout имеет
  `pyproject.toml version=1.2.15`. Вызов
  `verify_model_bundle(bundle, app_version="1.2.15")` завершился
  `BundleVerificationError: compatibility mismatch`. App version не менялась и
  manifest не переписывался. Это блокирует безопасное использование одобренного
  bundle через managed Worker/materialize путь.
- `data/source/nhl/source.csv`: 22 218 строк, максимальная дата матча
  2026-06-15, то есть нет предстоящих матчей относительно даты preflight
  2026-10-10. `data/interim/nhl/matches_interim.parquet`: 12 строк, содержит
  искусственный матч с датой 2027-01-01; он не является реальным inference
  входом и не используется для заявления о полном цикле.
- Поэтому интеграционный тест и A→B→A цикл не реализовывались: это потребовало
  бы ослабить runtime gate либо представить синтетические данные как реальный
  NHL вход.
- Handoff PO: нужен одобренный bundle, совместимый с app 1.2.15, либо отдельное
  явное решение о выпуске нового bundle из тех же байтов с полным compatibility
  evidence; также нужен свежий NHL inference dataset с реальным будущим матчем.

## Решение PO 2026-10-10

- Блокер версии снят только для локального контура: разрешён новый manifest v2
  для app 1.2.15 с теми же bytes модели (`4042e853...`), с сохранением исходного
  v1 bundle ID и происхождения в evidence. Исходный v1 manifest не переписывать;
  при проверке v1 не подменять app version.
- Production pointer и production promotion запрещены для этого TASK.
- Данные: официальный NHL API имеет реальные upcoming матчи; isolated refresh
  использует существующие `NhlWebApiSourceProvider`/`conf/source/nhl.yaml`, без
  записи в root `source.csv`, checkpoints или production storage.

## Результат gate 2026-10-10

- NHL API retrieval для `2026020084` SEA@WSH: `2026-10-10T11:11:44Z`;
  диапазон календаря — 2026-10-11; 51 будущая игра. Результат прошёл штатные
  clean/features stages во временном каталоге. Inference — 110 строк и 489
  признаков; event имеет 2 строки, 170 NaN ячеек (ожидаемые missing values
  upcoming roster/истории). Никакие значения не impute-ились.
- Feature parquet SHA-256: `433d5980935555498cbc5e3e29391bcd43371dea54913298c5645fc9704500dd`.
- Исходный approved v1 bundle: `sha256:a94173608d42bc69363be243527c1bdd893e2eee81c98f6615c01232aed1f64a`;
  CatBoost bytes SHA-256 `4042e85367a9d3c493a15ef45d0d9dcba9c78004833761224e379c360b0b5cda`.
  Временный managed CatBoost v2: `sha256:bd15a687b5c6439fce296d7c5a29351a90fbf952304e12f6bb1eb41052a55d24`;
  LightGBM fixture bundle: `sha256:3814e77c1f0fc0ad0eabf04838134cd73ae7cc9b7782736c1a1b7d184dac46a6`.
- Runtime: app 1.2.15, CatBoost 1.2.8, LightGBM 4.6.0. CatBoost adapter дал
  finite probabilities `[[0.2903, 0.7097], [0.6546, 0.3454]]`; LightGBM adapter
  на тех же двух event rows — `[[0.4634, 0.5366], [0.6441, 0.3559]]`. Обе
  матрицы лежат в [0,1] и суммируются в 1. LightGBM fixture обучен на 2 500
  размеченных строках read-only train history, с исходным target
  `pl_goals_full > opp_goals_full`.
- PostgreSQL 16 disposable container использовал отдельные базы и `tmpfs`,
  миграции прошли с `0001` по `0024`. Контейнер удалён после тестов; source/train
  parquet не менялись. Локальные веса и feature parquet остаются только в
  `/tmp`/pytest temp и не добавлены в Git.
- Integration test зафиксировал три уникальные immutable revisions в порядке
  `CatBoost A → LightGBM B → CatBoost A`, active pointer и API отражают A.
  Повреждённый candidate и NaN probabilities не изменили pointer/current
  revision; повторный `run_id` остался idempotent.
- Во время gate обнаружены и исправлены два дефекта: sklearn LightGBM 4.6.0
  требовал `fitted_` после adapter load; Worker раньше не передавал свой run ID
  в revision provenance. Для обоих добавлены адресные проверки.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-028-5-two-algorithm-local-cycle.md`.
- После независимого review Product Owner сверяет весь [REQ-028](../../product/requirements/REQ-028-production-model-contract.md), документацию, CI и PR gates.
