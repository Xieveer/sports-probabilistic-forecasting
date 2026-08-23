# ADR-013 — Изолированный Research Loop поверх Engineering Workflow

> **Статус:** accepted
> **Дата:** 2026-08-23
> **Связанное требование:** [REQ-013](../../product/requirements/REQ-013-research-mode.md)

## Контекст и критерии выбора

Проект уже имеет зрелый Engineering Workflow, в котором роли не вызывают друг друга. Для
длительного поиска в условиях неопределённости нужен повторяемый Research Loop, но нельзя
полагаться на память LLM, создавать вторую engineering-команду или менять service runtime.
Решение должно переживать потерю любого agent context, блокировать experiment до verified
Engineering TASK и хранить результаты, релевантные следующей гипотезе.

## Рассмотренные варианты

1. **Status quo:** описывать цикл Markdown-инструкцией главному агенту. Переходы и память
   зависят от чата, поэтому вариант не удовлетворяет требованию восстановления.
2. **Вариант A:** отдельный Research Orchestrator со state machine, Pydantic contracts,
   файловым run ledger и адаптерами изолированных ролей.
3. **Вариант B:** новый постоянный сервис/очередь с БД и встроенным LLM runner. Подходит для
   будущей эксплуатации, но добавляет инфраструктуру до доказательства минимального цикла.

## Решение

Принят вариант A. `sports_forecast.research` является opt-in библиотечным контуром вне API.
Он сохраняет `GoalContract`, `ResearchState`, findings и catalog в workspace run, строит
минимальные `ContextPackage` и вызывает внешние role adapters строго по текущему состоянию.
Каждый ответ валидируется Pydantic до перехода. Значение `PASS` / `FAIL` / `INVALID` получает
только детерминированный `EvaluationHarness`; LLM-evaluator дополняет finding интерпретацией.

`EngineeringRequest` — граница, а не альтернативный workflow: gateway возвращает ссылку на
обычную TASK и `verified` только после её существующего полного процесса. До этого run ждёт.
Data source metadata хранится отдельно от transient tool output. Locked holdout отмечается
как раскрытый и блокирует повторное доказательство успеха.

## Последствия

- Положительные: явный opt-in, воспроизводимые handoff, testable transitions, no service impact
  и отсутствует зависимость от непроверенной context isolation Codex.
- Отрицательные и стоимость: v1 требует adapter implementation для реального LLM, runner и
  durable production storage; JSON ledger не является multi-process database.
- Безопасность и эксплуатация: data-researcher документирует только законно доступные публичные
  источники; credentials, обход ограничений и raw responses не сохраняются. Operations Agent
  не участвует в research control loop.

## Проверка и пересмотр

Unit-тест с заново созданным orchestrator после каждого шага должен пройти две итерации и
закончиться `SUCCESS`. Решение пересматривается при появлении подтверждённого Codex context
contract либо при требованиях concurrent/multi-day runs: тогда файловый ledger заменяется
транзакционным хранилищем без изменения contracts.

TASK-013-2 подтвердил на текущем launcher раздельные calls с `fork_turns=none`, но также
выявил необходимость schema/as-of/provenance и retry после strict validation. Эти изменения
реализованы TASK-013-3; повторный pilot показал корректный retry Scientist и safe rejection
неполного DataResearchResult. Pilot не считается доказательством API-level isolation.

## Источники и неизвестное

- [REQ-013](../../product/requirements/REQ-013-research-mode.md).
- Локальные `.codex/config.toml` и profiles: задают модель, sandbox и max threads, но не
  описывают передачу context.
- [Официальное руководство моделей OpenAI](https://developers.openai.com/api/docs/guides/latest-model):
  описывает multi-agent как beta API-возможность, но не устанавливает семантику текущего
  локального Codex custom-agent runner. Поэтому она считается неизвестной.
