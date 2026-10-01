# TASK-025-34 — Ежедневный Data Cycle без будущих odds

> **Статус:** in_progress
> **Владелец:** Product Owner; реализация — Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **Решение:** [ADR-028](../../architecture/adr/ADR-028-data-cycle-source-before-features.md)

## Цель и граница

Для NHL получить работающий ручной Data Cycle по общему для турниров
контракту: обновить завершённые и будущие матчи, сохранить canonical,
синхронизировать проверенный снимок с Object Storage, построить данные и
признаки из того же снимка, рассчитать вероятности и обновить витрину БД.
После успешного цикла `/predict` сразу читает прогнозы из БД и отдельно
получает live odds/edge по поддерживаемому рынку. Ежедневный цикл не делает
запроса на будущие odds и не отправляет прогнозы в Telegram. Административный
итог run остаётся частью существующего контракта.

Текущий внутренний stage `publication` означает materialization в БД и может
сохранить имя для совместимости истории. Предсезонную границу исправляет
[TASK-025-33](TASK-025-33-nhl-preseason-model-boundary.md). Исторические
closing odds, переобучение модели и новые odds-провайдеры вне задачи.

## Факты исходного состояния

- Source acquirer уже вызывает NHL provider с `--odds-enabled false`.
- Worker отдельно выполняет `data_odds`, если `SF_DATA_ODDS_ENABLED=true`;
  если явно `false`, стадия даёт `partial_success`, и весь run не становится
  `success`.
- Worker экспортирует canonical и NHL source-state archive только после
  успешной materialization, а systemd runner загружает их после Worker.
- `/predict` для NHL moneyline читает сохранённый прогноз и отдельно
  запрашивает текущую линию Pinnacle через The Odds API. Для других рынков
  такой live-адаптер пока отсутствует.
- На production v1.2.12 API и бот здоровы, но оба NHL timer выключены;
  Gate F последнего ручного запуска имел `0/208` matched future odds.

## Критерии приёмки

- [ ] Сбор завершённых и будущих событий и canonical quality выполняются
  до Object Storage sync. В архиве зафиксированы `run_id`, целостность и
  идентификатор snapshot; Worker использует ровно этот snapshot.
- [ ] Сбой синхронизации оставляет новую витрину неопубликованной и run
  завершённым с конкретной ошибкой `archive_sync`; не требуется новый
  внешний запрос odds для повторного расчёта из уже проверенного снимка.
- [ ] Ежедневный run не обращается к future odds provider. Отсутствие
  `data_odds` не приводит к `partial_success`, если все обязательные
  стадии успешны. История стадий честно показывает пропущенный этап.
- [ ] Вероятности обновляются в БД атомарно с состоянием витрины;
  `/predict` использует их и получает live odds/edge только при запросе.
  Недоступная линия не скрывает прогноз. Цикл не делает рассылку прогнозов.
- [ ] Адресные тесты проверяют порядок, отсутствие вызова odds, успешный
  итог, ошибку sync, повторный запуск и прежнее поведение календаря,
  прогноза и административного summary. NHL ручной run подтверждает эти
  критерии на production до включения расписания.
- [ ] Независимый review, CI и release gates пройдены. Включение timer
  допустимо после отдельной проверки [TASK-025-33](TASK-025-33-nhl-preseason-model-boundary.md)
  и фактической готовности source quality; без отдельного разрешения на
  deployment production не изменяется.

## План и handoff

1. Developer: зафиксировать падающими тестами порядок snapshot → sync →
   features → DB и policy отсутствующих daily odds.
2. Исправить существующий Worker/runner минимальным срезом, сохранив
   ownership, recovery, source и DB publication contract.
3. Reviewer: независимо проверить целостность snapshot, failure paths,
   прежнюю доступность прогнозов и тесты разных турниров.
4. Product Owner: после зелёного CI передать ограниченный release
   Operations Agent; перед включением таймера проверить ручной run и
   связанный preseason gate.

Отчёт реализации хранится в `docs/changes/done/`; итоговые production
доказательства добавить только после фактического ручного запуска.

## Локальный результат 2026-10-01

- Предвычислительный шаг обновляет canonical, проверяет свежесть и создаёт
  immutable source/canonical archive с descriptor текущего `run_id`.
  Host синхронизирует ровно два artifact из descriptor до Worker; Worker
  проверяет оба архива и читает из canonical artifact. ID этого artifact
  записывается в provenance прогнозов.
- `data_odds` помечается `skipped`, а optional skipped не снижает итог
  обязательного цикла до `partial_success`. Пустой подтверждённый inference
  создаёт пустую витрину; некорректный непустой inference вызывает ошибку.
- Первый независимый review нашёл обход через старые manifest; он устранён.
  Последующие проверки нашли и устранили пустой inference и некорректную
  агрегацию. Текущие локальные unit-тесты зелёные; полный production gate
  остаётся открытым. Фактические команды и ограничения — в
  [отчёте реализации](../../changes/done/TASK-025-34-data-cycle-source-first.md).
- Блокер ручного production run: соседняя TASK-025-33 должна определить
  допуск 124 исторических NHL-событий с другими `game_type`. Оба NHL timer
  остаются выключены. CI, release и production smoke ещё не выполнялись.
