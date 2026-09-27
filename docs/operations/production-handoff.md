# Передача сервиса в эксплуатацию: v1.2.5 candidate

> Фактическое состояние на 2026-09-27: API и Telegram-бот v1.2.4 healthy,
> календарь NHL содержит 187 матчей на 30 дней с coverage `complete`.
> Ручной цикл завершился ошибками odds acquisition и publication.
> Оба NHL timer выключены. Production acceptance открыт.

- Статус подготовки: `candidate`
- Сервис: sports-probabilistic-forecasting
- Canonical repository: Xieveer/sports-probabilistic-forecasting
- Инициатива: [EPIC-025](../backlog/EPIC-025-bot-schedule-readiness.md),
  [TASK-025-9](../backlog/tasks/TASK-025-9-release-readiness.md),
  [TASK-025-16](../backlog/tasks/TASK-025-16-odds-secret-files-and-stdout-logging.md),
  [TASK-025-17](../backlog/tasks/TASK-025-17-promoted-feature-contract.md).
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- source_tag: `v1.2.5` (после независимого review и terminal PR CI).
- source_commit: exact merged `main` commit фиксируется перед tag.

v1.2.5 исправляет передачу file-backed ключей Odds API в общий клиент и
Worker, а также возвращает прикладные логи Hydra в stdout. Причина отказа
publication установлена на изолированной копии данных: runtime basic-признаки
не соответствовали promoted advanced-модели. Кандидат закрепляет сбор
признаков по verified promoted contract.
Схема БД и последовательность Data Cycle не меняются. Теги v1.2.0–v1.2.4
остаются неизменными.

## Идентификация и ответственность

Production serving API/bot используют exact v1.2.4 digests, PostgreSQL healthy,
Alembic head `0017_data_cycle_notification_outbox`. Ручной run
`dcd54406-7b88-4061-85b0-c60d76aef127` импортировал 34 NHL матча за
7 дней и 187 за 30 дней; API календаря 0/7/30 отвечает 200. Odds attempt
содержит `provider_not_configured`: 0 provider events и 187 матчей без
линии; quota не измерена. Publication вернула `materialization_failed`:
изолированный replay подтвердил 139 колонок при expected 489 и
`CatBoostError` по имени признака. Прогнозы не опубликованы. После host
stop proof run закрыт, outbox
`nhl_admins` доставлен один раз. Активного executor нет, оба timer disabled.

## Runtime и конфигурация

Compose получает только immutable `IMAGE@sha256:DIGEST` из проверенного
release manifest и защищённые `*_FILE` paths. Odds keys монтируются
read-only в Worker и source-acquirer, а значения не попадают в Compose,
environment, handoff или логи. DB URL, Telegram token, chat ID и пароли
также не записываются в Git. Приложение работает без host ports под
UID/GID `10001:10001`. Alias `nhl_admins` должен совпадать между API,
Worker и bot-only destination map.

До первого v1.2.5 Worker Operations создаёт и проверяет immutable model
bundle `app_version=1.2.5` из тех же одобренных весов и feature names.
Активный v1.2.4 bundle:
`sha256:2a29c3ebe13b37ac1d39b24bf1c32bf97b92391804292244714d643aef8d6293`.
Проверить SHA-256, model identity, feature contract и загрузку в exact
v1.2.5 Worker; сохранить прежний pointer для rollback.
Protected NHL runtime setting `SF_FEATURES=advanced` сверяется с bundle,
но feature processing берёт конфигурацию из verified promoted contract.

## Healthcheck и smoke-проверка

После ограниченного rollout сверить exact running digests, `/health`,
`/ready`, NHL calendar API 0/7/30 суток, coverage и readiness. Кодовый
smoke Telegram проверяет публичный календарь, admin status/history/schedule
и manual run без второго исполнителя. Один ручной цикл должен завершиться
terminal success, фактическим 30-дневным coverage, измеренными future
odds/quota, опубликованными прогнозами и одним итоговым уведомлением с тем
же run ID. Успех job без свежего календаря не считается готовностью NHL.

Operations запускает `make acceptance-check` только с утверждёнными runtime
inputs после health/smoke. Старый NHL timer остаётся выключенным. Новый
dispatcher timer включать лишь после успешного ручного цикла; затем
проверить next trigger, первый плановый run и сообщение администратору.
При ошибке оставить timer выключенным, сохранить безопасные failure codes
и выполнить host stop proof до нового run.

## Данные и совместимость

Перед v1.2.5 изменением создать свежий root-only `pg_dump -Fc` после
последнего failed run, проверить checksum/catalog, isolated restore на exact
PostgreSQL image и off-host download/hash. Проверенный pre-v1.2.4 dump
29 313 196 bytes, SHA-256
`ea217fde1ef82abc173b1482af8bfcf75e97f9b5f870ded346b5a97439499594`,
устарел после календарной записи; его нельзя использовать как единственную
точку отката. Bucket retention/encryption текущему service account
недоступны; третья сверенная копия хранится на машине владельца.

Схема должна остаться на `0017_data_cycle_notification_outbox`;
role-bootstrap/migrator повторяются idempotently только из approved image.
Serving rollback на v1.2.4 API/bot возможен по сохранённым digest и env;
его Data Cycle всё ещё не публикует прогнозы. Destructive downgrade БД
запрещён.

## Наблюдаемость

В production change record сохранить UTC-время, source commit, manifest hash,
running image IDs, restart counts, DB revision, backup hash, model bundle ID,
run/stage statuses, 30-дневное coverage, odds quota, notification delivery и
timer last/next trigger. Не публиковать полные Docker/DB логи, external
payload или значения secrets. Истёкший heartbeat сам по себе не разрешает
второго исполнителя: recovery требует host stop proof.

## Артефакт и откат

После независимого review и terminal PR CI Reviewer создаёт annotated
`v1.2.5` на exact merged commit `main`. Tag pipeline должен завершить CI,
Security, first-rollout contract, публикацию linux/amd64 images, scan и
provenance. Release owner создаёт отдельный immutable evidence commit/tag;
validator вызывается с `--handoff docs/operations/production-handoff.md`.
Operations сверяет manifest и только после этого меняет VPS.

Operations использует временный audited operator access и пошаговый runbook
в репозитории `operations-agent`. Перед изменением source/env/model pointer
сохранить root-only копии. Rollback serving не восстанавливает работу Data
Cycle; после неуспеха нужен forward fix или отдельное восстановление
проверенного backup с оценкой записей после снимка.

## Нерешённые вопросы

Для GO ещё нужны red→green correction publication, terminal PR/tag/evidence
CI, свежий backup/restore/off-host evidence, совместимый v1.2.5 model bundle,
полный успешный ручной цикл с 30-дневным coverage, измерение future
odds/quota и первый плановый NHL run. TASK-025-9 и EPIC-025 остаются
`in_progress` до этих runtime gates.
