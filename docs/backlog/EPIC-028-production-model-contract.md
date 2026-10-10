# EPIC-028 — Контракт выбранной production-модели

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-028](../product/requirements/REQ-028-production-model-contract.md), confirmed
> **ADR:** [ADR-030](../architecture/adr/ADR-030-production-model-contract.md), accepted

## Память Product Owner

- Инициатива: `EPIC-028`.
- Ветка инициативы: `initiative/epic-028-production-model-contract`; отдельный worktree `.worktrees/epic-028-production-model-contract`.
- Workflow / этап: `engineering / TASK-028-2 reviewed; TASK-028-3`.
- Исходная цель: production загружает выбранную проверенную модель без знания её алгоритма и сохраняет точную версию каждого прогноза.
- Критерии и DoD: [REQ-028](../product/requirements/REQ-028-production-model-contract.md); пара legacy NHL CatBoost + локальная LightGBM на том же `winner_withOT` подтверждена. Затем ADR, red → green → refactor, независимый review, PR и окончательно зелёный CI.
- Релиз: production-развёртывание не запрошено.
- Выполнено: 2026-10-10 подтверждён REQ и принят ADR-030. [TASK-028-1](tasks/TASK-028-1-bundle-registry-guard.md) завершён на `3f4ea4b`, повторное review без P0–P2; 49 адресных тестов. [TASK-028-2](tasks/TASK-028-2-bundle-manifest-v2.md) завершён на `aa204834`: замечания по реальному `deploy.yaml` и правилам `winner_withOT` исправлены; повторное review без P0–P2, 40 адресных тестов. Найден локальный NHL CatBoost payload: SHA-256 совпадает с весами staged v1.2.12 bundle.
- Решения: [ADR-030](../architecture/adr/ADR-030-production-model-contract.md) принят Product Owner 2026-10-10: registry DB — единственный pointer managed-пары; legacy-файловый pointer остаётся явным отдельным профилем. Нынешний upsert не сохраняет историю версий.
- Артефакты: [REQ-028](../product/requirements/REQ-028-production-model-contract.md), [ADR-030](../architecture/adr/ADR-030-production-model-contract.md), [TASK-028-1](tasks/TASK-028-1-bundle-registry-guard.md), [отчёт TASK-028-1](../changes/done/TASK-028-1-bundle-registry-guard.md), [TASK-028-2](tasks/TASK-028-2-bundle-manifest-v2.md), [отчёт TASK-028-2](../changes/done/TASK-028-2-bundle-manifest-v2.md), [TASK-028-3](tasks/TASK-028-3-managed-pointer-activation.md), [TASK-028-4](tasks/TASK-028-4-immutable-prediction-revisions.md), [TASK-028-5](tasks/TASK-028-5-two-algorithm-local-cycle.md), [долгосрочный план](index.md#долгосрочные-инициативы-платформы).
- Предыдущая роль: Reviewer — повторная независимая проверка TASK-028-2 без P0–P2.
- Следующая роль: Developer — TASK-028-3 через red → green → refactor; затем независимый Reviewer.
- Открытые вопросы / блокеры: для TASK-028-3 согласовать Alembic head с EPIC-027; для TASK-028-4 — namespace события и nullable связь с odds observation до миграции; для TASK-028-5 — совместимость локального bundle v1.2.12 с выбранным runtime и точный feature/outcome contract по payload. Локальный staged bundle: `/home/xieveer/Документы/codex_projects/operations-agent/tmp/v1.2.12-model-stage/bundles/sha256:a94173608d42bc69363be243527c1bdd893e2eee81c98f6615c01232aed1f64a`. Не копировать веса в Git.
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

Каждый следующий TASK начинается после независимого review предыдущего.

## Риски и rollout

Не менять NHL production pointer в ходе разработки; проверять bundle и обратную совместимость на изолированном контуре. Выкладка — отдельное решение.
