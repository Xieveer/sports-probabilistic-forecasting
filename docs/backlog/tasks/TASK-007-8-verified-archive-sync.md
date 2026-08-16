# TASK-007-8 — Проверяемый archive sync и local training import

> **Статус:** done
> **Владелец:** implementer + security-reviewer
> **Эпик:** [EPIC-007](../EPIC-007-autonomous-production-data-runtime.md)
> **Требование:** [REQ-008](../../product/requirements/REQ-008-reliable-nhl-delivery.md)
> **ADR:** [ADR-008](../../architecture/adr/ADR-008-reliable-delivery-and-private-rollout.md)

## Результат и границы

Отдельный retryable VPS-to-Object-Storage sync remote-verify-ит immutable
archive до cleanup; local read-only command import-ит его для ручного DVC
workflow. Worker не получает S3 credentials, DVC автоматически не вызывается.

## Критерии приёмки

- [x] Upload failure сохраняет staging и durable retry/failure state.
- [x] Service account/prefix не расширяют Worker credentials.
- [x] Local import идемпотентен, проверяет archive и создаёт descriptor; corrupt
  archive не меняет training input.

## План реализации

1. Написать failing upload/retry/corruption tests с fake storage.
2. Реализовать sync state, VPS sync и local pull/import commands.
3. Обновить env/runbooks/observability и провести security review.

## Проверка

Archive round-trip/retry tests, credential-boundary tests, security review.
