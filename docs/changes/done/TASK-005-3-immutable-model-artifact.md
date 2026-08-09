# TASK-005-3 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-09
> **Задача:** [TASK-005-3](../../backlog/tasks/TASK-005-3-immutable-model-artifact.md)

## Реализованный результат

Добавлен immutable production model bundle. Его ID рассчитывается от полного
manifest payload: списка файлов и SHA-256, `model_identity`, версии приложения,
source commit и release. Проверка до использования сверяет состав, ID каталога,
compatibility и checksum каждого файла.

`install_model_bundle()` сначала проверяет bundle, затем атомарно меняет
symbolic pointer `current`, сохраняя прошлый проверенный bundle в `previous`.
`rollback_model_bundle()` проверяет `previous` и возвращает его без обучения или
удаления artifact. Явные операции доступны через
`python -m sports_forecast.deploy.model_bundle install|rollback`.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/deploy/model_bundle.py` | Создание, верификация, explicit promotion, rollback и read-only loader bundle. |
| `tests/test_model_bundle.py` | Контракты ID, checksum, compatibility, pointer и rollback. |
| `docs/operations/model-bundle.md` | Runbook bundle без deployment или доступа к секретам. |

Legacy NHL artifacts, обучение, MLflow/DVC и production deployment не изменялись.

## Доказательство TDD

- **Red:** import/вызовы bundle loader, install и rollback отсутствовали;
  первые contract tests завершались `ModuleNotFoundError`.
- **Green:** после реализации `tests/test_model_bundle.py` — 6 passed.
- **Refactor:** ID стал включать весь manifest payload, включая provenance;
  верификатор дополнительно запрещает абсолютные и traversal-пути из manifest.

## Фактически выполненные проверки

| Команда | Результат |
|---|---|
| `uv run pytest tests/test_model_bundle.py -q` | Успешно: 6 passed. |
| `uv run ruff check sports_forecast/deploy/model_bundle.py tests/test_model_bundle.py` | Успешно. |
| `uv run pre-commit run mypy --files sports_forecast/deploy/model_bundle.py tests/test_model_bundle.py` | Успешно. |
| `make lint` | Успешно. |
| `make test-unit` | Успешно: 829 passed, 8 deselected. |

## Остаточные риски и handoff

Loader сам не выполняет inference и не пишет predictions: при absent, corrupted
или incompatible bundle он выбрасывает `BundleVerificationError` до передачи
пути модели. TASK-005-4 должен вызвать `load_current_model_bundle()` первым
шагом bounded Worker, прежде materialization. Production Object Storage,
read-only mount и фактическая promotion на VPS не выполнялись: это требует
отдельного разрешения владельца.
