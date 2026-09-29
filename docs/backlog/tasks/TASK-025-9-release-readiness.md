# TASK-025-9 — Production выпуск и проверка NHL

> **Статус:** in_progress — v1.2.10 serving; v1.2.11 candidate, timer disabled
> **Владелец:** Product Owner и Operations Agent
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

> Текущий v1.2.10 обслуживает API и бота. Ручной Data Cycle записал 1 834
> прогноза, но host unit завершился после `archive_sync/ReadTimeoutError`;
> run в БД остался `running`. Recovery dispatcher v1.2.10 тоже завершился
> ошибкой из-за `SELECT FOR UPDATE` без UPDATE grant у Control API.
> Исправления готовятся в PR #53 для v1.2.11. Оба NHL timer выключены.

## Результат

Довести проверенный release candidate `v1.2.11` до production,
запустить NHL Data Cycle по
расписанию и подтвердить работу бота, API и ежедневного scheduler на
production. Тег `v1.2.1` остаётся неизменным; футбольный production pipeline
не включается. Тег `v1.2.2` остаётся неизменным.

## Критерии приёмки

- [ ] Все функциональные TASK инициативы прошли независимое review, full EPIC
  review, локальные проверки и terminal PR CI нового кандидата.
  `pyproject.toml` и handoff указывают `1.2.11 candidate`;
  `make production-check` должен пройти для final candidate.
- [ ] Operations имеет привилегированное read-only evidence текущих image
  digests, Docker/DB состояния, последнего NHL run, календарного покрытия,
  прав/секретов по metadata и проверенного PostgreSQL backup. До этого
  rollback target не считается установленным.
- [ ] Production alias map уведомлений настроен и проверен: непустой
  `SF_DATA_CYCLE_NOTIFICATION_ALIASES` одинаков у API и Worker, защищённый
  `BOT_NOTIFICATION_DESTINATIONS_FILE` доступен только боту, каждый alias
  соответствует ровно одному chat ID и оба списка совпадают. Отсутствие
  или расхождение блокирует включение Data Cycle.
- [ ] Измерены длительность полного NHL цикла и подтверждено отсутствие
  provider HTTP в odds OFF-режиме; выбранные cadence/allowlist не создают
  overlap. Старый timer и новый dispatcher
  переключаются взаимоисключающе, с проверкой disabled/enabled и следующего
  trigger. На preflight 2026-09-26 старый NHL timer был disabled/inactive.
- [ ] Reviewer создаёт tag только на проверенном commit в `main`. Tag pipeline
  завершён успешно, immutable image digests/provenance/security evidence
  проверены перед изменением VPS.
- [ ] Operations подтверждает действующий Alembic head 0017, проверяет
  свежий backup, повторяет idempotent role grants и выполняет ограниченный
  rollout и smoke: `/health`, `/ready`, календарь 0/7/30, event readiness, admin
  status/history/schedule/manual run, terminal stages, timer next trigger,
  допустимый журнал и отсутствие дубля цикла. Проверка не публикует секреты
  или полный внешний ответ.
- [ ] До Worker run установлен и проверен immutable model bundle с
  `app_version=1.2.11` из неизменённых одобренных весов/features; старый
  `current` и checksums сохранены для rollback.
- [ ] После первого scheduled запуска подтверждены run_id, дата/время,
  стадии, фактическое 30-дневное coverage и сообщение администратору.
  Неуспех запускает документированный rollback/forward fix, не ложный DoD.

## Текущее evidence и блокеры

