# TASK-004-3 — Воспроизводимая проверка готовности NHL

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-004](../EPIC-004-nhl-release-readiness.md)
> **Требование:** [REQ-004](../../product/requirements/REQ-004-nhl-readiness-and-release-versioning.md)
> **ADR:** [ADR-004](../../architecture/adr/ADR-004-release-version-and-odds-api-key-failover.md)

## Результат и границы

Одна безопасная CLI-операция запускает/координирует существующие NHL refresh,
quality gate и odds backfill, а затем выдаёт краткий отчёт: дозагрузка
завершённых матчей, historical odds, статус будущего расписания и возможность
materialization. Отсутствие расписания — ожидаемый статус. Не выполнять эту
операцию с реальными секретами в рамках разработки задачи.

## Критерии приёмки

- [x] Команда не создаёт фиктивных будущих матчей и различает
  `no_upcoming_schedule`, недоступные historical odds и техническую ошибку.
- [x] Перед materialization будущих матчей вызывается существующий quality gate.
- [x] Dry-run/fixtures доказывают порядок шагов, идемпотентность и безопасный
  вывод без API-ключей и полных внешних ответов.
- [x] Инструкция запуска содержит требуемые secret variables и ожидаемые статусы.

## План реализации

1. Добавить красные CLI/contract tests со стабами NHL и Odds API.
2. Собрать команду из текущих refresh/gate/backfill entry points и компактного
   result model; не дублировать provider-логику.
3. Документировать dry-run и запустить целевые проверки.

## Затрагиваемые области и зависимости

- NHL provider/schedule, `source_refresh`, odds refresh/backfill, tournament
  quality gate, CLI docs/tests.
- Зависит от [TASK-004-2](TASK-004-2-odds-api-key-ring.md).

## Проверка

- Targeted pytest с fixtures и `make lint`; dry-run на локальных fixture data.
- Итог CLI содержит только счётчики, статусы и публичные идентификаторы матчей.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-004-3-nhl-readiness-command.md`.
- Follow-up / findings: нет.
