# Production observability mapping

Grafana Alloy собирает container logs и внутренние HTTP signals; Caddy не
публикует `/metrics`. В публичный ingress доступны только API routes, а
`/health`/`/ready` используются отдельными probes.

| Signal | Источник | Alert condition |
|---|---|---|
| API liveness/readiness | `/health`, `/ready` | non-200 или DB unavailable |
| Bot | `/tmp/sf-bot-heartbeat.json` healthcheck | старше 120 сек. или Telegram/internal API false |
| Worker | `worker_executions` и container exit | failed, нет daily success или `materialization_failed` |
| Prediction freshness | `predictions.prediction_ts` | старше daily SLA |
| Resources/restarts | container/host metrics Alloy | memory/CPU limit, restart loop |

Для canonical full-history NHL alert memory должен срабатывать до `3 GiB` hard
limit: локальное evidence зафиксировало ≈2.31 GiB peak RSS. `materialization_failed`
при нулевом upcoming inference input — безопасный failed run, а не основание
выдавать предыдущую витрину публично.

Heartbeat и execution state содержат только timestamps, boolean flags,
allow-listed code и count. Нельзя передавать в Alloy token, user/chat ID,
username, текст сообщения, query secrets или ответы Telegram API.
