# EPIC-030 — итог финансового исследования NHL/Pinnacle `winner_withOT`

> **Статус:** завершено — независимое research review принято; решение STOP
> **Протокол:** [NHL protocol](epic-030-nhl-protocol.md)
> **Требование:** [REQ-030](../product/requirements/REQ-030-financial-research-validation.md)
> **Архитектура:** [ADR-032](../architecture/adr/ADR-032-reproducible-financial-research-evaluation.md)

Протокол, модель, порог ставки и критерии были закреплены до открытия исходов. Выполнены один первичный locked OOS/evaluator run и один технический replay на идентичных входах после форматирования кода. Кандидат улучшил LogLoss и Brier, но получил отрицательный ROI и меньший simulated profit, чем baseline. Формальный финансовый gate — **FAIL**; после независимой проверки Product Owner принял решение **STOP** для этой фиксированной гипотезы.

## Техническая история запуска

Первая команда OOS 2026-10-10 остановилась до создания `op1` на проверке `Provider source IDs do not exactly cover pinned universe`: verifier сравнивал полный universe `[2023-10-01, 2026-05-01)` с оконным locked `pd1` `[2024-10-01, 2026-05-01)`. Исходы и ROI тогда не читались. Engineering исправил проверку оконного provider partition с независимым контролем полного universe; Reviewer принял исправление без P0–P2, 29 связанных тестов прошли. После этого выполнен первый фактический OOS run. Первый вызов evaluator содержал опечатку в пути `--universe-manifest`, завершился `FileNotFoundError` до создания output; исправленная команда ниже завершилась один раз. Опечатка не создала другого набора параметров или результата.

После типовых/format правок pre-commit 2026-10-10 повторены **те же команды** ниже на тех же pinned входах исключительно для проверки воспроизводимости. `op1` JSONL SHA `55f03cd6641ad235965d6f6839556cbfa2f9b5589c3a3b9c79cd5e1190f2d945` и manifest SHA `5615f449bf6730beb623fea978770f1989ecd0af62acb4e939e98e2361ad6253` совпали побайтно. JSON evaluator replay имеет SHA `41e9ad96c5344aa1f4bed4c6bb85ad1ea74e00e5e43c910655ae6f67450e833d`; первичный JSON с SHA `bb94c4bbfefec01f291cad0c230ad96da015ca4d13ab055c9d1101bcd04bcd36` сохранён как исходное evidence. Сравнение структур JSON после исключения только `provenance.code_fingerprints` дало точное равенство всех остальных полей, включая полный trace, 1568 comparable, 815/940 ставок, ML и финансовые метрики, bootstrap, sensitivity и решение. Trace SHA остался `7ce00041d210c2097973a28ccb2f04f9caf47ee0a14ba50a47ae0298941d4732`. Replay не создаёт новый holdout и не меняет вывод.

## Закреплённые входы и исполнение

