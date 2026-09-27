# ADR-026 — Календарь событий и управление Data Cycle через Telegram

> **Статус:** accepted
> **Дата:** 2026-09-26
> **Связанное требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **Инициатива:** [EPIC-025](../../backlog/EPIC-025-bot-schedule-readiness.md)

Независимое архитектурное review 2026-09-26 не нашло блокирующих findings.
Операционные неизвестные и численные политики остаются release gates ниже.

## Контекст и критерии выбора

REQ-025 требует независимый от прогнозов календарь на 30 букмекерских суток,
управляемый через Telegram единый цикл и наблюдаемые состояния всех стадий.
Футбол проверяется контрактным примером без включения в production. Модели
обучения и формулы прогнозирования не меняются.

Текущие компоненты дают основу, но не реализуют весь контракт:

- `canonical_events` имеет устойчивый ключ `(tournament, source, source_event_id)`,
  время и revisions. NHL import сводит состояние к `upcoming/finished`; участники
  находятся в provider payload. Новая календарная проекция должна нормализовать эти поля.
- `/predict/upcoming/{tournament}` читает опубликованные predictions. Эта витрина
  не доказывает существование или отсутствие события календаря.
- NHL provider расширяет горизонт до окна quality gate; недельный schedule collector
  уже есть. Положительный ответ источника ещё не доказывает покрытие всех 30 суток.
- `worker_executions` описывает materialization. Source acquisition выполняется
  раньше Worker и при ошибке не получает полного durable lifecycle Data Cycle.
- systemd wrapper создаёт `run_id`, выполняет source acquisition, Worker и archive-sync.
  `RefreshLock` блокирует только участок внутри Worker. Admin `/refresh` вызывает Airflow.
- API имеет read-only DB роль; бот не имеет доступа к БД, Docker или host filesystem.

Критерии: сохранить существующие source/model/archive границы, один источник истины
для расписания, отсутствие дублей, проверяемость без Telegram/VPS, небольшой
эксплуатационный объём и явные минимальные права. ADR обязателен: меняются
долговечные API/DB-контракты, scheduler ownership и граница записи административного API.

## Рассмотренные варианты

| Вариант | Простота и проверка | Безопасность и эксплуатация | Стоимость, переносимость и обратимость |
|---|---|---|---|
| Status quo: прогнозная выдача, Airflow `/refresh`, systemd cadence | Наименьшее изменение; unit-тесты уже есть | Два способа запуска, нет управления реальным scheduler и полной истории | Бесплатен сейчас, но не выполняет REQ; сохраняется как исходное состояние для сравнения |
| Расширить текущий API/Worker, хранить control state в PostgreSQL, systemd вызывает dispatcher | Нужны узкие control routes и bounded CLI; общая библиотека правил тестируется отдельно | API получает ограниченную дополнительную capability; host запускает только установленные профили | Без нового постоянного сервиса и брокера; additive migration, заменяемый executor; выбран |
| Отдельный внутренний control API и постоянный scheduler service | Чище process isolation, те же календарные и run-модели | Отдельные health, secrets, deployment и мониторинг; отдельный сервис тоже требует защиты | Жизнеспособен, дороже сопровождение; выделение возможно позже без изменения Telegram DTO |
| Изменять systemd timer drop-in из бота через privileged bridge | Меньше application scheduling logic, но конфигурация и история всё равно нужны в БД | Требуются права на host/systemd и reconciliation двух состояний после сбоя | Сильнее привязка к VPS; сложнее тестировать атомарность DB/file/reload; не выбран |

Перевод production на Airflow или введение очереди Redis/Celery не устраняет потребность
в canonical calendar/readiness и durable run state, но добавляет инфраструктуру.
Для одного текущего production pipeline это не минимальное решение.

## Решение

Выбрать расширение текущего контура. PostgreSQL хранит календарь, конфигурацию
расписания, запросы и результаты циклов. API отдаёт календарь и принимает узкие
административные операции. systemd остаётся внешним supervisor/executor;
периодическое пробуждение dispatcher отделено от пользовательского расписания.

### Calendar и идентичность

Использовать существующий `canonical_events.id` как непрозрачный `event_id`, сохраняя
source key и revisions. Перенос обновляет ту же запись; исчезновение из ответа не
удаляет событие. Для участника нужен нормализованный идентификатор и display name.
Provider mapping выполняется при ingest, API не извлекает спортивные поля из сырого JSON.
Аддитивно сохраняются canonical status, timestamps успешного наблюдения календаря и
признак изменения относительно предыдущей revision. Legacy `upcoming` читается как
`scheduled`; backfill не должен выдумывать более точное состояние.

