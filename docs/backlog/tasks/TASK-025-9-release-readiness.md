# TASK-025-9 — Production выпуск 1.2.1 и проверка NHL

> **Статус:** in_progress — v1.2.1 частичный rollout; первый цикл failed
> **Владелец:** Product Owner и Operations Agent
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат

Выпустить проверенный exact commit как `v1.2.1`, запустить новый NHL Data Cycle
по расписанию и подтвердить работу бота, API и ежедневного scheduler на
production. Футбольный production pipeline не включается.

## Критерии приёмки

- [ ] Все функциональные TASK инициативы прошли независимое review, full EPIC
  review, локальные проверки и terminal PR CI. `pyproject.toml` и handoff
  указывают `1.2.1`; `make production-check` прошёл для `candidate`.
- [ ] Operations имеет привилегированное read-only evidence текущих image
  digests, Docker/DB состояния, последнего NHL run, календарного покрытия,
  прав/секретов по metadata и проверенного PostgreSQL backup. До этого
  rollback target не считается установленным.
- [ ] Production alias map уведомлений настроен и проверен: непустой
  `SF_DATA_CYCLE_NOTIFICATION_ALIASES` одинаков у API и Worker, защищённый
  `BOT_NOTIFICATION_DESTINATIONS_FILE` доступен только боту, каждый alias
  соответствует ровно одному chat ID и оба списка совпадают. Отсутствие
  или расхождение блокирует включение Data Cycle.
- [ ] Измерены длительность полного NHL цикла и quota future odds; выбранные
  cadence/allowlist не создают overlap. Старый timer и новый dispatcher
  переключаются взаимоисключающе, с проверкой disabled/enabled и следующего
  trigger. На preflight 2026-09-26 старый NHL timer был disabled/inactive.
- [ ] Reviewer создаёт tag только на проверенном commit в `main`. Tag pipeline
  завершён успешно, immutable image digests/provenance/security evidence
  проверены перед изменением VPS.
- [ ] Operations применяет additive migrations с backup, ограниченный rollout
  и smoke: `/health`, `/ready`, календарь 0/7/30, event readiness, admin
  status/history/schedule/manual run, terminal stages, timer next trigger,
  допустимый журнал и отсутствие дубля цикла. Проверка не публикует секреты
  или полный внешний ответ.
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

Read-only preflight Operations Agent 2026-09-26: unit/drop-in NHL timer
установлен, конфигурация 10:00 Europe/Moscow проверена, но timer
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
- Перед rollout обновить `docs/operations/production-handoff.md` до
  `v1.2.1 candidate`, выполнить `make production-check`.
- Deployment evidence и итоговый done report ожидаются после production smoke.
