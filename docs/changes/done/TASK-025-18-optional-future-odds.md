# TASK-025-18 — Явное отключение future odds

> **Статус:** код и независимое review завершены; CI/runtime gate открыт
> **Задача:** [TASK-025-18](../../backlog/tasks/TASK-025-18-optional-future-odds.md)

## Граница

Внешний сбор коэффициентов в source post-step и future batch выключается
явной настройкой profile;
календарь, прогнозы и публикация работают без него. Результат остаётся
`partial_success` с видимым отсутствием коэффициентов.

## Доказательство

Red-тесты зафиксировали HTTP в source-acquirer и Worker при OFF. Green
проверяет default/ON/OFF, нулевые Odds API вызовы и попытки, сохранение
facts-only source snapshot, `data_odds=partial_success`, readiness
`missing` после старых failed attempts/observations, переходы OFF→ON и
football fixture. Developer: 139 целевых тестов; Reviewer: 67 целевых
тестов, P0–P2 после correction не осталось. Полный unit suite: 1227 passed,
13 deselected; `make lint`, `make production-check` и `make docs`
(155 warnings) прошли. PR CI и production gate открыты.

Проверенный content commit: `c8895fdb9fdb3ccba6c74a33373124fa2cefc4a0`.
Reviewer повторно выполнил `make pre-commit` и 67 целевых тестов перед
коммитом; оба gate прошли.
