# TASK-025-20 — Доступ календаря к состоянию odds-стадии

> **Статус:** cancelled — оставшиеся критерии сняты решением владельца 2026-10-03
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)

## Наблюдаемый дефект

После ограниченного serving rollout v1.2.6 `/health` и `/ready` вернули 200,
но `/calendar/nhl?period=today` вернул 500. Запрос
`_latest_cycle_disables_odds` читает `data_cycle_stage_results` и делает JOIN
с `data_cycle_runs` через `sf_api_reader`; её точечный список `SELECT`-прав
не включает обе таблицы. PostgreSQL вернул `InsufficientPrivilege` сначала
на `data_cycle_stage_results`. Operations откатил serving на
v1.2.5; календарь 0/7/30, health и readiness снова работают. Ручной цикл
v1.2.6 не запускался, оба NHL timer выключены.

## Критерии исправления

- [x] Idempotent role bootstrap выдаёт `sf_api_reader` `SELECT` на
  `data_cycle_stage_results` и только `SELECT (run_id, tournament)` на
  `data_cycle_runs`; другие control-таблицы закрыты.
- [x] Red→green тест и first-rollout contract проверяют фактический JOIN
  календаря под API role до запуска API; disposable PostgreSQL probe
  подтвердил column-level grants и отсутствие доступа к `failure_code`.
- [x] Независимый review не выявил блокирующих замечаний после correction.
- [ ] До immutable tag локальный first-rollout из этой ветки поднимает
  миграции/roles, HTTP-календарь 0/7/30 и бот на disposable окружении;
  OFF prediction path подтверждён isolated replay на тех же весах.
- [ ] PR/tag/evidence CI и production smoke подтверждают `/calendar/nhl`
  для 0/7/30 дней под API role.
- [ ] После ручного OFF Data Cycle API показывает odds `missing`, точные
  predictions/readiness; архив и уведомление проверены до включения таймера.

## Handoff

Результат фиксируется в [отчёте](../../changes/done/TASK-025-20-calendar-stage-read-grant.md).

## Итог закрытия EPIC-025

Реализация включена в выпущенную v1.2.15. Неотмеченные выше критерии отдельного релиза/проверки не подтверждены в этой TASK и сняты при принятии итогового результата EPIC-025 владельцем. Это не отметка об их успешном выполнении.

Production calendar smoke и ограниченные DB grants подтверждены.
