# TASK-025-2 — Готовность прогноза и коэффициентов события

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат и границы

API календаря из TASK-025-1 дополняет каждое событие независимыми состояниями
календаря, прогноза и коэффициентов, временем последнего успешного обновления
и агрегированным состоянием для Telegram. Событие без прогноза остаётся в
выдаче. Этот срез не меняет формулы ML, odds или Data Cycle scheduler.

Readiness projection вычисляется по predictions, подтверждённым odds
observations и persisted odds acquisition attempts. Неподтверждённая попытка
показывает `failed` только после preparation deadline и только для события внутри
её UTC window. Успешная более новая попытка без линии возвращает компонент в
`missing`; старые observations сохраняются и показываются отдельно через
`last_success_at`.

## Критерии приёмки

- [x] Событие без prediction сохраняется; calendar (`current`, `changed`,
  `postponed`, `cancelled`, `needs_review`), prediction и odds имеют независимые
  статусы и проверяемые reason codes.
- [x] Prediction статусы (`pending`, `ready`, `partial`, `failed`, `unavailable`)
  и odds статусы (`missing`, `partial`, `ready`, `stale`) применяются по policy,
  не выводятся из `Prediction.odds_raw`.
- [x] Odds status `failed` основан на persisted failed-attempt record; окно
  должно покрывать событие, попытка должна быть новее успешного observation или
  успешной попытки и выполниться после preparation deadline. Вне окна/до срока
  readiness остаётся `missing` или `pending`.
- [x] Legacy OddsStore winner observation допускается только при подтверждённом
  2-way h2h и provider `market.last_update`; `fetched_at` не доказывает свежесть.
- [x] Состояния календаря, прогноза и коэффициентов имеют проверяемые reason codes
  и не зависят от наличия Prediction row.
- [x] Наличие старого прогноза/коэффициентов не означает `ready`; отдельные
  policy TTL, deadline и обязательные рынки/букмекеры применяются по турниру.
- [x] Несовпадение prediction kickoff/участников с canonical event помечает
  календарь `changed`, а прогноз — `partial/event_identity_changed`, без удаления
  последней версии. Сравнение `canonical_snapshot_id` с event revision SHA не
  выполняется: это разные идентификаторы.
- [x] Агрегат «Готово / Частично готово / Ожидает / Ошибка» следует deadline
  и обязательности компонентов; отмена/перенос остаются отдельным calendar state.
- [x] Контрольный футбольный event с другим market/spec и policy проходит тот
  же API/readiness контракт без NHL-ветвей в общей логике.

## План реализации

1. Red: тесты missing, partial, stale, failed, deadline и football fixture.
2. Green: минимальная проекция odds/readiness, policy и API-поля поверх
   события календаря с сохранением предыдущего прогнозного API.
3. Refactor: общая чистая функция readiness и документация состояний.

## Затрагиваемые области и зависимости

- Зависит от TASK-025-1; затронет service DB/API, odds ingestion/readiness и
  конфигурацию турнира. Точный путь определяется после review TASK-025-1.
- Не выводить `ready` только по существованию `Prediction.odds_raw` или по
  успешному exit code Worker.

## Проверка

- Целевые unit/integration тесты с фиксированным временем и двумя видами спорта.
- Регрессия prediction API, materialization и odds; lint.
- Readiness policy defaults явно заданы и изменяемы без смены API: NHL TTL
  24h/6h, deadline 6h; EPL fixture TTL 12h/3h, deadline 4h.
- Calendar-first future odds acquisition и failed-attempt projection завершены в
  [TASK-025-6](TASK-025-6-future-odds.md); production football adapter не входит.

## Handoff и отчёт

- Отчёт выполнения: [TASK-025-2](../../changes/done/TASK-025-2-event-readiness.md).
- Follow-up / findings: два P1 и дополнительный odds provenance correction
  исправлены; failed odds attempt и calendar-first future poll завершены в
  TASK-025-6.
- Review: повторное независимое review TASK-025-2 и расширения TASK-025-6
  без блокирующих findings.
- Commit/push: расширение TASK-025-6 ожидает content commit gate.
