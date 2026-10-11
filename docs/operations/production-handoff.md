# Передача сервиса в эксплуатацию: v1.3.1 candidate

- Статус подготовки: `candidate`
- Решение на 2026-10-11: `GO`; ограниченный rollout завершён, остаточные риски перечислены ниже.
- Инициатива: [EPIC-032](../backlog/EPIC-032-v1-3-0-release.md).
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- Целевая среда: production VPS `ops-prod-01`; версия: `1.3.1`.
- source_tag: `v1.3.1` — annotated tag на exact merge commit `757d3af338bb2bb36304cb3e81c0f2c93a0834e5` после terminal PR CI.
- source_commit: `757d3af338bb2bb36304cb3e81c0f2c93a0834e5`.
- evidence_tag: `v1.3.1-evidence.1` — immutable evidence, [CI success](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38146778838).
- CI: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38145027492 — terminal PR CI.
- Security: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38145027276 — terminal PR security.
- Docker: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38145180090 — успешный exact tag pipeline.
- first-rollout: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38145180090/job/114488128391 — clean first-rollout contract.
- postgres: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94` — exact работающий PostgreSQL image.
- api: published; linux/amd64; image scan; provenance; `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:4bf7c27dbd25ec88d14183704a076b5a9ac824003de754fe49fb344a69fcda8c`.
- worker: published; linux/amd64; image scan; provenance; `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:80de5332a5e7b5431cac5089bd6af27e6b70a50d758485f3e39105f2081196e3`.
- telegram_bot: published; linux/amd64; image scan; provenance; `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:8232f8643968694a50b2dbe5c96f33683592bff18952b98af08c64d89b577add`.
- archive_sync: published; linux/amd64; image scan; provenance; `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:622bca60a525ee820e25483e9033ef09603fa85ea596c1aaa42a18490cbbbf17`.
Нельзя подставлять commit ветки или mutable image tag. Успех tag pipeline не
заменяет отдельный evidence gate и серверный acceptance.

## Идентификация и ответственность

Состав выпуска: интегрированные [EPIC-026](../backlog/EPIC-026-entity-registry.md),
[EPIC-027](../backlog/EPIC-027-historical-odds.md),
[EPIC-028](../backlog/EPIC-028-production-model-contract.md),
[EPIC-029](../backlog/EPIC-029-configured-tournament-onboarding.md),
[EPIC-030](../backlog/EPIC-030-financial-research-validation.md) и
[EPIC-031](../backlog/EPIC-031-real-bets-ledger.md). Исходный production выпуск
был v1.2.15; read-only preflight подтвердил checkout
`774602cb3d2db8ce65b4411637ff86e057fc76ec` и schema revision
`0017_data_cycle_notification_outbox` на сервере. EPIC-030 завершён решением STOP: новый алгоритм не
продвигается. Турнир ENG1 не добавляется автоматически в расписание или выдачу.

Серверный gate [TASK-026-5](../backlog/tasks/TASK-026-5-registry-publication.md)
пройден в этом выпуске. EPIC-026 остаётся `blocked` по REQ-026 #10:
строгий server reader выключен, непустой кандидатный цикл ещё не наблюдался.

## Runtime и конфигурация

Production использует только `IMAGE@sha256:DIGEST`, ограниченные роли PostgreSQL,
Compose secret mounts через `*_FILE` paths и прежние ограничения ресурсов. `SF_APP_VERSION=1.3.1`
должна совпадать с package, source tag, модельным bundle и `/health`.
`BET_OWNER_USER_ID` должен быть непустым Telegram ID владельца из
`BOT_ADMIN_USER_IDS`; API и бот должны получить одно значение. Проверять
только равенство/членство, не выводя ID или секрет в evidence.
Утверждённые веса модели не переобучать и не менять в рамках релиза. Текущая
production модель — legacy CatBoost v1, без managed promotion. Проверенные
локальные артефакты прежнего wrapper имеют те же SHA-256 трёх payload-файлов,
что документированы для v1.2.15. После merge собрать из них новый immutable
wrapper через `build_model_bundle(..., app_version="1.3.1",
source_commit=<exact merge SHA>, release="v1.3.1")`; проверить checksums,
загрузку CatBoost и 489 признаков локально и внутри exact Worker image без
сети. Старые wrappers v1.2.15 и 1.3.0 несовместимы со строгой проверкой версии 1.3.1.
Wrapper `sha256:956edb47e9737516ce8a29ed42a6cea08af6522fed1b9510a614201c20daad09`
собран из тех же утверждённых payload без переобучения; manifest SHA-256
`20c078dc194093b915f38e9f9afe5627efa9ce771e2766021b8f7fd44c6dc104`.
Проверка внутри exact опубликованного Worker image с UID 10001, отключённой
сетью и read-only mounts прошла: bundle загрузился, CatBoost и все 489
признаков совпали. Приватное evidence:
`operations-agent/tmp/v1.3.1-model-stage/evidence.json`. На VPS bundle
установлен официальным installer; `current` указывает на v1.3.1, `previous`
сохраняет v1.2.15 для отката.

До GO были отдельно проверены доступы серверного registry sync/feedback,
точечные grants, доставка Object Storage credentials и расписание. Прежняя
production конфигурация сохранена в закрытом rollback artifact. Ключи не
записывались в Git, логи или полный rendered Compose; legacy NHL timer
выключен.

## Healthcheck и smoke-проверка

До выпуска восстановленная копия production БД прошла миграции, grants и
проверку runtime ролей. После переключения read-only HTTP/DB/health probes
подтвердили `/health` 200, `/ready` 200 с PostgreSQL и версией 1.3.1,
`/docs` 200 HTML, `/openapi.json` 200 с версией 1.3.1, 51 предстоящий
NHL прогноз и индивидуальный `/predict/{match_id}` 200 с ожидаемой версией
модели. Последний `worker_executions` — `succeeded`, 219 созданных прогнозов;
бот healthy. Exact image refs, схема `0025`, restart/OOM и timers сверены.

Ручной NHL Data Cycle завершился `success`; archive sync и публикация прошли,
штатное Telegram уведомление владельцу доставлено с первой попытки. Затем
включён dispatcher, старый NHL timer оставлен выключенным; первый tick не
создал дублирующий run. Registry publication и sync прошли; feedback и
local importer на пустой очереди завершились штатно. Непустой кандидатный
цикл и строгий reader остаются в EPIC-026/REQ-026 #10.

Команда `make acceptance-check` не запускалась: Makefile передаёт закрытый
DB URL через аргумент процесса. Вместо неё выполнены перечисленные выше
безопасные GET/SELECT/health проверки без вывода secret или payload.
Production ручной ввод ставки, audit исправления и месячная сводка не
проверялись тестовыми записями, чтобы не загрязнять пользовательский журнал;
их контракт проверен в тестах EPIC-031 до выпуска.

## Данные и совместимость

Исходная production схема до rollout была
`0017_data_cycle_notification_outbox`; текущая после применения линейных
миграций `0018`–`0025` — `0025_real_bets_ledger`. `0023` и `0025` содержат
append-only данные; Alembic downgrade запрещён. Перед миграцией были
подтверждены root-only backup, isolated restore, off-host копия с совпадающей
SHA-256 и репетиция upgrade на восстановленной БД. `role-bootstrap` выполнен
до `migrator`; затем применены Alembic и grants. Доступ под runtime ролями
проверен, старый API на новой схеме проверен на изолированной БД. Если
совместимость старого Worker не подтвердится при rollback, требуется
восстановление backup в окно простоя либо проверенный forward-fix.

Read-only осмотр VPS подтвердил около 14 ГБ свободного места (83% занято),
8,9 млн свободных inode, 5,8 ГиБ доступной RAM и БД размером около 180 МБ.
Из 53 ГБ Docker images 46 ГБ были отмечены как reclaimable. После pull
четырёх release images место упало до 7,16 ГБ; по отдельному разрешению
владельца удалены ровно четыре старых образа без container refs. Все active
и rollback refs сохранены; после rollout свободно 14,15 ГБ (83% занято).
Перед следующей записью повторно проверить ёмкость и ограничить расход места
без удаления данных без решения владельца.

Предпродовый backup gate 2026-10-11: новый root-only custom dump
`pre-v1.3.1-20261011T135600167242653.dump` размером `58 239 623` байта,
SHA-256 `f0c4670b295e0fc51ac1462d640b1834c434da3ec1f0f7b0635d1a04163b3456`.
Off-host объект полностью прочитан обратно: размер, SHA-256 и побайтовое
сравнение совпали. Изолированный restore в exact production PostgreSQL image,
без сети и production volume, завершился за 12 секунд; схема `0017`,
22 575 событий и 1 913 прогнозов. Production DB осталась healthy.
Evidence Operations Agent: `operations-agent/docs/changes/2026-10-11-v1.3.1-backup-gate.md`.
Локальная репетиция на этом снимке сохранила владельцев таблиц и sequence,
соответствующих production: все 25 таблиц и 24 sequence принадлежат
`sf_migrator`. Tagged `v1.3.1` role bootstrap, миграции `0018`–`0025` и
grants прошли; три runtime privilege tests для API, control, Worker, registry
sync и feedback прошли. Исходные 22 575 событий и 1 913 прогнозов
сохранились; новые `prediction_revisions` и `real_bets` пусты. Отчёт:
`operations-agent/docs/changes/2026-10-11-v1.3.1-db-rehearsal.md`.

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

Annotated `v1.3.0` уже поставлен на проверенный merge commit, но
[tag pipeline](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38142671658)
упал на Compose gate до build/push. Тег не перемещать; владелец утвердил
`v1.3.1` для исправленного кандидата. Terminal PR CI и новый annotated tag
получены; [успешный tag pipeline](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38145180090)
выполнил CI, Security, first-rollout contract, публикацию linux/amd64 образов,
scan и provenance. Первый дублирующий tag run `38145180105` упал на
`502 Bad Gateway` при запуске Docker Buildx до сборки двух OCI artifacts;
образов он не публиковал. Immutable manifest и handoff прошли
`make verify-release-evidence` с `--handoff docs/operations/production-handoff.md`.
До switch сохранены прежние exact image refs, root-only env и модельный
`previous` pointer. Rollback target — v1.2.15, commit
`774602cb3d2db8ce65b4411637ff86e057fc76ec`; его API, bot, Worker,
archive-sync и PostgreSQL refs сохранены в Docker cache. Старый API прочитал
схему `0025` на изолированной копии. Off-host backup имеет SHA-256
`f0c4670b295e0fc51ac1462d640b1834c434da3ec1f0f7b0635d1a04163b3456`;
изолированный `pg_restore --exit-on-error` занял 12 секунд, что не является
оценкой полного времени восстановления. Старый Worker после новых записей
не проверен; при сбое остановить dispatcher и использовать проверенный
forward-fix либо согласованное восстановление backup.

## Нерешённые вопросы

На `ops-prod-01` развёрнут exact `v1.3.1`: source commit и immutable image
digests совпадают с manifest, БД обновлена до `0025_real_bets_ledger`, API и
бот healthy без restart/OOM. Ручной NHL Data Cycle завершился `success` с 51
прогнозом; одна штатная Telegram notification владельцу доставлена с первой
попытки. Dispatcher, registry sync и feedback timers включены; первые
плановые ticks успешны, legacy NHL timer выключен. Проверены backup/off-host
readback/restore, миграция копии БД, реальный server sync sequence 1 и
раздельные credentials/grants. [Operations rollout evidence](https://github.com/Xieveer/operations-agent/pull/33)
прошло независимое review и слито.

1. Registry feedback/ack на production прошёл с пустой очередью; непустой
   кандидат → локальное решение → новая публикация ещё не проверены. Строгий
   server reader не включён. Это отдельный gate EPIC-026/REQ-026 #10.
2. Локальный registry master из trusted NHL seed требует защищённой копии.
   Следить за свободным местом VPS и ростом outbox.
3. Старый API прочитал схему `0025` на копии БД. Старый Worker после новых
   записей не проверен; при неудаче timer останавливается до forward-fix либо
   согласованного восстановления backup.

`candidate` здесь означает заполненный handoff contract; фактический
production rollout и его проверка завершены.
