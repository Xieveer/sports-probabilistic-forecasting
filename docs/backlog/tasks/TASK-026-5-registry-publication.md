# TASK-026-5 — Публикация registry и серверная установленная версия

> **Статус:** blocked
> **Владелец:** Developer
> **Эпик:** [EPIC-026](../EPIC-026-entity-registry.md)
> **Требование:** [REQ-026](../../product/requirements/REQ-026-entity-registry.md)
> **ADR:** [ADR-029](../../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md)

## Результат и границы

Локальный publisher выкладывает проверенный снимок в Object Storage и обновляет
текущую публикацию последней. Отдельный server sync устанавливает версию в
PostgreSQL; runtime читает закреплённую версию без сетевого запроса к storage.
Production включение требует отдельного release gate.

## Критерии приёмки

- [x] Remote bytes проверены до смены current; CAS не теряет конкурирующую
      публикацию. Условные записи проверены на локальном S3 endpoint.
- [x] Ошибка сети, checksum или установки сохраняет прежнюю active version.
- [x] Установка snapshot идемпотентна, а новая publication sequence активируется
      даже при откате к ранее установленному snapshot.
- [x] Одновременные запросы и runs читают pinned snapshot; API/Worker не получают
      Object Storage credentials.
- [x] Предыдущие версии сохраняются для выполняющихся runs и отката;
      runbook описывает требуемые grants. На рабочем Object Storage проверены
      conditional writes, фактические IAM grants и retention prefix.
- [ ] При следующем релизе отдельные PostgreSQL grants и server sync/feedback
      проверены в целевой среде; credentials доставлены только выделенным
      процессам. До этого TASK остаётся `blocked`.

## План реализации

1. Написать падающие transport/DB fault tests и endpoint contract probe.
2. Реализовать immutable upload, publication/current и server staging/activation.
3. Проверить pinned runtime read, откат, least privilege и документацию.

## Зависимости и проверка

- После [TASK-026-4](TASK-026-4-local-registry-snapshot.md).
- Затрагивает Object Storage sync, server DB, runtime reader, grants и runbook;
  команды записать в отдельном отчёте `done`.
- Код прошёл независимый review; evidence —
  [отчёт о реализации](../../changes/done/TASK-026-5-registry-publication.md).
  Object Storage gate закрыт 2026-10-09; см. раздел live evidence в отчёте.
  Блокер завершения TASK — PostgreSQL grants и серверная интеграция,
  перенесённые владельцем на следующий релиз новой версии 2026-10-09.
