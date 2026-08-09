# EPIC-002 — NHL production MVP

> **Статус:** done
> **Приоритет:** high
> **Владелец:** главный агент
> **Требование:** [REQ-002](../product/requirements/REQ-002-nhl-production-mvp.md)
> **ADR:** [ADR-002](../architecture/adr/ADR-002-nhl-telegram-notification-orchestration.md)

## Цель и границы

Реализовать подтверждённый NHL MVP через турнир-нейтральный конфигурационный
контур: ежедневный refresh в 10:00 МСК, полный
контроль расписания и результатов, начальный Telegram-digest всем получателям и
15-минутные агрегированные обновления коэффициентов. API сохраняется техническим
внутренним интерфейсом бота; deployment, Grafana и уведомления об окончательном
отсутствии линий не входят в эпик. NHL — первый notification-профиль; значения
его сценария не должны быть зашиты в Python или DAG-код.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-002-1](tasks/TASK-002-1-nhl-quality-gate.md) | NHL gate полноты расписания и результатов | — | unit + integration gate tests | done |
| [TASK-002-2](tasks/TASK-002-2-nhl-notification-state.md) | Персистентный контракт дельт и доставок Telegram | — | unit + DB integration tests | done |
| [TASK-002-3](tasks/TASK-002-3-nhl-morning-digest.md) | Refresh в 10:00 МСК, initial fan-out и admin failure notify | TASK-002-1, TASK-002-2 | DAG + contract tests | done |
| [TASK-002-4](tasks/TASK-002-4-nhl-odds-poll.md) | 15-минутный poll и агрегированные delta-digest | TASK-002-2, TASK-002-3 | DAG + delta/delivery tests | done |

## Риски и rollout

- Вызов Telegram нельзя сделать строго exactly-once на границе HTTP/БД; принят
  best-effort ledger из ADR-002.
- Новые таблицы требуют проверки создания в уже работающей PostgreSQL БД до
  production; rollout не выполняется в рамках эпика без отдельного разрешения.
- Rollback: отключить DAG poll и feature flag уведомлений; утренний heavy refresh
  остаётся доступным без удаления данных notification ledger.