Ограниченный rollout 2026-09-27 выполнен после verified pre-migration dump,
isolated restore и off-host download/hash проверки. БД обновлена до Alembic
`0017_data_cycle_notification_outbox`; exact v1.2.1 API и bot healthy,
`/health`, `/ready`, календарь today/7/30 и admin schedule отвечают 200.
Persisted schedule: 10:00 Europe/Moscow, интервал 24h. Первый run
`5d9be516-13b6-4ea7-9709-0fbe26b1b649` завершился
`failed/source_fetch_failed`; уведомление `nhl_admins` доставлено один раз.
Обнаружены четыре дефекта [TASK-025-13](TASK-025-13-production-runtime-hotfixes.md):
Control API column grant, исполняемость скрипта, DB URL source-acquirer и
heartbeat watcher. Новый и старый NHL timer оставлены disabled. 30-дневное
coverage, quota и первый плановый запуск остаются открытыми. Bucket
retention/encryption не подтверждены доступным service account. Фактический
change record и incident находятся в репозитории `operations-agent`.
v1.2.2 tag/evidence CI прошли, serving API/bot healthy. Ручной run
`b4e312c2-59c2-4917-8e06-8483cd06a3b3` завершился
`failed/source_fetch_failed`: snapshot ошибочно требовал closing line у
1 899 будущих матчей. Host stop proof, terminalization и одно уведомление
подтверждены; оба timer disabled. Дефект исправляется в
[TASK-025-14](TASK-025-14-future-close-odds-snapshot.md). Active model bundle
был перепакован и проверен для 1.2.3, поэтому для v1.2.4 требуется новый
content-addressed wrapper с теми же весами/features.
v1.2.3 tag/evidence, backup и ограниченный serving rollout прошли. Ручной run
`e96868fa-04cd-4c3a-bff8-c5b34f51b709` опубликовал source snapshot
181 826 590 bytes, но canonical Worker завершился при попытке Hydra создать
log file в read-only `/app`. Host stop proof, terminalization и одно
уведомление подтверждены; календарь 0/7/30 остаётся пустым, оба timer
disabled. Исправление в [TASK-025-15](TASK-025-15-readonly-worker-hydra-logging.md).

v1.2.4 tag/evidence, backup и ограниченный serving rollout прошли. Ручной run
`dcd54406-7b88-4061-85b0-c60d76aef127` импортировал 34 NHL матча за
7 дней и 187 за 30 дней, coverage `complete`, API календаря отвечает 200.
Odds stage сохранила `provider_not_configured`: production Worker не получал
mounted secret files, а клиент не читал `*_FILE`. Publication вернула
`materialization_failed`; изолированный replay подтвердил mismatch 139
`basic` против 489 `advanced` признаков promoted-модели.
После host stop proof run закрыт, уведомление доставлено один раз; оба timer
disabled. [TASK-025-16](TASK-025-16-odds-secret-files-and-stdout-logging.md)
исправляет secret-file contract и stdout-логи;
[TASK-025-17](TASK-025-17-promoted-feature-contract.md) закрепляет сбор
признаков по promoted contract. Для v1.2.5 нужен новый
model wrapper с прежними весами и features.

v1.2.5 PR/tag/evidence и serving rollout прошли: API/bot healthy, calendar
7d 34/30d 187 с coverage `complete`. Два ручных run
`56c0ab25-b17d-496e-bb91-6b85bc6f6521` и
`8d2f9806-3ffd-4441-9ba6-db653578a0e1` завершились
`failed/prediction_failed`: фактический systemd `nhl.env` сначала
указывал Worker/version v1.2.4, затем algorithm `catboost` вместо
promoted `catboost_reg`. Profile исправлен и проверен по actual systemd
EnvironmentFiles, exact manifest и model contract. Оба run закрыты после
host stop proof, outbox доставлен один раз на run, active0. Три distinct
Odds API ключа дали HTTP 401 `INVALID_KEY`; владелец решил продолжать без
odds. [TASK-025-18](TASK-025-18-optional-future-odds.md) добавляет явное
отключение необязательной стадии. Оба timer disabled; публикация прогнозов
и первый плановый run остаются runtime gates. Последний post-failure backup
`a77fbf3b…` прошёл catalog, isolated restore, off-host hash и третью копию.
Изолированный replay v1.2.5 подтвердил запись 1 834 прогнозов и 187
eligible future matches, но обнаружил нулевые in-transaction counters при
`autoflush=False`. Исправление в
[TASK-025-19](TASK-025-19-publication-count-flush.md) входит в v1.2.6.

