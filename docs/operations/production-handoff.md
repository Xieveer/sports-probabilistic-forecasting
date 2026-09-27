# Передача сервиса в эксплуатацию: v1.2.3 candidate

> Фактическое состояние на 2026-09-27: API, Telegram-бот и PostgreSQL v1.2.2
> healthy без рестартов; два первых Data Cycle завершились
> `failed/source_fetch_failed`. Оба NHL timer выключены. Этот handoff не
> подтверждает production acceptance.

- Статус подготовки: `candidate`
- Сервис: sports-probabilistic-forecasting
- Canonical repository: Xieveer/sports-probabilistic-forecasting
- Инициатива: [EPIC-025](../backlog/EPIC-025-bot-schedule-readiness.md),
  [TASK-025-9](../backlog/tasks/TASK-025-9-release-readiness.md),
  [TASK-025-14](../backlog/tasks/TASK-025-14-future-close-odds-snapshot.md).
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- source_tag: `v1.2.3` (после независимого review и terminal PR CI).
- source_commit: exact merged `main` commit фиксируется перед tag.

v1.2.3 убирает требование исторической closing line у будущего NHL матча при
публикации source snapshot. Это следует из [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md):
календарь доступен до коэффициентов и прогнозов. Последовательность Data Cycle
и DB schema не меняются. Теги v1.2.0–v1.2.2 остаются неизменными.

## Идентификация и ответственность

Production checkout сейчас указывает на source commit v1.2.2
`3f2b4bb94421bdc00aa1d5185bdfaaf30a94acee`; serving API/bot используют
exact v1.2.2 digests, PostgreSQL healthy, Alembic head
`0017_data_cycle_notification_outbox`. Ручной run v1.2.2
`b4e312c2-59c2-4917-8e06-8483cd06a3b3` дошёл до provider source: 22 496
строк, 1 899 будущих без closing line, historical odds merge успешен. Старый
валидатор отклонил snapshot. Unit завершился; после host stop proof run закрыт
как `failed/source_fetch_failed`, outbox `nhl_admins` доставлен один раз.
Активного executor нет, старый и новый таймеры disabled. Production календарь
0/7/30 пока пуст с coverage `unavailable`.

## Runtime и конфигурация

Compose получает только immutable `IMAGE@sha256:DIGEST` из проверенного
release manifest и защищённые `*_FILE` paths. DB URL, API key, Telegram token,
chat ID и пароли не записываются в Git, handoff, чат или полный лог. Приложение
работает без host ports под UID/GID `10001:10001`. Alias `nhl_admins` должен
оставаться согласованным между API/Worker и bot-only destination map.

Перед выпуском проверить, что активный model bundle совместим с `1.2.3`.
Сейчас `current` указывает на manifest с `app_version=1.1.14`; без явной
проверенной repackage/promotion Worker остановится на compatibility gate.
Существующие веса и feature files нельзя менять или переобучать в этом
release; новый content-addressed wrapper допускается только после сверки
checksums, model identity и feature contract. Сохранить старый bundle и
pointer для rollback. Обновить operations runbook точными результатами.

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

Перед v1.2.3 изменением повторить privileged preflight, создать свежий
root-only `pg_dump -Fc`, проверить checksum/catalog, isolated restore на exact
PostgreSQL image и off-host download/hash. Проверенный pre-v1.2.2 dump от
2026-09-27 не включает последующие run records, поэтому не заменяет новый
снимок. Backup bucket retention/encryption текущему service account
недоступны; третья сверенная копия хранится на машине владельца.

Схема должна остаться на `0017_data_cycle_notification_outbox`;
role-bootstrap/migrator повторяются idempotently только из approved image.
Serving rollback на v1.2.2 API/bot возможен по сохранённым digest и env;
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
`v1.2.3` на exact merged commit `main`. Tag pipeline должен завершить CI,
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
evidence, совместимый model bundle, проверка полного ручного цикла с
30-дневным coverage, измерение future odds/quota и первый плановый NHL run.
TASK-025-9 и EPIC-025 остаются `in_progress` до этих runtime gates.
