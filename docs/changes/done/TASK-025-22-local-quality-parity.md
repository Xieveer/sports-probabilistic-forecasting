# TASK-025-22 — Предварительный отчёт о локальной проверке quality gate

> **Статус:** in_progress; локальный run и тестовый Telegram-путь проверены,
> exact systemd/Compose wrapper и release gates открыты.

## Исправление и локальное доказательство

Freshness gate теперь считает пропущенными результаты только предматчевых
прогнозов с истёкшим deadline. На изолированной копии backup перед v1.2.8
старое правило обнаружило 1 621 матч без `finished`, а исправленное — 0:
все 1 621 прогноза были созданы после начала матча. Фактический вызов
исправленного validator в Worker-контейнере вернул `valid=True`,
`expired=0`, `missing=0`. PostgreSQL 16 работал без сети с лимитом 1 GiB;
Worker probe также был ограничен 1 GiB. В отчёт сохранены только счётчики.

Четыре адресных pytest-теста прошли под лимитом 4 GiB и таймаутом 30 секунд.
Независимый Reviewer не нашёл P0–P2 замечаний к коду и тестам; указанный им
разрыв ссылки на этот отчёт устранён его созданием.

Worker-срез на полной локальной истории завершился без OOM, execution —
`succeeded`, publication — `public`, опубликовано 1 838 прогнозов. Созданы
canonical и source-state archives (шесть файлов, суммарно около 230 MB).
Первый source-state sync вызвал `OOMKilled=true`, `exit=137` при лимите
archive-sync 512 MiB; ошибка возникла на remote verification. Дефект
исправлен в [TASK-025-24](../../backlog/tasks/TASK-025-24-archive-sync-bounded-memory.md):
повторные source-state и canonical sync завершились без OOM при том же лимите,
оба durable state — `verified`. Изолированный API v1.2.8 под ролью
`sf_api_reader` ответил `/ready` 200 с `db_connected=true`;
`/calendar/nhl?period=30&limit=1` вернул 200,
`total=198`, `coverage=stale` для восстановленного снимка. Потребление API
составило около 136 MiB при лимите 1.5 GiB.
`/predict/upcoming/nhl` под ролью `sf_api_reader` вернул 200 и 198 прогнозов
с `live_pinnacle=false`, без внешнего HTTP. Владелец подтвердил, что
`@SSPredictBot` является тестовым. Одно контрольное сообщение отправлено в
единственный `BOT_ALLOWED_USER_IDS`: Telegram вернул `ok=true` и message ID;
текст был явно обозначен как локальная проверка, не прогноз. Адресные тесты
bot calendar/notifications: 11 passed под лимитом 2 GiB и таймаутом 60 секунд.
Бот v1.2.8 запущен под лимитом 384 MiB: heartbeat сообщает
`telegram_ok=true`, `internal_api_ok=true` при маршруте через внутреннюю сеть
к локальному API. Data Cycle runner contract/lifecycle: 41 passed под лимитом
2 GiB и таймаутом 60 секунд. Владелец отправил `/upcoming` тестовому боту и
подтвердил корректный ответ с календарём NHL; локальный bot container
обработал updates без polling conflict и API 5xx, `OOMKilled=false`.

Связанный локальный run `43d645fe-8c0e-406e-9e7d-ef45da4a9d2f` на полном
фиксированном NHL snapshot завершился terminal `partial_success`. Стадии:
`calendar=success` (22 201 source events), `data_odds=partial_success`
(odds явно выключены), `quality=success`, `predictions=success`,
`publication=success` (1 838 прогнозов), `archive_sync=success` (два
артефакта). Worker: `exit=0`, `OOMKilled=false`, лимит 3 GiB; оба sync:
`exit=0`, `OOMKilled=false`, лимит 512 MiB, durable state `verified`.
Источник был локальным snapshot, без внешнего fetch; запуск стадий выполнен
через lifecycle CLI, а не exact systemd/Compose wrapper.

API с ролью `sf_control_api` ответил на защищённый `/admin/pipelines` 200.
После terminal status тот же producer метод отдельно поставил один outbox
item; bot poller через Control API доставил его в тестовый Telegram и
подтвердил за одну попытку (`delivered`). Атомарное создание outbox вместе с
terminal status в этом прогоне не проверялось; шесть repository tests,
включая PostgreSQL lease race на отдельной временной схеме, прошли под
лимитом 2 GiB и покрывают этот контракт.
Владелец подтвердил получение уведомления и корректный ответ
`/cycle_history` с локальным запуском. `make lint`, `make type-check` и
`git diff --check` прошли; для первых двух задан лимит памяти 2 и 3 GiB.
Exact Compose archive-sync command выявил дефект `/tmp=64m` и после
исправления [TASK-025-25](../../backlog/tasks/TASK-025-25-archive-sync-tmpfs.md)
remote-verified оба архива при `mem_limit=512m` и прежнем tmpfs.
Внешний NHL source-acquirer завершился успешно на копии каталога под лимитом
1 GiB; source покрывает календарь до 2026-10-29. Следующий связанный run
`1d9130eb-c281-43d2-8bca-3100cc28a1fa` с актуальным source и весами
production-модели остановлен memory cgroup Worker 3 GiB после валидации
полных train-таблиц. Он безопасно переведён в terminal
`failed/prediction_failed`, а тестовый бот доставил уведомление. Причина и
исправление — в [TASK-025-26](../../backlog/tasks/TASK-025-26-refresh-inference-memory.md).
Исправленный связанный run `876f0523-3f8c-44b6-95a8-0234b4258fbd`
завершился `partial_success` при явно выключенных odds: Worker `exit=0`,
`OOMKilled=false`, 1 847 прогнозов, оба archive-sync `exit=0`,
`OOMKilled=false`, durable state `verified`; notification outbox доставлен
тестовому боту за одну попытку. Все три контейнера были ограничены production
лимитами 3 GiB / 512 MiB / 512 MiB и swap отключён.

## Открытые gates

- Exact systemd wrapper целиком ещё не проверен. Внешний provider fetch
  прошёл отдельно; полный Worker на его source и terminal+outbox path
  прошли в связанном локальном цикле.
- Тестовый Telegram-бот подтвердил доставку, `/upcoming`, `/cycle_history`
  и terminal notification через локальный API.
- Полный relevant suite и CI не выполнялись. Production rollout не начинался.
- PostgreSQL, S3 fixture и API сейчас работают в изолированном локальном
  контуре с ограничениями памяти; production не затронут. Данные, модель и
  архивы оставлены в `/tmp` для продолжения проверки.
