# EPIC-003 — Масштабируемая мультиспортивная платформа

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** главный агент
> **Требование:** [REQ-003](../product/requirements/REQ-003-scalable-multisport-platform.md)
> **ADR:** [ADR-003](../architecture/adr/ADR-003-configured-multisport-portfolio.md)

## Цель и границы

Реализовать принятый конфигурационный контур, в котором типовой турнир
подключается ML-инженером, а границы `sport`, `tournament`, `model_pool` и
`market/spec` не смешиваются. Первый прикладной маршрут — футбольные winner,
затем total; статистические и player-рынки следуют после них. NHL можно
мигрировать, но его одобренные артефакты должны остаться загрузимыми и
воспроизводимыми.

Эпик не включает подключение конкретного футбольного провайдера, deployment,
поиск составов или одновременную реализацию всех будущих рынков. Эти работы
начинаются только с отдельного подтверждённого scope и данных.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-003-1](tasks/TASK-003-1-portfolio-catalog.md) | Валидируемый каталог портфеля и документация его контракта | — | unit config contract | done |
| [TASK-003-2](tasks/TASK-003-2-model-pool-training.md) | Pooled training и отчёт кандидата для футбольского winner | TASK-003-1 | unit + integration training contract | done |
| [TASK-003-3](tasks/TASK-003-3-model-provenance-promotion.md) | Model identity, ручной promotion и legacy NHL manifest | TASK-003-1, TASK-003-2 | DB/model-registry contract | done |
| [TASK-003-4](tasks/TASK-003-4-portfolio-orchestration.md) | Конфигурационный heavy fan-out без статических списков | TASK-003-1, TASK-003-3 | DAG/command integration tests | done |
| [TASK-003-5](tasks/TASK-003-5-lineup-fast-path.md) | Минутный fast path составов с версионированием и надёжной доставкой | TASK-003-3, TASK-003-4 | DB + idempotency integration tests | done |
| [TASK-003-6](tasks/TASK-003-6-special-and-player-markets.md) | Расширяемый контракт статистических и player-рынков | Футбольские winner и total одобрены | market contract tests | backlog |

## Риски и rollout

- Начинать с каталога и его валидатора: это даёт проверяемую точку остановки до
  миграции путей, БД и DAG.
- Миграции БД только аддитивны; legacy NHL pointer и артефакты не удаляются.
- Переключение production pointer остаётся ручным. Rollback — возврат на
  прежний immutable manifest, без переобучения и удаления данных.
- Параллельность включается только после измерения нагрузки источников и
  успешных изоляционных тестов; глобальный lock не снимается заранее.
