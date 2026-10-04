# TASK-026-5 — Публикация registry и серверная установленная версия

> **Статус:** backlog
> **Владелец:** Developer
> **Эпик:** [EPIC-026](../EPIC-026-entity-registry.md)
> **Требование:** [REQ-026](../../product/requirements/REQ-026-entity-registry.md)
> **ADR:** [ADR-027](../../architecture/adr/ADR-027-local-entity-registry-and-snapshots.md)

## Результат и границы

Локальный publisher выкладывает проверенный снимок в Object Storage и обновляет
текущую публикацию последней. Отдельный server sync устанавливает версию в
PostgreSQL; runtime читает закреплённую версию без сетевого запроса к storage.
Production включение требует отдельного release gate.

## Критерии приёмки

- [ ] Remote bytes проверены до смены current; CAS не теряет конкурирующую
      публикацию. Возможности текущего endpoint подтверждены contract probe.
- [ ] Ошибка сети, checksum или установки сохраняет прежнюю active version.
- [ ] Установка snapshot идемпотентна, а новая publication sequence активируется
      даже при откате к ранее установленному snapshot.
- [ ] Одновременные запросы и runs читают pinned snapshot; API/Worker не получают
      Object Storage credentials.
- [ ] Предыдущие версии сохраняются для выполняющихся runs и отката;
      grants, retention и runbook проверены без production deployment.

## План реализации

1. Написать падающие transport/DB fault tests и endpoint contract probe.
2. Реализовать immutable upload, publication/current и server staging/activation.
3. Проверить pinned runtime read, откат, least privilege и документацию.

## Зависимости и проверка

- После [TASK-026-4](TASK-026-4-local-registry-snapshot.md).
- Затрагивает Object Storage sync, server DB, runtime reader, grants и runbook;
  команды записать в отдельном отчёте `done`.
- Следующий gate: независимый review, затем TASK-026-6.
