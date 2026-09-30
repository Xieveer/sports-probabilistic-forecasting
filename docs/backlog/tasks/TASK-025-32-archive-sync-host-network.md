# TASK-025-32 — Восстановить сетевой путь archive-sync

> **Статус:** in_progress
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-027](../../architecture/adr/ADR-027-archive-sync-host-network.md) (accepted)

## Наблюдаемый дефект

На `ops-prod-01` штатный `archive-sync` v1.2.11 в Docker bridge получает
`ReadTimeoutError` во время TLS handshake к Yandex Object Storage даже при
отправке 686-байтного manifest. Тот же immutable image через сеть host завершает
TLS за 0,12 секунды; с хоста `PutObject` и обратная SHA-256 проверка 49,7 МБ
успешны. Production Data Cycle остаётся `running/archive_sync`, а оба NHL timer
выключены. Подробное evidence — в operations change record
`docs/changes/2026-09-30-v1.2.11-archive-network-diagnosis.md` отдельного
репозитория Operations Agent.

## Критерии исправления

- [x] Только one-off `archive-sync` использует host network; API, bot, Worker,
  dispatcher, PostgreSQL и source-acquirer сохраняют прежнюю сетевую границу.
- [x] Compose продолжает монтировать archive staging read-only, sync state
  read-write и только два Object Storage secret files в `archive-sync`; UID/GID,
  read-only root filesystem, ресурсы и отсутствие published ports сохраняются;
  capabilities сброшены и запрещено повышение привилегий.
- [x] Production Compose render проходит локальную проверку; контрактный тест
  обнаруживает возвращение `archive-sync` в bridge или расширение host network
  на другие сервисы.
- [ ] Независимый review и CI подтверждают config/security gates до production.
- [ ] На VPS из exact release image штатный sync remote-verify-ит оба сохранённых
  artifact. После штатного recovery старого run новый ручной цикл завершается
  terminal, доставляет одно уведомление и сохраняет odds evidence; только затем
  разрешается включить ежедневный dispatcher timer.

## Граница

Не меняются модели, данные, код S3 transport, timeout/retry policy, роли БД,
секреты, API/Telegram runtime и глобальная Docker network/firewall policy.
Точечный host network расширяет доступ sync-контейнера к локальным сетевым
службам VPS; решение, проверка и rollback описаны в ADR-027.

## План проверки

1. Red: контрактный тест Compose service network boundary.
2. Green: минимальное изменение `docker-compose.prod.yml`, адресные тесты и
   `docker compose config --quiet` с synthetic env.
3. Review и release gates; на VPS сверить exact revision, backup и состояние
   старого run до sync/recovery. При ошибке остановить rollout.

## Handoff

- Отчёт выполнения: [TASK-025-32](../../changes/done/TASK-025-32-archive-sync-host-network.md) после завершения Developer.
- Production результат фиксирует Operations Agent отдельно.
