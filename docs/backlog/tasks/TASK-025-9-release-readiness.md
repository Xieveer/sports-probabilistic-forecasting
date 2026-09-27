# TASK-025-9 — Production выпуск 1.2.1 и проверка NHL

> **Статус:** in_progress — local candidate, production gates ожидаются
> **Владелец:** Product Owner и Operations Agent
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат

Выпустить проверенный exact commit как `v1.2.1`, запустить новый NHL Data Cycle
по расписанию и подтвердить работу бота, API и ежедневного scheduler на
production. Футбольный production pipeline не включается.

## Критерии приёмки

- [x] Все функциональные TASK инициативы прошли независимое review, full EPIC
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
- [x] Reviewer создаёт tag только на проверенном commit в `main`. Tag pipeline
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
`v1.2.1` указывает на merge commit `0c56bf10d52e9802d75627988605f455714cef96`.
[Tag pipeline 36305286708](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36305286708)
завершился успешно: release gates, пять build artifacts, isolated first-rollout,
четыре publish/scan/provenance jobs. GHCR manifest digest и `linux/amd64`
сверены для каждого application image; candidate evidence manifest находится
в `deploy/release-manifest.json`. Fixture first-rollout подтвердил migration
`0017_data_cycle_notification_outbox`, тестовый isolated restore и health
контракты. Manual evidence gate ещё ожидает отдельного запуска.
Привилегированный preflight 2026-09-27 выявил, что серверные control DB/key,
notification destinations и dispatcher.env ещё не созданы. Действующие API и
бот используют secret files в `/etc/operations/services/sports-probabilistic-forecasting/secrets`;
новые пути нужно готовить там после сверки actual runtime config. Секретные
значения не публиковались.
Каноническое evidence хранится в отдельном operations repo:
`docs/changes/2026-09.md` и `docs/services/sports-probabilistic-forecasting.md`.

## Handoff и отчёт

- Зависит от всех функциональных TASK инициативы, включая TASK-025-10,
  и полного EPIC review.
- Перед rollout обновить `docs/operations/production-handoff.md` до
  `v1.2.1 candidate`, выполнить `make production-check`.
- Deployment evidence и итоговый done report ожидаются после production smoke.
