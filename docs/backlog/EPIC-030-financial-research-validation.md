# EPIC-030 — Воспроизводимая финансовая оценка моделей

> **Статус:** done — исследование завершено решением STOP; PR #69 ожидает merge после финального CI
> **Приоритет:** medium
> **Владелец:** Product Owner
> **Требование:** [REQ-030](../product/requirements/REQ-030-financial-research-validation.md) (`confirmed`)
> **ADR:** [ADR-032](../architecture/adr/ADR-032-reproducible-financial-research-evaluation.md) (`accepted`)

## Память Product Owner

- Инициатива: `EPIC-030`.
- Ветка инициативы: `initiative/epic-030-financial-research-validation`, отдельный worktree.
- Workflow / этап: `research + ограниченный engineering / все TASK done; research и полное EPIC review приняты; PR #69 и финальный CI`.
- Исходная цель: сравнивать кандидата с baseline по вероятностным и финансовым метрикам на исторически доступной информации.
- Критерии и DoD: сценарии ниже и [REQ-030](../product/requirements/REQ-030-financial-research-validation.md); владелец подтвердил ROI > 0, долю block-bootstrap прогонов с ROI > 0 не ниже 80%, покрытие ставок не ниже 20% пригодных событий и profit выше baseline на тех же матчах.
- Релиз: production-развёртывание не запрошено; GO не означает promotion.
- Выполнено: направление зафиксировано 2026-10-04, первый срез NHL/Pinnacle/`winner_withOT` и финансовые пороги подтверждены владельцем 2026-10-10. Pinned `ir1` и оконный `pd1` дали 1568 пригодных для сравнения событий; исследовательский цикл завершён и независимо проверен.
- Gate TASK-030-1: локальный `ir1:65ba2acd9aa49921f27912be924b272e4f0e9c2ebd63db165c3633bcce783498` закрепил 4150 regular/playoffs матчей; 300 иных game types исключены до odds. Из всех historical source events 2788 разрешены, 755 не разрешены, 610 конфликтуют. Код принят независимым Reviewer после 66 адресных тестов; [evidence](../changes/done/TASK-030-1-pinned-nhl-universe.md). Это ещё не покрытие пригодной Pinnacle линии.
- Gate TASK-030-2: provider-as-of dataset `pd1:4fd4501440a3054b69fdce5f2dce8c70c109c064132f023b2c5bf7725f37f5f6` закрепил тест `[2024-10-01,2026-05-01)`: 2751 ожидаемый матч, 1568 пригодных линий, 1181 отсутствие подтверждённого odds mapping, 2 просроченные цены. Полное окно и fingerprints — в [evidence](../changes/done/TASK-030-2-provider-as-of-dataset.md). Независимый Reviewer принял код после 37 адресных тестов; исходы/ROI не читались.
- Gate TASK-030-3: OOS contract `op1` и development smoke закрепили 1217 прогнозируемых событий из 1399 подтверждённых матчей до `2024-10-01`; candidate сошёлся на всех 9 месячных fit steps. Обычный runner сохранён, исследовательский `prediction_only` режим не оценивает test target; [evidence](../changes/done/TASK-030-3-oos-prediction-contract.md). Независимый Reviewer принял код после 18 адресных тестов; закрытые исходы/ROI не использовались.
- Решения: [ADR-032](../architecture/adr/ADR-032-reproducible-financial-research-evaluation.md) принят 2026-10-10: локальный закреплённый dataset, общий контракт прогнозов и evaluator поверх существующих компонентов. Использовать существующие walk-forward и bootstrap как исходную базу; не считать прежние odds автоматически локально известными к прошлому T; сначала проверить и закрепить сопоставление событий и покрытие.
- Артефакты: [REQ-030](../product/requirements/REQ-030-financial-research-validation.md), [ADR-032](../architecture/adr/ADR-032-reproducible-financial-research-evaluation.md), [протокол](../research/epic-030-nhl-protocol.md), [аудит данных](../research/epic-030-data-audit.md), [итоговый отчёт](../research/epic-030-nhl-financial-result.md), [TASK-030-1](tasks/TASK-030-1-pinned-nhl-universe.md), [EPIC-027](EPIC-027-historical-odds.md), [EPIC-021](EPIC-021-football-1x2-research.md).
- Предыдущая роль: Research Scientist — закрепил [протокол](../research/epic-030-nhl-protocol.md) до просмотра исходов; Architect — подготовил принятый [ADR-032](../architecture/adr/ADR-032-reproducible-financial-research-evaluation.md).
- Предыдущая инженерная роль: Developer — [TASK-030-1](tasks/TASK-030-1-pinned-nhl-universe.md), принят независимым Reviewer; [отчёт](../changes/done/TASK-030-1-pinned-nhl-universe.md).
- Предыдущая инженерная роль: Developer — [TASK-030-2](tasks/TASK-030-2-provider-as-of-dataset.md), принят независимым Reviewer; [отчёт](../changes/done/TASK-030-2-provider-as-of-dataset.md).
- Предыдущая инженерная роль: Developer — [TASK-030-3](tasks/TASK-030-3-oos-prediction-contract.md), принят независимым Reviewer; [отчёт](../changes/done/TASK-030-3-oos-prediction-contract.md).
- Gate TASK-030-4: evaluator и строгая проверка `op1` приняты Reviewer; оконная проекция `ir1` для locked `pd1` исправлена до чтения locked исходов, повторное review принято. Development replay и 74 адресных теста прошли; [engineering evidence](../changes/done/TASK-030-4-financial-evaluator.md).
- Research cycle 1: один locked OOS и один завершённый evaluator на `[2024-10-01,2026-05-01)`; `1568` comparable событий, кандидат `815` ставок, ROI `−2.6773%`, simulated profit `−218.2`; baseline profit `−199.4`; positive-ROI bootstrap `0.2414`. Покрытие ставок `815/1568=51.977%`. Финансовый gate `FAIL` по ROI, bootstrap и profit против baseline; независимый research Reviewer подтвердил identity, все 16 training masks, trace и bootstrap без P0–P2. [Полный отчёт](../research/epic-030-nhl-financial-result.md).
- Решение Product Owner: **STOP** для зафиксированной гипотезы NHL/Pinnacle/`winner_withOT` с данным кандидатом и policy. Новая гипотеза, включая предел свежести 1 час, требует отдельного заранее закреплённого holdout; текущий разрез не используется для перенастройки. Production promotion не выполняется.
- Gate полного EPIC review: Reviewer принял кодовые TASK и связность REQ/ADR/EPIC/TASK/README/исследовательского отчёта без P0–P2; ссылки и границы проверены. После правок REQ и README типовых секретов не найдено, `git diff --check` пройден.
- Evidence commit gate: проверенный diff закреплён Reviewer в `8296cb886533de8ba9b2d1d08e6fc512e50304ec`; pre-commit hooks `ruff`, `ruff-format`, `mypy` и проверка AI roles/skills прошли. Отдельный documentation-only commit фиксирует этот hash для PR и terminal CI.
- Gate интеграции: [PR #69](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/69) открыт; CI `lint-test (3.12)` и Security `Python dependencies` / `Filesystem and secrets` завершились успешно на evidence commit `ebe20277fb72d2bd0eefe2bd211ca8e38565681b`. После этого изменения статуса нужен новый terminal CI.
- Следующая роль: Reviewer — documentation commit gate статуса; затем Product Owner — terminal CI и merge без release.
- Открытые ограничения: `retrieved_at` неизвестен для 1568 пригодных исторических цен, 1181 матч не имеет подтверждённого bookmaker mapping; simulated stake не подтверждает исполнимость ставки.
- Обновлено: 2026-10-10.

## Цель и границы

Проверить один кандидат и baseline на одинаковом temporal/walk-forward срезе со снимками провайдера, датированными до момента решения, и явным статусом локального получения. Отчёт должен отделять качество вероятностей, симулированную доходность, её неопределённость и покрытие данных. Не заявлять production edge на основании одного положительного ROI.

## Проверяемый результат

1. Кандидат и baseline сравниваются на одном зафиксированном наборе событий и допустимых odds.
2. Отчёт содержит LogLoss, Brier, калибровку, число ставок, turnover, ROI, bootstrap-интервал, покрытие odds и причины исключения строк.
3. Повторный запуск на тех же версиях данных, кода и конфигурации воспроизводит результат в заранее согласованной числовой точности.
4. Исследовательский итог оформляется как GO/ITERATE/STOP после независимой проверки leakage и расчётов.

## Декомпозиция

| Задача | Результат | Зависимости | Проверка | Статус |
| --- | --- | --- | --- | --- |
| [TASK-030-1](tasks/TASK-030-1-pinned-nhl-universe.md) | Полный pinned NHL universe и строгое сопоставление bookmaker source events | REQ-030, ADR-032 | 66 tests, offline smoke, `ir1` verify, independent review | done |
| [TASK-030-2](tasks/TASK-030-2-provider-as-of-dataset.md) | Provider-as-of dataset с per-event T, provenance цены и coverage | TASK-030-1 | 37 tests, full/locked smoke, independent review | done |
| [TASK-030-3](tasks/TASK-030-3-oos-prediction-contract.md) | Проверенный общий набор и OOS прогнозы baseline/candidate | TASK-030-2 | 18 tests, development smoke, independent review | done |
| [TASK-030-4](tasks/TASK-030-4-financial-evaluator.md) | Общий evaluator, bootstrap, evidence и запуск исследования | TASK-030-3 | 74 адресных теста, development replay, независимые engineering и research review | done |

## Зависимости и следующий gate

Исторический контракт [EPIC-027](EPIC-027-historical-odds.md), финансовые критерии [REQ-030](../product/requirements/REQ-030-financial-research-validation.md) и результат [исследования](../research/epic-030-nhl-financial-result.md) закреплены. Следующий gate — финальный CI PR и merge; отдельная новая гипотеза не входит в эту инициативу. Исследование не заменяет [EPIC-021](EPIC-021-football-1x2-research.md) и не меняет статус его historical odds.

## Риски и rollout

Историческая котировка не доказывает возможность поставить по этой цене; допущения о задержке, лимитах и расчёте рынка указывать в отчёте. Выпуска модели эта инициатива не разрешает.