v1.2.6 PR/tag/evidence CI и isolated true OFF replay прошли: exact Worker
опубликовал 1 834 прогнозов, `predictions_ready=187/187`, odds attempts 0.
Свежий backup прошёл restore/off-host/third-copy, exact model contract и
pre-switch gates прошли. После ограниченного API/bot switch `/health` и
`/ready` были 200, но calendar smoke дал HTTP 500: API role не имела
`SELECT` на `data_cycle_stage_results`. Serving и конфигурация восстановлены
на v1.2.5; календарь 0/7/30 = 0/34/187, active0, оба timer disabled.
Ручной v1.2.6 Data Cycle не запускался. Точечное исправление и release
smoke exact JOIN находятся в
[TASK-025-20](TASK-025-20-calendar-stage-read-grant.md).

v1.2.7 PR/tag/evidence и локальный first-rollout под production DB roles
прошли. Serving API/bot healthy, calendar 0/7/30 = 0/34/187,
`/health`/`/ready` 200. Ручной OFF Data Cycle
`31644fe1-f4ef-46f3-8678-791b597c498f` записал 1 834 прогнозов и
достиг `predictions_ready=187/187`, odds attempts 0, но завершился
`failed/archive_sync_failed`: runner запустил системный `sync` вместо
Python CLI. Host stop proof и owner-fenced terminalization подтверждены;
active0, одно уведомление delivered, оба NHL timer disabled.
Локальный first-rollout проверял другой archive path и не заметил дефект.
[TASK-025-21](TASK-025-21-archive-sync-runner-command.md) исправляет путь
и добавляет проверку exact production Compose-команды до тега v1.2.8.

Исторический preflight до ограниченного rollout v1.2.1: Operations Agent 2026-09-26
подтвердил установленный unit/drop-in NHL timer и конфигурацию 10:00
Europe/Moscow, но timer оставался
`disabled/inactive`, last/next trigger отсутствуют. Текущий SSH-пользователь
не имеет доступа к Docker, DB, protected deploy record и журналу systemd;
эти gates требуют привилегированной операционной проверки. Сервер не менялся.
Привилегированный вывод владельца от 2026-09-26T18:14:20Z подтвердил
healthy контейнеры `sports-forecast` API, Telegram bot и PostgreSQL; в
защищённом deployment record перечислен `release-manifest-v1.1.22.json`.
Следующий read-only вывод подтвердил совпадение running image digests этих
трёх сервисов с manifest `v1.1.22` и source commit
`97b24b3c95f10ced132a581cbec36cab06eb101b`. В production DB таблица
`canonical_events` существует, таблиц calendar coverage и Data Cycle ещё нет,
а будущих NHL событий на 30 дней — `0`. Текущий immutable rollback target
для запущенных сервисов установлен; backup/restore evidence и совместимость
отката после migrations ещё не подтверждены.
Read-only проверка 2026-09-27 показала `87 MB` (`90 881 047` bytes) для
production DB, `20 GiB` свободного места на root filesystem и `6.1 GiB`
доступной RAM. NHL timer по-прежнему `disabled/inactive`. Backup должен быть
создан и проверен непосредственно перед additive migrations; текущие
ресурсы сами по себе не являются backup/restore evidence.
Operations подготовил runbook `docs/runbooks/sports-forecast-v1.2.0-postgres-backup-restore.md`
в отдельном репозитории `operations-agent` (`f425102`): root-only dump,
checksum/catalog check и isolated restore на exact PostgreSQL image.
Последовательность success/fault проверена локально; production backup,
off-host retention и совместимость rollback пока не подтверждены.
Тег `v1.2.0` указывает на merged main commit `84a2ac18e84ed58674bc5854696911498de7d879`.
[Tag pipeline 36300221666](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36300221666)
остановился в Compose gate: валидатор ожидал старый набор API environment,
не включавший control secret files и aliases. Образы не строились, VPS не
менялся. Пользователь согласовал `v1.2.1` для первого production выпуска;
`v1.2.0` остаётся неизменным.
Каноническое evidence хранится в отдельном operations repo:
`docs/changes/2026-09.md` и `docs/services/sports-probabilistic-forecasting.md`.

## Handoff и отчёт

- Зависит от всех функциональных TASK инициативы, включая TASK-025-10,
  и полного EPIC review.
- Перед следующим rollout подтвердить exact candidate в
  `docs/operations/production-handoff.md` и выполнить
  `make production-check`.
- Deployment evidence и итоговый done report ожидаются после production smoke.
