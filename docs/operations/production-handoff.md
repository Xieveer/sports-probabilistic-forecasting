# Передача сервиса в эксплуатацию: v1.2.4 candidate

> Фактическое состояние на 2026-09-27: API и Telegram-бот v1.2.3,
> PostgreSQL healthy без рестартов. Третий ручной Data Cycle опубликовал
> source snapshot, но завершился ошибкой логирования Worker до canonical
> materialization. Оба NHL timer выключены. Production acceptance открыт.

- Статус подготовки: `candidate`
- Сервис: sports-probabilistic-forecasting
- Canonical repository: Xieveer/sports-probabilistic-forecasting
- Инициатива: [EPIC-025](../backlog/EPIC-025-bot-schedule-readiness.md),
  [TASK-025-9](../backlog/tasks/TASK-025-9-release-readiness.md),
  [TASK-025-14](../backlog/tasks/TASK-025-14-future-close-odds-snapshot.md),
  [TASK-025-15](../backlog/tasks/TASK-025-15-readonly-worker-hydra-logging.md).
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- source_tag: `v1.2.4` (после независимого review и terminal PR CI).
- source_commit: exact merged `main` commit фиксируется перед tag.

v1.2.4 сохраняет публикацию будущих NHL матчей без closing line и исправляет
запуск Hydra CLI в read-only Worker: логи идут в stdout, Hydra не создаёт
файлы в `/app`. Последовательность Data Cycle и DB schema не меняются.
Теги v1.2.0–v1.2.3 остаются неизменными.

## Идентификация и ответственность

Production checkout сейчас указывает на v1.2.3 commit
`6c077a3f929fb6c3aea506c8b1b0e1cdb18d9fef`; serving API/bot используют
exact v1.2.3 digests, PostgreSQL healthy, Alembic head
`0017_data_cycle_notification_outbox`. Ручной run
`e96868fa-04cd-4c3a-bff8-c5b34f51b709` опубликовал source snapshot
181 826 590 bytes. Затем Hydra file handler попытался создать
`/app/canonical_full_refresh_cli.log` в read-only Worker. После host stop
proof run закрыт как `failed/source_fetch_failed`, outbox `nhl_admins`
доставлен один раз. Активного executor нет, оба таймера disabled. Календарь
0/7/30 пока пуст с coverage `unavailable`.

## Runtime и конфигурация

Compose получает только immutable `IMAGE@sha256:DIGEST` из проверенного
release manifest и защищённые `*_FILE` paths. DB URL, API key, Telegram token,
chat ID и пароли не записываются в Git, handoff, чат или полный лог. Приложение
работает без host ports под UID/GID `10001:10001`. Alias `nhl_admins` должен
оставаться согласованным между API/Worker и bot-only destination map.

Перед первым v1.2.4 Worker проверить и активировать model bundle с
`app_version=1.2.4`. Сейчас `current` указывает на совместимый с v1.2.3
bundle `sha256:d11cee7e1f7531e095d5d9ba416507e562604a250101acc427a512e112b9ac5e`;
exact version gate не пропустит его в v1.2.4 Worker. Собрать новый
content-addressed wrapper из тех же трёх файлов без изменения весов и 489
feature names. Проверить SHA-256, model identity, feature contract и загрузку
в exact v1.2.4 Worker; сохранить прежний pointer для rollback.

## Healthcheck и smoke-проверка

После ограниченного rollout проверить exact running digests, `/health`,
`/ready`, NHL calendar API 0/7/30 суток, статус coverage и readiness без
прогноза/коэффициентов. Кодовый smoke Telegram проверяет публичный календарь,
admin status/history/schedule и manual run без второго исполнителя. Один
ручной цикл должен завершиться terminal status, фактическим 30-дневным
coverage, измеренными future odds/quota и одним итоговым уведомлением с тем
же run ID. Успех job без свежего календаря не считается готовностью NHL.

Operations запускает `make acceptance-check` только с утверждёнными runtime
inputs после health/smoke. Старый NHL timer остаётся выключенным. Новый
dispatcher timer включать лишь после успешного ручного цикла; затем проверить
next trigger, первый плановый run и сообщение администратору. При любой
ошибке оставить timer выключенным, сохранить безопасные failure codes и
выполнить host stop proof до нового run.

## Данные и совместимость

Перед v1.2.4 изменением повторить privileged preflight, создать свежий
root-only `pg_dump -Fc`, проверить checksum/catalog, isolated restore на exact
PostgreSQL image и off-host download/hash. Проверенный pre-v1.2.3 dump от
2026-09-27 не включает последний run record, поэтому не заменяет новый
снимок. Backup bucket retention/encryption текущему service account
недоступны; третья сверенная копия хранится на машине владельца.
Pre-v1.2.4 dump уже создан: 29 313 196 bytes, SHA-256
`ea217fde1ef82abc173b1482af8bfcf75e97f9b5f870ded346b5a97439499594`.
Isolated restore на exact PostgreSQL image подтвердил Alembic 0017,
22 218 canonical events и три run records; Object Storage download/hash и
третья локальная копия совпали. Перед rollout повторить проверку актуальности
снимка и состояния writers.

Схема должна остаться на `0017_data_cycle_notification_outbox`;
role-bootstrap/migrator повторяются idempotently только из approved image.
Serving rollback на v1.2.3 API/bot возможен по сохранённым digest и env;
его Data Cycle остаётся неисправным. Destructive downgrade БД запрещён.

## Наблюдаемость

В production change record сохранить UTC-время, source commit, manifest hash,
running image IDs, restart counts, DB revision, backup hash, model bundle ID,
run/stage statuses, 30-дневное coverage, odds quota, notification delivery и
timer last/next trigger. Не публиковать полные Docker/DB логи, external
payload или значения secrets. Истёкший heartbeat сам по себе не разрешает
второго исполнителя: recovery требует host stop proof.

## Артефакт и откат

После независимого review и terminal PR CI Reviewer создаёт annotated
`v1.2.4` на exact merged commit `main`. Tag pipeline должен завершить CI,
Security, first-rollout contract, публикацию linux/amd64 images, scan и
provenance. Release owner создаёт отдельный immutable evidence commit/tag;
validator вызывается с `--handoff docs/operations/production-handoff.md`.
Operations сверяет manifest и только после этого меняет VPS.

Действующий deploy wrapper разрешает лишь старую версию; Operations использует
временный audited operator access и пошаговый runbook в репозитории
`operations-agent`. Перед изменением source/env/model pointer сохранить
root-only копии. Rollback serving не восстанавливает работу Data Cycle; после
неуспеха нужен forward fix или отдельное восстановление проверенного backup
с оценкой записей после снимка.

## Нерешённые вопросы

Для GO ещё нужны terminal PR/tag/evidence CI, свежий backup/restore/off-host
evidence, совместимый v1.2.4 model bundle, проверка полного ручного цикла с
30-дневным coverage, измерение future odds/quota и первый плановый NHL run.
TASK-025-9 и EPIC-025 остаются `in_progress` до этих runtime gates.
