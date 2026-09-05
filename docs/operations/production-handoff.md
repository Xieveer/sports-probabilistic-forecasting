# Передача сервиса в эксплуатацию

Этот документ — контракт между командой приложения и DevOps Operations Agent. Команда
приложения заполняет его до запроса на production-развёртывание. Operations Agent использует
его как входные данные, но самостоятельно проверяет сервер, секреты, Compose, мониторинг,
rollout и rollback в репозитории управления инфраструктурой.

- Статус подготовки: `candidate`

`draft` означает, что контракт ещё заполняется и развёртывание не разрешено. Перед передачей
в эксплуатацию установите `candidate`, замените все шаблонные пометки и выполните
`make production-check`.

## Идентификация и ответственность

- Название сервиса: Sports Probabilistic Forecasting 1.1.6.
- Репозиторий и основной branch: SportsProbabilisticForecasting, `main`.
- Владелец приложения: пользователь.
- Владелец решения о production-развёртывании: пользователь.
- DevOps Operations Agent получает право только на подготовку PR; само развёртывание требует
  отдельного явного одобрения владельца.

## Runtime и конфигурация

- Private Telegram-only candidate: `docker compose -f docker-compose.prod.yml up -d`.
  Public ingress требует отдельного явного opt-in:
  `docker compose -f docker-compose.prod.yml -f docker-compose.public.yml up -d`.
- Требуемая версия Python и системные зависимости: Python 3.12; curl и libpq-dev в Dockerfile.
- Runtime dependency boundary: `uv sync --frozen --no-dev` устанавливает только
  serving-зависимости. DVC, DVC S3, MLflow и Optuna находятся в dev-группе для
  local training/control plane и не должны попадать в API, Worker или bot image.
- Runtime identity boundary: API, Worker, Telegram bot и archive-sync запускаются
  как непривилегированный container user `sf` с UID/GID `10001:10001`. До
  rollout Operations создаёт на VPS отдельного host user `sf-runtime` с теми же
  UID/GID, подтверждает отсутствие коллизии и назначает его владельцем только
  требуемых source/archive bind mounts. UID/GID `999:999` запрещён: на
  `ops-prod-01` он занят `zabbix:systemd-journal`.
- Переменные окружения (значения хранятся только в secret store):
  `POSTGRES_PASSWORD` — пароль PostgreSQL; `SF_API_DATABASE_URL` — scoped
  read-only URL API; `SF_WORKER_DATABASE_URL` — scoped write URL refresh;
  `SF_API_IMAGE`, `SF_WORKER_IMAGE`, `SF_BOT_IMAGE`, `SF_POSTGRES_IMAGE`,
  `SF_ARCHIVE_SYNC_IMAGE` — точные `image@sha256:digest`; `SF_CADDY_IMAGE` и
  `SF_API_DOMAIN` нужны только public overlay; `SF_APP_VERSION` — версия
  приложения; `SF_WORKER_RUN_ID` — уникальный scheduler ID; `BOT_TOKEN`, `BOT_ALLOWED_USER_IDS`, `BOT_ADMIN_USER_IDS`,
  `BOT_API_BASE_URL` — Telegram и внутренний API; `ODDS_API_KEY_FREE`,
  `ODDS_API_KEY_20K`, `ODDS_API_KEY_100K`, `ODDS_API_KEY` — ключи Odds API;
  `DATABASE_URL` — только host CLI; `SF_CANONICAL_SOURCE_ROOT` — read-only
  provider snapshot; `SF_MODEL_RUNTIME_ROOT=/srv/sports-forecast/runtime_models`
  — read-only Worker model root; `SF_OPERATIONAL_ARCHIVE_ROOT` — persistent local staging;
  `SF_OBJECT_STORAGE_ENDPOINT`,
  `SF_OBJECT_STORAGE_BUCKET`, `SF_OBJECT_STORAGE_ACCESS_KEY_ID`,
  `SF_OBJECT_STORAGE_SECRET_ACCESS_KEY`, `SF_OPERATIONAL_ARCHIVE_PREFIX`, `SF_NHL_SOURCE_STATE_PREFIX`,
  `SF_SERVING_DATA_PREFIX` — archive/bundle; `MLFLOW_TRACKING_URI` — только
  local training. Acceptance использует отдельные operator-only
  `SF_ACCEPTANCE_BASE_URL`, `SF_ACCEPTANCE_PREDICTION_PATH`,
  `SF_ACCEPTANCE_MODEL_VERSION`, `SF_ACCEPTANCE_DATABASE_URL`,
  `SF_ACCEPTANCE_WORKER_RUN_ID`, `SF_ACCEPTANCE_BOT_HEALTH_COMMAND`.
