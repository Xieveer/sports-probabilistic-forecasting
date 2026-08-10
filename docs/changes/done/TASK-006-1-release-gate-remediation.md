# TASK-006-1 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-10
> **Задача:** [TASK-006-1](../../backlog/tasks/TASK-006-1-release-gate-remediation.md)

## Реализованный результат

Production runtime dependency boundary отделён от local training/control plane:
DVC, DVC S3, MLflow и Optuna исключены из runtime images. Locked runtime
dependencies обновлены, а Docker workflow нормализует GHCR image name в
lowercase, поэтому Trivy корректно сканирует опубликованные образы.

Docker workflow [#31382689135](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/31382689135)
успешно выполнил gates, build/push, Trivy image scan, provenance и publication
evidence для API, Worker и Telegram bot. Все image scans показали 0 HIGH/CRITICAL
findings.

## Immutable candidate

| Компонент | Immutable image |
|---|---|
| API | `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:b6054d35896e500866f902324f3e3aef1758cfcb2fe79b8925ff3e5740a7a8ad` |
| Worker | `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:df985fb62974b7ebfe5f0c1f48788e3daae1f88f0b96d517ed408911a8837b9b` |
| Telegram bot | `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:2f1db660b29e4972935a99d30dea088e14c9a6db3cf996416c851482e1bfdf58` |

## Фактически выполненные проверки

| Проверка | Результат |
|---|---|
| Local `make security` | `No known vulnerabilities found`. |
| Local `make test-unit` | 848 passed, 8 deselected. |
| Local `make production-check` | `Production handoff is valid.` |
| GitHub Docker Release gates | Успешно: lint, unit tests, dependency audit, filesystem/secret scan. |
| GitHub build-push | Успешно для API, Worker и Telegram bot: build/push, Trivy scan, provenance, evidence. |

## Не выполнено и handoff

VPS rollout, production DB migration/readiness, external Telegram/API
connectivity и сообщение владельцу не выполнялись. Они остаются в
[TASK-006-3](../../backlog/tasks/TASK-006-3-authorized-rollout-and-first-delivery.md)
и требуют отдельного разрешения владельца.
