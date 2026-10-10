# TASK-030-4 — Общий финансовый evaluator и воспроизводимый evidence

> **Статус:** done — инженерное и исследовательское review пройдены; [результат STOP](../../research/epic-030-nhl-financial-result.md)
> **Владелец:** Developer / Research Scientist
> **Эпик:** [EPIC-030](../EPIC-030-financial-research-validation.md)
> **Требование:** [REQ-030](../../product/requirements/REQ-030-financial-research-validation.md) (`confirmed`)
> **Решение:** [ADR-032](../../architecture/adr/ADR-032-reproducible-financial-research-evaluation.md) (`accepted`)
> **Протокол:** [NHL protocol](../../research/epic-030-nhl-protocol.md)

## Результат и границы

Общий evaluator принимает verified dataset и OOS прогнозы
[TASK-030-3](TASK-030-3-oos-prediction-contract.md), проверяет общий список
событий, симулирует ставки кандидата и baseline по одной закреплённой
политике и создаёт event trace, метрики и bootstrap evidence. На первом срезе
используются NHL/Pinnacle/`winner_withOT`; рынок и правила расчёта передаются
явно, чтобы последующие модели могли дать прогноз по тому же контракту.

Research Scientist после инженерного review запускает один закрытый тест,
независимый Reviewer проверяет leakage и расчёты, Product Owner фиксирует
GO/ITERATE/STOP. Этот TASK не выпускает модель и не меняет production цикл.

## Критерии приёмки

1. Dataset ID, fingerprints, версия формата, market rules и список event UUID
   проверяются до расчёта; дубли, пропуски, неконечные вероятности,
   несовпадение исходов или лишние прогнозы вызывают ошибку. При отсутствии
   сопоставимой действующей модели этот факт явно указан, а baseline и
   candidate оцениваются на всех одинаковых пригодных матчах. Для каждого
   monthly training step проверяются не только hash/count, но и полный ordered
   список eligible source IDs, независимо восстановленный из verified raw по
   train-start, team eligibility, valid-score и label cutoff правилам.
2. По каждому событию и модели сохраняются `decision_at`, `ho1`, пара
   вероятностей/цен, edge для обеих сторон, выбор максимум одной ставки,
   причина no-bet, stake, outcome, profit и cumulative bankroll. Порог edge
   фиксируется на development; flat stake 10, банк 1000 и 10% лимит задаются
   протоколом. Итоговые profit/turnover/ROI и max drawdown считаются из того
   же cumulative trace; обобщение step traces их не подменяет.
3. LogLoss, Brier и калибровка считаются на всём comparable set. Отдельно
   показаны полный expected universe, пригодная линия, comparable set,
   placed bets и взаимно исключающие причины исключений. Покрытие ставок по
   REQ-030 делит число ставок на **все пригодные тестовые события с линией**;
   разница с comparable set сохраняется в отчёте.
4. `BlockBootstrap` по хронологическим размещённым ставкам даёт 5000
   повторов, circular blocks 10–30 ставок, seed 777, 95% interval и долю
   ROI > 0. Нулевые/недостаточные ставки и вырожденная выборка помечаются
   недостаточной доказательностью. Чувствительность к пределам возраста цены
   1/6 часов выполняется без переобучения и смены policy.
5. Отчёт отделяет provider-as-of `observed_at` от nullable `retrieved_at` и
   не заявляет фактическую доступность ставки. Финансовый GO требует все
   подтверждённые пороги REQ-030, а также исследовательскую нижнюю границу
   200 событий в comparable set, 40 ставок и 4 месяца со ставками; отсутствие одного
   условия даёт ITERATE/STOP с причинами, а не молчаливый GO.
6. Повторный запуск с теми же dataset/prediction/code/config IDs и seed даёт
   тот же состав ставок, trace hash и результаты в зафиксированной числовой
   точности. Финальный research report содержит hashes, версии, разрезы,
   фактические команды, остаточные риски и независимое review.

## Red → green → refactor

1. Synthetic случаи win/loss/no-bet, равного edge, разворота команд,
   неполного прогноза, расхождения market rules, нулевого/отрицательного ROI,
   bootstrap seed и малого числа ставок — сначала красные тесты.
2. Использовать `BettingSimulator` для единого cumulative trace и совместимо
   расширить `BlockBootstrap` долей положительных ROI. ML-ошибки нельзя
   превращать в нулевые метрики; отсутствующая метрика помечается явно.
3. Адресные тесты и engineering offline replay только на synthetic/development
   данных, [done](../../changes/done/TASK-030-4-financial-evaluator.md),
   независимое code review. После него Research Scientist открывает закрытый
   тест один раз; итог отдельно проверяет независимый Reviewer.

## Handoff

Developer → Reviewer → Research Scientist → независимый Reviewer → Product
Owner. Исследовательское решение оформляется в EPIC и связанном отчёте;
production promotion требует отдельного решения владельца.