Нормализованные состояния — `scheduled`, `postponed`, `cancelled`, `started`, `finished`.
Неизвестный provider status даёт причину «требует проверки»; локальное наступление
времени старта само по себе не доказывает `started`. Неполный ответ источника не
считается подтверждением отмены. Запись с явно отменённым будущим стартом остаётся
видимой с пометкой отмены; события с подтверждённым стартом/завершением исключаются
из будущей выдачи. Перенос без нового известного времени сохраняет последнее время
как неподтверждённое и явно обозначается пользователю.

Связь прогнозов с событием вводится аддитивным nullable `event_id` и проверенным
backfill по tournament/source mapping. Для старых данных нельзя соединять только
по `match_id` или времени. Новые forecasts обязаны ссылаться на canonical event;
существующий API прогнозов остаётся совместимым. Расширение calendar projection
не должно подменять богатую canonical revision для исторического feature rebuild:
календарные поля обновляются независимо, merge не затирает результаты и статистику.
Изменение revision должно иметь корректный checksum и контракт чтения старых snapshots.

Добавить событие-ориентированный read endpoint, например `GET /calendar/{tournament}`,
с периодом, границами UTC, зоной, coverage и пагинацией. Переход `/upcoming` на него
устраняет зависимость существования события от прогноза. API возвращает timestamps
и reason codes, Telegram занимается форматированием.

### Периоды и покрытие источника

Единственная backend-функция вычисляет начало текущих букмекерских суток в
`Europe/Moscow`: до 08:00 берётся 08:00 предыдущего дня. Период N — полуинтервал
`[day_start, day_start + N суток)`, для будущей выдачи нижняя граница дополнительно
ограничена текущим временем. «Завтра» — следующие полные букмекерские сутки.
В 03:00 «Сегодня» заканчивается в 08:00 того же утра. Все хранение/сравнения — UTC,
границы строятся timezone-aware; форматирование не пересчитывает бизнес-период.

Календарный адаптер NHL использует недельные запросы существующего schedule client,
покрывающие окно до конца 30-х букмекерских суток, с запасом по календарным датам
источника и точной фильтрацией по UTC. Dedup идёт по source ID. Calendar acquisition
выполняется до дорогого обогащения и сохраняется независимо от odds/model failure.
Нельзя расширить только список anchors, оставив `finished_only` или checkpoint,
который повторно публикует старое окно как свежее.

Хранить попытки покрытия: `requested_from/until`, подтверждённые интервалы,
`observed_at`, `completed_at`, `run_id`, `complete/partial/failed`, reason code.
Завершение HTTP-запросов без проверки структуры и покрытия дат не даёт `complete`.
Пропуск страницы/якоря оставляет неполное покрытие; отдельные успешно проверенные
интервалы остаются доступными. Coverage нельзя выводить из даты последнего матча:
в пустом календаре тоже может быть подтверждённое покрытие. API различает
`confirmed_empty`, `incomplete`, `stale`, `unavailable` и доступные события.

30 суток — горизонт календаря. Горизонты подготовки predictions/odds задаются
отдельно по pipeline; отсутствие коэффициентов на далёкую дату не требует
делать дорогие исторические odds-запросы и само по себе не является ошибкой.

### Readiness и происхождение данных

Readiness — вычисляемая проекция canonical event, действующей публикации forecasts,
сохранённых odds и последних попыток подготовки. Нужны отдельные `observed_at`,
`last_success_at`, `last_attempt_at`, `last_failure_code`, `run_id` по компонентам,
а для прогноза — canonical revision/model identity, на которых он рассчитан.
Новая попытка, refresh import и рестарт не обновляют время свежести старой линии.
Исторические odds без времени наблюдения имеют неизвестную свежесть.

Для календаря, прогноза и коэффициентов конфигурация задаёт независимые TTL/SLA,
окно подготовки, deadline/grace и требуемые рынки/bookmakers. Значения и версия
политики отражаются в run metadata. SLA не определяется успешным exit code Worker.
Прогноз после существенного переноса или изменения входных данных требует проверки
даже при свежем `prediction_ts`.

Сохранять детальные состояния REQ и причины, агрегировать централизованно:
«Готово» — все обязательные компоненты свежи и пригодны; «Частично готово» — есть
пригодная часть; «Ожидает» — подготовка ещё не должна была завершиться; «Ошибка» —
обязательная подготовка сорвана/просрочена. Отмена и перенос показываются отдельно
от этой оценки. Ошибка обязательного компонента после deadline имеет приоритет над
«Частично готово»; пригодные данные при этом не скрываются из детальных статусов.