- Внешние зависимости, адреса и ожидаемые таймауты: PostgreSQL, Telegram, NHL API и The Odds API; timeout Odds API 120 секунд. MLflow остаётся в локальном training-контуре.
- Порты и исходящие сетевые соединения: private base не публикует ports; Caddy
  80/443 появляется только в public overlay; исходящий HTTPS к внешним API.

## Healthcheck и smoke-проверка

- Команда или endpoint liveness: `curl -sf http://127.0.0.1:8000/health`.
- Команда или endpoint readiness, проверяющий значимые зависимости: `curl -sf http://127.0.0.1:8000/ready`; `/health` остаётся liveness и не обращается к БД.
- Безопасная smoke-проверка после запуска: GET `/health`, `/ready`, `/docs` и
  заранее выбранного known prediction c `live_pinnacle=false`; acceptance
  дополнительно читает `worker_executions` через отдельную DB role только с
  `SELECT` и запускает только heartbeat healthcheck bot.
- Ожидаемый результат и максимальное время ожидания: HTTP 200 за 90 секунд.

## Данные и совместимость

- Постоянные данные и mounts: `pg_data` — единственный Docker named volume.
  `SF_MODEL_RUNTIME_ROOT` — host bind mount Worker только для чтения;
  canonical source-state — read-only bind mount; archive staging Worker —
  read-write, archive-sync — read-only; sync state — отдельный host bind mount.
  API и bot не монтируют models/data; фактические пути проверяет Operations Agent.
- Scheduler/topology: [production-runtime-topology.md](production-runtime-topology.md).
- Runbook serving-data/archive: [serving-data.md](serving-data.md).
- Миграции и порядок их выполнения: после успешного backup и до API/Worker выполнить `docker compose -f docker-compose.prod.yml run --rm --no-deps api uv run alembic -c alembic.ini upgrade head`, затем проверить `/ready` и только после этого запускать Worker. API и Worker не выполняют DDL при старте.
- Runbook migration/recovery: [database-migrations.md](database-migrations.md).
- Совместимость новой версии с предыдущей: rollback выполняется immutable предыдущим образом; миграции не удаляют данные в этом выпуске.
- Требования к резервному копированию и восстановлению: Operations Agent делает backup PostgreSQL и persistent volumes до rollout и проверяет restore.

## Наблюдаемость

- Структурированные события запуска, остановки, heartbeat и ошибок: приложение пишет структурированные логи; container lifecycle собирает Operations Agent.
- Поля для корреляции: `service`, `environment`, `version` и прикладные идентификаторы.
- Метрики доступности, ошибок, ресурсов и результата работы: `/metrics`, healthcheck, container/host metrics; dashboards и alerts настраивает Operations Agent.
- Данные, которые необходимо маскировать до отправки логов: все env secrets, Telegram token, пароли, Odds API keys и HTTP query с ключами.
- Предлагаемые пороги оповещений и ссылки на runbook: недоступность `/health`, restart loop, ошибка refresh; runbook — `docs/source/nhl_local_operations.rst`.
- Ресурсный budget canonical Worker до подтверждённой оптимизации: `2.0` CPU,
  не менее `3g` RAM и scheduler timeout `45m`. Full-history NHL evidence:
  bootstrap 26.86 сек. / ≈1.05 GiB RSS, refresh 1:42.02 / ≈2.31 GiB RSS для
  22 218 canonical events; см. [worker-measurement-evidence.md](worker-measurement-evidence.md).
  Compose limit установлен в `3g`. Локальная future fixture также подтвердила
  inference и атомарную публикацию; production всё равно требует повтора на
  актуальном provider snapshot.
- Retention: на VPS `runtime_data` не более 7 дней, current/previous model и
  serving-data bundles сохраняются для rollback. Object Storage lifecycle
  удаляет только `operational-archive/nhl-source-state/` старше 90 дней;
  приложение и его service accounts не имеют DeleteObject. Перед включением
  lifecycle Operations измеряет первый artifact и прогноз storage. Object Lock
  и versioning shared bucket не включаются.

## Acceptance и release evidence

- Точная non-mutating команда после запуска candidate (значения берутся из
  защищённого operator environment):

  ```bash
  make acceptance-check
  ```

  Команда выполняет только GET `/health`, `/ready`, `/docs` и known prediction,
  проверяет API/model version, выполняет параметризованный `SELECT` safe outcome
  Worker и bot heartbeat. Она не запускает Worker/training, не отправляет
  Telegram-сообщения, не делает DML и не выводит response payloads или secrets.
