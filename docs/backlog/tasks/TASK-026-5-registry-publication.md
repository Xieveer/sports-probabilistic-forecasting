# TASK-026-5 — Публикация registry и серверная установленная версия

> **Статус:** blocked
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

- [x] Remote bytes проверены до смены current; CAS не теряет конкурирующую
      публикацию. Условные записи проверены на локальном S3 endpoint.
- [x] Ошибка сети, checksum или установки сохраняет прежнюю active version.
- [x] Установка snapshot идемпотентна, а новая publication sequence активируется
      даже при откате к ранее установленному snapshot.
- [x] Одновременные запросы и runs читают pinned snapshot; API/Worker не получают
      Object Storage credentials.
- [ ] Предыдущие версии сохраняются для выполняющихся runs и отката;
      runbook и требуемые grants описаны. Фактические grants, retention и
      contract probe текущего endpoint ожидают эксплуатационной проверки.

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
  Блокер завершения TASK — live probe текущего endpoint и проверка IAM/DB grants,
  retention. Разработка TASK-026-6 может продолжаться на проверенном контракте.
