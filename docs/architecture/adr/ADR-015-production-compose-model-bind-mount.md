# ADR-015 — Host bind mount для production model runtime

> **Статус:** accepted
> **Дата:** 2026-09-05
> **Связанное требование:** [REQ-016](../../product/requirements/REQ-016-production-compose-contract-v1-1-6.md)

## Контекст и критерии выбора

Проверенный bundle и symbolic pointer `current` создаются Operations на VPS в
`/srv/sports-forecast/runtime_models`. Named volume Compose является другим,
пустым хранилищем и нарушает application contract `/app/models`.

## Рассмотренные варианты

1. **Status quo: named volume.** Не видит host bundle и не годится.
2. **Bind mount host root (выбран).** Явно связывает проверенный host state с
   `/app/models:ro`; contract можно рендерить и тестировать.
3. **Копировать bundle в image.** Нарушает независимую promotion/rollback и
   увеличивает release artifact.

## Решение

Worker использует `${SF_MODEL_RUNTIME_ROOT}:/app/models:ro`. В Compose остаётся
только persistent Docker volume `pg_data`; model root принадлежит Operations и
проверяется перед rollout. CI создаёт fixture через штатные model builder и
installer, а затем проверяет mount в final image.

## Последствия

- Положительные: pointer/current и immutable bundle одинаковы у host и Worker.
- Отрицательные и стоимость: Operations обязан подготовить host directory с
  UID/GID `10001:10001` и минимальными правами.
- Безопасность и эксплуатация: Worker не получает write в model root или model
  storage credentials; активация выполняется отдельным privileged process.

## Проверка и пересмотр

Rendered Compose gate и final-image model-mount gate обязательны до publish.
Пересмотр требуется, если model delivery переедет в иной проверяемый runtime
artifact mechanism.

## Источники и неизвестное

- [REQ-016](../../product/requirements/REQ-016-production-compose-contract-v1-1-6.md).
- Реальные VPS paths, ownership и IAM подтверждаются только server-side review.
