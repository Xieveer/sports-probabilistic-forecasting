# EPIC-004 — Готовность NHL и релиза 1.0.0

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** главный агент
> **Требование:** [REQ-004](../product/requirements/REQ-004-nhl-readiness-and-release-versioning.md)
> **ADR:** [ADR-004](../architecture/adr/ADR-004-release-version-and-odds-api-key-failover.md)

## Цель и границы

Подтвердить NHL-контур в межсезонье и подготовить воспроизводимый production
release `1.0.0`. Эпик вводит единый SemVer-контракт, безопасную последовательность
ключей The Odds API и операционную проверку данных/коэффициентов/расписания.
Он не создаёт реальные ключи, не покупает тарифы, не публикует Git-тег или
Docker-образы и не выполняет deployment.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-004-1](tasks/TASK-004-1-release-version-contract.md) | Единая версия package/API и проверяемый release-tag/image contract | — | unit + workflow/static tests | done |
| [TASK-004-2](tasks/TASK-004-2-odds-api-key-ring.md) | Key-ring free → 20k → 100k с безопасным failover | — | unit tests без сети | done |
| [TASK-004-3](tasks/TASK-004-3-nhl-readiness-command.md) | Воспроизводимая NHL readiness-команда и отчёт статусов | TASK-004-2 | CLI/integration fixtures | done |
| [TASK-004-4](tasks/TASK-004-4-nhl-preproduction-validation.md) | Фактический pre-production NHL run и release handoff `1.0.0` | TASK-004-1, TASK-004-3 | run report + production-check | done |
| [TASK-004-5](tasks/TASK-004-5-mypy-baseline.md) | Восстановить зелёный mypy baseline для безусловного release gate | — | full mypy + targeted tests | done |

## Риски и rollout

- До TASK-004-4 не выполняются Git release, публикация образов или deployment.
- Использование реальных ключей разрешено только в secret environment и только
  для TASK-004-4; в тесты, кэш и отчёт их значения не попадают.
- Rollback key-ring: очистить три новые переменные и временно использовать
  существующий `ODDS_API_KEY`. Rollback версии: не создавать `v1.0.0` до
  прохождения release handoff; published immutable тег не переиспользуется.
- Полный mypy baseline содержит 22 ошибки вне TASK-004-1--004-4. До завершения
  TASK-004-5 решение о выпуске остаётся `CONDITIONAL GO`.
