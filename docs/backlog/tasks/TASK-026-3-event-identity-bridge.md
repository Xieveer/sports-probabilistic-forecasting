# TASK-026-3 — Проектные события и совместимость календаря

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-026](../EPIC-026-entity-registry.md)
> **Требование:** [REQ-026](../../product/requirements/REQ-026-entity-registry.md)
> **ADR:** [ADR-029](../../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md)

## Результат и границы

Проектный UUID события связывает спортивный и букмекерский source ID. Старый
`canonical_events.id` остаётся публичным `event_id`; привязка к UUID хранится
по версии registry. Рабочий режим нового matcher остаётся выключенным до
проверенной установки снимка на сервере.

## Критерии приёмки

- [x] Перенос времени при том же confirmed source ID сохраняет проектный UUID;
      противоречие с другими confirmed tournament/team IDs возвращает conflict.
- [x] Разные unconfirmed source IDs одного scope не auto-link к одному project
      event; confirmed source-key history remains valid при повторном backfill.
- [x] Resolved mapping ссылается только на project UUID из frozen projection;
      normalization version включена в digest и должна поддерживаться reader-ом.
- [x] Автоматическое решение использует только подтверждённых участников и
      однозначное точное время; отсутствие времени, конфликт или несколько
      событий дают unresolved/conflict/ambiguous mapping без project UUID.
- [x] Tournament/team/event designations и conflict overlays применяются на
      дату canonical event (`[valid_from, valid_until)`); просроченный alias не
      связывается; pending designation не отменяет confirmed alias без open
      overlay; при отсутствии даты для временных confirmed связей возвращается
      ambiguous.
- [x] Таблица bridge хранит разные отображения для разных снимков; закреплённый
      run читает свою frozen версию из content-derived snapshot projection.
- [x] Старые `event_id`, prediction `match_id`, revisions и архивы остаются
      читаемыми; backfill не объединяет по одному имени или времени.

## План реализации

1. Написать падающие тесты повторных матчей, переноса и pinned versions.
2. Добавить аддитивную схему, строгий resolver и dry-run backfill.
3. Проверить календарь, прогнозы, odds и совместимость старых snapshots.

## Зависимости и проверка

- После [TASK-026-1](TASK-026-1-source-neutral-entity-registry.md).
- Затрагивает canonical DB, event resolver, миграцию и тесты; точные команды
  записать в отдельном отчёте `done`.
- Независимый review пройден без P0–P2: 68 целевых тестов, Ruff,
  mypy и `git diff --check` повторены Reviewer.
- Следующий gate: commit/evidence/push Reviewer, затем TASK-026-4.

## Реализованная граница

Добавлены project event relations и журнал решений в локальный registry schema
v8; source event designation связываются с project UUID из того же registry
snapshot. Строгий resolver и bridge/backfill описаны в
[отчёте выполнения](../../changes/done/TASK-026-3-event-identity-bridge.md).
Режим чтения нового bridge выключен в `conf/identity_event.yaml`; legacy matcher,
календарный API и production routes не переключались. Backfill по умолчанию
только строит dry-run; apply использует content-derived ID закреплённой
event-проекции.