| Поле | Значение |
| --- | --- |
| Рынок | NHL, Pinnacle `h2h` → `winner_withOT`, полный матч с ОТ и буллитами, два исхода |
| Закрытое окно kickoff, UTC | `[2024-10-01T00:00:00Z, 2026-05-01T00:00:00Z)` |
| Момент решения | `kickoff − 15 минут`; `observed_at ≤ T`, возраст цены `≤ 24 часа` |
| NHL universe run | `13afa80adc3d80b91ee7463b8dfbb31f2e5b3a62c36c2b1e290f1c36cffdb5b5` |
| Registry snapshot | `ir1:65ba2acd9aa49921f27912be924b272e4f0e9c2ebd63db165c3633bcce783498` |
| NHL raw fingerprint | `sha256:b6eaed0092a8d7dad4d6fd070b0f71d64493003b4fc6d7c55095a01dd7bb8fb3` |
| Historical imports fingerprint | `sha256:0755bcc3f8453b75a9b2a7ebe5c912920683429c562614dd4b05e4ad4cc48a10` |
| Locked provider dataset | `pd1:4fd4501440a3054b69fdce5f2dce8c70c109c064132f023b2c5bf7725f37f5f6` |
| Locked events SHA-256 | `sha256:1a3f731655517f120f6e796d73ad3bac9ca8dc2b73eefb999024e32e5c1b2f11` |
| Team seed SHA-256 | `sha256:df626f0624c7c0afd6bdffc4f10b9c0694822898baaf270d0c2def52ac3de291` |
| OOS prediction ID | `op1:55f03cd6641ad235965d6f6839556cbfa2f9b5589c3a3b9c79cd5e1190f2d945` |
| OOS manifest / predictions SHA-256 | `sha256:5615f449bf6730beb623fea978770f1989ecd0af62acb4e939e98e2361ad6253` / `sha256:55f03cd6641ad235965d6f6839556cbfa2f9b5589c3a3b9c79cd5e1190f2d945` |
| Evaluator format | `sports-forecast-financial-evaluation` v1 |
| Evaluator report SHA-256, первичный / replay | `sha256:bb94c4bbfefec01f291cad0c230ad96da015ca4d13ab055c9d1101bcd04bcd36` / `sha256:41e9ad96c5344aa1f4bed4c6bb85ad1ea74e00e5e43c910655ae6f67450e833d` |
| Trace SHA-256, оба запуска | `sha256:7ce00041d210c2097973a28ccb2f04f9caf47ee0a14ba50a47ae0298941d4732` |
| HEAD при оформлении отчёта | `000a36ddcc0d4101e903b3e4ddde0fb0bfe398fb`; точные fingerprints исполнявшихся модулей ниже |

Проверка закреплённых SHA raw NHL, team seed и SQLite перед запуском пройдена. OOS manifest дополнительно фиксирует provider dataset SHA `0eff5d3a727a0694c751cd0ab827cabab2094ccc9668180d620625011b582fc4` и полный universe SHA `42f83639cc06bd012c020e40b3a593f4982c627ef4dff2124770dedcb36522e7`. Текущие fingerprints кода из replay: OOS contract `c8b109f1f57a74e1ffcecfb5447fe42943a0e83e925ac30b48f0c81fa82b71b0`, evaluator `e596d24f97bf59c766307a40c7ae0fcf75d6573b45b60e54da390a48256d62c9`, simulator `e0617bfac92f39fabc32cf4ba10737f4b79e5bfcbc7f8da1e8e6578669a43fbc`, bootstrap `ef67fcfd2fb7a4a96cb3ec5d8b18d12bb4a0057823ab43445814900ee9a762f3`. В первичном run первые два fingerprints были соответственно `b93ec41f22094c0ddf3b3d3ea8c71305c834973f718a12eba912f47c648344b6` и `e79c0cc1cdc7beaf92d4ff54bc65705214ddd4a8e8e9ff8b3d4231f107983703`. Файлы результатов: первичный `/tmp/epic-030-locked-evaluation/bb94c4bbfefec01f291cad0c230ad96da015ca4d13ab055c9d1101bcd04bcd36.json`, replay `/tmp/epic-030-locked-evaluation/41e9ad96c5344aa1f4bed4c6bb85ad1ea74e00e5e43c910655ae6f67450e833d.json`.

## Universe, сопоставимость и покрытие

| Уровень / причина | Событий | Пояснение |
| --- | ---: | --- |
| NHL expected universe | 2751 | `regular` / `playoffs` в закрытом окне |
| Пригодная Pinnacle линия | 1568 | 56.997% от expected; знаменатель REQ-030 для покрытия ставок |
| `mapping_error` | 1181 | Связь с source event не подтверждена; отсутствие линии не доказано |
| `stale_price` | 2 | Цена старше 24 часов к T |
| `no_line` / `no_snapshot` / conflict | 0 / 0 / 0 | По locked `pd1` |
| Не подтверждён target / признаки | 0 | OOS manifest: `invalid_target=0`, `not_finished=0`, `unconfirmed_team_identity=0` |
| Несовместимый или отсутствующий прогноз на пригодной линии | 0 | `op1` содержит все 1568 line eligible; 1568 уникальных сопоставимых событий |
| Общий comparable set | 1568 | 100% от пригодной линии; одинаковые event UUID для candidate и baseline |
| Ставки candidate / baseline | 815 / 940 | 51.977% / 59.949% от 1568 |
| Месяцы со ставками candidate | 15 | Минимум 4 пройден |

