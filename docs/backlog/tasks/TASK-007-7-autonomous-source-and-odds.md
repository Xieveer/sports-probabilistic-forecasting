# TASK-007-7 — Автономный source snapshot и odds observations

> **Статус:** done
> **Владелец:** implementer + test-designer
> **Эпик:** [EPIC-007](../EPIC-007-autonomous-production-data-runtime.md)
> **Требование:** [REQ-008](../../product/requirements/REQ-008-reliable-nhl-delivery.md)
> **ADR:** [ADR-008](../../architecture/adr/ADR-008-reliable-delivery-and-private-rollout.md)

## Результат и границы

VPS самостоятельно получает NHL facts и обязательные odds, атомарно публикует
source snapshot для read-only Worker и сохраняет distinct forecast/reference
odds provenance. Не включать scheduler на VPS.

## Критерии приёмки

- [x] Ошибка NHL/Odds не заменяет snapshot и не запускает refresh по partial CSV.
- [x] Reference quote выбирается из `T-60…T-0` ближайшей к `T-15`; forecast
  quote/backfill не переписывают друг друга.
- [x] Historical backfill заполняет отдельные `*_t15` и timing provenance,
  сохраняя legacy `*_close` без изменений.
- [x] Scheduler исполняет acquisition → quality gate → canonical refresh с
  bounded timeout, locks и safe signals.

## План реализации

1. Написать failing atomic-promotion и quote-selection tests.
2. Реализовать acquisition/odds state и orchestration без S3 access.
3. Обновить Compose/systemd/runbooks и проверить dry-run.

## Проверка

Targeted provider/orchestration tests, `docker compose config` и negative
odds/provider failures.
