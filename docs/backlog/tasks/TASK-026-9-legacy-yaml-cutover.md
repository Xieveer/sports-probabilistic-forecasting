# TASK-026-9 — Вывод legacy NHL YAML из рабочего пути

> **Статус:** blocked — локальная owner master и NHL event-cycle evidence недоступны
> **Эпик:** [EPIC-026](../EPIC-026-entity-registry.md)
> **Требование:** [REQ-026 #13](../../product/requirements/REQ-026-entity-registry.md)

## Результат

Подтверждённые NHL-связи registry заменяют legacy YAML в runtime без изменения
ожидаемых связей и прогноза. Старый код чтения остаётся для явного отката;
его удаление относится к более позднему изменению. Переход и возврат прежней
версии описаны в runbook.

## Критерии

1. Полнота переноса NHL-обозначений из YAML проверена против локального master.
2. Контрольный NHL цикл после переключения выдаёт ожидаемые связи и прогнозы.
3. При включённом strict reader runtime не читает
   `conf/bookmaker/team_name_registry/nhl.yaml`; следующее обновление registry
   не требует правки YAML.
4. До production-переключения задокументирован обратимый откат на прежний
   проверенный выпуск и snapshot.

## План и проверка

После завершения [TASK-026-8](TASK-026-8-local-registry-catalog.md) проверить
паритет seed/master, выбрать минимальный путь чтения подтверждённого registry,
написать проваливающиеся тесты потребителей, переключить локальный runtime,
провести NHL цикл, обновить документацию и передать на review.

## Локальная подготовка

- [x] Строгие odds/readiness/live paths не открывают legacy YAML; выключенный
  compatibility reader сохраняет прежний путь для обратимого rollback.
- [x] Добавлен read-only checker YAML → master → проверенный snapshot;
  воспроизводимый сценарий описан в
  [локальном руководстве](../../operations/identity-registry-local.md).
- [x] Synthetic NHL strict cycle проверяет неизвестную designation → owner
  decision → новый snapshot → успешное разрешение и повторный цикл без дубля.
- [ ] Полная приёмка остаётся заблокированной: доступный staging snapshot имеет
  ноль project events, а актуальный owner master отсутствует в worktree. Поэтому
  staging parity не заменяет owner-master parity, и реальный NHL event/forecast
  cycle здесь не подтверждён. Подробности: [отчёт локальной подготовки](../../changes/done/TASK-026-9-legacy-yaml-cutover.md).
