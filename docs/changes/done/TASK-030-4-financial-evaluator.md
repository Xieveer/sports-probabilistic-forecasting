# Выполнение TASK-030-4 — Общий финансовый evaluator

## Результат

Добавлен `sports_forecast.research.financial_evaluator`: CLI принимает pinned
`ir1`, verified `pd1`, provenance и OOS `op1`; сверяет dataset/source fingerprints,
manifest/content hashes, market rules, полуоткрытое окно, source UUID, kickoff,
decision time и точное множество priced OOS event IDs. Evaluation window должен
лежать внутри provider dataset; событие на `start` входит, событие ровно на
`end` не входит. Режим `development` запрещает `end > 2024-10-01T00:00:00Z`.

На общем comparable set считаются LogLoss, Brier и калибровочные бины. На каждом
событии и для candidate/baseline формируется trace с `decision_at`, `ho1`/`ir1`,
receipt и source-file provenance, обеими вероятностями, Pinnacle prices, двумя
edges, максимум одной выбранной стороной, no-bet reason, stake, outcome, profit
и cumulative bankroll. Для расчёта финансовых агрегатов вызывается существующий
`BettingSimulator`; его API обратно совместимо расширен `bet_eligible_mask`,
который позволяет запретить ставку, не затирая рассчитанный edge в simulator
trace. В равенстве максимальных edges ставка не ставится (равенство проверяется
с абсолютным допуском `1e-12`).

Отчёт отдельно содержит знаменатели expected universe, события с пригодной
линией, comparable events и placed bets, взаимно исключающие причины исключения,
coverage, финансовые агрегаты, max drawdown, 1/6-часовую чувствительность,
95% интервал и долю положительных ROI для 5000 circular block bootstrap
реплик с seed 777 и блоками 10–30 ставок. Малая или вырожденная bootstrap
выборка явно обозначается как недостаточная. `observed_at` трактуется как
provider-as-of; nullable `retrieved_at` сохраняется отдельно и не считается
доказательством доступности цены в прошлом. Машинный статус относится только
к финансовым порогам; `research_decision` остаётся
`pending_independent_review`, так что evaluator сам не объявляет GO.

## Проверки

Сначала тест evaluator ожидаемо падал на отсутствующем модуле. После реализации:

```text
.venv/bin/pytest -q tests/test_research_financial_evaluator.py tests/test_block_bootstrap.py tests/test_betting_simulator.py
58 passed, 1 warning (до review fixes)

.venv/bin/ruff check sports_forecast/research/financial_evaluator.py sports_forecast/betting/bootstrap.py sports_forecast/betting/simulator.py tests/test_research_financial_evaluator.py tests/test_block_bootstrap.py tests/test_betting_simulator.py
All checks passed
```

После review fixes и pre-commit typing/formatting gate выполнена расширенная
адресная проверка:

```text
.venv/bin/pytest -q tests/test_research_nhl_universe.py tests/test_research_provider_dataset.py tests/test_research_oos_predictions.py tests/test_research_financial_evaluator.py tests/test_walk_forward_runner.py tests/test_walk_forward_slicer.py tests/test_historical_odds.py tests/test_betting_simulator.py tests/test_block_bootstrap.py
121 passed, 3 warnings

uv run pre-commit run ruff --all-files
Passed
uv run pre-commit run ruff-format --all-files
Passed
uv run pre-commit run mypy --all-files
Passed
git diff --check
Passed
```

Исправления для mypy сводятся к явным типам на динамических границах pandas/
numpy и test fixtures; формулы, маски, policy, модельные и betting параметры не
менялись. Ruff-format hook применил форматирование к изменённым файлам до
повторной чистой проверки.

Synthetic regressions проверяют выигрышную и проигрышную ставки, пропуск ставки,
положительные равные edges, одинаковый comparable set, несовпадающие/неполные
вероятности, duplicate IDs, дату решения, 24-часовую границу линии, trace vs
profit/ROI/bankroll, outcome settlement, границы op1 window и pending review
после прохождения финансовых gates. Bootstrap фиксирует долю положительных
реплик и её воспроизводимость при одинаковом seed. Проверка simulator напрямую
подтверждает, что `bet_eligible_mask=False` сохраняет вычисленный edge.

После независимого review добавлены regressions для `late_retrieval=True` при
`retrieval_status=known`, целостности manifest model config и строгой валидации
score при settlement. `_winner_with_ot_target` возвращает отсутствующую метку
для отрицательных, дробных, бесконечных и ничейных счетов. Verifier восстанавливает
полный упорядоченный список eligible training source IDs из verified raw для
каждого месяца и точно сравнивает его с manifest, поэтому пересчёт hash/count
после пропуска строки не проходит.

## Development replay

Запущен полный engineering replay только для `[2023-10-01, 2024-10-01)`; он
использовал ранее закреплённые development `pd1/op1`. Закрытый интервал не
открывался, его исходы и метрики не читались.

