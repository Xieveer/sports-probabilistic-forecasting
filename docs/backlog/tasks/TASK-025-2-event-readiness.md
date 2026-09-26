# TASK-025-2 — Готовность прогноза и коэффициентов события

> **Статус:** blocked — `odds.failed` зависит от TASK-025-3
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат и границы

API календаря из TASK-025-1 дополняет каждое событие независимыми состояниями
календаря, прогноза и коэффициентов, временем последнего успешного обновления
и агрегированным состоянием для Telegram. Событие без прогноза остаётся в
выдаче. Этот срез не меняет формулы ML, odds или Data Cycle scheduler.

Реализована projection часть readiness на наблюдаемых данных. Текущий API может
показать `failed` для prediction row со статусом `error`; persisted odds
observation является только подтверждённым успехом. Отдельная запись ошибки odds
acquisition будет добавлена в TASK-025-3; до этого API не выдумывает `failed`.

## Критерии приёмки

- [x] Событие без prediction сохраняется; calendar (`current`, `changed`,
  `postponed`, `cancelled`, `needs_review`), prediction и odds имеют независимые
  статусы и проверяемые reason codes.
- [x] Prediction статусы (`pending`, `ready`, `partial`, `failed`, `unavailable`)
  и odds статусы (`missing`, `partial`, `ready`, `stale`) применяются по policy,
  не выводятся из `Prediction.odds_raw`.
- [ ] Odds status `failed` основан на persisted failed-attempt record; отложено
  до [TASK-025-3](TASK-025-3-data-cycle-runs.md).
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
- Calendar-first future odds acquisition не входит в этот срез: текущий odds
  refresh ограничен `need_to=today`, live polling выбирает только predictions.
  Это release gap передан в TASK-025-3.

## Handoff и отчёт

- Отчёт частичного выполнения: [TASK-025-2](../../changes/done/TASK-025-2-event-readiness.md).
- Follow-up / findings: два P1 исправлены; failed odds attempt и calendar-first
  future odds poll переданы TASK-025-3.
- Review: повторное независимое review без блокирующих findings; 47 целевых
  тестов прошли.
- Commit/push: ожидается после review.
