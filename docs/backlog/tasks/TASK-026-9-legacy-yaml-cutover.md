# TASK-026-9 — Вывод legacy NHL YAML из рабочего пути

> **Статус:** blocked — owner master/snapshot подготовлены, реальный NHL forecast cycle ещё не проверен
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
- [x] Локальный owner master защищён резервной копией и наполнен 51
  однозначным событием из официального NHL schedule; новый verified snapshot
  разрешает все 51 source event ID. Паритет 100 старых team aliases сохранён.
  Подробности: [TASK-026-11](TASK-026-11-nhl-event-bootstrap.md).
- [ ] Полная приёмка остаётся заблокированной до реального NHL
  event/forecast cycle на production горизонте после установки нового snapshot.
  Подробности предыдущего этапа: [отчёт локальной подготовки](../../changes/done/TASK-026-9-legacy-yaml-cutover.md).