- Контролируемая первая доставка выполняется только после успешного
  `make acceptance-check`, published immutable image evidence и отдельного
  разрешения владельца. Оператор задаёт в secret environment `BOT_TOKEN` и
  один `SF_DELIVERY_VERIFICATION_CHAT_ID`, затем запускает:

  ```bash
  uv run python -m sports_forecast.orchestration.delivery_verification \
    --send \
    --release-image "${SF_API_IMAGE}" \
    --model-version "${SF_ACCEPTANCE_MODEL_VERSION}"
  ```

  Команда не имеет retry, не запускается CI/scheduler/acceptance и не выводит
  token, chat ID либо тело ответа Telegram. При неуспехе повтор возможен только
  новым явным операторским запуском после проверки причины.
- Локальные evidence: [контракт runner](../../tests/test_acceptance_check.py),
  [строгий handoff gate](../../tests/test_production_readiness_validation.py),
  [worker measurement](worker-measurement-evidence.md), [migration/recovery](database-migrations.md),
  [signals](observability.md), [model bundle](model-bundle.md), [serving data](serving-data.md).
- Source-state evidence: initial bundle → verify → VPS install, successful
  incremental odds refresh, export → Object Storage → local read-only import /
  checksum и failure preservation. Static handoff/runbook/Compose/systemd
  changes входят в commit до release tag; после tag Git commit запрещён.
  Image digests/provenance передаются из CI/GHCR evidence без post-tag commit.
- v1.1.2 уже опубликован и остаётся immutable historical evidence, но имеет
  production-blocker: Worker не может импортировать verifier bundle без MLflow.
  Запрещено перепубликовывать image, переносить tag или менять любой digest
  v1.1.2: это разрушит связь version → commit → digest, rollback и audit trail.
- `v1.1.4` остаётся immutable historical blocker: Worker image не видел
  `omegaconf`, потому что bare `python` не выбирал uv-venv. Запрещено менять его
  tag или digest. Только следующий patch release `v1.1.5` после успешных checks
  на итоговом `main` может быть candidate. Его pipeline до push обязан собрать
  Worker и через bare `python` в final image проверить imports source-state,
  canonical-bootstrap, model-bundle и archive-sync, UID/GID `10001:10001`, а
  также bind-mounted content-addressed source-state/canonical-bootstrap fixtures
  штатными validators. Gate использует `--read-only`, `--network none` и
  `--mount type=bind`; он не запускает install/import в БД или scheduler.
  После этого pipeline фиксирует новые GitHub CI, dependency/filesystem/image
  scans, GHCR provenance и четыре published immutable digests (api, worker,
  telegram-bot и archive-sync). До этих фактов release и rollout — NO-GO.
- `v1.1.5` также остаётся immutable historical evidence и не переписывается.
  Candidate следующего patch — только `v1.1.6`: до его tag CI обязан выполнить
  rendered-Compose gate и final Worker model-mount gate. Их output, четыре
  image@digest, commit SHA и provenance передаются Operations из CI после tag;
  до этого v1.1.6 не имеет разрешения на rollout.
- Локальный `make security` на 2026-08-09 успешно выполнил `pip-audit` для
  locked production runtime dependencies: `No known vulnerabilities found`.
  Он не заменяет dependency/filesystem/image scans опубликованных образов и
  external evidence, поэтому production rollout всё ещё запрещён до их получения.

## Артефакт и откат

- Registry и неизменяемый идентификатор image: для v1.1.6 использовать только
  новые GHCR `image@sha256:digest`; SemVer tag не является runtime ID.
- Способ доказать происхождение артефакта: итоговый commit SHA, Git tag
  `v1.1.6`, совпадающий с `pyproject.toml`, CI provenance attestation и
  отдельный digest каждого runtime image.
- Release evidence v1.1.2 (только historical evidence, не использовать для
  rollout): tag указывает на `eadbdb4bfe979cfdb37b31bd64975d0cfd5ad556`;
  [GitHub Actions run 32239173166](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/32239173166)
  успешно завершил release gates, published-image scans и provenance для:
  - API: `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:e613ba9c05d4040530ea138b6e6cc36169445ef331ce515c0dc796b7ebf38096`.
  - Worker: `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:5731b374e02f544e35f8884d45c81dfed9086c95620387e1f66123ee71d0d926`.
  - Telegram bot: `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:30dff19e339d79632ee83d5f046edf45145eef2e4c9046320a19bcb245dc3bf4`.
  - Archive-sync: `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:17dbba8452ab1fa0eeeb6df0ae338ac6be54da5fddbdac42cd1fd3afcc86e3f3`.
- Release evidence v1.1.3 (historical; не candidate): tag указывает на `3f67aa8c8e28bc4311b2c1146662b12f9a9e8055`;
  [GitHub Actions run 32395043783](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/32395043783)
  успешно выполнил release gates, Worker import gate, image scans и provenance:
  - API: `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:fbe16fd5f6381fcfb81ef79c8817831addd02d1becb699b066fc03e9b550bd04`.
  - Worker: `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:0c2b6db2bbbbee03d79100a89b2389003de8df112b22f035389881063e34c9e5`.
  - Telegram bot: `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:bef3ab26a848e839b126886277144123dac808a0cf23e97817bbbb03aa293016`.
  - Archive-sync: `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:8dbf8582f36bb3516422c59a4db0f899718083e68c304742ce5f913b59ac4a49`.
