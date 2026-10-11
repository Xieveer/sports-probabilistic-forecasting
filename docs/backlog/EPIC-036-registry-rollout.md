# EPIC-036 — Выпуск с рабочим NHL registry

> **Статус:** in_progress — v1.3.3 NO-GO, исправление и gates v1.3.4
> **Приоритет:** critical
> **Владелец:** Product Owner
> **Ветка:** `initiative/epic-036-v1-3-3-release`
> **Предыдущий кандидат:** [EPIC-035 v1.3.2](EPIC-035-v1-3-2-registry-rollout.md), NO-GO

## Цель и решение владельца

Выпустить новую production-версию после исправления контракта
[EPIC-026](EPIC-026-entity-registry.md): registry содержит словари турниров,
команд, рынков и исходов; NHL котировки сопоставляются с календарём по
подтверждённым участникам, сторонам и времени UTC в пределах 15 минут при
взаимной уникальности. Source event IDs и фактическая связь котировки с
календарным событием сохраняются как provenance, но не требуют owner
designation каждого матча. Будущие игроки имеют словарь и интервальную
связь с командами. Legacy код остаётся для явного rollback.

Владелец разрешил довести исправления до новой версии и deployment после
review, CI и release gates. `v1.3.3` создан на exact merge commit
`a89f1f95bcc5112ecae3f145253e01ab90d9ab7b`, но получил NO-GO до
production switch: strict reader невозможно включить через существующий
production Compose. Docker run `38177105034` отменён. Следующий тег —
`v1.3.4`; прежние теги не меняются.

## Память Product Owner

- Текущий production: v1.3.1, strict reader off; установлен snapshot
  `ir1:e0070e397775a9227300d3edb061b20a15744f5317ccd7e56752e6ab67e196ce`,
  51/51 NHL событий в preflight. Рабочую v1.3.1 не переключать до GO.
- Обнаруженные blockers v1.3.2: шесть живых котировок исчезают при сдвиге
  старта +10 минут; реальный ORM `INSERT ... RETURNING` в outbox отклонён.
  На сервере не выполнен полный кандидат → решение → publication/sync.
- Production preflight v1.3.1 выявил ещё два дефекта: source-first Data Cycle
  пропускает `data_odds`, поэтому будущие NHL котировки не обновлялись с
  1 октября; dispatcher timer с минутным интервалом упирается в лимит пяти
  запусков за 15 минут и теряет heartbeat. Оба дефекта входят в v1.3.3.
