# TASK-025-36 — Первый выпуск: подготовка Data Cycle до Worker

> **Статус:** in_progress — code/review done; terminal CI и production gate открыты
> **Владелец:** Product Owner / Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-028](../../architecture/adr/ADR-028-data-cycle-source-before-features.md)

## Дефект

Tag pipelines [v1.2.13](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36921903369)
и [v1.2.14](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36925157393)
остановились на first-rollout Worker до публикации образов. После исправления
`game_type` тестового source fixture точное локальное воспроизведение v1.2.14
показало вторую причину: Worker завершился с кодом 1, потому что тестовый
сценарий не создал Data Cycle run и подготовленный immutable snapshot.
`run_full_refresh` сообщил: «Подготовленный snapshot требует Data Cycle run».
Контейнер удалялся до сохранения безопасной диагностики.

## Результат и критерии

- First-rollout воспроизводит порядок source/canonical → подготовка и
  подтверждение archive sync → Worker, включая durable run и тот же run ID.
- Worker завершается успешно, повторный запуск остаётся идемпотентным;
  обязательные проверки публикации и отсутствия утечки секретов сохраняются.
- При ошибке Worker first-rollout выдаёт безопасную причину и сохраняет
  диагностическую возможность без вывода секретов.
- Адресный red → green тест покрывает отсутствовавшую связь; полный
  first-rollout с immutable образами проходит до публикации нового тега.
- v1.2.13 и v1.2.14 остаются неизменными и не служат основанием deployment;
  исправление выпускается отдельным тегом v1.2.15.

## Evidence

Точное локальное воспроизведение построено из пяти OCI artifacts run
`36925157393`; секретные значения проверены локальной функцией redaction
перед чтением лога. Production остаётся v1.2.12, оба NHL timer выключены.
Итог Developer, review и CI фиксируются в
[отчёте](../../changes/done/TASK-025-36-first-rollout-source-first-lifecycle.md).

Независимый Reviewer не выявил P0–P2 findings после проверки порядка стадий,
executor fencing, Docker mounts, redaction, идемпотентности и release
контракта. Локальный Docker gate прошёл на v1.2.14 OCI с обновлённым host
runner; exact v1.2.15 tag CI остаётся обязательным перед production.
