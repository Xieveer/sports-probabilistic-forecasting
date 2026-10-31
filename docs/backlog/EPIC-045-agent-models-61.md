# EPIC-045 — Обновление Sol для агентов

> **Статус:** done
> **Приоритет:** medium
> **Владелец:** Product Owner
> **Требование:** [REQ-045](../product/requirements/REQ-045-agent-models-61.md)
> **ADR:** не требуется

## Память Product Owner

- Инициатива: `EPIC-045`.
- Ветка инициативы: `initiative/epic-045-agent-models-61`.
- Workflow / этап: `engineering / merge candidate; merge pending`.
- Исходная цель: обновить Sol-профили до 6.1, сохранив Luna и Astra; [REQ-045](../product/requirements/REQ-045-agent-models-61.md).
- Критерии приёмки и DoD: три критерия REQ-045, независимое review, зелёный CI и merge.
- Релиз: не требуется.
- Выполнено: зафиксирована карта моделей; тест валидатора прошёл red → green;
  12 AI-тестов и `make ai-validate` прошли; независимый Reviewer подтвердил TASK
  и полный scope EPIC без блокирующих findings. Все TASK завершены;
  [PR #105](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/105)
  прошёл три проверки CI на `d985aca16dcf8a8d6108ccfd8773476d85350c5f`.
- Решения: Terra не назначается после уточнения владельца; ADR не нужен.
- Артефакты: REQ-045, [TASK-045-1](tasks/TASK-045-1-agent-models-61.md),
  [отчёт `done`](../changes/done/TASK-045-1-agent-models-61.md), PR #105 и CI ниже.
- Предыдущая роль: Reviewer — полное EPIC review и проверка финальной документации.
- Следующая роль: Product Owner — дождаться повторного terminal CI документационного
  коммита и выполнить merge PR #105. Интеграция в `main` ещё не выполнена.
- Открытые вопросы / блокеры: нет.
- Research: не применяется.
- Обновлено: 2026-10-31.

## Цель и границы

Обновить назначение моделей Sol в проектном AI-слое без изменения ролей, процесса и
production-приложения. Исторические артефакты сохраняют состояние своего периода.

## Декомпозиция

| Задача | Результат | Проверка | Статус |
|---|---|---|---|
| [TASK-045-1](tasks/TASK-045-1-agent-models-61.md) | Профили, валидатор и текущая карта моделей | AI tests, `make ai-validate` | done |

## Риски и rollout

Проектные настройки применяются после доверия репозиторию и запуска новой сессии Codex.
Откат — возврат профилей и валидатора в отдельном PR. Production rollout не нужен.

## Полное EPIC review

Независимый Reviewer проверил REQ-045, профили, валидатор, тесты и текущую карту моделей.
Прежний Sol заменён во всех активных назначениях; Luna, Astra, reasoning и sandbox
сохранены. Замечание форматирования теста устранено; блокирующих findings нет.
Проверки: 12 AI-тестов, `make ai-validate`, целевые Ruff check/format и `git diff --check`
прошли. Production-код, секреты и внешние сервисы этим diff не менялись.
Hash проверенного коммита: [`d29a40a3f952675bcc0733988f3af3f4b1054f58`](https://github.com/Xieveer/sports-probabilistic-forecasting/commit/d29a40a3f952675bcc0733988f3af3f4b1054f58).
Этот hash зафиксирован отдельным documentation-only evidence-коммитом
`d985aca16dcf8a8d6108ccfd8773476d85350c5f`.

[PR #105](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/105) на этом
evidence-коммите получил terminal `SUCCESS` по всем трём проверкам:

- [lint-test (3.12)](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/41230165234/job/124622530153);
- [Python dependencies](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/41230165205/job/124622530490);
- [Filesystem and secrets](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/41230165205/job/124622530283).

Reviewer повторно проверил только итоговую документацию; новых findings нет.
Статус `done` фиксирует завершённый scope TASK и готовность кандидата к интеграции;
`merge pending` остаётся явным до повторного зелёного CI текущего документационного
коммита и фактического merge. Новый production-релиз не требуется.
