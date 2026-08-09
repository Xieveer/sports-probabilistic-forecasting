# TASK-005-7 — Serving-data sync и operational archive

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-005](../EPIC-005-production-serving-readiness.md)
> **Требование:** [REQ-005](../../product/requirements/REQ-005-production-serving-release.md)
> **ADR:** [ADR-005](../../architecture/adr/ADR-005-production-serving-boundary.md)

## Результат и границы

Определить и реализовать однонаправленный поток VPS → operational archive →
локальный DVC и локальный DVC → compact serving-data bundle → VPS. VPS не
запускает DVC и не хранит полный dataset; на нём остаётся максимум семь дней
runtime data. Не включать lineup fast path или automatic retraining.

## Критерии приёмки

- [x] Каждый archived production snapshot имеет immutable ID, timestamp,
  checksum и безопасный manifest; данные не смешиваются с DVC cache.
- [x] Локальная import-команда валидирует/deduplicates archive до обновления
  DVC revision; ошибка не меняет training dataset.
- [x] Serving-data bundle содержит только доказанно необходимые feature state/
  lookback data, имеет checksum и current/previous rollback, а VPS читает его
  read-only.
- [x] Runtime cleanup старше семи дней происходит только после успешной
  archival verification; cloud archive не удаляется автоматически.

## План реализации

1. Написать failing tests на manifest, validation-before-import и retention
   safety.
2. Ввести minimal archive/bundle CLI, Object Storage layout и read/write env
   contracts без значений секретов.
3. Проверить local round-trip fixture и document operator workflow.

## Проверка

- Archive/bundle contract tests, local fixture round-trip, `make test-unit`.

## Handoff и отчёт

- Блокер: TASK-005-1 устанавливает production topology и credentials boundary.
- Отчёт выполнения: [TASK-005-7](../../changes/done/TASK-005-7-serving-data-sync-and-archive.md).
