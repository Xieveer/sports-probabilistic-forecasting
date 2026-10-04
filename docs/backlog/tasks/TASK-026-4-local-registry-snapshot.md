# TASK-026-4 — Проверяемый локальный снимок и provenance обучения

> **Статус:** backlog
> **Владелец:** Developer
> **Эпик:** [EPIC-026](../EPIC-026-entity-registry.md)
> **Требование:** [REQ-026](../../product/requirements/REQ-026-entity-registry.md)
> **ADR:** [ADR-027](../../architecture/adr/ADR-027-local-entity-registry-and-snapshots.md)

## Результат и границы

Локальный master экспортирует полный переносимый снимок и закрепляет его
версию для загрузки истории и обучения. Публикация в Object Storage — отдельная
TASK.

## Критерии приёмки

- [ ] Два экспорта одинакового состояния дают один content ID и проверяемые
      hashes/counts/schema version без секретов и provider payload.
- [ ] Неполный или изменённый снимок отвергается до установки.
- [ ] Исторический ingest и training run работают без сервера на закреплённой
      версии; изменения master в середине run не меняют разрешение.
- [ ] Идентификатор registry snapshot сохраняется в provenance данных и модели.

## План реализации

1. Написать падающие тесты детерминизма, повреждения и pinned read.
2. Добавить полный JSONL export/verification и offline reader.
3. Привязать version к локальному ingest/training provenance и проверить регрессии.

## Зависимости и проверка

- После [TASK-026-1](TASK-026-1-source-neutral-entity-registry.md) и
  [TASK-026-3](TASK-026-3-event-identity-bridge.md).
- Затрагивает identity export, локальный data/training contract и тесты;
  команды записать в отдельном отчёте `done`.
- Следующий gate: независимый review, затем TASK-026-5.
