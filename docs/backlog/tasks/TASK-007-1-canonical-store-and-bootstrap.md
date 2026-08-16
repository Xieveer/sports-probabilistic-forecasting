# TASK-007-1 — Canonical store и initial NHL bootstrap

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-007](../EPIC-007-autonomous-production-data-runtime.md)
> **Требование:** [REQ-007](../../product/requirements/REQ-007-production-data-runtime.md)
> **ADR:** [ADR-007](../../architecture/adr/ADR-007-autonomous-production-data-runtime.md)

## Результат и границы

Добавить versioned PostgreSQL schema для полной canonical истории NHL и
идемпотентный initial bootstrap из локального immutable data bundle. Bundle
содержит исходные canonical данные и manifest/checksums, но не features,
training artifacts или secrets. После успешного import VPS способен стать
источником последующих provider updates.

## Критерии приёмки

- [x] Schema хранит event identity/revision, расписание, результат, source и
  ingestion provenance, tournament boundary и refresh watermark без NHL-only
  имён таблиц.
- [x] Bootstrap проверяет manifest и checksum до любой DB-записи, повторный
  запуск с тем же immutable ID идемпотентен, а ошибка не публикует partial state.
- [x] Migration additive, имеет backup/recovery инструкции и PostgreSQL
  integration test.

## План реализации

1. Написать failing tests на schema constraints, повреждённый manifest и
   repeated bootstrap.
2. Реализовать migration, bundle builder/verifier/importer и safe execution
   state.
3. Документировать локальное создание bundle и VPS import без доступа к API.

## Проверка

Targeted unit tests, disposable PostgreSQL migration/import integration tests,
bootstrap fixture round-trip.

## Handoff и отчёт

Отчёт выполнения: [TASK-007-1](../../changes/done/TASK-007-1-canonical-store-and-bootstrap.md).