Каждый trace содержит 2751 строку: 1568 comparable, 1183 без пригодной линии. В OOS manifest по месяцам 1568 событий: октябрь 2024 — май 2025: `130, 196, 181, 198, 94, 178, 98, 3`; октябрь 2025 — апрель 2026: `62, 72, 72, 85, 57, 102, 40`. Это помесячное покрытие **пригодной линии**; точные помесячные знаменатели полного universe в этом артефакте не опубликованы. Не трактовать отсутствие подтверждённой связи как доказанное отсутствие котировки.

## Модели, вероятности и финансовый trace

Baseline — Beta(1,1) частота побед хозяев на той же training mask. Candidate — помесячная logistic regression на `weekday_utc`, `hour_utc` и фиксированных one-hot командах, `L2`, `C=1`, `saga`, `max_iter=1000`, `random_state=777`, `n_jobs=1`; дополнительной калибровки нет. Для обоих используется proxy доступности label `kickoff + 7 суток ≤ month_start`. OOS manifest содержит cutoff и train source IDs каждого шага: первый train 9077 строк, последний 11606. Порог edge строго `>0.05`, flat stake `10`, банк `1000`, лимит `10%` текущего банка, не более одной ставки на событие. Profit сравнивается на общем comparable set, хотя стороны и число ставок различаются.

| Метрика закрытого теста | Candidate | Baseline | Действующая модель |
| --- | ---: | ---: | --- |
| LogLoss (`n=1568`) | 0.681938 | 0.688658 | Неприменимо: нет совместимого OOS контракта |
| Brier (`n=1568`) | 0.244414 | 0.247758 | Неприменимо |
| Калибровка: ECE по bins evaluator | 0.034888 | 0.011967 | Неприменимо |
| Ставок | 815 | 940 | Неприменимо |
| Turnover, условные единицы | 8150.0 | 9400.0 | Неприменимо |
| Simulated profit, условные единицы | −218.2 | −199.4 | Неприменимо |
| ROI, % | −2.6773 | −2.1213 | Неприменимо |
| Final bankroll | 781.8 | 800.6 | Неприменимо |
| Max drawdown, единицы / % | 424.4 / 35.8053% | 498.1 / 44.9103% | Неприменимо |
| Покрытие ставок от 1568, % | 51.9770 | 59.9490 | Неприменимо |

Калибровка по сохранённым bins (`count`, mean probability, observed rate), ECE — взвешенное абсолютное расхождение. Candidate bins: `3: 0.277→0.667`, `181: 0.368→0.470`, `408: 0.455→0.500`, `551: 0.551→0.532`, `321: 0.645→0.632`, `104: 0.732→0.712`. Baseline имеет один bin `1568: 0.537→0.549`; его ECE по одному bin не показывает локальную калибровку. Калибровочный метод не применялся.

Trace reconciliation: candidate `2751` строк, `815` ставок, сумма stake `8150`, сумма profit `−218.2`, final bankroll `1000−218.2=781.8`; baseline `2751`, `940`, `9400`, `−199.4`, final bankroll `800.6`. No-bet причины candidate: `1183 missing_prediction` (строки без пригодной линии), `753 edge_below_threshold`; baseline: `1183` и `628`. Максимум ставок за день — candidate `9`, baseline `12`; за месяц — `97` и `127` соответственно. Средний и максимальный возраст цены для **ставок** отдельно не фиксировались evaluator; медиана candidate `8362` сек, максимум `36261` сек, baseline `8363` и `36262` сек. Все ниже 24 часов.

