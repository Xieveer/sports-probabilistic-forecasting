# TASK-014-3 — Каталог Smart Tables API

> **Статус:** done
> **Задача:** [TASK-014-3](../../backlog/tasks/TASK-014-3-smart-tables-api-catalog.md)
> **Эпик:** [EPIC-014](../../backlog/EPIC-014-research-api-catalog.md)

## Результат

- Созданы [машиночитаемая карточка](../../research/catalogs/smart-tables-football-api.json)
  и [словарь полей](../../research/smart-tables-football-api-catalog.md): 36 endpoints,
  включая 7 с наблюдённой схемой, 28 `unobserved` и один `denied`; 367 field records.
- Для `match-center/{id}` сохранены 261 path/type records без сырого ответа.
  У всех 261 и одного поля `match-card` назначение `unknown`. Для 238 полей
  толкование выведено из имени и локальной разведки, 23 остаются непрозрачными.
  Эти записи не разрешены для модели без проверки смысла и времени доступности.
- Read-only GET 2026-10-11 завершился тайм-аутом без ответа; ограничение доступа
  и полноты явно отмечено.

## Проверка и решение

- `uv run pytest tests/test_research_api_catalog.py tests/test_research_orchestrator.py -q`:
  54 теста прошли; Ruff и `git diff --check` прошли; `make docs` завершился с
  одним предупреждением. Проверенный diff: `f262145e8e2f558b56d88681b00e2b7b0e11bcfe`.
- Независимое review после исправлений не нашло P0–P2. Итоговый review и CI
  всего EPIC фиксируются в [EPIC-014](../../backlog/EPIC-014-research-api-catalog.md).
- Владелец 2026-10-11 принял исследовательский каталог с явными `unknown`
  и разрешил завершить инициативу. Интерпретации не являются подтверждённым
  контрактом поставщика.

## Неизменённое и остаточный риск

Ingest, обучение, production API и расписание сбора не менялись. У источника
остаются ограничения доступа и использования; исследование не разрешает
массовый сбор или обход ограничений.
