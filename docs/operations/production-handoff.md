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

- Название сервиса: Sports Probabilistic Forecasting 1.0.0.
- Репозиторий и основной branch: SportsProbabilisticForecasting, `main`.
- Владелец приложения: пользователь.
- Владелец решения о production-развёртывании: пользователь.
- DevOps Operations Agent получает право только на подготовку PR; само развёртывание требует
  отдельного явного одобрения владельца.

## Runtime и конфигурация

- Команда запуска контейнера: `docker compose -f docker-compose.prod.yml up -d`.
- Требуемая версия Python и системные зависимости: Python 3.12; curl и libpq-dev в Dockerfile.
- Runtime dependency boundary: `uv sync --frozen --no-dev` устанавливает только
  serving-зависимости. DVC, DVC S3, MLflow и Optuna находятся в dev-группе для
  local training/control plane и не должны попадать в API, Worker или bot image.
- Переменные окружения (значения хранятся только в secret store):
  `POSTGRES_PASSWORD` — пароль PostgreSQL; `SF_API_IMAGE`, `SF_WORKER_IMAGE`,
  `SF_BOT_IMAGE` — точные `image@sha256:digest`; `SF_APP_VERSION` — версия
  приложения; `SF_WORKER_RUN_ID` — уникальный scheduler ID; `SF_API_DOMAIN` —
  публичный DNS; `BOT_TOKEN`, `BOT_ALLOWED_USER_IDS`, `BOT_ADMIN_USER_IDS`,
  `BOT_API_BASE_URL` — Telegram и внутренний API; `ODDS_API_KEY_FREE`,
  `ODDS_API_KEY_20K`, `ODDS_API_KEY_100K`, `ODDS_API_KEY` — ключи Odds API;
  `DATABASE_URL` — только host CLI; `SF_OBJECT_STORAGE_ENDPOINT`,
  `SF_OBJECT_STORAGE_BUCKET`, `SF_OBJECT_STORAGE_ACCESS_KEY_ID`,
  `SF_OBJECT_STORAGE_SECRET_ACCESS_KEY`, `SF_OPERATIONAL_ARCHIVE_PREFIX`,
  `SF_SERVING_DATA_PREFIX` — archive/bundle; `MLFLOW_TRACKING_URI` — только
  local training. Acceptance использует отдельные operator-only
  `SF_ACCEPTANCE_BASE_URL`, `SF_ACCEPTANCE_PREDICTION_PATH`,
  `SF_ACCEPTANCE_MODEL_VERSION`, `SF_ACCEPTANCE_DATABASE_URL`,
  `SF_ACCEPTANCE_WORKER_RUN_ID`, `SF_ACCEPTANCE_BOT_HEALTH_COMMAND`.
- Внешние зависимости, адреса и ожидаемые таймауты: PostgreSQL, Telegram, NHL API и The Odds API; timeout Odds API 120 секунд. MLflow остаётся в локальном training-контуре.
- Порты и исходящие сетевые соединения: API 8000; Caddy 80/443; исходящий HTTPS к внешним API.

## Healthcheck и smoke-проверка

- Команда или endpoint liveness: `curl -sf http://127.0.0.1:8000/health`.
- Команда или endpoint readiness, проверяющий значимые зависимости: `curl -sf http://127.0.0.1:8000/ready`; `/health` остаётся liveness и не обращается к БД.
- Безопасная smoke-проверка после запуска: GET `/health`, `/ready`, `/docs` и
  заранее выбранного known prediction c `live_pinnacle=false`; acceptance
  дополнительно читает `worker_executions` через отдельную DB role только с
  `SELECT` и запускает только heartbeat healthcheck bot.
- Ожидаемый результат и максимальное время ожидания: HTTP 200 за 90 секунд.

## Данные и совместимость

- Постоянные данные и тома: PostgreSQL, `runtime_data` (не более семи дней), `runtime_models` (current/previous model bundles), read-only `serving_data` для Worker и Caddy volumes; фактические пути проверяет Operations Agent.
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
- Ресурсный budget Worker: `2.0` CPU, `2048m` RAM и внешний scheduler timeout
  `20m`; локальное production-like evidence — 4.48 сек. и ≈399.6 MiB RSS для
  3 248 inference rows, см. [worker-measurement-evidence.md](worker-measurement-evidence.md).
- Retention: на VPS `runtime_data` не более 7 дней, current/previous model и
  serving-data bundles сохраняются для rollback; operational archive в Object
  Storage не удаляется автоматически, стоимость и целостность проверяет Operations Agent.

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
- Полученное remote evidence 2026-08-10: Docker workflow
  [#31382689135](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/31382689135)
  завершился успешно. CI gates, dependency/filesystem/image scans и provenance
  прошли для трёх runtime images; Trivy сообщил 0 HIGH/CRITICAL findings.
  Immutable references для candidate commit `d37469e`:

  ```text
  SF_API_IMAGE=ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:b6054d35896e500866f902324f3e3aef1758cfcb2fe79b8925ff3e5740a7a8ad
  SF_WORKER_IMAGE=ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:df985fb62974b7ebfe5f0c1f48788e3daae1f88f0b96d517ed408911a8837b9b
  SF_BOT_IMAGE=ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:2f1db660b29e4972935a99d30dea088e14c9a6db3cf996416c851482e1bfdf58
  ```

  Production DB role, external Telegram/API connectivity и VPS rollout ещё не
  проверялись; их нельзя отмечать как выполненные до соответствующего remote run.
- Локальный `make security` на 2026-08-09 успешно выполнил `pip-audit` для
  locked production runtime dependencies: `No known vulnerabilities found`.
  Он не заменяет dependency/filesystem/image scans опубликованных образов и
  external evidence, поэтому production rollout всё ещё запрещён до их получения.

## Артефакт и откат

- Registry и неизменяемый идентификатор image: три `SF_*_IMAGE` digest выше;
  SemVer tag не используется как runtime ID.
- Способ доказать происхождение артефакта: commit SHA, Git tag `v1.0.0`,
  совпадающий с `pyproject.toml`, CI provenance attestation и отдельный digest
  каждого runtime image. Для candidate `d37469e` provenance создан в Docker
  workflow [#31382689135](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/31382689135).
- Предыдущая исправная версия: определяется Operations Agent из последнего работоспособного immutable image.
- Процедура и допустимое время отката: до migration вернуть Compose на предыдущий immutable image; после additive migration использовать forward-fix либо восстановить проверенный backup — destructive downgrade запрещён. После действия проверить `/ready`; целевое время определяет Operations Agent.
- Критерии остановки rollout: health не 200, DB недоступна, crash loop или рост ошибок refresh.

## Нерешённые вопросы

- До отдельного разрешения не созданы Git tag и deployment; Operations Agent
  использует зафиксированные выше digest и GitHub/GHCR scan/provenance evidence,
  scheduler owner, backup RPO/RTO, read-only acceptance DB role и VPS evidence
  перед rollout.

## Граница ответственности

Агент приложения отвечает за код, тесты, Dockerfile, healthcheck, безопасные логи,
CI-проверки, неизменяемый артефакт и этот документ. DevOps Operations Agent отвечает за
проверку фактического production-окружения, секреты, Compose/systemd, доступы, наблюдаемость,
rollout, rollback и эксплуатационную документацию. Ни одна из сторон не подменяет явное
одобрение владельца на production-развёртывание.
