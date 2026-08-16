# ADR-008 — Надёжная delivery-цепочка NHL и закрытый первичный rollout

> **Статус:** accepted
> **Дата:** 2026-08-16
> **Связанное требование:** [REQ-008](../../product/requirements/REQ-008-reliable-nhl-delivery.md)

## Контекст и критерии выбора

Текущий scheduler ожидает CSV, archive создаётся только локально, Caddy обязателен,
а Docker публикует images при push в `main`. Нужно исключить потерю server data,
разделить credentials, сохранить betting provenance и разрешить private rollout.

## Рассмотренные варианты

1. **Status quo:** ручной source/S3 путь и обязательный ingress не выполняют REQ-008.
2. **Один privileged Worker:** проще, но Worker получает S3 credentials и связывает
   forecast с transient Object Storage failure.
3. **Разделённые acquisition, refresh и archive-sync jobs (выбран):** отдельные
   границы credentials/retry; ingress и release artifacts включаются явно.

## Решение

- Acquisition job получает NHL facts и обязательные odds и атомарно продвигает
  versioned source snapshot; Worker читает его read-only.
- Forecast quote сохраняется отдельно. Historical reference выбирается среди
  observations `T-60…T-0` ближайшей к `T-15`; backfill хранит provider и
  retrieval timestamps и не меняет published forecast provenance.
- После committed refresh отдельный S3 sync с write-only service account
  upload-ит manifest/partitions, remote-verifies hashes/sizes и лишь затем
  очищает persistent staging. Ошибка оставляет durable retry state.
- Local read-only import verify/deduplicate-ит archive и создаёт descriptor;
  DVC commit остаётся явным действием оператора.
- Base Compose — private DB/API/bot/worker; Caddy находится в public overlay.
  CI/security запускаются на PR/main, image publication/provenance — только tag.

## Последствия

- Положительные: автономность VPS, отсутствие S3 keys у Worker, нет потери
  archive при transient failure, private Telegram rollout не требует DNS.
- Отрицательные: отдельные jobs/state/service accounts и integration tests.
- Безопасность: secrets/payloads не пишутся в manifests/logs; stalled sync
  наблюдаем и retryable.

## Проверка и пересмотр

TDD проверяет atomic source promotion, mandatory odds failure, reference quote
selection/backfill, upload retry/corruption, private/public Compose и tag-only
workflow. Пересмотреть при необходимости автоматического DVC commit.

## Источники и неизвестное

- [REQ-008](../../product/requirements/REQ-008-reliable-nhl-delivery.md).
- [ADR-007](ADR-007-autonomous-production-data-runtime.md) — базовая topology.
