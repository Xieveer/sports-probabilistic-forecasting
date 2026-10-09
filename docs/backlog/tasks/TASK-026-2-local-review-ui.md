# TASK-026-2 — Локальная очередь подтверждения связей

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-026](../EPIC-026-entity-registry.md)
> **Требование:** [REQ-026](../../product/requirements/REQ-026-entity-registry.md)
> **ADR:** [ADR-029](../../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md)

## Результат и границы

Владелец локально просматривает кандидатов, ищет и фильтрует их, подтверждает,
отклоняет или откладывает по одному и ограниченным пакетом. Решения и автор
сохраняются. Роуты редактирования не входят в production API.

## Критерии приёмки

- [x] Локальная страница показывает исходное обозначение, источник, scope,
      возможные сущности и основания; поиск, source/tournament фильтры,
      поиск project entity и next/previous пагинация работают.
- [x] Подтверждение, отклонение и откладывание сохраняются и повторный ingest
      не открывает идентичный закрытый кандидат.
- [x] Пакетная операция атомарна и отвергает устаревшую revision любой строки.
- [x] Внешние candidate поля имеют пределы размера; evidence history хранится
      полностью, а в очереди показывается ограниченный preview с отдельной
      постраничной историей.
- [x] Локальная сессия, CSRF и Origin/Host защищают POST; внешние имена
      безопасно отображаются, а production роуты недоступны.

## План реализации

1. Написать падающие HTTP/DB тесты одиночного, пакетного и конфликтного решения.
2. Добавить локальный entry point и формы с bounded действиями.
3. Проверить security cases и сквозной путь ingest → очередь → resolver.

## Зависимости и проверка

- После [TASK-026-1](TASK-026-1-source-neutral-entity-registry.md).
- Затрагивает локальный UI, identity service и тесты; точные команды и результат
  записать в отдельном отчёте `done`.
- Новая schema v6 добавляет evidence-кандидаты с origin/idempotency/revision;
  server-first origin поддержан, перенос server feedback остаётся в TASK-026-6.
- Schema v7 сохраняет предыдущие evidence revisions; новые факты создают
  pending review revision, не отзывая подтверждённую base designation. Решение
  по новой revision также не снимает существующую связь при reject/defer.
- Входные source/kind/value/raw/origin/idempotency/basis/observed_at, scope,
  facts и proposed IDs проверяются до начала транзакции и имеют явные лимиты.
- Очередь загружает последние пять evidence revisions на кандидата; полная
  история доступна отдельной страницей с bounded pagination.
- Основные пути локальной SQLite и secret добавлены в `.gitignore`; POST body
  ограничен streaming-лимитом до form parsing.
- Запуск, локальные права secret file и остановка описаны в
  [локальном runbook](../../development/local-identity-review.md).
- Проверки и результаты: [отчёт done](../../changes/done/TASK-026-2-local-review-ui.md).
- Независимый review пройден без P0–P2: 58 целевых тестов, Ruff, mypy,
  `git diff --check` и проверка игнорирования локальных файлов повторены Reviewer.
- Следующий gate: commit/evidence/push Reviewer, затем TASK-026-3.
