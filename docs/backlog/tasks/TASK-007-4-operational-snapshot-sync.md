# TASK-007-4 — Immutable operational snapshot sync

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-007](../EPIC-007-autonomous-production-data-runtime.md)
> **Требование:** [REQ-007](../../product/requirements/REQ-007-production-data-runtime.md)
> **ADR:** [ADR-007](../../architecture/adr/ADR-007-autonomous-production-data-runtime.md)

## Результат и границы

После каждого successfully committed refresh VPS создаёт immutable manifest и
content-addressed Parquet partitions canonical dataset в Object Storage.
Локальная команда проверяет manifest, докачивает только отсутствующие partitions
и явно создаёт DVC training input. Direct DB access, DVC в VPS runtime и export
features не входят в задачу.

## Критерии приёмки

- [x] Manifest включает schema/data snapshot identity, run/config/source
  provenance, относительные paths, size и SHA-256 без secrets/payloads.
- [x] Upload staging artifact выполняется только после successful DB commit; failure не создаёт
  manifest, который выдаётся за актуальное состояние.
- [x] Local import валидирует/deduplicates всё до изменения DVC input; repeat
  import идемпотентен и повреждённый partition не меняет состояние.

## План реализации

1. Написать failing manifest, partition hash, atomic publish и local import
   contract tests.
2. Реализовать export/import CLI и separate Object Storage prefixes/roles.
3. Документировать training sync workflow и provenance, без автоматического train.

## Итог

Выполнено; отчёт: [TASK-007-4](../../changes/done/TASK-007-4-operational-snapshot-sync.md).

## Проверка

Archive/import round-trip fixtures, corruption/retry tests, security review
credentials boundary.
