# TASK-032-1 — Production роли registry и prediction revisions

> **Статус:** done — локальная реализация и независимое review завершены
> **EPIC:** [EPIC-032](../EPIC-032-v1-3-0-release.md)
> **Приоритет:** high

## Причина

Предпродовый аудит 2026-10-11 выявил, что `sf_refresh_writer` не имеет
грантов на `prediction_revisions`, а отдельные DB identities для registry
sync и feedback не создаются при production bootstrap. По
[runbook](../../operations/entity-registry-publication.md) они должны иметь
разные credentials и ограниченные права. В текущем виде новый путь может
завершиться `permission denied` либо потребовать worker credential с лишними
правами. Независимое первичное review подтвердило блокирующий finding P1.

## Проверяемый результат

1. Bootstrap создаёт отдельные роли registry sync и feedback с разными secret
   files, без вывода паролей и без изменения прав других ролей сверх нужного.
2. Grants соответствуют фактическим операциям: sync устанавливает projection
   и pointer, feedback работает только с candidate outbox/sequence, worker
   пишет prediction revision и runtime candidates/bridge.
3. Новые процессы запускаются только явным одноразовым профилем, не меняя
   ежедневное расписание и обычный Compose up.
4. Тесты сначала показывают отсутствующие права, затем проходят на контрактном
   и disposable PostgreSQL уровне; denied operations тоже проверены.

## Границы и gate

Изменения ограничены role bootstrap, grants, явной конфигурацией процессов и
проверкой release contract. Серверные credentials и реальный sync/feedback
остаются в [TASK-026-5](TASK-026-5-registry-publication.md) и требуют
эксплуатационного gate EPIC-032. После исправления нужен независимый review,
полный EPIC review и terminal CI перед релизом.

## Результат локального gate

Раздельные роли и one-shot профили реализованы; [отчёт](../../changes/done/TASK-032-1-registry-production-roles.md)
содержит проверенные команды и ограничения. Повторное независимое review не
нашло P0–P2 после исправления первоначального P1. Terminal CI и серверный
gate TASK-026-5 относятся к EPIC-032 и остаются открытыми.
