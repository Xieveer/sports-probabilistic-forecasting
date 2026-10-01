# TASK-025-34 — Отчёт Developer: Data Cycle из архивированного входа

> **Статус:** локальная реализация и review выполнены; CI и production gate
> ожидаются.
> **Дата:** 2026-10-01
> **Задача:** [TASK-025-34](../../backlog/tasks/TASK-025-34-data-cycle-source-first.md)
> **Решение:** [ADR-028](../../architecture/adr/ADR-028-data-cycle-source-before-features.md)

## Результат

Runner после source acquisition запускает отдельный canonical import/quality,
создаёт два immutable artifact и descriptor с ID текущего run. Host sync
выбирает только эти два ID, подтверждает удалённую целостность, затем Worker
читает проверенный canonical artifact и строит признаки. ID архива входит в
provenance предиктов. Прежняя DB-транзакция materialization и publication
state сохранена. Daily `data_odds` не запрашивается, stage `skipped` не снижает
успешный итог. `/predict` продолжает получать live Pinnacle независимо от run.

Пустой подтверждённый inference теперь записывается как пустой parquet и
очищает активный showcase; некорректный непустой inference не очищает его и
завершается ошибкой. Архивный sync при ошибке блокирует Worker.
Пропущенная `data_odds` содержит `disabled=1`, чтобы календарь после нового
цикла не наследовал настройку сбора коэффициентов от старого запуска.

## Red → green → refactor

- `test_auto_success_accepts_intentionally_skipped_optional_odds`: red
  `partial_success`, green `success` после изменения policy.
- `test_empty_inference_replaces_showcase_with_empty_slice`: red — прежний
  `ok` прогноз оставался активным; green — 0 активных строк.
- `test_inference_only_writes_empty_tables_when_no_upcoming_match`: red —
  `FileNotFoundError`; green — оба пустых parquet доступны.
- `test_nonempty_inference_without_both_sides_does_not_clear_showcase`: red —
  ожидаемая ошибка не возникала; green — ошибка и сохранение прежнего ряда.
- Новый тест run descriptor проверяет точные два пути и отклонение отсутствующего
  artifact; тест prepared Worker проверяет отсутствие вызова future odds и
  provenance ID. Ruff format применён к затронутым Python-файлам.
- Повторное review нашло P2 в календарной готовности: skipped stage не имела
  `disabled=1`. Добавлены counts и регрессия перехода старый enabled run →
  новый skipped run; адресные 13 тестов прошли, повторное review чистое.

## Фактические проверки

| Проверка | Результат |
|---|---|
| `make lint` | passed |
| `make test-unit` | 1 259 passed, 13 deselected, 40 warnings после обновления версии и исправления calendar P2 |
| `uv run pytest -q tests/test_materialize.py tests/test_features_inference_only.py` | 10 passed |
| `uv run pytest -q tests/test_canonical_run_input.py tests/test_canonical_full_refresh.py` | 20 passed |
| `bash -n deploy/systemd/run-canonical-refresh.sh`, `git diff --check` | passed |
| Независимый Reviewer | найденные P1/P2 устранены; финальная проверка provenance без новых findings, 7 адресных тестов passed |

## Ограничения и следующий gate

- Текущий runner реализован для NHL; REQ/ADR задают общий контракт для
  последующего подключения турниров без обязательной daily odds стадии.
- Production v1.2.12 не менялась. Read-only проверка VPS подтвердила, что
  последний run `7ae3909e-73f7-473b-ab54-22909fda2cad` завершён
  `partial_success`, обе timers выключены и active run нет.
- Владелец подтвердил модельную политику для 124 исторических матчей иных
  NHL `game_type`: хранить, но исключать из модели. Реализацию и review
  завершает TASK-025-33 до ручного production запуска. Выпущенная модель не
  переобучалась. CI после этого уточнения, release evidence, ручной
  production cycle и timer gate остаются открытыми.
