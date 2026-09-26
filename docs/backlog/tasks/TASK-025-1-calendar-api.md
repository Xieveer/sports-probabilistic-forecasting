# TASK-025-1 — Календарь NHL независимо от прогноза

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат и границы

Подтверждённые source события NHL, в том числе без прогноза, сохраняются в
canonical store и выдаются отдельным API календаря на запрошенный период
букмекерских суток. Доказуемое покрытие 30 суток не зависит от даты последнего
матча. Этап не добавляет readiness, админ-управление и Telegram UX.

## Критерии приёмки

- [x] Событие со стабильным source ID при переносе обновляет ту же canonical
  запись и сохраняет revision; исчезновение из неполного ответа не удаляет её.
- [x] API отдаёт события без прогноза, поддерживает 08:00 МСК, «Сегодня»,
  «Завтра», 3/7/14/30 суток, верхнюю исключающую границу и pagination.
- [x] Ответ отличает подтверждённо пустой период от неполного/stale coverage.
- [x] NHL acquisition проверяет и записывает покрытие всех 30 суток, в том
  числе когда в периоде нет матчей; malformed/ошибка anchor оставляет manifest
  `complete=false`, а cached complete progress не выдаётся за новую проверку.
- [x] Статусы scheduled/postponed/cancelled/started/finished нормализованы;
  unknown NHL provider state mapped to `needs_review`;
  богатые historical canonical revisions и прежний прогнозный API не повреждены.
- [x] Один fixture с футбольным event ID и источником проходит общий API
  контракт без добавления football production adapter.

## Реализация и известная граница

- API использует opaque `canonical_events.id`, source calendar projection и
  окно полуинтервала в UTC. Для «Сегодня» и числового периода начало ограничено
  текущим моментом; «Завтра» остаётся полными букмекерскими сутками. Coverage
  считается stale после 24 часов без успешной проверки.
- Provider сначала атомарно записывает manifest `complete=false`, очищает
  cached weekly progress, строго валидирует ровно семь дат weekly anchor как
  непрерывное окно, а `complete=true` ставит только после успешного обхода и
  сохранения source snapshot.
- `import-nhl` — явный CLI entrypoint для bootstrap bundle. Другой bundle может
  законно быть импортирован после первого, поэтому importer сохраняет новые
  immutable revisions, но не перезаписывает уже существующую current projection;
  актуализация выполняется canonical refresh path.
- Если acquisition завершается ошибкой, manifest в source-каталоге остаётся
  incomplete. Текущий вертикальный срез не передаёт failed attempt в DB
  `calendar_coverages`: API пока может показывать предыдущее успешное состояние
  до истечения 24 часов. Перед релизом Data Cycle должен публиковать последнее
  failed/partial coverage состояние в DB, чтобы прежний success не выглядел
  подтверждённым после свежей ошибки. Product Owner добавляет это в следующий
  TASK по Data Cycle; production readiness этим TASK не подтверждается.

## План реализации

1. Red: тест календарного API, показывающий canonical event без prediction;
   выполнен `uv run pytest -q tests/test_calendar_api.py` — ожидаемо упал,
   потому что у `CanonicalEvent` пока нет полей участников.
2. Green: аддитивная migration и минимальные нормализованные поля/coverage,
   source mapping и endpoint календаря.
3. Refactor: убрать дубли правил окна, проверить текущие canonical и
   prediction regression tests, обновить API документацию.

## Затрагиваемые области и зависимости

- `sports_forecast/data/providers/nhl/`, `sports_forecast/deploy/canonical_bootstrap.py`,
  `sports_forecast/service/db/`, `sports_forecast/service/routers/`, `migrations/`.
- Нельзя использовать `predictions` как единственный источник календаря,
  полагаться на дату последнего события для coverage или писать сырые ответы
  источника в логи/тесты.
- Зависимость: принятый ADR-026; операции с production DB не входят в TASK.

## Проверка

- Целевые unit/integration тесты с фиксированным временем и fixture NHL.
- Регрессионные canonical bootstrap/full refresh и prediction API тесты.
- `make lint` и релевантные тесты после refactor.

## Handoff и отчёт

- Отчёт выполнения: [TASK-025-1 done](../../changes/done/TASK-025-1-calendar-api.md).
- Follow-up: [TASK-025-3](TASK-025-3-data-cycle-runs.md) передаёт failed/partial acquisition в persisted coverage.
- Review: повторное независимое review 2026-09-26 чистое; Reviewer запустил
  46 целевых тестов. Первые findings по пустой странице, status mapping,
  неполной неделе и bootstrap projection устранены в correction cycle.
- Review evidence: content commit `b23e2ccc3b869667e95e0f46fbe472731a6f1c8e`;
  повторный commit gate прошёл ruff, форматирование, mypy и остальные hooks.

## Correction cycle после независимого review

- `calendar_coverages.status=confirmed_empty` выбирается только при `total == 0`;
  пустая страница из-за pagination offset остаётся `complete`.
- Calendar query исключает `started` и `finished` по canonical status, даже если
  запланированное время ошибочно осталось в будущем.
- Unknown NHL `gameState` не трактуется как scheduled и получает `needs_review`.
- Weekly `gameWeek` должен содержать все семь ожидаемых дат ровно по одному разу;
  partial fixture отвергается до записи complete manifest.
- Проверки и source evidence correction cycle находятся в done отчёте.
