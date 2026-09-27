# TASK-025-21 — Единая команда archive-sync для production runner

> **Статус:** in_progress — код и независимое review готовы, release/runtime gate открыт
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)

## Наблюдаемый дефект

Ручной OFF Data Cycle v1.2.7 завершил календарь, quality, predictions и
publication, но runner вызвал `docker compose run archive-sync sync --archive`.
Compose заменил CMD образа на системный `sync`, который отверг `--archive`.
Первый rollout-тест проверял архив другим путём и не обнаружил расхождение.
После host stop proof run закрыт `failed/archive_sync_failed`; outbox
доставлен один раз, active0, оба NHL timer выключены. В production остались
1 834 прогнозов и готовность 187/187 будущих матчей; два immutable
архива staged локально, удалённая синхронизация не завершена.

## Критерии исправления

- [x] Production runner явно запускает Python archive-sync CLI внутри
  approved образа и передаёт проверенный immutable artifact, state root и
  prefix для обоих видов архива.
- [ ] Локальный first-rollout до immutable tag выполняет **ту же команду**
  через Compose с S3 fixture и проверяет результат, а не отдельный путь.
- [x] Red→green regression обнаруживает прежний вызов системного `sync`;
  fault-case оставляет цикл failed, без ложного archive success.
- [ ] Независимый review, полный локальный first-rollout, PR/tag/evidence CI
  и production ручной OFF Data Cycle подтверждают archive success, 187/187
  прогнозов, odds attempts 0 и одно уведомление до включения таймера.

## Handoff

Результат фиксируется в [отчёте](../../changes/done/TASK-025-21-archive-sync-runner-command.md).
