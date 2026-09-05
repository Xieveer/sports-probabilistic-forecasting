# REQ-016 — Production Compose contract для v1.1.6

> **Статус:** confirmed
> **Владелец продукта:** пользователь
> **Создано:** 2026-09-05

## Результат и ценность

Worker v1.1.6 на VPS читает проверенный model bundle из
`/srv/sports-forecast/runtime_models` через неизменяемый `/app/models`, а CI
до публикации образов доказывает rendered Compose и final-image contract.

## Scope

- Bind mount `SF_MODEL_RUNTIME_ROOT` вместо Docker named volume, fixture и gates.
- Final Worker проверяет model pointer, source-state/bootstrap и runtime identity.
- Обновление v1.1.6, runbooks, handoff и pre-release boundary review.

## Non-scope

- Запуск PostgreSQL, миграций, application runtime, timer, deployment, tag или публикация image.
- Изменение immutable v1.1.5 или выдача IAM/secrets.

## Сценарии

1. Rendered Compose получает только immutable images и host mounts без published ports.
2. Final Worker без сети и с read-only root filesystem читает `current` model bundle.
3. Повреждённый mount, named model volume или неразрешённый service останавливают CI до publish.

## Критерии приёмки

- [x] Worker монтирует `${SF_MODEL_RUNTIME_ROOT}:/app/models:ro`; `runtime_models` не является Docker volume.
- [x] CI рендерит Compose с безопасным fixture и программно валидирует topology, mounts, resources и immutable images.
- [x] CI создаёт model fixture штатными builder/installer и проверяет его в final Worker image как `10001:10001` без сети и записи.
- [x] CI проверяет source-state/canonical bootstrap validators и imports operational modules в том же final image.
- [x] Runbook/handoff содержат v1.1.6 contract, risk review и DevOps handoff fields.

## Ограничения, зависимости и риски

- Host mount ownership и реальные image digests проверяет DevOps после CI; fixture не заменяет VPS validation.
- Initial model activation допускает отсутствие `previous`; rollback возможен только после следующей promotion.

## Подтверждение

ТЗ пользователя «v1.1.6 — production Compose contract и pre-deployment gates» от 2026-09-05.
