# EPIC-044 — Надёжный Data Cycle и результат фактических ставок

> **Статус:** in_progress — реализация и локальные проверки, выпуск ожидается
> **Приоритет:** high
> **Владелец:** Product Owner
> **Ветка:** `initiative/epic-044-bets-cycle-report`
> **Требование:** [REQ-044](../product/requirements/REQ-044-automatic-bet-settlement-and-season-report.md)

## Цель

Выпустить на production одну новую immutable версию, которая продолжает
ежедневный цикл при недоступности GHCR, автоматически рассчитывает однозначные
открытые ставки и даёт владельцу сводку новых расчётов и сезонный результат.

## Проверяемые срезы

1. Локальный exact image при обычном запуске; release pull и digest gate
   сохраняются. Проверка: контракт Compose/runner и запуск без registry.
2. Идемпотентный расчёт открытых ставок по canonical результату с audit и
   явным пропуском неоднозначных случаев. Проверка: unit/API и повторный цикл.
3. Отдельная сводка новых расчётов с устойчивым outbox. Проверка: сбой доставки,
   retry и одна подтверждённая сводка.
4. Сезонный отчёт и PNG-график с конфигурационной датой старта; месячный
   отчёт сохраняется. Проверка: границы сезона, сводка и Telegram photo.
5. Review, CI/Security, release evidence, backup, production Data Cycle и
   полезный результат в Telegram. Откат — предыдущий exact release с
   сохранённой БД и журналом ставок. После успешного запуска — отдельное
   стартовое сообщение владельцу с версией и краткими изменениями.

## Память Product Owner

- Этап: код TASK-044-1/2/3 реализован и проверен локально; TASK-044-4
  содержит review/CI/production rollout. На production остаётся v1.3.7.
- Задачи: [TASK-044-1](tasks/TASK-044-1-local-cycle-images.md),
  [TASK-044-2](tasks/TASK-044-2-auto-bet-settlement.md),
  [TASK-044-3](tasks/TASK-044-3-season-report.md),
  [TASK-044-4](tasks/TASK-044-4-release.md).
- Основание: инцидент 2026-10-23 с истекшим GHCR PAT остановил цикл при
  локально сохранённых образах; действующий журнал требует ручного расчёта,
  `/bet_report` показывает только месяц.
- Решения владельца: неоднозначные ставки остаются открытыми с причиной;
  отдельная сводка новых расчётов после цикла, без окна суток;
  график накопленного общего денежного PnL;
  начало сезона по конфигурации, NHL 1 сентября.
- Дополнение владельца: стартовое сообщение новой версии после успешного
  production smoke.
- Release intent: явный запрос на новую production-версию от 2026-10-31;
  target `v1.4.0`, rollback `v1.3.7`; release gates в
  [production handoff](../operations/production-handoff.md).
- Канонический вход: [REQ-044](../product/requirements/REQ-044-automatic-bet-settlement-and-season-report.md),
  [REQ-031](../product/requirements/REQ-031-real-bets-ledger.md),
  [ADR-034](../architecture/adr/ADR-034-manual-bet-market-rules.md),
  [ADR-044](../architecture/adr/ADR-044-automatic-bet-settlement.md).
- Evidence: `make test` — 1741 passed, 10 skipped; `make lint`,
  `make security` (после обновления четырёх уязвимых зависимостей),
  `make docs`, `make pre-commit` и `make production-check` прошли. Миграция SQLite и переход
  PostgreSQL 16 с существующей outbox строкой прошли. Последние UX-правки:
  адресный набор 30 passed. Итоговый review и CI ещё ожидаются.
- Предыдущая роль: Developer. Следующая роль: независимый Reviewer, затем
  Product Owner и Operations Agent для выпуска.
- Обновлено: 2026-10-31.

## Независимый EPIC review

- Проверенный diff: commit `8e84e13` в ветке
  `initiative/epic-044-bets-cycle-report`. После commit локальные
  pre-commit hooks прошли без изменений.
- Проверены границы прав владельца в claim API и Telegram, идемпотентность
  расчёта, audit с canonical revision, отдельный outbox, финансовая формула,
  конфигурация сезона, Compose и миграция PostgreSQL 16 с существующей строкой.
- Первоначальные findings по доступу к сводке, миграции PostgreSQL,
  молчаливому отсутствию owner ID, audit provenance и mypy исправлены до
  проверенного commit. Блокирующих findings в итоговом diff нет.
- Локальные gates: `make test` — 1741 passed, 10 skipped; `make lint`,
  `make security`, `make docs`, `make pre-commit`, `make production-check` —
  прошли. Предупреждения Sphinx и пропущенные тесты с внешними prerequisites
  остаются в evidence команд; production цикл ими не подтверждён.
- Остаточный риск: Telegram delivery использует at-least-once и может
  повторить сообщение, если отправка состоялась, а ack не сохранился.
  Выпуск остаётся в TASK-044-4 до terminal CI, exact image gates, backup,
  production smoke и сообщения владельцу.
