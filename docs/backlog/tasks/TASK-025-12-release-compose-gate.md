# TASK-025-12 — Исправить Compose gate для Data Cycle

> **Статус:** done — исправление и независимое review завершены; release CI в TASK-025-9
> **Владелец:** Product Owner, Developer, Reviewer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)

## Дефект

Тег `v1.2.0` создан на проверенном merge commit, но
[tag pipeline 36300221666](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36300221666)
остановился до сборки образов: validator production Compose ожидал единственное
поле `DATABASE_URL_FILE` у API и отверг новые secret file paths и aliases.
Профиль dispatcher также не входил в проверяемый rendered Compose. На VPS
изменений не было. Пользователь согласовал новый immutable `v1.2.1`.

## Критерии

- [x] Red: rendered Compose текущего release воспроизводит failure validator.
- [x] Green: validator проверяет reader/control secret paths, общий service key,
  aliases и dispatcher profile; прямой DB URL отвергается.
- [x] Одновременный лимит `db+api+bot+dispatcher+Worker` сохраняет ресурсный
  резерв; завышенный dispatcher limit отвергается.
- [x] Независимое review P0–P2 без findings; terminal PR CI и tag pipeline
  `v1.2.1` отслеживаются отдельно в TASK-025-9.

## Evidence

Локально: 37 targeted tests passed; `make test-unit` — 1196 passed,
13 deselected; `make lint`, `make ai-validate`, `make production-check` passed;
`make docs` exit 0 с прежними предупреждениями. Итоговый отчёт после review:
[TASK-025-12](../../changes/done/TASK-025-12-release-compose-gate.md).
