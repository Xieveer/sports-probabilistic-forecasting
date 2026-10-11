# TASK-037-1 — Передача installation ID производителям кандидатов

> **Статус:** done — ожидает финальный review и terminal CI
> **Эпик:** [EPIC-037](../EPIC-037-v1-3-5-registry-cycle.md)
> **Тип:** очевидный дефект production gate
> **Ветка:** `initiative/epic-037-v1-3-5-release`

## Проблема

Контрольный strict Data Cycle v1.3.4 остановился на стадии календаря: запись неизвестного обозначения вызывает `RegistryFeedbackError: SF_ENTITY_REGISTRY_INSTALLATION_ID не задан`. Compose передаёт этот ID только процессу публикации feedback, а не производителям кандидатов. До успешного полного цикла v1.3.4 имеет решение NO-GO.

## Критерии готовности

- Rendered Compose передаёт один installation ID из production profile каждому процессу, способному вызвать `enqueue_unknown_designation` или `enqueue_unresolved_canonical_event`.
- Тест контракта падает на старом Compose и проходит после минимальной правки; профиль и верификатор учитывают новый обязательный вход.
- Не меняются словари, матчер, grants, модельные веса и публикация уже установленного v2 snapshot.
- Независимый review, terminal CI/Security и новый immutable выпуск обязательны; на VPS strict Data Cycle должен пройти до возобновления таймеров.

## Передача

Developer ведёт red → green → refactor; результат и проверки фиксируются в [отчёте done](../../changes/done/TASK-037-1-candidate-producer-installation-id.md). Затем независимый Reviewer и Product Owner выполняют release gates.

## Результат Developer

Минимальная Compose правка и verifier с проверкой канонического UUID готовы; red/green и локальные результаты приведены в [отчёте done](../../changes/done/TASK-037-1-candidate-producer-installation-id.md). Серверный strict Data Cycle и release gates ещё не завершены.
