# EPIC-028 — Контракт выбранной production-модели

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-028](../product/requirements/REQ-028-production-model-contract.md), confirmed
> **ADR:** [ADR-030](../architecture/adr/ADR-030-production-model-contract.md), accepted

## Память Product Owner

- Инициатива: `EPIC-028`.
- Ветка инициативы: `initiative/epic-028-production-model-contract`; отдельный worktree `.worktrees/epic-028-production-model-contract`.
- Workflow / этап: `engineering / review TASK-028-1`.
- Исходная цель: production загружает выбранную проверенную модель без знания её алгоритма и сохраняет точную версию каждого прогноза.
- Критерии и DoD: [REQ-028](../product/requirements/REQ-028-production-model-contract.md); пара legacy NHL CatBoost + локальная LightGBM на том же `winner_withOT` подтверждена. Затем ADR, red → green → refactor, независимый review, PR и окончательно зелёный CI.
- Релиз: production-развёртывание не запрошено.
- Выполнено: направление зафиксировано 2026-10-04; 2026-10-10 подтверждён REQ, принят ADR-030, TASK-028-1 реализован через red → green → refactor; 47 адресных тестов и commit hooks прошли. Независимое review открыто.
- Решения: [ADR-030](../architecture/adr/ADR-030-production-model-contract.md) принят Product Owner 2026-10-10: registry DB — единственный pointer managed-пары; legacy-файловый pointer остаётся явным отдельным профилем. Нынешний upsert не сохраняет историю версий.
- Артефакты: [REQ-028](../product/requirements/REQ-028-production-model-contract.md), [ADR-030](../architecture/adr/ADR-030-production-model-contract.md), [TASK-028-1](tasks/TASK-028-1-bundle-registry-guard.md), [отчёт TASK-028-1](../changes/done/TASK-028-1-bundle-registry-guard.md), [долгосрочный план](index.md#долгосрочные-инициативы-платформы).
- Предыдущая роль: Developer — TASK-028-1 и адресные проверки.
- Следующая роль: Reviewer — независимая проверка TASK-028-1, включая прямой вызов materialize и пустой вход; затем Product Owner декомпозирует следующие срезы ADR-030.
- Открытые вопросы / блокеры: одобренный NHL payload отсутствует в Git и нужен на изолированном контуре; общий schema gate с EPIC-027 для ссылок на prediction revisions и odds observations.
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

Первый малый срез — [TASK-028-1](tasks/TASK-028-1-bundle-registry-guard.md):
проверять совпадение verified bundle и registry до inference и публикации,
включая empty input. Он не требует миграции и не закрывает весь REQ.
После него Product Owner выделяет задачи на managed pointer/manifest v2,
immutable revisions и сквозной двухалгоритмовый прогон с rollback.
Схему revisions и odds observations согласовать с EPIC-027 до миграций.

## Риски и rollout

Не менять NHL production pointer в ходе разработки; проверять bundle и обратную совместимость на изолированном контуре. Выкладка — отдельное решение.
