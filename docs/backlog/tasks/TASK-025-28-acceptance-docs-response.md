# TASK-025-28 — Исправить проверку `/docs` в acceptance script

> **Статус:** reviewed_pending_release
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)

## Дефект и критерии

В v1.2.10 `make acceptance-check` ложно сообщал `docs: недоступен`:
`scripts/acceptance_check.py` разбирал HTML ответа FastAPI `/docs` как JSON,
а тест подменял его нереалистичным JSON.

- [x] `/docs` проверяется по HTTP 200 и `text/html` без разбора body.
- [x] `/openapi.json` проверяется как JSON с ожидаемой версией API.
- [x] Адресные тесты воспроизводят старый отказ и проверяют неверный media type.
- [x] Проверка остаётся read-only и не выводит HTTP payload или credentials.
- [x] Независимое review кода и документации без блокирующих findings.
- [ ] Финальные release и production gates завершены.

Результат — в [отчёте](../../changes/done/TASK-025-28-acceptance-docs-response.md).
