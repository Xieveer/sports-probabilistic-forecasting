# TASK-007-9 — Private ingress и tag-only release artifacts

> **Статус:** done
> **Владелец:** implementer + devops-reviewer
> **Эпик:** [EPIC-007](../EPIC-007-autonomous-production-data-runtime.md)
> **Требование:** [REQ-008](../../product/requirements/REQ-008-reliable-nhl-delivery.md)
> **ADR:** [ADR-008](../../architecture/adr/ADR-008-reliable-delivery-and-private-rollout.md)

## Результат и границы

Base Compose запускает private Telegram-only candidate без Caddy/domain/public
ports. Public ingress отдельный opt-in overlay. Image publication/provenance
выполняется только versioned tag; tag/deployment не выполняются задачей.

## Критерии приёмки

- [x] Private config валиден без Caddy, `SF_API_DOMAIN` и `80/443`.
- [x] Public overlay сохраняет запрет public metrics.
- [x] CI/security работают для PR/main, image scans/provenance/digests — exact tag.
- [x] Handoff содержит immutable model ID/checksum/compatibility и rollback.

## План реализации

1. Написать failing Compose/workflow/model-handoff tests.
2. Реализовать overlays, workflow gates и runbooks.
3. Провести release/devops/security review без публикации artifacts.

## Проверка

`docker compose config` private/public, workflow tests, `make production-check`.
