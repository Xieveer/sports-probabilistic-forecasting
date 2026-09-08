# Передача сервиса в эксплуатацию: v1.1.14 candidate

- Статус подготовки: `candidate`
- Сервис: `sports-probabilistic-forecasting`
- Canonical repository: `Xieveer/sports-probabilistic-forecasting`
- Владелец приложения и решения о rollout: пользователь.
- source_tag: `v1.1.14`
- source_commit: `9daf2d5bb040a5b8860961a12cb81a48997eaeac`
- evidence_tag: `v1.1.14-evidence.2`

Evidence tag создаётся только после успешного evidence gate и является annotated,
immutable указателем на этот evidence commit. Его commit SHA намеренно не записан
в самого себя: Operations получает tag и разрешает его externally, без self-reference.

## Подтверждённые gates

- CI: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/34231526622
- Security: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/34231526630
- Docker: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/34231529542
- first-rollout: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/34231529542

CI и Security относятся к review/evidence-base commit
`c50ec4073ec88b6de833626a977965122bfaa942`; Docker и first-rollout относятся к
exact application source commit `9daf2d5bb040a5b8860961a12cb81a48997eaeac`.
Docker run подтвердил publication, linux/amd64, image scan и provenance для всех
application images; first-rollout был выполнен только в одноразовом изолированном
CI-контуре с local registry и redacted evidence. Новый Docker run для evidence.2
должен быть успешно завершён до создания tag; production deployment этой задачей не
выполняется.

## Immutable runtime references

- SF_POSTGRES_IMAGE: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`
- api: published; linux/amd64; image scan; provenance; `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:736a96cb4ece6f5dfe369462851f757e47ba847ea94e1e827969106439870176`
- worker: published; linux/amd64; image scan; provenance; `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:3f802d34f6673afa7a3df74e6fa89554a77170856108ef2347306e752ee89325`
- telegram_bot: published; linux/amd64; image scan; provenance; `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:dc442b3c3f227b16884adff696d6afded982cf049b83a6abd91b305f175c3fba`
- archive_sync: published; linux/amd64; image scan; provenance; `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:1db2271fd8690dc83c04aae40a0936602f654b3f7b2209b61d2098ca0d936c2d`

`deploy/release-manifest.json` из этого commit является единственным декларативным
источником runtime references; manifest не содержит secrets, credentials, IDs,
Object Storage keys или environment values. SemVer tags не являются runtime
identifiers.

Перед annotated evidence tag release owner запускает manual workflow либо его
эквивалентный evidence gate с `--handoff docs/operations/production-handoff.md`;
успех gate не является разрешением на deployment.

## Исправление Worker evidence.2

В `v1.1.14-evidence.1` был записан `sha256:c963ed…`, то есть Sigstore/SLSA
provenance referrer с пустым OCI config, а не его subject image. Поэтому Docker
production-сервера не мог разрешить из него `linux/amd64`. В evidence.2 только
`images.worker` заменён на runnable subject manifest `sha256:3f802d…`; остальные
четыре immutable references сохранены. Docker pipeline теперь получает digest из
tagged remote manifest, проверяет его через `docker buildx imagetools inspect` на
`linux/amd64`, а для Worker выполняет pull, image inspect и non-root read-only
runtime import smoke по exact reference.

## Граница первого rollout

Первый rollout private и Telegram-only. Public ingress, DNS, TLS, Caddy, новые
inbound ports и firewall changes не входят в scope. Base Compose не публикует host
ports. API, Worker, Telegram bot, source-acquirer и archive-sync используют
UID/GID `10001:10001`.

Scheduler/timer остаётся disabled до отдельного owner approval и successful bounded
initial refresh. Этот candidate не разрешает deployment, production migrations,
bootstrap import или Telegram delivery verification.

## Контракт Operations и recovery boundaries

До любого одобренного запуска Operations проверяет server-side paths, ownership
`10001:10001`, permissions, ресурсы, локально доступные pinned images, secrets
metadata без чтения значений, backups, telemetry и отсутствие active incidents.
Root-owned wrapper принимает только:

```text
deploy sports-probabilistic-forecasting v1.1.14
```

Он сверяет service, version, source commit и все digest с локально установленным
verified manifest; не принимает image references, paths, environment values или
дополнительные аргументы. `deployer` не получает shell, sudo, Docker CLI,
port/agent/X11 forwarding. До изменения entrypoint Operations создаёт timestamped
backup, выполняет syntax/config dry-run и доказывает rejection запрещённых команд.

При отдельном owner approval порядок строго следующий:

1. Проверить pre-existing initial source-state, canonical bootstrap и model bundle
   в pinned Worker image; создать verified PostgreSQL backup до migrations/import.
2. Выполнить `role-bootstrap`, затем отдельный `migrator`; API/Worker не выполняют
   DDL при старте.
3. Выполнить idempotent canonical bootstrap import; запустить API и Telegram bot.
4. Выполнить только безопасные `/health`, `/ready`, `/docs` и заранее выбранную
   known prediction с `live_pinnacle=false`; ожидается HTTP 200 не позднее 90 секунд.

Stop criteria: crash loop, DB failure, non-200 readiness/health, missing verified
backup либо отклонение manifest/wrapper. До migration разрешён rollback только на
предыдущие immutable references; после additive migration — forward-fix либо verified
backup restore. Destructive downgrade запрещён. Continuous deployment остаётся
выключенным до успешного первого production rollout и проверенного recovery path.