Описательные разрезы candidate: сезон 2024/25 — `553` ставок, profit `−127.6`, ROI `−2.307%`; 2025/26 — `262`, `−90.6`, `−3.458%`. Baseline: `704`, `−249.0`, `−3.537%`; `236`, `+49.6`, `+2.102%`. По выбранному коэффициенту candidate: `<1.5`: `6` ставок, `+28.8`; `1.5–<2`: `204`, `−89.4`; `2–<3`: `480`, `+197.8`; `≥3`: `125`, `−355.4`. Эти разрезы получены после открытия теста; использовать их для перенастройки на этом holdout нельзя.

## Неопределённость и чувствительность

Circular block bootstrap по хронологическим **размещённым ставкам**: `5000` прогонов, блок `10–30` ставок, seed `777`, 95% percentile interval. Оба bootstrap имеют статус `ok`.

| Поле | Candidate | Baseline |
| --- | ---: | ---: |
| 95% интервал ROI | `[−9.6606%, +4.4298%]` | `[−9.8469%, +5.8665%]` |
| Доля прогонов с ROI > 0 | 0.2414 | 0.3030 |
| Невырожденность | `ok`, 5000 прогонов | `ok`, 5000 прогонов |

Чувствительность посчитана на тех же прогнозах, пороге и ставке, без переобучения. В отчёте evaluator число событий отдельно для подмножеств 1 и 6 часов не опубликовано; значения ниже — числа ставок.

| Предел возраста `T − observed_at` | Ставок candidate | Profit / ROI candidate | Интерпретация |
| --- | ---: | ---: | --- |
| 1 час | 286 | `+163.9` / `+5.7308%` | Описательный разрез после locked test |
| 6 часов | 630 | `−2.8` / `−0.0444%` | Описательный разрез после locked test |
| 24 часа, основной результат | 815 | `−218.2` / `−2.6773%` | Совпадает с основным trace |

Положительный 1h разрез не исправляет заранее заданный основной критерий и не разрешает выбрать новый freshness threshold на этом же тесте. Интервал ROI пересекает ноль; оба сезона candidate отрицательны.

## Проверка критериев и решение

| Условие | Порог до теста | Факт | Выполнено |
| --- | --- | --- | --- |
| ROI кандидата | `> 0` | `−2.6773%` | Нет |
| Доля положительных ROI bootstrap | `≥ 0.80` | `0.2414` | Нет |
| Покрытие ставок от line eligible | `≥ 0.20` | `815/1568=0.51977` | Да |
| Profit кандидата против baseline | Строго выше на тех же матчах | `−218.2 < −199.4` | Нет |
| Против действующей модели | Строго выше, если сопоставима | Совместимого OOS ряда нет | Неприменимо |
| Comparable set | `≥ 200` | `1568` | Да |
| Ставок кандидата | `≥ 40` | `815` | Да |
| Месяцев со ставками | `≥ 4` | `15` | Да |
| Независимая проверка leakage и расчётов | Принята | Принята без P0–P2 | Да |

Evaluator: `financial_gate_status=fail`, причины `positive_roi`, `bootstrap_positive_fraction`, `profit_above_baseline`; машинное поле `research_decision=pending_independent_review` отражает состояние на момент расчёта и не переписывается задним числом. **Решение Product Owner: STOP** для этой фиксированной комбинации модели, рынка, порога и окна. Модель лучше baseline по LogLoss на `0.00672` и Brier на `0.00334`, но это не реализовалось в лучшей финансовой метрике при закреплённой ставке. Доказательность по размеру достаточна, поэтому отрицательный результат нельзя объяснить только малым числом ставок. Возможная новая гипотеза о свежести цены требует нового заранее закреплённого holdout; 1h разрез текущего теста остаётся описательным. Production promotion не выполняется.

## Ограничения и независимое review

У всех 1568 priced snapshots `retrieved_at=null`: исторический cache подтверждает только `observed_at` у провайдера, не фактическое получение цены системой к T. Provider-as-of цена не доказывает возможность размещения ставки, сохранность коэффициента или лимит. Proxy `kickoff + 7 суток` заменяет неизвестный фактический timestamp завершения игры. Большая доля `mapping_error` (`1181/2751`) ограничивает перенос вывода на весь NHL universe. Ставки моделируются без фактического исполнения. Финансовый результат применим к закреплённому рынку, данным, цене и модели.