Нельзя переиспользовать `Prediction.odds_raw` как единственное хранилище доступности
odds: событие может иметь линию без прогноза. Добавить компактную нормализованную
проекцию odds/readiness с event/market/bookmaker и временем источника; исходный
OddsStore остаётся в acquisition-контуре. Требуемый набор рынков — конфигурация
турнира, без NHL moneyline в общих моделях.

### Durable Data Cycle и защита от дублей

Новые control entities: `pipeline_schedules`, `data_cycle_runs`,
`data_cycle_stage_results`, coverage/readiness projections и notification outbox.
`WorkerExecution` остаётся нижележащим журналом Worker и связывается с общим `run_id`;
не следует выдавать его `succeeded` за успех полного цикла.

Запрос API атомарно создаёт `waiting` run с UUID и idempotency key; повтор того же
Telegram update/callback возвращает прежний run. Повторное осознанное нажатие после
terminal failure создаёт новый UUID. В один момент допустим только один active run
(`waiting/running`) на pipeline, а исполнение общей canonical области сериализуется
по tournament. PostgreSQL constraint/транзакция обеспечивают это и при нескольких
API processes; проверка «прочитал, затем вставил» недостаточна.

Dispatcher атомарно принимает waiting run. `started_at` появляется при начале
исполнения, а не при принятии запроса. Run создаётся **до** source acquisition,
его UUID передаётся всем стадиям, Worker, архиву и уведомлению. Lock охватывает
весь цикл; существующий внутренний lock Worker должен распознавать владельца
этого run, а не блокировать его повторно. Все entry points производственного
цикла используют тот же механизм. Старый прямой timer отключается при переходе.

Стадии: `calendar → data/odds → quality checks → predictions → publication`,
плюс отдельный operational результат `archive_sync`. У каждой есть
`waiting/running/success/partial_success/failed/skipped`, timestamps, счётчики,
безопасные error codes. Ошибка до Worker и завершение по timeout становятся
terminal run outcome. Не начавшиеся стадии получают `skipped` с причиной.
Обязательные quality failures продолжают закрывать publication; календарь при
этом остаётся доступным. `partial_success` не разрешает обход quality gate.

Обязательность стадий и проверяемый publication target определяются pipeline
policy: `failed` — не достигнут обязательный результат, `partial_success` —
основной результат достигнут, но часть событий/дополнительных данных не готова,
`success` — выполнены все ожидаемые результаты. Для подтверждённо пустого окна
допустим успех без forecasts; denominator покрытия 0 даёт `n/a`, а не 100%.
Summary хранит отдельно всех известных и eligible для подготовки событий,
новые/изменённые, готовые predictions/odds, доли с явным denominator, ошибки
и длительность. Архивная ошибка после публикации остаётся видимой и не меняет
фактическую свежесть уже опубликованных данных; её влияние на итог задаётся
обязательностью operational stage.

Сбой executor не должен оставлять вечный `running`: heartbeat + deadline и
reconciliation фактического bounded процесса позволяют записать
`executor_interrupted/timeout`. Истёкший heartbeat сам по себе не разрешает
конкурентный запуск: сначала подтверждается остановка владельца либо применяется
проверяемый fencing token на всех записях. Для одного VPS минимален host lock,
проверка завершения контейнера и новый run после terminalization. Запретить
автоматическое удаление lock только по возрасту.

### Персистентное расписание и systemd

Pipeline profile в Hydra определяет tournament, адаптеры, timeout, допустимые
интервалы и readiness policy. Администратор хранит в БД только `enabled`,
основное локальное время, IANA timezone, интервал повтора и revision настроек.
Default инициализируется однократно; рестарт не перезаписывает выбор пользователя.
Изменение расписания использует optimistic revision и возвращает conflict при
конкурентном редактировании. Новые параметры действуют на следующие слоты,
уже активный run сохраняет snapshot исходной конфигурации.

Подтверждённая семантика — повтор от основного времени: 10:00 и каждые 6 часов
дают 10:00, 16:00, 22:00, 04:00. При неизменной зоне МСК ежедневный основной
запуск и равномерный интервал совместимы, когда интервал делит 24 часа.
Предлагаемый config allowlist выбирается из таких интервалов с учётом measured
runtime и квоты источников; окончательные числа подтверждаются в TASK до включения.
Контракт хранит duration, не список часов и не произвольную cron/shell строку.
Для будущей зоны с DST политика неоднозначного/несуществующего локального времени
должна быть явно определена перед включением этого pipeline.