- [TASK-036-1](tasks/TASK-036-1-candidate-outbox-writer-grants.md) исправил
  grants и проверку реального INSERT под ролью Worker; review, CI/security и
  merge [PR #88](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/88)
  завершены.
- [TASK-036-2](tasks/TASK-036-2-prepared-refresh-daily-odds.md) восстанавливает
  сбор коэффициентов после проверки подготовленного архива.
- [TASK-036-3](tasks/TASK-036-3-dispatcher-minute-cadence.md) исправляет
  лимит запусков минутного dispatcher.
- EPIC-026 реализует словари рынков/исходов и общий derived matcher для live,
  future batch и materialization; ADR-035 задаёт staged compatibility старого
  и нового snapshot без удаления event history. Полное review чистое, 1706
  unit-тестов прошли; [PR #89](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/89)
  прошёл terminal CI/security и объединён с `main`.
- Объединённый v1.3.3 release worktree: 1707 unit passed, полный pre-commit,
  Sphinx docs, `make ai-validate`, `make production-check` и
  `uv lock --check --offline` прошли; release code/TASK-036-2/3 независимые
  локальные review прошли без P0–P2. PR #90, terminal CI/security и source
  tag прошли. Pre-switch проверка обнаружила baked `false` без runtime override;
  [TASK-036-4](tasks/TASK-036-4-runtime-strict-switch.md) исправляет release blocker.
- Свежий production DB backup от 2026-10-11 21:36 UTC прошёл off-host
  readback и isolated restore. Сервер остаётся на v1.3.1, strict выключен;
  v2 snapshot не опубликован.
- Следующая роль: Developer → независимый Reviewer → terminal CI/tag pipeline;
  Operations Agent повторит model/server gates на новом exact образе.
- Предыдущая роль: Product Owner зафиксировал NO-GO v1.3.2 и контракт
  корректировки; локальный grant fix проверен на disposable PostgreSQL.
- Блокеры: TASK-036-4, новый source/image/model evidence, проверенный
  feedback цикл и серверный forecast/odds/bot smoke.
- Обновлено: 2026-10-12.

## Критерии GO

1. Словари рынков/исходов доступны локально и в установленном snapshot;
   NHL/Pinnacle `h2h` означает полный матч с ОТ/буллитами, два исхода без
   ничьей. Старый snapshot читается новой версией до публикации нового.
   Runtime strict switch одинаков в `/etc/sf/production.env` и отдельном
   systemd profile `/etc/sports-forecast/refresh/nhl.env`; оба rendered
   Compose проверены до включения и при rollback.
2. Один алгоритм для live, future и materialization связывает шесть
   контрольных +10 минут котировок с правильными матчами без owner event
   links. При двух подходящих матчах, двух source event IDs, неизвестной
   команде или несовместимом рынке котировка не присоединяется.
3. Реальный кандидат появляется в outbox под Worker identity, доходит до
   локального владельца, принятое решение публикуется и устанавливается;
   права записи ограничены и проверены на production-подобной БД.
4. Source PR проходит независимый review, terminal CI/security и
   `make production-check`. На exact merge commit ставится новый annotated
   tag v1.3.4; все образы проходят scan/provenance и release-evidence gate;
   model bundle соответствует exact версии без изменения весов.
5. До switch проходят свежие backup, off-host readback и isolated restore,
   disk/role/snapshot preflight. После switch проходят health, NHL forecast,
   действующая линия в API/боте и первые плановые ticks. Реальный source-first
   цикл после проверки архива выполняет ограниченный odds batch, записывает
   attempt и даёт ненулевые будущие observations; dispatcher проходит 20
   последовательных минутных ticks без `start-limit-hit` и stale heartbeat.
   Rollback на exact v1.3.1 и совместимый snapshot проверен и доступен.

## Независимое review кандидата v1.3.3

- Проверенный diff: `dd5184b3475200abdf217340f9dc62db279a7142`.
- P0–P2 findings не обнаружены. Проверены порядок валидации архива и запроса
  котировок, семантика выключенного `data_odds`, лимит минутного systemd
  dispatcher, версия, документация, безопасность и rollback.
- Независимо повторены 59 целевых тестов, Ruff и `git diff --check`; все
  прошли. Автором до review заявлены 1707 unit passed, полный pre-commit,
  Sphinx docs, `make ai-validate`, `make production-check` и
  `uv lock --check --offline`.
- Остаточный риск, пропущенный review: baked strict flag не имел production
  override. После выявления до server switch v1.3.3 получил NO-GO. Фактические
  provider odds, 20 минутных ticks и полный candidate feedback остаются
  серверными gates следующего выпуска.

## Независимое review кандидата v1.3.4

- Проверенный source+docs commit:
  `98d9cf3e0d0f248b9c6b217827d6cb5b18b9a0b7`.
- Первое review выявило P1: systemd Data Cycle использовал отдельный
  `nhl.env`, поэтому переключение только `production.env` оставляло Worker
  в legacy режиме. После red/green исправления оба профиля и два Compose
  render gate описаны в runbook; независимый re-review P0–P2 не выявил.
- Reviewer повторил 97 целевых тестов, Ruff и `git diff --check`; перед
  первым коммитом pre-commit hooks, включая Ruff и mypy, прошли. Автором
  заявлены 1715 unit passed, lint/type-check/pre-commit/docs/AI validation/
  production-check и offline lock check.
- Остаточные gates: terminal CI/Security, immutable source/image/model
  evidence, backup/restore и реальный strict/candidate/odds/bot/timer цикл.
  Локальный `make security` не дошёл до pip-audit из-за DNS/PyPI.

## Решение и остановка

До выполнения всех критериев GO статус release — NO-GO. При потере линии,
прогнозов, неполной уникальности matcher, провале publication, feedback или
backup переключение запрещено; после switch применяется проверенный rollback.
Финальные факты записываются в
[production handoff](../operations/production-handoff.md).
