# TASK-025-28 — Исправить проверку `/docs` в acceptance script

> **Статус:** cancelled — оставшиеся критерии сняты решением владельца 2026-10-03
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

## Итог закрытия EPIC-025

Реализация включена в выпущенную v1.2.15. Неотмеченные выше критерии отдельного релиза/проверки не подтверждены в этой TASK и сняты при принятии итогового результата EPIC-025 владельцем. Это не отметка об их успешном выполнении.

v1.2.15 acceptance проверил /docs и /openapi.json с HTTP 200.
