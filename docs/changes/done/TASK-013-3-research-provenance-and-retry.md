# TASK-013-3 — отчёт о provenance и retry structured contracts

> **Статус задачи:** done
> **Дата:** 2026-08-24
> **Задача:** [TASK-013-3](../../backlog/tasks/TASK-013-3-research-provenance-and-retry.md)

## Реализованный результат

`ContextPackage` и `ResearchState` теперь имеют `schema_version` и UTC `as_of`; package также
получает deterministic `package_id`. `DataResearchFinding` и `ResearchFinding` содержат
`ArtifactProvenance` с ролью, package id и временной точкой. Добавлен
`ValidatedRoleGateway`: он получает raw JSON от изолированного invoker, валидирует Pydantic
contract, один раз передаёт validation feedback и поднимает исходную validation error после
исчерпания попыток. Orchestrator при этом переводит run в `FAILED`, не создавая hypothesis и
не переходя к data research.

Повторный actual pilot подтвердил, что Scientist исправил оба первоначальных type mismatch по
явному feedback. Data Researcher дважды вернул неполную/несовместимую карточку источника;
это ожидаемо завершится validation error, а не попадёт в memory. Следовательно retry path
явно fail-safe. Production-quality prompt/schema transport не реализуется: соответствующий
scope TASK-013-4 отменён пользователем.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/research/contracts.py` | Версия, as-of и provenance typed contracts |
| `sports_forecast/research/adapters.py` | Raw isolated JSON → validated retry gateway |
| `sports_forecast/research/orchestrator.py` | Timestamped package/finding provenance |
| `tests/test_research_orchestrator.py` | invalid-then-valid retry и exhausted retry gate |
| `docs/research/`, `ADR-013`, `EPIC-013` | Поведение и фактическое evidence |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_research_orchestrator.py -q` — отсутствовал
  `sports_forecast.research.adapters`; после contracts refactor тест также фиксировал
  неструктурированные data findings как validation error.
- **Green:** `uv run pytest tests/test_research_orchestrator.py -q` — 5 passed.
- **Refactor:** один generic `ValidatedRoleGateway` обслуживает Scientist, Data Researcher и
  Evaluator без копирования retry logic.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest tests/test_research_orchestrator.py -q` | 5 passed |
| `uv run ruff check sports_forecast/research tests/test_research_orchestrator.py` | успешно |
| `uv run pre-commit run mypy --files …` | Passed |
| Repeated isolated Scientist retry (`fork_turns=none`) | исправил string/list и string/bool mismatches |
| Repeated isolated Data Researcher retry (`fork_turns=none`) | обе попытки не соответствуют strict `DataSourceRecord`/`DataResearchFinding`; fail-safe validation требуется |

## Документация, review и follow-up

- Документация: [Research Mode](../../research/research-mode.md),
  [ADR-013](../../architecture/adr/ADR-013-research-mode-state-machine.md).
- Review / security: независимый reviewer нашёл P1/P1/P2/P2; исправлены fail-closed gates
  обязательных metrics и Engineering receipt, sanitation external payload и cancellation scope.
  Повторный review нашёл P1 на stale ExperimentResult; добавлена fail-closed проверка
  `experiment_id` и `temporal_validation`. Финальный review: P0/P1/P2 findings нет.
- Commit/push: проверенный commit `889147f447eda37ee713d7ab893f494418be8cf3`; hash фиксируется отдельным
  documentation-only evidence-коммитом reviewer.
- Follow-up: TASK-013-4 `cancelled` пользователем 2026-08-24: runtime/API adapter и durable
  multi-process storage не реализуются.

## Остаточные риски

- Concrete Codex invoker всё ещё не существует: текущий adapter определяет contract и retry,
  но не вызывает platform runtime сам.
- Retry feedback повышает шанс корректного JSON, но не является гарантией; external model
  может исчерпать budget, как показал Data Researcher pilot.
- Current JSON workspace остаётся single-writer local storage.

## Независимый review

Reviewer повторно воспроизвёл исправленные негативные сценарии и проследил переходы до
persistence/evaluation. Invalid structured payload не раскрывается в state/logs, обязательные
robustness metrics не допускают ложный `PASS`, чужие EngineeringReceipt и ExperimentResult не
открывают следующий этап. Финальный результат: P0/P1/P2 findings отсутствуют. Выполнены
`make test` (935 passed), целевой mypy hook (Passed), `make lint`, `make ai-validate`,
`make docs` и `git diff --check` (успешно; один существующий Sphinx warning о `_static`).