- Staged initial source-state
  `sha256:0bca266747aac0f0050271c231f61a0c22d5e553b9219d8760795663d56421c4`
  и canonical bootstrap
  `sha256:bb8f3ac446e9599a8b24b96eeb279a0fc540af3e86b4e089900761ab5e1effb1`
  для `v1.1.4` сохраняются immutable: их не пересобирать, если v1.1.5 не
  меняет contract. Operations сначала повторяет только verify в новом Worker
  image. Model delivery bundle для v1.1.5 при необходимости собирается из тех
  же трёх файлов с `app_version=1.1.5`; identity/checksum и source commit
  передаются вместе с новыми image digests.
- Предыдущая исправная версия: определяется Operations Agent из последнего
  работоспособного immutable image; v1.1.2 не является rollback-кандидатом.
- Model delivery bundle: перед rollout Operations получает путь/immutable
  `bundle_id`, manifest checksum, `app_version` и source commit; `current` и
  `previous` устанавливаются только через [model-bundle.md](model-bundle.md).
  Rollback model выполняется проверенным `previous` pointer, rollback image —
  предыдущими image digests; destructive migration downgrade запрещён.
- Процедура и допустимое время отката: до migration вернуть Compose на предыдущий immutable image; после additive migration использовать forward-fix либо восстановить проверенный backup — destructive downgrade запрещён. После действия проверить `/ready`; целевое время определяет Operations Agent.
- Критерии остановки rollout: health не 200, DB недоступна, crash loop или рост ошибок refresh.

## Pre-release review v1.1.6

| Boundary | Статус и обязательное подтверждение до rollout |
|---|---|
| Host paths | **Ожидает server-side validation:** все host bind paths существуют, принадлежат `10001:10001`, model/source read-only, archive/sync state имеют минимальные права. CI проверяет только rendered topology. |
| Runtime identity | **Подтверждено в final-image gate:** application images используют `sf=10001:10001`; Operations подтверждает отсутствие host UID collision. |
| Secrets | **Подтверждено contract review:** env files вне Git/image/logs; fixture содержит только placeholders; Operations разделяет model-reader и runtime/archive credentials. |
| Object Storage | **Ожидает IAM evidence:** model reader получает только read `production-models/*`; archive identity не получает model credentials. |
| Database | **Ожидает owner approval:** migrations additive, bootstrap только после backup evidence, startup DDL не выполняет. Ни один DB command не запускался этой задачей. |
| Resource budget | **Подтверждено rendered contract:** base (`db+api+bot`) и один bounded job одновременно дают максимум 6.375 GiB; gate требует минимум 1.4 GiB резерва на 8 GiB VPS для host/Docker/Alloy. Operations подтверждает фактическое потребление до запуска. |
| Networking | **Подтверждено rendered contract:** base Compose не публикует ports; Telegram использует long polling. |
| Scheduler | **Ожидает owner approval:** timer остаётся disabled до initial DB bootstrap, bounded refresh и отдельного решения владельца. |
| Recovery | **Подтверждено документацией:** rollback source-state/model pointer/images/DB описан; первый model install допускает отсутствие `previous`. |
| Observability | **Ожидает server-side validation:** labels, dashboard/alert contract и scrubbed telemetry должны быть готовы до runtime start. |

DevOps handoff для tag `v1.1.6`: передать exact four `image@sha256:digest`,
tag, commit SHA, CI run URL и результаты `rendered Compose`, `final model mount`
и `staged artifacts` gates. До получения этих dynamic evidence решение — NO-GO.

## Нерешённые вопросы

- Deployment не выполнялся. Operations Agent получает выше новые digests и
  GitHub/GHCR scan/provenance evidence, после чего подтверждает scheduler owner,
  backup RPO/RTO, read-only acceptance DB role, worker memory limit не менее
  3 GiB, успешный refresh с актуальными upcoming матчами provider и VPS mount
  ownership для `sf-runtime:10001:10001`.

## Граница ответственности

Агент приложения отвечает за код, тесты, Dockerfile, healthcheck, безопасные логи,
CI-проверки, неизменяемый артефакт и этот документ. DevOps Operations Agent отвечает за
проверку фактического production-окружения, секреты, Compose/systemd, доступы, наблюдаемость,
rollout, rollback и эксплуатационную документацию. Ни одна из сторон не подменяет явное
одобрение владельца на production-развёртывание.
