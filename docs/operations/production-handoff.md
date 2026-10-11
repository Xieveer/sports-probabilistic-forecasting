# Передача сервиса в эксплуатацию: v1.3.0 candidate

- Статус подготовки: `candidate`
- Решение на 2026-10-11: `NO-GO`; открытые условия перечислены ниже.
- Инициатива: [EPIC-032](../backlog/EPIC-032-v1-3-0-release.md).
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- Целевая среда: production VPS `ops-prod-01`; версия: `1.3.0`.
- source_tag: `v1.3.0` — annotated tag на exact merge commit `main` после review и CI; пока не создан.
- evidence_tag: `v1.3.0-evidence.1` — после проверки immutable manifest; пока не создан.
- Source commit, image digests, model bundle, CI и release evidence указываются здесь после их получения и до переключения сервера. Нельзя подставлять commit ветки или mutable image tag.

## Идентификация и ответственность

Состав выпуска: интегрированные [EPIC-026](../backlog/EPIC-026-entity-registry.md),
[EPIC-027](../backlog/EPIC-027-historical-odds.md),
[EPIC-028](../backlog/EPIC-028-production-model-contract.md),
[EPIC-029](../backlog/EPIC-029-configured-tournament-onboarding.md),
[EPIC-030](../backlog/EPIC-030-financial-research-validation.md) и
[EPIC-031](../backlog/EPIC-031-real-bets-ledger.md). Последний документированный
production выпуск — v1.2.15; фактическую работающую ревизию необходимо считать
с сервера до rollout. EPIC-030 завершён решением STOP: новый алгоритм не
продвигается. Турнир ENG1 не добавляется автоматически в расписание или выдачу.

EPIC-026 остаётся `blocked`: его серверный
[TASK-026-5](../backlog/tasks/TASK-026-5-registry-publication.md) входит в
обязательную проверку этого выпуска. Подготовка образа не закрывает этот gate.

## Runtime и конфигурация

Production использует только `IMAGE@sha256:DIGEST`, ограниченные роли PostgreSQL,
Compose secret mounts через `*_FILE` paths и прежние ограничения ресурсов. `SF_APP_VERSION=1.3.0`
должна совпадать с package, source tag, модельным bundle и `/health`.
`BET_OWNER_USER_ID` должен быть непустым Telegram ID владельца из
`BOT_ADMIN_USER_IDS`; API и бот должны получить одно значение. Проверять
только равенство/членство, не выводя ID или секрет в evidence.
Утверждённые веса модели не переобучать и не менять в рамках релиза. Текущая
production модель — legacy CatBoost v1, без managed promotion. Проверенные
локальные артефакты прежнего wrapper имеют те же SHA-256 трёх payload-файлов,
что документированы для v1.2.15. После merge собрать из них новый immutable
wrapper через `build_model_bundle(..., app_version="1.3.0",
source_commit=<exact merge SHA>, release="v1.3.0")`; проверить checksums,
загрузку CatBoost и 489 признаков локально и внутри exact Worker image без
сети. Старый wrapper v1.2.15 несовместим со строгой проверкой версии 1.3.0.

До GO отдельно проверить доступы серверного registry sync/feedback, выдачу
точечных grants, доставку отдельных Object Storage credentials, расписание и
отсутствие конфликтующих legacy путей. Ключи не записывать в Git, логи или
полный rendered Compose. Текущие значения production config сначала сохранить
в закрытом rollback artifact.

## Healthcheck и smoke-проверка

На изолированном контуре с восстановленной production-подобной БД до выпуска:
применить миграции и grants под штатными ролями, проверить `/health`, `/ready`,
`/docs`, `/openapi.json`, NHL календарь, `/predict` с текущей линией и без неё,
предстоящие события, bot heartbeat и частный Telegram `/predict`.
Отдельно проверить неизменяемую prediction revision, ручной ввод и расчёт
ставки в боте, audit исправления, месячную сводку и отсутствие смешивания с
симуляцией. Registry должен пройти publication → server sync → candidate
feedback → local review без потери или повторного создания ID. Повторный
Data Cycle не должен дублировать outbox, snapshot или ставки.