```bash
.venv/bin/python -m sports_forecast.research.financial_evaluator \
  --matches ../../data/raw/nhl/matches.parquet \
  --team-seed conf/bookmaker/team_name_registry/nhl.yaml \
  --universe-manifest /tmp/epic-030-nhl-universe-final/runs/13afa80adc3d80b91ee7463b8dfbb31f2e5b3a62c36c2b1e290f1c36cffdb5b5/manifest.json \
  --provider-manifest /tmp/epic-030-provider-dataset/53edba6acfdeeb1e1ccb20a024f8eeecc88c9dd792f7c90ce1cb580bfa5de64e/manifest.json \
  --historical-database /tmp/epic-030-nhl-history.sqlite3 \
  --snapshot /tmp/epic-030-nhl-universe-final/snapshots/65ba2acd9aa49921f27912be924b272e4f0e9c2ebd63db165c3633bcce783498 \
  --prediction-manifest /tmp/task0303-dev-p2/d4fb51dadf2d7406b7e45942c2e407cac886203eee3cd42516140418c6907202.manifest.json \
  --end 2024-10-01T00:00:00Z --mode development \
  --output /tmp/task0304-financial-eval
```

Development replay после исправления `ir1`/`pd1` projection и pre-commit
typing/formatting изменений завершился успешно и сохранил immutable report и trace:

- report path `/tmp/task0304-financial-eval/a726e4806aac2fcf9ec037eb913480da28437efa92d143a5ddd7a0951f9d25d7.json`;
- `ev1:a726e4806aac2fcf9ec037eb913480da28437efa92d143a5ddd7a0951f9d25d7`;
- report SHA-256 `a726e4806aac2fcf9ec037eb913480da28437efa92d143a5ddd7a0951f9d25d7`;
- trace SHA-256 `07f44ee7399af4eab505ccce8ff8b04936c6fd810fde1255119caa059a172472`;
- trace rows: 2798;
- code SHA-256: evaluator `e596d24f97bf59c766307a40c7ae0fcf75d6573b45b60e54da390a48256d62c9`,
  simulator `e0617bfac92f39fabc32cf4ba10737f4b79e5bfcbc7f8da1e8e6578669a43fbc`,
  bootstrap `ef67fcfd2fb7a4a96cb3ec5d8b18d12bb4a0057823ab43445814900ee9a762f3`,
  OOS contract `c8b109f1f57a74e1ffcecfb5447fe42943a0e83e925ac30b48f0c81fa82b71b0`;
- inputs: `pd1:53edba6acfdeeb1e1ccb20a024f8eeecc88c9dd792f7c90ce1cb580bfa5de64e`,
  `op1:d4fb51dadf2d7406b7e45942c2e407cac886203eee3cd42516140418c6907202`,
  `ir1:65ba2acd9aa49921f27912be924b272e4f0e9c2ebd63db165c3633bcce783498`;
- raw matches SHA-256 `b6eaed0092a8d7dad4d6fd070b0f71d64493003b4fc6d7c55095a01dd7bb8fb3`;
- denominators: 1399 expected, 1217 eligible line, 1217 comparable, 694 candidate bets;
- line coverage 86.99%, candidate bet coverage on eligible lines 57.03%; exclusions:
  181 `mapping_error`, one `no_line`;
- candidate: turnover 6940, profit −98.80, ROI −1.424%, max drawdown 455.30;
  5000-replicate positive ROI fraction 0.3808 and 95% ROI interval
  [−10.068%, 7.518%];
- baseline: 770 bets, turnover 7700, profit −19.80, ROI −0.257%;
- candidate sensitivity at price age ≤1h / ≤6h: 247 / 555 bets, profit 158.00 /
  −85.00, ROI 6.397% / −1.532%.

Это только development evidence для проверки пайплайна. Числа не являются
закрытым research result и не должны переноситься в итоговое решение по гипотезе.

## Остаточные ограничения и handoff

Historical `retrieved_at` неизвестен для всех 1217 priced development events;
отчёт явно сохраняет это ограничение, а `late_retrieval` считается по отдельному
boolean-флагу провайдера (в development срезе late receipts нет). Block bootstrap
крутится только когда есть не менее зафиксированного минимума ставок и
различающиеся прибыли;
иначе он помечает evidence insufficient. В текущем implementation отсутствие
comparable current model отражается его отсутствием в сравнении. Production
workflow не менялся.

Инженерное review пройдено: P0–P2 findings отсутствуют. После найденного
pre-outcome bug исправлена точная проверка `pd1` projection для полного `ir1`;
повторный review принят без findings. TASK4 готов к передаче Research Scientist
для единственного locked run. Далее: Research Scientist → независимый research
Reviewer → Product Owner. Commit и push не выполнялись.

Последующий locked run и независимое исследовательское review завершены;
[итоговый отчёт](../../research/epic-030-nhl-financial-result.md) фиксирует
решение Product Owner `STOP` для первой гипотезы. Engineering evidence выше
относится только к development окну.
