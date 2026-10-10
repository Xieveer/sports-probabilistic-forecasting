# TASK-028-5 — Локальный цикл двух алгоритмов и rollback

> **Статус:** backlog
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

- [ ] Локальный CatBoost payload сверен с documented approved bundle по SHA-256,
  загружается на совместимом runtime; его реальные feature order/types,
  market rules и `home_win / away_win` установлены по артефакту. Старые
  неизвестные training refs не заполняются догадками.
- [ ] LightGBM fixture построен на совместимом входе для того же рынка и
  исходов, проходит тот же manifest v2 verifier и Loader/Worker/API без
  алгоритмических веток и без production promotion.
- [ ] CatBoost → LightGBM → rollback CatBoost даёт три успешных локальных run;
  каждый сохраняет отдельную immutable revision с точным bundle ID, feature
  contract, временем и вероятностями. Старые revisions читаются по ID;
  актуальная витрина/API отражает последнюю активацию.
- [ ] Повреждённый или несовместимый candidate, а также невалидный набор
  вероятностей не меняют active pointer или текущую публикацию.
- [ ] Для `winner_withOT` до публикации проверены конечность, диапазон и
  сумма вероятностей `home_win / away_win`; при нарушении витрина и revisions
  остаются прежними.
- [ ] Evidence содержит версии runtime, checksums и результаты теста без
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

- Новый адресный integration test с реальными библиотеками CatBoost и LightGBM
  и изолированной PostgreSQL DB — ожидается success; mock не заменяет gate.
- `make lint`, `make test-unit`, затронутые API/Worker tests и независимый review.
- Наблюдение: три revision ID и последовательность bundle IDs `A → B → A`,
  актуальная API-выдача с `A`, история содержит все три версии.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-028-5-two-algorithm-local-cycle.md`.
- После независимого review Product Owner сверяет весь [REQ-028](../../product/requirements/REQ-028-production-model-contract.md), документацию, CI и PR gates.