Systemd запускает короткий dispatcher tick с фиксированным техническим периодом
(предложение: 60 секунд). Host adapter через bounded CLI внутри существующего
runtime image проверяет due slots/очередь в БД и запускает установленный профиль
с принятым `run_id`; CLI получает отдельную ограниченную scheduler DB role.
Тяжёлая job не блокирует наблюдение/heartbeat dispatcher. Host adapter принимает
только allowlisted pipeline ID и валидный UUID, никакие paths, images, команды
или Hydra overrides из Telegram не исполняются. API/бот не получают Docker socket.

Business schedule живёт в БД; systemd timer показывает частоту пробуждения.
Следующий бизнес-запуск вычисляет одна и та же библиотека для API и dispatcher.
При остановленном dispatcher бот показывает просрочку heartbeat и не обещает
исполнение только потому, что `next_run_at` вычислен. Ручной запуск работает и
при `enabled=false`; он не сдвигает фазу планового расписания.

Уникальный `(pipeline_id, schedule_revision, scheduled_for)` исключает дубли слота.
При простое несколько пропущенных слотов объединяются в один актуальный catch-up,
сохранённые метаданные показывают задержку. Во время active run новые scheduled
слоты фиксируются как пропущенные/объединённые, без бесконечной очереди. Новое
включение/изменение расписания считает следующий слот от момента применения,
не воспроизводит историю выключенного периода.

### Административный API и права

Предлагаемый минимальный контракт: `GET /admin/pipelines`,
`GET/PATCH /admin/pipelines/{id}/schedule`, `POST /admin/pipelines/{id}/runs`,
`GET /admin/pipelines/{id}/runs`, `GET /admin/runs/{run_id}`.
Ответ manual POST — accepted `waiting` либо текущий active run со stage/start;
API не ждёт окончания работы.

Авторизация обязательна в handler и API. Bot проверяет Telegram `from_user.id`
для message и callback, API проверяет отдельный service credential и допустимого
admin principal, переданного доверенным ботом. Пустые настройки — deny. Одного
числа user ID в неаутентифицированном заголовке недостаточно. Секрет доставляется
через `*_FILE`, не выводится в логи; публичный ingress не маршрутизирует admin
paths. API доступен боту в закрытой application-сети; control routes разрешены
только доверенному внутреннему пути. При добавлении публичного ingress нужен
явный allowlist read routes и негативный network-тест admin paths. Одного
отсутствия ссылки на endpoint в меню недостаточно. Отдельная сеть для control
процесса относится к варианту отдельного control API, а не обещается внутри
одного процесса. Ошибки не возвращают tracebacks, URLs с credentials или внешний payload.

API использует отдельное DB connection/role для control routes: чтение control
state, создание запроса run, изменение schedule и acknowledgement outbox; никаких
прав записи predictions, canonical events или migration DDL. `sf_api_reader`
сохраняет прежние права на serving. Worker/executor завершает stages/runs;
API не принимает от бота terminal status или произвольное имя стадии.
Отдельные SQL grants и негативные тесты обязательны. Это сознательное расширение
capability API process относительно production topology ADR-005/ADR-007: при
компрометации процесса атакующий сможет планировать разрешённые циклы. Ограниченные
профили, concurrency gate и rate limit ограничивают последствия; полной process
изоляции этот вариант не даёт. Если такая граница неприемлема, выбирается отдельный
control API с теми же DTO и таблицами.

Итоговое уведомление создаётся transactional outbox вместе с terminal run status.
Bot доставляет только в заранее настроенные admin destinations и подтверждает
доставку через control API; scheduled run даёт один компактный итог, manual —
принятие и итог. При рестарте сообщение не теряется. Между Telegram send и DB ack
возможен повтор: обещать exactly-once доставку нельзя; run ID позволяет узнать
повтор. В outbox достаточно destination alias и run ID, без копирования текста
пользователя, персональных данных или raw Telegram updates.

## Последствия

- Положительные: единые time/readiness правила; календарь остаётся видимым при
  сбое прогнозирования; ручной и плановый циклы используют общую историю; source
  acquisition failure не исчезает из наблюдения; футбол подключает адаптер/policy.
- Стоимость: additive migrations, safe backfill, второй ограниченный DB capability
  API, изменение systemd adapter и operational handoff, fixture и PostgreSQL tests.
  Полный runtime нужно измерить: текущий full-history rebuild может ограничивать
  допустимую частоту, а odds quota — допустимую интенсивность acquisition.
