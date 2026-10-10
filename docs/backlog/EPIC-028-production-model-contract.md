# EPIC-028 — Контракт выбранной production-модели

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-028](../product/requirements/REQ-028-production-model-contract.md), confirmed
> **ADR:** решение о единственном production pointer принять перед реализацией

## Память Product Owner

- Инициатива: `EPIC-028`.
- Ветка инициативы: `initiative/epic-028-production-model-contract`; отдельный worktree `.worktrees/epic-028-production-model-contract`.
- Workflow / этап: `engineering / уточнение требований`.
- Исходная цель: production загружает выбранную проверенную модель без знания её алгоритма и сохраняет точную версию каждого прогноза.
- Критерии и DoD: [REQ-028](../product/requirements/REQ-028-production-model-contract.md); пара legacy NHL CatBoost + локальная LightGBM на том же `winner_withOT` подтверждена. Затем ADR, red → green → refactor, независимый review, PR и окончательно зелёный CI.
- Релиз: production-развёртывание не запрошено.
- Выполнено: направление зафиксировано 2026-10-04; 2026-10-10 изучены bundle, registry, Worker, materialize, витрина и их тесты; REQ подтверждён для локальной пары двух алгоритмов.
- Решения: использовать существующие model bundle и promotion как исходные механизмы; источник истины и cardinality pointer ещё не выбраны. Нынешний upsert не сохраняет историю версий.
- Артефакты: [REQ-028](../product/requirements/REQ-028-production-model-contract.md), [долгосрочный план](index.md#долгосрочные-инициативы-платформы), [EPIC-003](EPIC-003-scalable-multisport-platform.md), [EPIC-005](EPIC-005-production-serving-readiness.md).
- Предыдущая роль: Product Owner — анализ текущего контракта и draft требований.
- Следующая роль: Architect — ADR о единственном источнике истины для выбранной модели, согласовании registry и bundle pointer, формате loader; затем Developer для минимального среза.
- Открытые вопросы / блокеры: одобренный NHL payload отсутствует в Git и должен быть доступен на изолированном контуре; соответствие registry pointer файловому bundle; общий schema gate с EPIC-027 для ссылок на prediction revisions и odds observations.
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

Первый вертикальный TASK после ADR: создать локальный контракт выбора проверенного
bundle для одной пары `nhl / winner_withOT`; red-тест предъявляет несовпадение
registry `model_identity` и bundle manifest, green сохраняет прежнюю публикацию
при mismatch и записывает `bundle_id` у новой версии прогноза. Проверка —
целевой unit/integration test `bundle → Worker → materialize → DB` с двумя
алгоритмами и rollback. Хранение версий и ссылки на odds observation согласовать
с EPIC-027 до общей миграции. Затрагиваемые области: deploy bundle, materialize,
PredictionRepository и DB models; Worker/API без алгоритмических веток.

## Риски и rollout

Не менять NHL production pointer в ходе разработки; проверять bundle и обратную совместимость на изолированном контуре. Выкладка — отдельное решение.
