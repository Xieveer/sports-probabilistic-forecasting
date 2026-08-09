# TASK-005-5 — Bot heartbeat и production observability

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-005](../EPIC-005-production-serving-readiness.md)
> **Требование:** [REQ-005](../../product/requirements/REQ-005-production-serving-release.md)
> **ADR:** [ADR-005](../../architecture/adr/ADR-005-production-serving-boundary.md)

## Результат и границы

Bot публикует безопасный heartbeat о event loop, Telegram API, internal API и
last success; API/Worker дают Alloy достаточные signals. Не публикуются tokens,
chat/user IDs, usernames, сообщения и ответы Telegram API.

## Критерии приёмки

- [x] Healthcheck bot проверяет свежий heartbeat, а не только PID; outage
  Telegram/internal API становится наблюдаемым без crash-loop masking.
- [x] Есть signals для readiness API/DB, bot, Worker success/failure/stale,
  prediction freshness, deploy/restart/resources и documented Alloy collection.
- [x] Tests доказывают redaction запрещённых полей в logs, metrics и alerts.

## План реализации

1. Добавить failing heartbeat/redaction tests с synthetic secrets/PII.
2. Внедрить state и minimal metrics/log fields; исключить public `/metrics` в
   production ingress.
3. Адаптировать dashboards/alerts как importable Grafana Cloud assets или
   задокументировать mapping для Operations Agent.

## Проверка

- Targeted bot/API tests, redaction inspection, Alloy scrape smoke без public ingress.

## Handoff и отчёт

- Блокер: TASK-005-1, TASK-005-2, TASK-005-4.
- Отчёт выполнения: `docs/changes/done/TASK-005-5-bot-heartbeat-and-observability.md`.