После переключения проверить exact running digests, health, restart/OOM,
один ограниченный ручной NHL Data Cycle до terminal `success`, remote verified
архивы до публикации, свежие прогнозы в API и полезные карточки в боте.
Выполнить `make acceptance-check` с защищёнными runtime inputs и версией
`1.3.0`. Расписание включать только после успешного ручного цикла;
legacy timer оставить выключенным. При любой ошибке остановить rollout,
не запускать повторный цикл вслепую и зафиксировать run/stage/failure code.

## Данные и совместимость

Документированная v1.2.15 схема — `0017_data_cycle_notification_outbox`;
кандидат содержит линейные миграции `0018`–`0025_real_bets_ledger`. Фактическую
серверную revision подтвердить отдельно. `0023` и `0025` содержат
append-only данные; Alembic downgrade запрещён. Перед production mutation
нужны свежий root-only backup, изолированный restore, off-host копия с
совпадающей SHA-256 и репетиция upgrade до `0025` на восстановленной БД.
После migration повторить role bootstrap/grants и проверить доступ под
`sf_api_reader`, `sf_control_api`, `sf_refresh_writer` и выделенной ролью
registry sync. Проверить прошлый образ с новой схемой на изолированной БД;
если совместимость не подтверждена, rollback означает восстановление backup
в окно простоя либо проверенный forward-fix, а не простое возвращение image.

Свободное место на первом read-only осмотре VPS составляло около 14 ГБ
(83% занято); текущий размер БД, image cache, свободные inode и запас для
backup/restore не проверены. До записи на VPS подтвердить ёмкость и
ограничить расход места без удаления данных без решения владельца.

## Наблюдаемость

В release evidence фиксировать UTC, source commit/tag, manifest digest,
running image digests, model bundle ID, Alembic revision, backup hash,
container restarts/OOM, RAM/disk, Data Cycle run/stage/failure codes,
количество опубликованных прогнозов, odds coverage, Object Storage
verification states, registry version/feedback и доставку уведомления.
Для журнала ставок использовать только агрегаты и технические статусы;
не сохранять персональные данные, коэффициенты чужих аккаунтов или полные
внешние ответы.

## Артефакт и откат

После независимого review и terminal PR CI Reviewer ставит annotated
`v1.3.0` на проверенный merge commit. Tag pipeline должен выполнить CI,
Security, first-rollout contract, публикацию linux/amd64 образов, scan и
provenance. Immutable manifest и handoff проверить через
`make verify-release-evidence` с `--handoff docs/operations/production-handoff.md`.
До switch сохранить exact прежние image digests, конфигурацию и model pointer;
rollback target определить по реально работающей версии, а не по старому
документу. На изолированном restore проверить возвращение прежнего приложения
после миграций. Время восстановления и окно наблюдения фиксируются
Operations Agent до GO. Если обратная совместимость не подтверждена,
предусмотреть restore/forward-fix и остановить изменение данных.

## Нерешённые вопросы

1. На disposable PostgreSQL синтетическая схема `0017` прошла dump/restore,
   upgrade до `0025`, выдачу grants и проверки прав под API, Worker, sync и
   feedback ролями. Проверка на свежей копии production БД и сквозной
   пользовательский smoke остаются открытыми.
2. EPIC-026/TASK-026-5 не прошёл серверный gate. Исправление bootstrap и
   grants локально проверено; доставку credentials, публикацию registry,
   реальный server sync/feedback и расписание ещё нужно подтвердить.
3. Серверные `BET_OWNER_USER_ID`, registry credentials, фактическая Alembic
   revision, deployed image digests и состояние расписания не подтверждены.
4. SSH после первого чтения завершался тайм-аутом; ёмкость и свежесть backup
   не доказаны. Rollback target и время восстановления не определены.
5. PR review/CI, annotated tag, tag pipeline, immutable images, scan,
   provenance, модельный wrapper 1.3.0 и release evidence ещё не получены.

До закрытия этих пунктов статус остаётся `NO-GO`. `candidate` означает
заполненный контракт проверки, а не разрешение на production switch.
