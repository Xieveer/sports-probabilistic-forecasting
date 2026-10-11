# TASK-026-9 — Локальная подготовка YAML cutover

## Результат

Добавлена проверяемая локальная подготовка перехода NHL odds-потребителей на
строгий registry. При включённом strict event reader команда загрузки
возвращает пустой legacy alias map и не открывает YAML; strict разрешение
продолжает выполняться через установленный registry snapshot. Готовность
календаря сравнивает подтверждённые project ID через закреплённый reader,
поэтому переименование той же команды не выглядит заменой участника. При выключенном
reader старый YAML путь сохранён как compatibility путь для rollback на прежний
проверенный выпуск.

Добавлен read-only checker `sports_forecast.identity.nhl_parity`: он проверяет
известные YAML aliases в трёх пространствах (`nhl_api`, `nhl_web_api`,
`the_odds_api`) против подтверждённых designation в master и затем против
верифицированного snapshot. Дополнительные обозначения master допустимы и не
считаются ошибкой автоматически.

## Доказательства

- Red: `uv run pytest -q tests/test_nhl_legacy_yaml_cutover.py` завершился
  ожидаемым `TypeError` на отсутствующем `strict_mode`.
- Green и регрессии: `uv run pytest -q tests/test_nhl_legacy_yaml_cutover.py tests/test_odds_backfill.py tests/test_future_odds_batch.py tests/test_odds_refresh.py tests/test_event_readiness.py tests/test_live_odds_enrichment.py tests/test_odds_poll_notification.py tests/test_registry_candidate_capture.py`
  — 96 passed.
- Synthetic строгий NHL цикл в
  `tests/test_registry_candidate_capture.py::test_owner_decision_republished_snapshot_unlocks_odds`
  проверяет неподтверждённого кандидата, решение владельца, выпуск и sync нового
  snapshot, успешный матч с прогнозными odds и повторное разрешение без
  дублирования observation. В цикле загрузчик подтверждает strict mode и
  возвращает пустой compatibility map.
- `uv run pytest -q tests/test_registry_candidate_capture.py::test_owner_decision_republished_snapshot_unlocks_odds`
  — 1 passed.
- `uv run ruff check` по затронутым production- и test-файлам — успешно.
- `uv run ruff format --check` по затронутым production- и test-файлам — успешно.
- `make docs` завершился успешно; Sphinx сообщил 24 предупреждения.
- После исправления import order `make lint` — passed.
- `uv run pytest -q tests/test_canonical_full_refresh.py tests/test_canonical_full_refresh_cli.py tests/test_event_readiness.py tests/test_registry_readiness.py` — 40 passed.
- `uv run pytest -q tests/test_nhl_legacy_yaml_cutover.py` — 8 passed; тест проверяет отсутствие отдельного `nhl_web_api/name`.
- `uv run pytest -q -m unit` — 1652 passed, 17 deselected.
- `uv run mypy --follow-imports=silent sports_forecast/service/registry_readiness.py sports_forecast/service/event_readiness.py` — passed.
- `make ai-validate` — passed; `git diff --check` — passed.
- Read-only parity CLI против доступного stage master из v1.3.1 и его snapshot
  `ir1:e4266bf9be668e1e666580b5f10bf9a81a0f623ab72a3d1535caa0403e6261ae`
  вернул `is_complete: true`, 100 source-scoped designation и ноль расхождений.
- Независимый Reviewer нашёл пропуск `nhl_web_api/name` в первом parity checker.
  После исправления и теста только этой связи повторное review не нашло P0–P2;
  `uv run pytest -q tests/test_nhl_legacy_yaml_cutover.py tests/test_registry_readiness.py tests/test_event_readiness.py tests/test_registry_candidate_capture.py`
  — 29 passed.

## Остаточные блокеры

Использованный master — staging артефакт выпуска v1.3.1, а не актуальная локальная
owner master; в worktree `data/registry/master.sqlite3` отсутствует. Его snapshot
не содержит project events. Поэтому эта сверка не подтверждает актуальный owner
master, и контрольный NHL event/forecast cycle на нём выполнить нельзя. TASK
остаётся `blocked` до появления доступной owner master/snapshot с NHL events и
повторной parity/cycle проверки. Production rollout и strict server reader этим
TASK не включались.