- Регрессии: current canonical revision используется для обучения/инференса;
  календарный импорт не должен стирать исторические поля и неправильно освежать
  predictions. Legacy routes и publication gates требуют отдельных regression tests.
- Футбол: контрольный fake adapter использует иной source, event ID, несколько
  market/spec и свою freshness policy/горизонт; базовые DTO не содержат NHL-констант.
  Production football adapter и обучение не входят в это решение.

## Проверка и пересмотр

Предлагаемые вертикальные TASK для декомпозиции Product Owner:

1. Calendar acquisition → canonical projection/coverage → API/Telegram periods;
   additive migration и fixtures 30 дней, 03:00/08:00, перенос, отмена, пустота/неполнота.
2. Event readiness/odds projection → API/Telegram labels, независимые freshness
   clocks, missing forecasts, deadline, изменение события, футбольный пример.
3. Durable Run/Stage → обёртка source/Worker/archive → history/summary;
   fault injection каждой стадии, partial_success, crash/timeout recovery.
4. Persisted schedule + idempotent manual control → authenticated admin handlers
   → dispatcher/systemd contract; real PostgreSQL race tests, restart persistence,
   concurrent schedule edit, catch-up, выключенный auto/manual и locked current run.
5. Outbox и полный кодовый сценарий Telegram update → handler → ASGI API → DB:
   fake Telegram transport, clock/provider fixtures, без production token/сети.
6. Operations: новые grants/secrets, миграция с backup, замена timer, измерение
   runtime/квот, candidate handoff, release/rollback 1.2.0 и фактический daily run.

Каждый TASK заканчивается review и done evidence по правилам репозитория.
SQLite полезен для отдельных unit tests, но не заменяет PostgreSQL concurrency
и least-privilege проверки. E2E transport может быть in-process `httpx`/ASGI;
systemd adapter проверяется отдельно dry-run и затем Operations на VPS.

Release gate должен проверить установленный timer, dispatcher heartbeat,
terminal run/stage history, 30-дневное coverage, API readiness и новую версию
бота. Старый handoff v1.1.22 разрешал только замену бота и не подходит 1.2.0:
Product Owner/Operations обновляют его до release. Этот proposed ADR не является
доказательством работоспособности production или разрешением обойти gates.

Откат: остановить новый dispatcher, подтвердить отсутствие активного cycle,
вернуть совместимые immutable images и прежний timer. Additive таблицы/история
сохраняются; destructive downgrade запрещён. Откат старого timer выполняется
взаимоисключающе с новым. Если backfill меняет семантику старых readers, нужен
проверенный compatible reader либо forward-fix до выпуска.

Пересмотреть решение при появлении нескольких executor hosts, недостаточности
host lock/recovery, необходимости process isolation admin API или подтверждённом
превышении resource budget. Control module можно выделить в отдельный сервис,
сохранив API, таблицы, event identity и scheduler-neutral run contract.

## Источники и неизвестное

- Подтверждённый [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
  и уточнение владельца 2026-09-26 о повторе через интервал от основного времени.
- Код: `sports_forecast/service/db/models.py`, `db/refresh_lock.py`,
  `service/routers/predictions.py`, `bot/handlers/admin.py`,
  `orchestration/canonical_full_refresh.py`, `deploy/canonical_bootstrap.py`,
  `data/providers/nhl/schedule.py`, `data/providers/nhl/provider.py`,
  `deploy/systemd/run-canonical-refresh.sh`.
- [Production topology](../../operations/production-runtime-topology.md),
  [handoff](../../operations/production-handoff.md),
  [NHL source contract](../../cursor/source_data/nhl_web_api.md).
- [PostgreSQL: explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html),
  проверено 2026-09-26: row locks удерживаются до конца транзакции; они пригодны для
  атомарного claim, но не являются долговечным lock всей внешней job.
- [systemd timer: первичный исходник документации](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.timer.xml),
  проверено 2026-09-26: активный service не перезапускается tick; AccuracySec влияет
  на фактический момент вызова. Бизнес-расписание и recovery должны быть явными.
- Не проверены в этой архитектурной работе: текущая схема публичного NHL API и
  фактическое 30-дневное покрытие, server timer/version, measured runtime 1.2.0,
  quotas, значения SLA/allowlist интервалов. Адаптер проверяется по fixtures и
  разрешённому read-only provider probe; production подтверждает Operations.
