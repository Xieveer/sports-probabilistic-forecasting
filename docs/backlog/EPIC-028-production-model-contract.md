# EPIC-028 — Контракт выбранной production-модели

> **Статус:** done — локальный результат и полное EPIC review; PR/terminal CI ожидаются
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-028](../product/requirements/REQ-028-production-model-contract.md), confirmed
> **ADR:** [ADR-030](../architecture/adr/ADR-030-production-model-contract.md), accepted

## Память Product Owner

- Инициатива: `EPIC-028`.
- Ветка инициативы: `initiative/epic-028-production-model-contract`; отдельный worktree `.worktrees/epic-028-production-model-contract`.
- Workflow / этап: `engineering / полное EPIC review завершено; PR и terminal CI ожидаются`.
- Исходная цель: production загружает выбранную проверенную модель без знания её алгоритма и сохраняет точную версию каждого прогноза.
- Критерии и DoD: [REQ-028](../product/requirements/REQ-028-production-model-contract.md); пара legacy NHL CatBoost + локальная LightGBM на том же `winner_withOT` подтверждена. Затем ADR, red → green → refactor, независимый review, PR и окончательно зелёный CI.
- Релиз: production-развёртывание не запрошено.
- Выполнено: 2026-10-10 подтверждён REQ и принят ADR-030. TASK-028-1 завершён на `3f4ea4b` (49 адресных тестов), TASK-028-2 на `aa204834` (40 тестов), оба после повторного review без P0–P2. [TASK-028-3](tasks/TASK-028-3-managed-pointer-activation.md) завершён на `35378e8f`: 52 адресных теста, PostgreSQL concurrency и Alembic `0022` прошли; два correction cycles закрыли managed rollback, legacy обход и DB/parquet границу; финальное независимое review без P0–P2. [TASK-028-4](tasks/TASK-028-4-immutable-prediction-revisions.md) завершён на `f5a9779`: append-only revisions, Alembic `0023`/`0024`, разделение источников в витрине и проверка вероятностей; PostgreSQL integration и 34 адресных теста прошли, независимое review без P0–P2. [TASK-028-5](tasks/TASK-028-5-two-algorithm-local-cycle.md) завершён на `258ee4c`: реальный будущий NHL вход, 489 признаков и локальный CatBoost → LightGBM → rollback, три immutable revisions, API и negative gates на PostgreSQL 16; независимое TASK review без P0–P2. DB — источник опубликованной витрины, parquet — вторичный артефакт. Исходный approved NHL CatBoost payload сохранил SHA-256.
- Решения: [ADR-030](../architecture/adr/ADR-030-production-model-contract.md) принят Product Owner 2026-10-10: registry DB — единственный pointer managed-пары; legacy-файловый pointer остаётся явным отдельным профилем. Из-за `app_version=1.2.12` исходного v1 bundle Product Owner разрешил только локально создать отдельный managed v2 для app 1.2.15 из тех же model bytes с сохранением исходного SHA/provenance; production promotion не разрешён.
- Артефакты: [REQ-028](../product/requirements/REQ-028-production-model-contract.md), [ADR-030](../architecture/adr/ADR-030-production-model-contract.md), [TASK-028-1](tasks/TASK-028-1-bundle-registry-guard.md), [отчёт TASK-028-1](../changes/done/TASK-028-1-bundle-registry-guard.md), [TASK-028-2](tasks/TASK-028-2-bundle-manifest-v2.md), [отчёт TASK-028-2](../changes/done/TASK-028-2-bundle-manifest-v2.md), [TASK-028-3](tasks/TASK-028-3-managed-pointer-activation.md), [отчёт TASK-028-3](../changes/done/TASK-028-3-managed-pointer-activation.md), [TASK-028-4](tasks/TASK-028-4-immutable-prediction-revisions.md), [отчёт TASK-028-4](../changes/done/TASK-028-4-immutable-prediction-revisions.md), [TASK-028-5](tasks/TASK-028-5-two-algorithm-local-cycle.md), [отчёт TASK-028-5](../changes/done/TASK-028-5-two-algorithm-local-cycle.md).
- Предыдущая роль: Reviewer — полное EPIC review после синхронизации с `main` без P0–P2; проверены REQ/ADR/TASK 1–5, миграции 0022–0024, Worker/API/бот и отсутствие чувствительных артефактов в diff. PostgreSQL/live NHL gate подтверждён отчётом Developer, Reviewer лично не повторял.
- Следующая роль: Product Owner — открыть PR, дождаться terminal CI и при зелёном результате слить в `main`.
- Открытые вопросы / блокеры: локальный gate не заблокирован. Повтор полного теста требует live NHL API, конкретного будущего события и локальных approved артефактов; production rollout, качество LightGBM и связь prediction revision с odds observation остаются отдельными решениями. Не копировать веса в Git.
- Research: не применяется.
- Обновлено: 2026-10-10.

