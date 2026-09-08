# Передача сервиса в эксплуатацию

Этот документ — статический application contract. В application tag он остаётся
`draft`: final digests, GitHub runs, source SHA и `candidate` возникают только
после успешного tag pipeline и фиксируются отдельным evidence commit/tag.

- Статус подготовки: `draft`

## Идентификация и ответственность

- Сервис: `sports-probabilistic-forecasting`; application version определяется
  `pyproject.toml`; canonical repository: `Xieveer/sports-probabilistic-forecasting`.
- Владелец приложения и решения о rollout: пользователь.
- Application tag и evidence tag являются annotated и immutable. Владелец репозитория
  обязан защитить оба от force-update/delete вне Git tree.
- Operations не получает общих Docker, shell, `sudo` или root прав. Production rollout
  допускается только отдельным явным одобрением владельца.

## Runtime и конфигурация

- Первый rollout — private Telegram-only. Base `docker-compose.prod.yml` не публикует
  host ports. Public ingress, DNS, TLS, Caddy, firewall changes и новые inbound ports
  не входят в scope.
- API, Worker, Telegram bot, source-acquirer и archive-sync запускаются с
  UID/GID `10001:10001`; host paths готовит Operations с теми же ownership/permissions.
- Все credentials передаются лишь через `*_FILE` paths и Docker secrets. Нельзя включать
  значения secrets, chat/user IDs, credentials или environment values в manifest/evidence.
- Runtime identifiers: только exact `image@sha256:...` для PostgreSQL, API, Worker,
  Telegram bot и archive-sync. SemVer image tag не является runtime identifier.

## Healthcheck и smoke-проверка

- Liveness: `GET /health`; readiness: `GET /ready`; safe smoke: `/health`, `/ready`,
  `/docs` и заранее выбранный known prediction с `live_pinnacle=false`.
- После запуска candidate Operations выполняет non-mutating `make acceptance-check` из
  защищённого operator environment. Команда не запускает Worker/training, не отправляет
  Telegram, не делает DML и не выводит secrets/payloads.
- Ожидаемый health/readiness result — HTTP 200 не позднее 90 секунд; crash loop,
  DB failure или не-200 являются stop criteria.

## Данные и совместимость

- До migrations/import Operations создаёт verified PostgreSQL backup. Затем: `role-bootstrap`,
  `migrator`, idempotent canonical bootstrap import, API и Telegram bot. API/Worker не
  выполняют DDL при старте.
- Operations до запуска проверяет existing initial source-state, canonical bootstrap и
  model bundle внутри pinned Worker image.
- Scheduler/timer остаётся disabled до отдельного owner approval и successful bounded
  initial refresh. Первичный import, migrations и Telegram delivery также не разрешены
  этим контрактом сами по себе.
- После additive migration допустимы forward-fix или verified backup restore; destructive
  downgrade запрещён. До migration rollback — previous immutable image references.

## Наблюдаемость

- Operations проверяет host/container telemetry, health, resource limits, backups и отсутствие
  active incidents до rollout. Logs не должны содержать tokens, passwords, keys или query secrets.
- Required signals: `/health`, `/ready`, restart loop, DB availability, refresh error и host
  resource exhaustion.

## Артефакт и откат

После зелёного application pipeline release owner создаёт отдельный evidence commit и только
после успешного evidence gate annotated tag `v1.1.14-evidence.1`. Evidence commit содержит:

1. `deploy/release-manifest.json` с `source_tag`, exact 40-hex `source_commit`, `evidence_tag`
   и ровно пять digest references;
2. этот handoff со статусом `candidate`, replacing historical blockers actual release evidence;
3. URLs successful CI, Security, Docker/image scan/provenance и first-rollout runs.

Перед evidence tag выполнить `make verify-release-evidence EVIDENCE_GATE_ARGS='--manifest deploy/release-manifest.json --rendered-compose <rendered.yml> --repository-root . --source-tag v<version> --version <version> --handoff docs/operations/production-handoff.md'`.
Workflow `Release evidence` повторяет проверку для evidence commit. Непройденный evidence gate,
отсутствующий run, mismatch digest/source binding или unprotected tag означает NO-GO.

## Нерешённые вопросы

- Application source не подтверждает successful external GitHub runs, publication, image scans,
  provenance, Linux/amd64 platform, evidence tag protection или VPS state; это обязательные
  post-tag доказательства до `candidate`.
- Deployment не выполнялся. Operations обязан проверить server-side paths, secrets metadata
  без чтения значений, wrapper restrictions, backup/recovery и acceptance после owner approval.

## Граница ответственности

Application team отвечает за source, automated gates, immutable artifact и этот contract.
Operations отвечает за host, secrets, wrapper, telemetry, rollout/recovery. Ни один документ
или зелёный pipeline не заменяет отдельное owner approval на production deployment.
