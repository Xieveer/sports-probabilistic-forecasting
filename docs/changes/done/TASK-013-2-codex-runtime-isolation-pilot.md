# TASK-013-2 — отчёт о pilot изоляции текущего Codex runtime

> **Статус задачи:** done
> **Дата:** 2026-08-23
> **Задача:** [TASK-013-2](../../backlog/tasks/TASK-013-2-codex-runtime-isolation-pilot.md)

## Реализованный результат

Проведён синтетический технический pilot без сети, ключей, service-кода или реальных
спортивных данных. Три agent calls были запущены по очереди с `fork_turns=none`; каждый получил
свой явно сформированный JSON package. Вызовы вернули результат в родительскую сессию, поэтому
она получила текст ответов, но следующий агент не использовал его напрямую: он получал новый
package, составленный как durable handoff.

Последовательность успешно исполнила Scientist → Data Researcher → Evaluator. Первые два
ответа одновременно выявили пользу strict contracts: Scientist нарушил два типа (`list` вместо
строки и строка вместо `bool`), Data Researcher вернул findings-objects вместо `list[str]`.
Следовательно, текущий orchestrator корректно обязан остановить такой переход до experiment.
Evaluator получил только нормализованный package и сохранил `FAIL`, не заменяя детерминированное
решение рассуждением.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `docs/backlog/tasks/TASK-013-2-codex-runtime-isolation-pilot.md` | Контракт и evidence pilot |
| `docs/changes/done/TASK-013-2-codex-runtime-isolation-pilot.md` | Канонический результат фактических agent calls |
| `docs/research/research-mode.md` | Уточнённый runtime audit и найденные contract gaps |
| `ADR-013`, `EPIC-013` | Зафиксированы границы доказательства и future scope |

## Evidence сессий

| Шаг | Переданный package | Наблюдение |
|---|---|---|
| Scientist | Goal + пустая memory + текущая задача | JSON без Markdown, но `falsification_criteria` вернул как массив, `temporal_validation` как строку; валидатор должен отклонить. |
| Data Researcher | Нормализованная active hypothesis + пустая history | Восстановил смысл задачи и назвал отсутствие `schema_version`, `as_of` и provenance; `findings` вернул объектами вместо строгого v1 `list[str]`. |
| Evaluator | Normalized data findings + deterministic `FAIL` | Вернул валидный JSON narrative; не изменил `FAIL` и не сделал вывода об edge. |

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| Три isolated agent calls с `fork_turns=none` | выполнены последовательно без сети и file edits агентами |
| Визуальная проверка outputs по Pydantic contract | обнаружены два intentionally-safe contract violations до перехода состояния |
| `make ai-validate` | `AI layer is valid.` в финальном review |

## Документация, review и follow-up

- Документация: [Research Mode](../../research/research-mode.md),
  [ADR-013](../../architecture/adr/ADR-013-research-mode-state-machine.md).
- Review / security: независимый финальный review завершён без P0/P1/P2 findings; проверялись
  только synthetic packages, без секретов, сети и external data.
- Commit/push: проверенный commit `889147f447eda37ee713d7ab893f494418be8cf3`; hash фиксируется отдельным
  documentation-only evidence-коммитом reviewer.
- Follow-up: `TASK-013-3` в [EPIC-013](../../backlog/EPIC-013-research-mode.md) для
  `schema_version` / `as_of` / provenance и structured-output retry; programmatic adapter
  отменён пользователем 2026-08-24.

## Остаточные риски

- `fork_turns=none` и раздельные calls доказывают дисциплину переданного package в данном
  pilot, но не являются формальной гарантией внутренней реализации или privacy-свойств Codex.
- Результат возвращается родительской сессии полностью, поэтому она растёт; durable state,
  а не её контекст, должен оставаться источником продолжения.
- Текущий runtime launcher не является Python adapter из `sports_forecast.research` и не
  исполняет custom profile `.codex/agents/research-*.toml` автоматически.

## Независимый review

Reviewer сверил pilot evidence с contracts, ADR-013 и последующим TASK-013-3. Ограничения
изоляции не выданы за API-level гарантию, а programmatic runner явно отменён вместе с
TASK-013-4. Финальный результат: P0/P1/P2 findings отсутствуют. Общие проверки EPIC:
`make test` (935 passed), mypy hook, lint, AI validation, docs и diff check — успешно.
