# EPIC-023 — Пилот агентского цикла: расписание NHL в Telegram

> **Статус:** in_progress
> **Приоритет:** high
> **Владелец:** главный агент
> **Требование:** [REQ-023](../product/requirements/REQ-023-nhl-schedule-agent-pilot.md)
> **ADR:** [ADR-023](../architecture/adr/ADR-023-minimal-agent-pilot-with-operations-agent.md)

## Цель и границы

Доказать одним принятым вертикальным срезом, что полезное изменение Telegram-бота
может пройти обычный инженерный цикл до ограниченного production-deploy и rollback
через `operations-agent`. Функция: выбор NHL, ввод горизонта `0–30`, расписание матчей
по датам МСК с существующими прогнозом, коэффициентами и value.

EPIC не включает Research, session memory, registry/lease, signed workflow packages,
новый CI gate, изменение прогнозной логики или расширение Telegram UX вне этого
сценария. Production acceptance пользователя остаётся ручной; агент не отправляет
пользовательский запрос production-боту.

### Предшествующий rollback EPIC-022

До перевода TASK-023-1 в `in_progress` главный агент в отдельном обратимом шаге
возвращает рабочее дерево к текущему принятому `HEAD` `a28af79`: удаляет только
незакоммиченные артефакты и изменения EPIC-022, перечисленные в плане TASK, и сохраняет
подтверждённые Git-изменения и независимые пользовательские изменения. Проверка:
`git diff`, `git status --short`, targeted search по `workflow`/`REQ-022` и
`git diff --check`. Никакой Git history не переписывается.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
|---|---|---|---|---|
| [TASK-023-1](tasks/TASK-023-1-nhl-schedule-agent-pilot.md) | Расписание NHL в Telegram и полный ограниченный delivery path | rollback EPIC-022, ADR-023, read-only discovery Operations Agent | tests/lint/CI, browser e2e test bot, limited deploy, health/logs либо rollback | in_progress |
| [TASK-023-2](tasks/TASK-023-2-ewm-optional-metric-contract.md) | Согласованный baseline optional EWM-метрики | существующий runtime-контракт | targeted test, полный test suite, независимый review | done (`8a30825`) |

## Риски и rollout

- До изменения production `operations-agent` проверяет фактические host/runtime,
  rollback target, разрешённый immutable deploy entrypoint, health/log checks и
  расхождения своего service passport. При расхождении останавливается и выносит
  точный blocker, не меняя сервер.
- Deploy начинается лишь с exact accepted commit, успешных полного test/lint набора,
  Git CI и browser e2e test bot. Секреты и production tokens остаются server-side.
- Неуспех technical health-check запускает автоматический rollback и возвращает TASK
  в `in_progress` или `blocked` с диагностикой; не создаёт отчёт `done`.
- Go: без нового bootstrap/recovery исключения, следующий агент продолжает только по
  артефактам, commit принят, а ручная цена приемлема владельцу. Stop/replan: новый
  вид bootstrap/recovery, невозможность связать clean worktree/commit/release evidence,
  отсутствие принятой TASK либо неприемлемая ручная стоимость.

## Полное EPIC review

Заполняет независимый reviewer после terminal TASK-023-1: покрытие REQ-023/ADR-023,
результаты browser/prod checks, rollback evidence, актуальность документов Operations
Agent, незавершённый scope и hash проверенного commit. До этого EPIC не получает статус
`done`.
