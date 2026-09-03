# Research Mode v1

Research Mode — явный opt-in контур для цели, способ достижения которой ещё неизвестен.
Он не заменяет Engineering Workflow: запрос на определённое изменение системы остаётся
Engineering Mode и идёт через существующие REQ → ADR → EPIC/TASK → TDD → review.

## Явный запуск и состояние

В v1 запуск — создание `GoalContract` и вызов `ResearchOrchestrator.start(goal)`. Контракт
задаёт scientific/business objective, target, horizon, market, odds source, allowed timestamp,
development/validation/locked-holdout periods, prediction/economic/robustness criteria и
experiment/compute/API budgets. Нет автоматической LLM-классификации: вызов orchestrator —
явный выбор Research Mode.

`ResearchRepository` сохраняет `runs/<run_id>/state.json`, а каталог источников —
`data-sources/<source_id>.json` в переданном workspace. Workspace выбирает оператор; он не
является сервисной БД и не коммитится по умолчанию. Следующий вызов создаёт новый orchestrator
и восстанавливает run только из durable state. Для глубоко исследованного API карточка имеет
`catalog_completeness="complete"`: endpoint и field-level contract с JSON path, типом,
семантикой, доступностью во времени и evidence. Краткая legacy-card (`partial`) не считается
доказательством схемы и не должна быть основанием для реализации или научной гипотезы без
повторной Data Researcher-проверки.

## State machine

```text
SCIENTIST → DATA_RESEARCH? → ENGINEERING? → EXPERIMENT → EVALUATION
    ↑                                                     │
    └──────────────────── FAIL / next iteration ─────────┘

EVALUATION PASS → SUCCESS
budget exhausted → EXHAUSTED
external decision / data unavailable → BLOCKED
unexpected orchestrator error → FAILED
```

`advance(run_id)` выполняет ровно один переход и сначала валидирует ответ Pydantic contract.
`WAITING_ENGINEERING` не позволяет запустить experiment: only `EngineeringReceipt(status=verified,
task_reference=...)` от gateway существующего workflow открывает переход.

## Контракты и минимальный context

Канонические схемы находятся в `sports_forecast.research.contracts`: `GoalContract`,
`HypothesisProposal`, `DataRequirement`, `DataResearchResult`, `ExperimentSpec`,
`EngineeringRequest`, `ExperimentResult`, `EvaluationResult`, `ResearchFinding` и
`HumanDecisionRequest`. `ContextPackage` получает только Goal, serializable state, active
hypothesis, последние findings, source IDs и текущую задачу. Он не получает историю чата или
полные raw responses.

`ResearchMemory` хранит evaluator findings, data-research findings, source references и факт раскрытия locked holdout. Harness
помечает повторный просмотр уже раскрытого locked holdout `INVALID`; Scientist не получает
его результаты как материал для очередной оптимизации.

## Роли и границы

`research-scientist` формирует гипотезу и information gain; `data-researcher` описывает
легально доступный источник; `research-evaluator` интерпретирует готовое решение. Каждая роль
получает изолируемый package и не вызывает следующую роль. Orchestrator — обычный код, который
вызывает adapter текущего state.

При потребности в коде или pipeline data-researcher/scientist возвращает `EngineeringRequest`.
Gateway обязан создать обычную REQ/TASK в existing Engineering Workflow и вернуть verified
receipt только после его доказательств. Research Mode не имеет implementer/reviewer-дублей.
Operations Agent также вне Research Loop: возможная передача candidate в deployment относится к
future scope и требует отдельной авторизации.

## Evaluation Harness

v1 детерминированно проверяет temporal validation, baseline LogLoss, целевой LogLoss, ROI,
число ставок и, когда заданы в Goal Contract, max drawdown, bootstrap lower bound и
concentration. `ExperimentResult` уже переносит Brier/calibration, bootstrap interval,
stability по сезонам/турнирам, threshold/odds sensitivity и CLV; их полный расчёт и policy
gate — следующий bounded scope. Все такие метрики вычисляет код; LLM добавляет только научную
интерпретацию.

Если Goal Contract требует bootstrap lower bound или concentration, а runner не вернул эту
метрику, Harness возвращает `INVALID`, а не `PASS`. Аналогично Engineering boundary принимает
`verified` receipt только при совпадении его `request_id` с активным `EngineeringRequest`.
Validation feedback и failure state содержат только безопасные имена полей/тип ошибки: raw
внешний payload не записывается в logs или JSON memory.

Перед сохранением raw experiment runner обязан вернуть тот же `experiment_id` и значение
`temporal_validation`, что указаны в active `ExperimentSpec`. Несовпадение считается `FAILED`
до добавления result в memory и до вызова evaluator.

## Context isolation audit

Профили `.codex/agents/` фактически задают model, reasoning effort, sandbox и лимит потоков,
но не содержат контракт inheritance/return размера context. Официальная документация OpenAI
описывает multi-agent API как beta, однако не определяет семантику локальных custom-agent calls
этого репозитория. В pilot TASK-013-2 три текущих agent calls с `fork_turns=none` получили
разные JSON packages и выполнили последовательный handoff; их complete outputs вернулись
родительской сессии. Это подтверждает практическую дисциплину package, но не внутреннюю
гарантию privacy/isolation и не Python adapter.

Pilot также показал, что package нужно расширить `schema_version`, `as_of` и provenance для
findings, а agent adapter — retry после Pydantic validation failure; это реализовано в
TASK-013-3 через `ValidatedRoleGateway`. Gateway принимает только raw JSON, валидирует contract
до перехода и передаёт один retry feedback. Исчерпание retry — `FAILED`, а не неявный переход.
Повторный Scientist pilot исправил type mismatch; Data Researcher исчерпал retry на полном
catalog contract, что подтверждает fail-safe свойство, но не достаточность prompt-only schema
transport. Runtime/API adapter обязан рассматривать вызов как уничтожаемую изолированную сессию
и передавать лишь `ContextPackage`.
