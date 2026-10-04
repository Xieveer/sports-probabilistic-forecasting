# TASK-026-4 — Проверяемый локальный снимок и provenance обучения

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-026](../EPIC-026-entity-registry.md)
> **Требование:** [REQ-026](../../product/requirements/REQ-026-entity-registry.md)
> **ADR:** [ADR-027](../../architecture/adr/ADR-027-local-entity-registry-and-snapshots.md)

## Результат и границы

Локальный master экспортирует полный переносимый снимок и закрепляет его
версию для загрузки истории и обучения. Публикация в Object Storage — отдельная
TASK.

## Критерии приёмки

- [x] Два экспорта одинакового состояния дают один content ID и проверяемые
      hashes/counts/schema version без секретов и provider payload.
- [x] Неполный или изменённый снимок отвергается до установки.
- [x] Исторический ingest и training run работают без сервера на закреплённой
      версии; изменения master в середине run не меняют разрешение.
- [x] Идентификатор registry snapshot сохраняется в provenance данных и модели.
- [x] Rollout задан per-tournament; каждый этап закрепляет один verified
      content-addressed package и не смешивает выбранную версию при переключении
      current во время обработки.
- [x] Пакет включает evidence финализированных owner decisions, исключая
      pending-only queue, и ограничивает чтение manifest до парсинга.
- [x] Каждое candidate decision ссылается на immutable evidence revision;
      verifier проверяет целостность и обе стороны связи.
- [x] Export/verifier принимают весь write-contract диапазон candidate evidence:
      факты до 1000 символов и предложенные bounded IDs сохраняются даже после
      reject, не требуя существования project entity.

## План реализации

1. Написать падающие тесты детерминизма, повреждения и pinned read.
2. Добавить полный JSONL export/verification и offline reader.
3. Привязать version к локальному ingest/training provenance и проверить регрессии.

Выполнен offline boundary для документированных NHL и Smart Tables adapters.
Неизвестные designation остаются unresolved и ставятся в локальную owner queue;
новое решение попадает в работу только после следующего selected snapshot. Pool
training с произвольным DataFrame fail-closed, пока не будет per-input provenance.
Для enabled турниров adapter preflight происходит до outputs, прочие турниры
явно остаются в legacy режиме. Historical adapter использует batch reverse
uniqueness; ingest/clean/features закрепляют один immutable archive pin на весь
stage run. Pending-only designation не меняет `ir1`, если не влияет на resolver;
активный conflict overlay сохраняется. Локальная schema v9 связывает owner
decision с точной evidence revision, которая входит в экспорт вместе с decision
IDs и проверяется offline verifier.
Модельный fit и полный DVC repro на пользовательской истории не запускались;
интеграционные fixtures проходят через реальные ingest/clean/features/trainer
entrypoints, при этом MLflow и model-fit side effects замоканы.

## Зависимости и проверка

- После [TASK-026-1](TASK-026-1-source-neutral-entity-registry.md) и
  [TASK-026-3](TASK-026-3-event-identity-bridge.md).
- Затрагивает identity export, локальный data/training contract и тесты;
  команды записать в отдельном отчёте `done`.
- Независимый review завершён без P0–P2; следующий gate — TASK-026-5.
