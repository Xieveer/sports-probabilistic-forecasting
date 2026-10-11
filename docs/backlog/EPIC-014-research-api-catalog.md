# EPIC-014 — Проверяемый каталог спортивных API для Research Mode

> **Статус:** done
> **Приоритет:** high
> **Владелец:** главный агент
> **Требование:** [REQ-014](../product/requirements/REQ-014-research-api-catalog.md)
> **ADR:** [ADR-014](../architecture/adr/ADR-014-versioned-api-catalog-contract.md)

## Цель и границы

Сделать Data Source Catalog пригодным для науки: structured endpoint/field contract и две
проверенные карточки полного публично наблюдаемого API — Smart Tables football и NHL Web API.
Ingest, production-интеграция и обход ограничений не входят.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-014-1](tasks/TASK-014-1-api-catalog-contract.md) | Typed endpoint/field contract, validation и документация формата | ADR-014 | unit tests + docs | done |
| [TASK-014-2](tasks/TASK-014-2-nhl-api-catalog.md) | NHL Web API card и dictionary с отмеченными неизвестными полями | TASK-014-1 | contract validation + source review | done |
| [TASK-014-3](tasks/TASK-014-3-smart-tables-api-catalog.md) | Smart Tables card и dictionary с отмеченными неизвестными полями | TASK-014-1 | contract validation + source review | done |

## Риски и rollout

Каталог не подключён к сервису, поэтому rollout не требуется. Внешние неофициальные API могут
менять схему; риск снижают `last_verified`, уровень evidence и повторная верификация, но не
исключают. Откат — удалить новые complete-card из workspace, сохранив legacy `partial` cards.

## Полное EPIC review

Владелец 2026-10-11 принял исследовательский результат с явно отмеченной
неизвестной семантикой полей и разрешил закрытие и интеграцию. Неизвестные и
интерпретированные поля не становятся подтверждённым контрактом поставщика;
перед моделированием требуется отдельная проверка.

Промежуточное независимое review 2026-10-11 обнаружило P1 в преждевременной
предматчевой классификации Smart Tables match-center и два P2 в роли ключа и
сводке документации. После исправления всех 261 записей reviewer повторно
проверил контракт v1/v2, карточки, словари и статусы: новых P0–P2 нет;
44 теста каталога прошли, `git diff --check` прошёл. Проверенный diff зафиксирован
коммитом `f262145e8e2f558b56d88681b00e2b7b0e11bcfe`; pre-commit hooks (включая Ruff,
mypy и AI validation) прошли.
Итоговое независимое review EPIC 2026-10-11 сверило [REQ-014](../product/requirements/REQ-014-research-api-catalog.md),
ADR-014, все три TASK и отчёты `done`, контракт, обе карточки и словари,
тесты, границы ingest и release evidence. P0–P2 не обнаружены. Повторно
прошли 54 целевых теста и `git diff --check`; количество endpoint/field records
и `unknown` совпадает с отчётами. Неподтверждённая семантика и ограниченный
доступ к источникам остаются явно записанными рисками. На окончательном HEAD
`995766329ce2a0b0b20f3b9f3e1ac3f124384f02` все три проверки
[PR #72](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/72)
завершились успешно; PR слит в `main` 2026-10-11 коммитом
`54c281d35bd47cc9e197f197035c59d4386039ba`.
Проверенный итоговый diff зафиксирован коммитом
`add9c4ed97d127f4753d6fa9e51405a657161d5c`.

## Память Product Owner

- Инициатива: `initiative/epic-014-research-api-catalog`; workflow —
  исследование источников и локальный engineering-контракт, без релиза и
  подключения к рабочему циклу приложения.
- Цель: понять доступные семейства данных NHL и Smart Tables, их происхождение,
  ограничения и допустимое время применения для будущих гипотез и моделей.
  Критерии закреплены в [REQ-014](../product/requirements/REQ-014-research-api-catalog.md).
- Решение: владелец 2026-10-11 принял каталог с явными неизвестными полями
  и разрешил закрыть EPIC и слить PR в `main`. После доступной разведки четыре
  NHL field records имеют `usage=unknown`. У Smart Tables все 261 поля
  match-center и одно поле `match-card` имеют `usage=unknown`:
  23 описания match-center остаются непрозрачными, 238 являются явно
  помеченными интерпретациями, а не подтверждённым контрактом поставщика.
  Проверка их смысла остаётся отдельной будущей задачей при появлении доказательств;
  эти поля не разрешены для признаков или меток модели.
- Evidence: [NHL-карточка](../research/catalogs/nhl-web-api.json),
  [Smart Tables-карточка](../research/catalogs/smart-tables-football-api.json),
  [NHL-словарь](../research/nhl-web-api-catalog.md),
  [Smart Tables-словарь](../research/smart-tables-football-api-catalog.md).
- Предыдущая роль: независимый Reviewer — итоговое review EPIC без P0–P2;
  Product Owner проверил terminal CI и интегрировал PR. Следующий шаг —
  зафиксировать эту запись и удалить чистый временный worktree.
- Проверки текущего diff: 54 теста двух затронутых suites прошли, Ruff и
  `git diff --check` прошли; `make docs` собрал документацию с 1 предупреждением.
  Reviewer gate для подготовленных исправлений пройден. Проверенный коммит
  `f262145e8e2f558b56d88681b00e2b7b0e11bcfe`, evidence-коммит
  `b2d33a876438f749ac1c98e214dd86a4a0c8fbc1`.
- [PR #72](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/72)
  слит в `main` после успешных `lint-test (3.12)`, `Python dependencies` и
  `Filesystem and secrets` на окончательном HEAD. Merge commit: `54c281d35bd47cc9e197f197035c59d4386039ba`.
- Проверенный closure diff зафиксирован коммитом
  `137178872309c5ed161d75a02da49a060d3b990b`.
- Ограничения: пять NHL GET 2026-10-11 вернули 200, но не проверяли всю схему;
  Smart Tables GET завершился тайм-аутом без ответа. Регулярный сбор или
  использование в модели требует отдельного решения и проверки доступа/as-of.
- Обновлено: 2026-10-11.
