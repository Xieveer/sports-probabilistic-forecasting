# TASK-029-1 — Кандидат Premier League

> **Статус:** реализация, независимый review и первоначальный CI PR #67 завершены
> **Задача:** [TASK-029-1](../../backlog/tasks/TASK-029-1-premier-league-candidate.md)
> **Требование:** [REQ-029](../../product/requirements/REQ-029-premier-league-candidate.md)
> **Решение:** [ADR-030](../../architecture/adr/ADR-030-local-candidate-cycle.md)

## Изменено

- Файловый source и Hydra-профиль `premier_league` выделяют `ENG1` из локального
  CSV клубного футбола; odds из карточек Smart Tables превращаются в
  `odds_raw` только для исследовательского candidate.
- Каталог хранит название, код соревнования и параметры candidate-запуска.
  Одна команда вызывает общий ingest, clean, features, train и создаёт отчёт
  из проверенного MLflow run и его betting trace. При пустом входе, неверном
  соревновании или неполных метриках выдаётся ошибка без отчёта.
- Raw validation принимает исходное поле `match_id` Smart Tables до его
  преобразования в `id` на clean.
- Обновлены [руководство](../../cursor/context/HOW_TO_ADD_NEW_TOURNAMENT.md),
  [source-контракт](../../cursor/source_data/football.md) и README.

## Реальный результат

Команда `.venv/bin/python -m sports_forecast.orchestration.candidate
premier_league_winner` завершилась успешно на локальной копии
`data/source/football_top_leagues/source.csv`. В raw — 4 138 матчей, только
`ENG1`; в processed — 8 276 long-строк. Raw/interim/processed gate прошли.
[JSON-отчёт](../candidates/premier_league-winner-225af497fb37.json) содержит
MLflow run ID, хэш processed-файла, logloss 0,6416, AUC 0,6474,
Brier 0,2216, 267 ставок на 414 матчах (828 строк сторон) тестовой выборки,
coverage симулятора 64,49% и фактическое покрытие матчей 266/414 = 64,25%,
ROI −14,82%, bootstrap SE ROI 9,33 п.п. Тестовое окно 2025-05-25—2026-09-06
сформировано trailing split; прежнее поле `locked_holdout` удалено, так как
trainer его не применял.
Отчёт и каталог сохраняют `candidate`; promotion не запускался.

## Проверки

- Red: `tests/test_premier_league_onboarding.py` падал из-за отсутствия
  `conf/source/premier_league.yaml`; `tests/test_candidate_onboarding_report.py`
  не импортировался без нового модуля; raw-тест падал при `match_id` без `id`.
  После реализации все три сценария зелёные.
- Review выявил две ошибки P2: неподдерживаемое обещание `locked_holdout` и
  неверное описание coverage. Добавлены тест фактического test window и тест,
  различающий число ставок от числа уникальных матчей со ставкой; повторный
  реальный запуск создал исправленный отчёт.
- Повторный независимый review: P0–P2 нет; Reviewer проверил формулы и
  документацию, запустил 75 целевых тестов и `git diff --check`.
- Проверенный reviewer-коммит: `c189f5baed382b6c6dd66b50225a1539a2c44b8c`.
  Commit hooks (`ruff`, `ruff format`, `mypy`, AI roles and skills и проверки
  файлов) завершились успешно. Этот hash фиксирует проверенный код и отчёт.
- `.venv/bin/pytest -q` на девяти затронутых suites: **128 passed, 5 warnings**,
  включая Smart Tables, каталог, validation, model pool, NHL provider и бот.
- `.venv/bin/ruff check sports_forecast tests` — passed;
  `ruff format --check` для затронутых Python-файлов — passed;
  scoped `mypy --follow-imports=silent --disable-error-code import-untyped`
  для четырёх production-модулей — passed; `git diff --check` — passed.
- `.venv/bin/sphinx-build -q -b html docs/source /tmp/epic029-docs` — exit 0;
  предупреждения об offline intersphinx и существующих docstrings.
- На коммите `54e93b9` в [PR #67](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/67)
  прошли GitHub Actions `lint-test (3.12)`, `Python dependencies` и
  `Filesystem and secrets`; после фиксации этого результата изменена только
  документация закрытия, для неё требуется повторный terminal CI.
- Полный `.venv/bin/pytest -q` остановлен вручную после длительного ожидания
  на `tests/test_admin_control_api.py` (exit 130); полный suite не подтверждён.
  `uv run pytest` не стартовал из-за ограничений установленного snap `uv`,
  поэтому проверки выполнены через локальную `.venv`.

## Остаточные риски

Исторические odds Smart Tables не имеют подтверждённого времени получения,
букмекера и prematch-статуса. Bootstrap характеризует разброс симуляции на
этой истории, не реальную ожидаемую доходность. Локальный CSV и MLflow DB
не входят в Git; повторение требует их получения у владельца. Регулярный
refresh будущих матчей и production-публикация не выполнялись.
