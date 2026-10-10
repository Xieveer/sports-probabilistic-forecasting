# TASK-028-2 — Проверяемый manifest v2 и legacy compatibility

## Результат

Добавлен `build_managed_model_bundle()` для сборки schema v2 и typed
`VerifiedModelBundle` для проверенного managed-контракта. Manifest content hash
включает пару model pool / market spec, явные правила рынка и outcomes,
feature contract ID, порядок и типы признаков, версию преобразований, алгоритм,
точный относительный entrypoint, app version и checksums файлов.

Verifier отклоняет неизвестный или пустой алгоритм, пустые обязательные поля,
неявные/несогласованные правила рынка, traversal и дубликаты путей, отсутствующий
entrypoint, повреждённые, лишние или неучтённые файлы, несовпадающие
`deploy.yaml`/`features.txt` и несовместимую версию приложения. Для рынка с ничьей
ожидаются три исхода; для бинарного — `home_win / away_win`. Профиль
`winner_withOT` задаёт overtime явно и draw=false.

`build_model_bundle()` и manifest v1 сохранены без изменения hash-контракта.
V1 по-прежнему возвращает прежний `ModelBundle`, а v2 — расширенный тип с полями
managed contract. Установка и rollback прежнего v1 bundle остаются совместимыми.

## Red → green → refactor

- **Red:** `uv run pytest -q tests/test_model_bundle.py -k 'manifest_v2'` завершился
  ошибкой импорта `build_managed_model_bundle`: тесты описывали ещё отсутствующее
  поведение v2.
- **Green:** targeted suite прошёл после реализации builder/verifier. Тесты
  проверяют roundtrip, неизменность ID при том же контракте, изменение ID при
  изменении market, invalid algorithm/path/outcomes, несовпадение compatibility
  files и повреждение model bytes.
- **Refactor:** контрактная валидация вынесена в helper и выполняется до записи
  bundle-каталога. Документация формата и legacy пути обновлена.

## Проверки

- `uv run pytest -q tests/test_model_bundle.py tests/test_worker.py tests/test_materialize.py` — 37 passed.
- `make lint` — Ruff: All checks passed.

## Границы и риски

- Изменены `sports_forecast/deploy/model_bundle.py`,
  `tests/test_model_bundle.py`, `docs/operations/model-bundle.md`, TASK и этот
  отчёт.
- Не изменялись registry/DB pointer, Worker/materialize, миграции, API, production
  bundle и артефакты моделей. Реальная загрузка одобренного NHL CatBoost и локального
  LightGBM остаётся следующим отдельным gate EPIC-028; TASK-028-2 проверяет
  структурный контракт без весов модели.
- Manifest v2 — внутренний формат на этом этапе; интеграция в managed activation
  выполняется TASK-028-3. Независимый review и PR не выполнялись.
