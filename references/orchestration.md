# Оркестрация ролей

## Основное правило

Роль не вызывает другую роль. Композицией управляет основной агент или пользователь. Skill
описывает процесс, роль — точку зрения и формат отчёта.

## Последовательный цикл

Использовать для зависимых этапов:

```text
product-analyst
→ architect/test-designer
→ implementer
→ reviewer
→ documentation-writer/devops-reviewer
```

Следующий этап получает подтверждённый артефакт предыдущего.

## Параллельная проверка

Допустима только для независимых read-only отчётов по одному diff:

```text
reviewer ───────────┐
security-reviewer ──┼→ основной агент → единый go/no-go
test-designer ──────┘
```

Не параллелить изменения одних файлов, зависимые решения и работу с общей mutable state.

## Запрещённые схемы

- роль-маршрутизатор без предметной ответственности;
- роль вызывает роль и пересказывает результат;
- несколько implementers меняют одну область;
- параллельный review без единого merge этапа;
- persona используется вместо подходящего skill.

## Opt-in Research Loop

Research Orchestrator — исключение только в том смысле, что это детерминированный код, а не
роль: он сам вызывает `research-scientist`, `data-researcher` и `research-evaluator` согласно
state machine. Эти роли по-прежнему не вызывают друг друга. При необходимости изменений
orchestrator создаёт `EngineeringRequest`; его исполнение принадлежит существующей цепочке
`architect → test-designer → implementer → reviewer`, а research experiment ждёт verified TASK.

Контекст role call должен быть восстановимым `ContextPackage`, не историей чата. См.
[`docs/research/research-mode.md`](../docs/research/research-mode.md).
