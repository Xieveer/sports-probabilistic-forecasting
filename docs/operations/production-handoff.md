# Передача сервиса в эксплуатацию: v1.2.1 candidate

> Фактическое состояние на 2026-09-27: v1.2.1 частично развёрнут на VPS,
> первый NHL Data Cycle завершился `failed/source_fetch_failed`, оба NHL timer
> выключены. Исправления в TASK-025-13 / PR #42 ожидают нового immutable
> release. Этот handoff не подтверждает production acceptance.

- Статус подготовки: `candidate`
- Сервис: sports-probabilistic-forecasting
- Canonical repository: Xieveer/sports-probabilistic-forecasting
- Инициатива: EPIC-025, TASK-025-9.
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- source_tag: `v1.2.1`
- source_commit: `0c56bf10d52e9802d75627988605f455714cef96`.

Этот handoff относится к согласованному production-выпуску 1.2.1. Тег v1.2.0
остался неизменным: его release gate завершился ошибкой до сборки образов.
CI/evidence v1.2.1, production backup и ограниченный rollout выполнены;
первый Data Cycle failed, поэтому статус handoff остаётся `candidate` до
исправленного релиза и runtime acceptance. Тег указывает на commit,
содержащий код, версию и исходный release contract.

## Идентификация и ответственность

Релиз добавляет календарь NHL на 0–30 суток независимо от прогнозов,
готовность событий, future odds, историю и управление единым Data Cycle через
Telegram, защиту от второго исполнителя и итоговые уведомления. Футбольный
контракт проверяется на fixture; футбольный production pipeline не включается.
Ручная команда запускает новый цикл, не перезапуская службы.

Read-only preflight 2026-09-26/27 подтвердил текущий v1.1.22 commit
97b24b3c95f10ced132a581cbec36cab06eb101b: running API, bot и PostgreSQL
healthy, без рестартов, их digests совпадают с release manifest. В production
БД 0 будущих NHL матчей на 30 дней, старый NHL timer disabled/inactive, без
last/next trigger. PostgreSQL занимает 87 MB, на root filesystem свободно
20 GiB. Повторить проверку непосредственно перед rollout.

## Runtime и конфигурация

Compose получает только immutable IMAGE@sha256:DIGEST из verified manifest и
server-side secrets через `*_FILE` paths. DB URL, token, service key, Telegram
IDs и пароли не передаются в Git, handoff, логи или чат. Контур остаётся
private, без host ports; application runtime UID/GID 10001:10001.

Operations проверяет метаданные secret files и конфигурацию
SF_CONTROL_DATABASE_URL_FILE, SF_CONTROL_API_KEY_FILE,
BOT_CONTROL_API_KEY_FILE, BOT_NOTIFICATION_DESTINATIONS_FILE и
SF_DATA_CYCLE_NOTIFICATION_ALIASES без чтения значений. Каждый безопасный
destination alias должен соответствовать ровно одному Telegram chat ID в
защищённом bot-only JSON file. Outbox хранит alias и run ID, но не chat ID.
Пустой или несогласованный alias map блокирует включение уведомлений.

Новая topology описана в docs/operations/production-runtime-topology.md:
отдельные DB роли для API reader, control API и Worker; dispatcher опрашивает
сохранённое расписание и запускает UUID unit. По умолчанию NHL 10:00
Europe/Moscow с интервалом 24 часа; уменьшение интервала возможно только
после измерения полного цикла и source quota. Перед activation проверить
docker compose config, bash syntax и systemd-analyze verify.

## Healthcheck и smoke-проверка

После ограниченного rollout проверить /health и /ready, NHL calendar API на
0/7/30 суток, coverage freshness и event readiness. Кодовый smoke Telegram
проверяет публичный календарь без прогнозов, административные status/history,
schedule и manual run без второго активного run. Сверить terminal run/stages,
summary, future odds и одно итоговое сообщение с тем же run ID. Первый полный
цикл должен подтвердить фактическое 30-дневное покрытие; успешный job без
свежего календаря не считается готовностью NHL.

Operations запускает make acceptance-check только с утверждёнными runtime
inputs после health/smoke. Production bot token и chat ID не выводятся.
Старый sports-forecast-canonical-refresh@nhl.timer остаётся выключенным.
После initial smoke включить только
sports-forecast-data-cycle-dispatcher.timer, проверить следующий trigger,
затем подтвердить первый плановый NHL run и уведомление администратору.

Stop criteria: crash loop, ошибка БД или миграции, отсутствующий verified
backup, неверный image/manifest, не-200 health/readiness, второй executor,
неполное 30-дневное coverage, несогласованные aliases либо превышение quota.

## Данные и совместимость

До migrations повторить privileged preflight по operations runbook
sports-forecast-v1.2.0-readonly-preflight.md. Создать root-only PostgreSQL
pg_dump -Fc непосредственно перед миграциями, проверить checksum/catalog и
isolated restore на exact PostgreSQL image по operations runbook
sports-forecast-v1.2.0-postgres-backup-restore.md. Подтвердить off-host copy,
retention и restore evidence; локальный dump не защищает от потери VPS.

Проверить фактический Alembic revision v1.1.22 и release head; неизвестный
revision останавливает rollout. После preflight и backup сначала выполнить
role-bootstrap для создания ограниченных ролей, затем migrator: additive
Alembic migrations и применение least-privilege grants после создания таблиц.
API и Worker не выполняют DDL при старте. Текущая БД
не содержит таблиц calendar coverage и Data Cycle; canonical_events и
OddsStore сохраняются.

## Наблюдаемость

В production change record зафиксировать UTC-время, source commit, running
image IDs/digests, restart counts, безопасные failure codes, migration head,
backup checksum, последний/первый Data Cycle run ID, 30-дневное coverage,
timer last/next trigger и результат notification. Не публиковать полные
Docker/DB логи, external payload или значения secrets. Истёкший heartbeat
сам по себе не разрешает нового исполнителя: recovery требует host stop proof.

## Артефакт и откат

После независимого review и terminal PR CI Reviewer ставит annotated tag
v1.2.1 на проверенном commit main. Tag pipeline должен завершить CI, Security,
isolated first-rollout contract, публикацию linux/amd64 images, scan и
provenance. Release owner запускает manual evidence gate с
--handoff docs/operations/production-handoff.md; Operations сверяет exact
digests с approved manifest. Mutable tag не служит runtime identifier.

Root-owned wrapper принимает только команду:

```text
deploy sports-probabilistic-forecasting v1.2.1
```

До migration rollback возможен на проверенную пару v1.1.22 image digests и
совместимые systemd units. После migration откат одних images допускается
только после isolated проверки старого API/bot на схеме 1.2.1. Пока её нет,
применяется forward-fix либо отдельный restore pre-migration backup с
остановкой writers и оценкой потери последующих записей. Destructive
downgrade запрещён. Новый dispatcher выключается до возврата старых units.

## Нерешённые вопросы

Для GO ещё нужны полное EPIC review, terminal PR/tag
CI, verified release manifest, фактический production backup/isolated
restore/off-host evidence, old-reader compatibility, измерение runtime/quota,
ограниченный rollout и первый плановый NHL run. Exact deployed revision и
результаты smoke фиксирует Operations; после них закрывается TASK-025-9.