## Цель и границы

Связать выбранный production pointer с реально загружаемым неизменяемым bundle и контрактом признаков/outcomes. Сохранять неизменяемую версию опубликованного прогноза для будущей ссылки из журнала ставок. Не автоматизировать promotion по одной метрике.

## Проверяемый результат

1. На локальном тестовом контуре активируются модели двух разных типов без изменения Worker и API; rollback возвращает проверенный прежний bundle.
2. У записи прогноза можно установить точный bundle, контракт признаков, время расчёта и вероятности; повторная материализация не уничтожает эту версию.
3. Невалидный или несовместимый bundle не меняет действующую публикацию.
4. Прежняя одобренная NHL-модель остаётся загрузимой на совместимом runtime.

## Зависимости и следующий gate

Можно вести отдельно от EPIC-027; нужен до полного результата [EPIC-029](EPIC-029-configured-tournament-onboarding.md) и [EPIC-031](EPIC-031-real-bets-ledger.md). Перед TASK — REQ и ADR о pointer/bundle/loader.

Архитектурный handoff: [ADR-030](../architecture/adr/ADR-030-production-model-contract.md)
сравнивает источники истины и закрепляет DB registry pointer для managed-пар,
manifest v2 и append-only prediction revisions. Решение принято.

[TASK-028-1](tasks/TASK-028-1-bundle-registry-guard.md) закрыл первый guard, но
не весь REQ. Последовательные срезы:

1. [TASK-028-2](tasks/TASK-028-2-bundle-manifest-v2.md) — manifest v2 verifier
   и совместимость legacy v1 без DB/Worker изменений.
2. [TASK-028-3](tasks/TASK-028-3-managed-pointer-activation.md) — DB pointer,
   ручная активация, общий resolver и PostgreSQL race gate.
3. [TASK-028-4](tasks/TASK-028-4-immutable-prediction-revisions.md) — append-only
   revisions и атомарная витрина после согласования схемы с EPIC-027.
4. [TASK-028-5](tasks/TASK-028-5-two-algorithm-local-cycle.md) — реальный
   локальный CatBoost → LightGBM → rollback и API-проверка.

Все пять TASK завершены после независимых review. Следующий gate — полное EPIC
review, PR и terminal CI. Production-развёртывание не запрошено.

## Риски и rollout

Не менять NHL production pointer в ходе разработки; проверять bundle и обратную совместимость на изолированном контуре. Выкладка — отдельное решение.

## Полное EPIC review

2026-10-10: независимый Reviewer проверил ветку после синхронизации с `main`,
REQ-028 и ADR-030, пять TASK и подготовленные Product Owner изменения статусов.
P0–P2 findings нет. Локальный реальный gate на NHL `2026020084` подтвердил
CatBoost A → LightGBM B → rollback A, три immutable revisions, текущую
API-выдачу и negative gates; точное evidence находится в
[отчёте TASK-028-5](../changes/done/TASK-028-5-two-algorithm-local-cycle.md).
Reviewer лично повторил адресный LightGBM reload, но полный PostgreSQL/live
NHL gate не запускал. После merge `main` Product Owner выполнил `make lint`
и `make test-unit`: 1525 passed, 16 deselected, 40 warnings.
Повтор полного интеграционного gate требует live NHL API и локальных модельных
артефактов; production-развёртывание не запрошено.
