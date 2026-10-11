# TASK-026-13 — Отчёт о производном сопоставлении NHL событий

## Результат

Реализован общий matcher двудольного соответствия по подтверждённым tournament/team
ID, направлению home/away и kickoff ±15 минут UTC. Допускается только взаимно
уникальная пара. Live quotes используют полный набор переданных календарных и
provider events; unknown aliases остаются в designation review, обычные неизвестные
event IDs больше не ставятся в очередь.

Future odds используют тот же matcher. Provider запрос расширен на ±15 минут за
фактические границы целевого окна. Календарь выбирается с тем же расширением для
проверки uniqueness; внецелевые календарные события не создают observations.
Повторные одинаковые provider IDs сворачиваются, конфликтующие валидные копии
отклоняются; структурно непригодная копия не блокирует единственную валидную строку.
Live и future требуют, чтобы разрешённый Pinnacle `h2h` был проектным рынком
`winner_withOT` с правилом game, overtime и shootout, без ничьей и ровно с
исходами home/away; live parser сопоставляет outcome labels по pinned registry team
ID, поэтому label может отличаться от display name события. Неразрешённый alias
рынка создаёт scoped candidate в owner review для future batch и OddsStore projection.
OddsStore NHL projection применяет aliases и семантическое market rule; для строк
без provider event ID значение не синтезируется.

## Изменённые файлы этой задачи

- `sports_forecast/identity/derived_event_matching.py`
- `sports_forecast/data/providers/odds/live_nhl_pinnacle.py`
- `sports_forecast/orchestration/future_odds.py`
- `sports_forecast/orchestration/live_odds_adapter.py`
- `sports_forecast/service/live_odds_enrichment.py`
- `sports_forecast/service/odds_projection.py`
- Тесты matcher, live odds, future batch, OddsStore projection и candidate capture.

## Red → green → refactor

- Добавлены тесты допуска ±15 минут, шести смещённых сопоставлений, отсутствующих
  aliases, неоднозначности, границы окна, одинаковых и конфликтующих повторов ID,
  market/outcome semantics, strict live market gate и фильтра unresolved designation.
- Исправлены найденные тестами интеграционные несоответствия live reader и seed
  market rule в тестовом registry snapshot.
- После реализации весь целевой набор ниже прошёл.

## Проверки

- `./.venv/bin/pytest -q tests/test_future_odds_batch.py tests/test_registry_candidate_capture.py tests/test_event_readiness.py tests/test_derived_event_matching.py tests/test_live_odds_enrichment.py tests/test_live_nhl_pinnacle.py tests/test_odds_refresh.py tests/test_odds_poll_notification.py tests/test_nhl_legacy_yaml_cutover.py` — **102 passed**, 3 warnings.
- `./.venv/bin/ruff check` по изменённым исходникам и прямым тестам — **passed**.
- `git diff --check` — **passed**.
- `PYTHONPATH=. .venv/bin/pytest -m unit -q` — **1706 passed**, 17 deselected,
  40 warnings на объединённом EPIC-026 diff.
- `UV_OFFLINE=1 make lint` и `UV_OFFLINE=1 make type-check` — **passed** после
  исправления двух повторных объявлений локальных переменных.
- Независимый повторный review закрыл findings по подтверждению рынка,
  unresolved кандидатам, дублям provider event ID и очереди неизвестного
  турнира; новых P0–P2 нет.

## Неизменённое и риски

- Исторические OddsStore строки не дают provider event ID или сырые provider outcome
  labels; provenance не выдумывается.
- Сопоставление не-NHL источников в OddsStore сохранено прежним до отдельной задачи.
- Полный прогнозный цикл на production snapshot и релизные gates не выполнялись;
  они входят в EPIC-036.
