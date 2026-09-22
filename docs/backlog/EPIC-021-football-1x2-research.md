# EPIC-021 — Исследование 1X2 для топовых футбольных лиг

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** главный агент
> **Требование:** [REQ-021](../product/requirements/REQ-021-top-football-winner-baseline.md)
> **ADR:** [ADR-021](../architecture/adr/ADR-021-football-1x2-research-pool.md)

## Цель и границы

Провести Research Mode цикл CatBoost для pooled футбольного 1X2: Big Five, РПЛ, ФНЛ, ЛЧ и
ЛЕ. Criteria locked holdout 2025/26: ROI ≥5%, coverage >20%, temporal validation и
probabilistic metrics. Historical `odd_*` — разрешённый пользователем, но непроверенный
last-prematch proxy; результат не означает подтверждённый production edge.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-021-1](tasks/TASK-021-1-club-pool-data-contract.md) | Изолированный club-pool contract, fixture и ingest/clean smoke | REQ-021, ADR-021 | red/green tests, schema gate | in_progress |
| TASK-021-2 | Advanced features и leakage audit | TASK-021-1 | feature tests, processed validation | backlog |
| TASK-021-3 | 1X2 target, CatBoost temporal baseline и Research Harness coverage gate | TASK-021-2 | temporal tests, experiment report | backlog |
| TASK-021-4 | Полный backfill, research iterations и итоговый report | TASK-021-3 | locked-holdout evidence | backlog |
| [TASK-021-5](tasks/TASK-021-5-bronze-completeness-manifest.md) | Manifest полноты bronze и поэтапный required/optional ingest | TASK-021-1 | unit/integration tests, coverage report | backlog |

## Риски и rollout

Не выполняются promotion, deployment и публикация модели. Массовый API backfill начинается
только после проверенного fixture-среза. ROI ограничен допущением historical odds; повторное
раскрытие locked holdout запрещено.

## Полное EPIC review

Заполняется независимым reviewer после terminal-статусов всех TASK.
