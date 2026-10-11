# Выполнение TASK-030-3 — Общий контракт OOS прогнозов

## Результат

Добавлен общий prediction contract NHL `winner_withOT` для Logistic Regression и
Beta(1,1) home-win baseline. Оба используют одну фактическую training mask из
`WalkForwardRunner`/`WalkForwardSlicer`, включая проверяемые условия
`finished`, валидный полный счёт, `kickoff >= 2017-10-01` и
`kickoff + 7d <= month_start` (то же, что `kickoff <= month_start - 7d`).
Runner в `prediction_only` режиме не читает OOS target для метрик, не строит
betting results и не refit-ит финальную модель. Числовой/категориальный feature
набор фиксирован протоколом: UTC weekday/hour и home/away one-hot по командам
с kickoff не позже `2024-09-24T00:00:00Z`; неизвестная команда получает
all-zero one-hot стороны.

CLI сам проверяет raw parquet и seed fingerprints из universe, universe hash и
raw identity partition через pinned `ir1`, provider manifest/content SHA и
канонический `pd1`, точный source ID/UUID/kickoff join и temporal NHL team
resolution. CLI development mode ограничен `end <= 2024-10-01`; произвольный
JSONL/self-asserted manifest больше не является допустимым CLI входом.
Raw parquet читает сначала identity-only projection. Score/status поля читаются
отдельным PyArrow dataset scan с predicate `datetime >= 2017-10-01` и
`datetime < end`; результат scanner проверяется на отсутствие ID за cutoff до
join, а уникальные ID обеих проекций должны совпасть точно до merge, чтобы
отсутствующий outcome не превращался в `NaN` label. Timed rows из universe
`nhl_diagnostics` входят в сверку raw partition и
provider source keys с `project_event_id=null`. Диагностические rows с командой,
не подтверждённой NHL seed и temporal `ir1`, не попадают в train/predictions и
учитываются в `unconfirmed_team_identity` exclusions.
Артефакт содержит только прогнозы, features и provenance; `generated_at` не
входит в deterministic manifest. `decision_at` явно задан как kickoff минус
15 минут.

## Проверки

Red: новые тесты slicer/runner сначала падали на неподдерживаемых параметрах.
Green/refactor: добавлены совместимые опциональные маски и `prediction_only`,
сохранено поведение стандартного runner API.

```text
uv run pytest -q tests/test_research_oos_predictions.py tests/test_walk_forward_slicer.py tests/test_walk_forward_runner.py
24 passed, 3 warnings

uv run ruff check sports_forecast/research/oos_predictions.py sports_forecast/training/walk_forward/runner.py sports_forecast/training/walk_forward/slicer.py tests/test_research_oos_predictions.py tests/test_walk_forward_runner.py tests/test_walk_forward_slicer.py
All checks passed

git diff --check
passed
```

## Development smoke

Дополнительно regression проверяет, что verified loader берёт ожидаемую identity
partition из полного pinned `ir1`, спроецированную на half-open окно `pd1`; строки
вне окна не должны мешать точной проверке provider ID. Проверены включённая start
и исключённая end границы, а также отказ для окна `pd1`, выходящего за `ir1`.

Применены raw NHL, pinned universe, TASK-030-2 `pd1`, `ir1` snapshot и
historical DB. При подготовке model input применён cutoff kickoff
`< 2024-10-01T00:00:00Z` до чтения score/status для target; результаты locked
периода не использовались и не выводились. OOS prediction smoke не считал ROI,
ML metrics, financial metrics или label summaries.

Команда smoke и её точный повтор:

```bash
uv run python -m sports_forecast.research.oos_predictions \
  --matches ../../data/raw/nhl/matches.parquet \
  --team-seed conf/bookmaker/team_name_registry/nhl.yaml \
  --universe-manifest /tmp/epic-030-nhl-universe-final/runs/13afa80adc3d80b91ee7463b8dfbb31f2e5b3a62c36c2b1e290f1c36cffdb5b5/manifest.json \
  --provider-manifest /tmp/epic-030-provider-dataset/53edba6acfdeeb1e1ccb20a024f8eeecc88c9dd792f7c90ce1cb580bfa5de64e/manifest.json \
  --historical-database /tmp/epic-030-nhl-history.sqlite3 \
  --snapshot /tmp/epic-030-nhl-universe-final/snapshots/65ba2acd9aa49921f27912be924b272e4f0e9c2ebd63db165c3633bcce783498 \
  --output /tmp/task0303-dev-p2 \
  --start 2023-10-01T00:00:00Z \
  --end 2024-10-01T00:00:00Z
```

Два идентичных полных CLI запуска в один output directory прошли без конфликта
артефактов. `prediction_id` и SHA-256 manifest совпали:

- OOS predictions: `op1:d4fb51dadf2d7406b7e45942c2e407cac886203eee3cd42516140418c6907202`;
- manifest SHA-256: `sha256:80d2b14e9c3574ceaaace9751902b0a3844123f07019488f8dbc23305b5f8235`;
- путь manifest:
  `/tmp/task0303-dev-p2/d4fb51dadf2d7406b7e45942c2e407cac886203eee3cd42516140418c6907202.manifest.json`;
- в development окне 1399 resolved raw NHL событий, из них 1217 с пригодным
  `pd1` price coverage и 182 без usable price; unresolved rows — 0;
- 9 календарных fit steps. Число training rows выросло с 7678 до 9061;
  первый cutoff kickoff `2023-09-24T00:00:00Z`, последний fit cutoff
  `2024-05-25T00:00:00Z` (последний месяц без пригодных OOS prices — только
  training step); последний месяц с prediction rows — май, cutoff
  `2024-04-24T00:00:00Z`;
- по шагам Logistic Regression завершалась за 23, 25, 26, 25, 25, 25, 25, 25
  и 27 итераций; convergence warnings не возникали.

Raw development окно содержит 1399 матчей (в том числе 82 shootout, согласно
зафиксированной проверке протокола). OOS output имеет 1217 событий на пару
моделей, 2434 prediction rows суммарно; причины исключения цены отражены
счётчиками выше. Manifest не включает исходы или оценочные метрики.

После замечаний независимого review добавлены regressions: fake Arrow scanner
подтверждает, что cutoff predicate задан до score/status projection, scanner
row после cutoff и неполное покрытие outcome IDs отклоняются до merge;
synthetic timed unknown-team diagnostic остаётся в raw/ir1 partition и явно
исключается из модельных rows. Обновлённый
реальный development smoke и его повтор в одном output directory завершились
успешно с одинаковым prediction ID и manifest SHA выше.

## Ограничения и handoff

TASK-030-3 не открывает locked окно, не считает для него оценки и не меняет
feature/model/threshold protocol. Единственный итоговый research run остаётся
за следующим согласованным этапом после независимого review. Изменены только
OOS contract/runner/slicer и относящиеся тесты; провайдерский dataset code не
менялся. Commit/push не выполнялись.

Developer → Product Owner → независимый Reviewer. Канонический TASK:
[TASK-030-3](../../backlog/tasks/TASK-030-3-oos-prediction-contract.md).
