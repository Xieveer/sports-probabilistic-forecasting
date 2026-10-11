# EPIC-036 — Исправляющий выпуск v1.3.3 с рабочим NHL registry

> **Статус:** in_progress — исправления и повторные release gates
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
review, CI и release gates. Следующий свободный тег — `v1.3.3`; exact source
commit и image digests закрепляются только после merge и terminal CI. Тег
`v1.3.2` не изменяется.

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
  локальные review прошли без P0–P2. Тег и production switch не выполнялись.
- Следующая роль: Reviewer — проверить объединённый release diff; Operations Agent — повторить
  backup/restore, publication, реальный NHL цикл и контролируемый rollout.
- Предыдущая роль: Product Owner зафиксировал NO-GO v1.3.2 и контракт
  корректировки; локальный grant fix проверен на disposable PostgreSQL.
- Блокеры: release review/terminal CI, новый source/image/model
  evidence, проверенный feedback цикл и серверный forecast/odds/bot smoke.
- Обновлено: 2026-10-12.

## Критерии GO

1. Словари рынков/исходов доступны локально и в установленном snapshot;
   NHL/Pinnacle `h2h` означает полный матч с ОТ/буллитами, два исхода без
   ничьей. Старый snapshot читается новой версией до публикации нового.
2. Один алгоритм для live, future и materialization связывает шесть
   контрольных +10 минут котировок с правильными матчами без owner event
   links. При двух подходящих матчах, двух source event IDs, неизвестной
   команде или несовместимом рынке котировка не присоединяется.
3. Реальный кандидат появляется в outbox под Worker identity, доходит до
   локального владельца, принятое решение публикуется и устанавливается;
   права записи ограничены и проверены на production-подобной БД.
4. Source PR проходит независимый review, terminal CI/security и
   `make production-check`. На exact merge commit ставится новый annotated
   tag v1.3.3; все образы проходят scan/provenance и release-evidence gate;
   model bundle соответствует exact версии без изменения весов.
5. До switch проходят свежие backup, off-host readback и isolated restore,
   disk/role/snapshot preflight. После switch проходят health, NHL forecast,
   действующая линия в API/боте и первые плановые ticks. Реальный source-first
   цикл после проверки архива выполняет ограниченный odds batch, записывает
   attempt и даёт ненулевые будущие observations; dispatcher проходит 20
   последовательных минутных ticks без `start-limit-hit` и stale heartbeat.
   Rollback на exact v1.3.1 и совместимый snapshot проверен и доступен.

## Решение и остановка

До выполнения всех критериев GO статус release — NO-GO. При потере линии,
прогнозов, неполной уникальности matcher, провале publication, feedback или
backup переключение запрещено; после switch применяется проверенный rollback.
Финальные факты записываются в
[production handoff](../operations/production-handoff.md).
