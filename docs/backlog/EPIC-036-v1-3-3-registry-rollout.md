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
- [TASK-036-1](tasks/TASK-036-1-candidate-outbox-writer-grants.md) исправляет
  grants и проверку реального INSERT под ролью Worker.
- EPIC-026 реализует словари рынков/исходов и общий derived matcher для live,
  future batch и materialization; ADR-035 задаёт staged compatibility старого
  и нового snapshot без удаления event history.
- Следующая роль: Developer — завершить EPIC-026; Reviewer — независимо
  проверить полный diff и release evidence; Operations Agent — повторить
  backup/restore, publication, реальный NHL цикл и контролируемый rollout.
- Предыдущая роль: Product Owner зафиксировал NO-GO v1.3.2 и контракт
  корректировки; локальный grant fix проверен на disposable PostgreSQL.
- Блокеры: реализация/merge EPIC-026, terminal CI, новый source/image/model
  evidence, проверенный feedback цикл и серверный forecast/odds/bot smoke.
- Обновлено: 2026-10-11.

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
   действующая линия в API/боте и первые плановые ticks. Rollback на exact
   v1.3.1 и совместимый snapshot проверен и доступен.

## Решение и остановка

До выполнения всех критериев GO статус release — NO-GO. При потере линии,
прогнозов, неполной уникальности matcher, провале publication, feedback или
backup переключение запрещено; после switch применяется проверенный rollback.
Финальные факты записываются в
[production handoff](../operations/production-handoff.md).
