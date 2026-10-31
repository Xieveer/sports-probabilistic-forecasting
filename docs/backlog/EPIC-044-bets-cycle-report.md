# EPIC-044 — Надёжный Data Cycle и результат фактических ставок

> **Статус:** done — v1.4.0 выпущена на production, controlled cycle успешен
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

- Этап: TASK-044-1/2/3/4 завершены. На production установлена v1.4.0;
  следующий плановый цикл назначен на 2026-11-01 10:00 МСК.
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
  `make security`, `make docs`, `make pre-commit` и `make production-check`
  прошли. Независимый review без блокеров; source PR #102, post-merge
  CI/Security и Docker/first-rollout success. Evidence PR #103 и workflow
  success. На production миграция 0026, backup/readback/restore, controlled
  Data Cycle `672444d9-3611-4793-8e97-81272ff75207` success, 232 прогноза,
  213 future ready, terminal notification delivered. Сезонный endpoint и
  PNG-график проверены; сообщение о версии владельцу отправлено.
- Предыдущая роль: Operations Agent. Следующий контроль: плановый слот
  2026-11-01 и первая реальная bet-summary после сыгранных матчей; это
  наблюдение эксплуатации, а не незавершённая задача выпуска.
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
  Release gates, backup, production smoke и сообщение владельцу выполнены;
  итоговый [отчёт TASK-044-4](../changes/done/TASK-044-4-release.md).
