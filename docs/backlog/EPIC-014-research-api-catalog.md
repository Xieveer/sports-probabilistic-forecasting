# EPIC-014 — Проверяемый каталог спортивных API для Research Mode

> **Статус:** blocked
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
| [TASK-014-2](tasks/TASK-014-2-nhl-api-catalog.md) | Полная verified NHL Web API card и dictionary | TASK-014-1 | contract validation + source review | blocked |
| [TASK-014-3](tasks/TASK-014-3-smart-tables-api-catalog.md) | Полная verified Smart Tables card и dictionary | TASK-014-1 | contract validation + source review | blocked |

## Риски и rollout

Каталог не подключён к сервису, поэтому rollout не требуется. Внешние неофициальные API могут
менять схему; риск снижают `last_verified`, уровень evidence и повторная верификация, но не
исключают. Откат — удалить новые complete-card из workspace, сохранив legacy `partial` cards.

## Полное EPIC review

Для закрытия эпика не выполнен подтверждённый пользователем критерий предметного смысла
каждого поля. Независимый reviewer отдельно проверяет подготовленные исправления контракта,
карточек и документации; его review не заменяет недостающего доказательства семантики.

Промежуточное независимое review 2026-10-11 обнаружило P1 в преждевременной
предматчевой классификации Smart Tables match-center и два P2 в роли ключа и
сводке документации. После исправления всех 261 записей reviewer повторно
проверил контракт v1/v2, карточки, словари и статусы: новых P0–P2 нет;
44 теста каталога прошли, `git diff --check` прошёл. Итоговое review EPIC
после снятия предметного блокера остаётся обязательным. Hash проверенного
коммита и PR/CI evidence добавляются отдельно.

## Память Product Owner

- Инициатива: `initiative/epic-014-research-api-catalog`; workflow —
  исследование источников и локальный engineering-контракт, без релиза и
  подключения к рабочему циклу приложения.
- Цель: понять доступные семейства данных NHL и Smart Tables, их происхождение,
  ограничения и допустимое время применения для будущих гипотез и моделей.
  Критерии закреплены в [REQ-014](../product/requirements/REQ-014-research-api-catalog.md).
- Текущий gate: владелец 2026-10-11 подтвердил, что для закрытия нужен
  предметный смысл каждого поля. После доступной публичной разведки четыре
  NHL field records имеют `usage=unknown`. У Smart Tables все 261 поля
  match-center и одно поле `match-card` имеют `usage=unknown`:
  23 описания match-center остаются непрозрачными, 238 являются явно
  помеченными интерпретациями, а не подтверждённым контрактом поставщика.
  Дальнейшая проверка заблокирована недостатком доказательств.
- Evidence: [NHL-карточка](../research/catalogs/nhl-web-api.json),
  [Smart Tables-карточка](../research/catalogs/smart-tables-football-api.json),
  [NHL-словарь](../research/nhl-web-api-catalog.md),
  [Smart Tables-словарь](../research/smart-tables-football-api-catalog.md).
- Предыдущая роль: независимый Reviewer — повторное review исправлений без
  P0–P2. Следующая роль: Product Owner ожидает дополнительных данных
  источников, после которых Data Researcher возобновит семантическую проверку
  и Reviewer выполнит итоговое review EPIC.
- Проверки текущего diff: 54 теста двух затронутых suites прошли, Ruff и
  `git diff --check` прошли; `make docs` собрал документацию с 1 предупреждением. Reviewer gate
  для подготовленных исправлений пройден; PR и terminal CI ещё не выполнены.
- Ограничения: пять NHL GET 2026-10-11 вернули 200, но не проверяли всю схему;
  Smart Tables GET завершился тайм-аутом без ответа. Регулярный сбор или
  использование в модели требует отдельного решения и проверки доступа/as-of.
- Обновлено: 2026-10-11.