| Проверка Reviewer | Evidence | Статус |
| --- | --- | --- |
| Identity, market rules и исход с ОТ/буллитами | Хеши `pd1`/`op1`/`ev1`/trace сверены; ровно 1568 одинаковых covered UUID у моделей | Принято |
| Feature/label cutoff и отсутствие test leakage | Независимо восстановлены все 16 полных месячных training masks: 0 расхождений; первый/последний шаг 9077/11606 | Принято |
| Trace ↔ ставки ↔ profit/turnover/ROI | По каждой ставке сверены T−15m, edge, возраст цены, settlement и bankroll: 0 ошибок; суммы 815/8150/−218.2 и 940/9400/−199.4 | Принято |
| Bootstrap, coverage denominators и воспроизводимость | 2751 = 1568 covered + 1181 mapping error + 2 stale; bootstrap повторён на trace с 5000 блоками 10–30 и seed 777, доли 0.2414/0.3030 и интервалы совпали | Принято |
| Итог независимой проверки | Reviewer: P0–P2 findings нет; ограничения по `retrieved_at`, mapping и исполнению ставки сохранены | Принято |

## Команды единственного закрытого запуска

После Engineering review и проверки pinned inputs выполнен OOS final:

```bash
uv run python -m sports_forecast.research.oos_predictions \
  --matches ../../data/raw/nhl/matches.parquet \
  --team-seed conf/bookmaker/team_name_registry/nhl.yaml \
  --universe-manifest /tmp/epic-030-nhl-universe-final/runs/13afa80adc3d80b91ee7463b8dfbb31f2e5b3a62c36c2b1e290f1c36cffdb5b5/manifest.json \
  --provider-manifest /tmp/epic-030-provider-dataset/4fd4501440a3054b69fdce5f2dce8c70c109c064132f023b2c5bf7725f37f5f6/manifest.json \
  --historical-database /tmp/epic-030-nhl-history.sqlite3 \
  --snapshot /tmp/epic-030-nhl-universe-final/snapshots/65ba2acd9aa49921f27912be924b272e4f0e9c2ebd63db165c3633bcce783498 \
  --output /tmp/epic-030-locked-oos \
  --start 2024-10-01T00:00:00Z \
  --end 2026-05-01T00:00:00Z \
  --mode final
```

Затем выполнен evaluator final с точным CLI из [TASK-030-4 done](../changes/done/TASK-030-4-financial-evaluator.md), locked `pd1` и полученным `op1`:

```bash
uv run python -m sports_forecast.research.financial_evaluator \
  --matches ../../data/raw/nhl/matches.parquet \
  --team-seed conf/bookmaker/team_name_registry/nhl.yaml \
  --universe-manifest /tmp/epic-030-nhl-universe-final/runs/13afa80adc3d80b91ee7463b8dfbb31f2e5b3a62c36c2b1e290f1c36cffdb5b5/manifest.json \
  --provider-manifest /tmp/epic-030-provider-dataset/4fd4501440a3054b69fdce5f2dce8c70c109c064132f023b2c5bf7725f37f5f6/manifest.json \
  --historical-database /tmp/epic-030-nhl-history.sqlite3 \
  --snapshot /tmp/epic-030-nhl-universe-final/snapshots/65ba2acd9aa49921f27912be924b272e4f0e9c2ebd63db165c3633bcce783498 \
  --prediction-manifest /tmp/epic-030-locked-oos/55f03cd6641ad235965d6f6839556cbfa2f9b5589c3a3b9c79cd5e1190f2d945.manifest.json \
  --end 2026-05-01T00:00:00Z \
  --mode final \
  --output /tmp/epic-030-locked-evaluation
```

Повторный технический запуск с идентичными входами допускается только для проверки воспроизводимости уже раскрытого результата; он не даёт новый независимый holdout и не служит основанием для перенастройки политики.
