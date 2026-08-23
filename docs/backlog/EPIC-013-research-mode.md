# EPIC-013 — Opt-in Research Mode v1

> **Статус:** done
> **Приоритет:** high
> **Владелец:** главный агент
> **Требование:** [REQ-013](../product/requirements/REQ-013-research-mode.md)
> **ADR:** [ADR-013](../architecture/adr/ADR-013-research-mode-state-machine.md)

## Цель и границы

Доказать автономный Research Loop, переживающий потерю LLM context и передающий изменения
только в существующий Engineering Workflow. Production service, deployment и реальное
долгое исследование не входят в EPIC.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-013-1](tasks/TASK-013-1-research-loop-vertical-slice.md) | Contracts, state machine, memory, роли, каталог и two-iteration proof | ADR-013 | unit + AI validation + docs | done |
| [TASK-013-2](tasks/TASK-013-2-codex-runtime-isolation-pilot.md) | Pilot фактической изоляции текущего Codex runtime | ADR-013 | три isolated agent calls | done |
| [TASK-013-3](tasks/TASK-013-3-research-provenance-and-retry.md) | Provenance/as-of contracts и retry после strict validation | Evidence TASK-013-2 | unit + повторный isolated pilot | done |
| TASK-013-4 | Реальный programmatic Codex runner и durable multi-process storage | Не требуется: scope отменён пользователем 2026-08-24 | не применимо | cancelled |

## Риски и rollout

Контур opt-in и не импортируется сервисом; rollout не требуется. JSON ledger предназначен для
одного локального run. Concurrent writers и реальный programmatic LLM execution отменены по
решению пользователя 2026-08-24; rollback не требуется, поскольку этот scope не реализовывался.

## Полное EPIC review

Независимый reviewer проверил полный diff EPIC: REQ-013, ADR-013, terminal TASK-013-1…3,
их отчёты, contracts/state machine/storage/adapters/harness, unit- и AI-тесты, роли,
Codex profiles и каноническую документацию Research Mode. Первичные findings о ложном
`PASS`, неверном EngineeringReceipt, раскрытии invalid payload и несинхронизированном scope,
а также повторный finding о stale/cross-run ExperimentResult исправлены через fail-closed
проверки и отрицательные тесты. В финальном review P0/P1/P2 findings нет.

Все критерии REQ-013 покрыты. TASK-013-1…3 имеют статус `done`; TASK-013-4 явно
`cancelled` пользователем 2026-08-24 и не оставляет скрытого future scope. Production service,
deployment, release и реальные внешние данные не менялись, поэтому release evidence и rollout
для EPIC не применимы. Остаточные ограничения v1 — внешний LLM/Codex invoker и single-writer
JSON storage — документированы как non-scope, а не как незавершённые задачи EPIC.

Фактически выполнены: `make test` (935 passed), целевой mypy hook (Passed), `make lint`
(Passed), `make ai-validate` (`AI layer is valid.`), `make docs` (успешно с одним существующим
warning о `_static`) и `git diff --check` (успешно).
Хеш проверенного коммита: `VERIFY_COMMIT_PENDING`.
