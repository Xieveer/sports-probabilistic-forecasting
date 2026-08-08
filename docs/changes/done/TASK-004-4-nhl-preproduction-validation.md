# TASK-004-4 — отчёт о выполнении

> **Статус задачи:** done (`CONDITIONAL GO`)
> **Дата:** 2026-08-09
> **Задача:** [TASK-004-4](../../backlog/tasks/TASK-004-4-nhl-preproduction-validation.md)

## Результат

NHL pre-production проверка подтвердила дозагрузку 8 матчей завершившегося сезона.
Источник не опубликовал будущий календарь, поэтому readiness вернул штатный
`no_upcoming_schedule`; materialization и Odds API не запускались.

Версия package/API — `1.0.0`; Docker workflow принимает будущий `v1.0.0` и
формирует SemVer/SHA-теги. Docker runtime непривилегированный, а `uv` закреплён
по digest. Production handoff имеет статус `candidate`.

## Фактически выполненные проверки

| Команда | Результат |
|---|---|
| NHL readiness refresh | 8 матчей получены; будущего расписания нет |
| `make production-check` | Успешно |
| `make lint` | Успешно |
| `make test-unit` | Успешно: 786 passed, 8 deselected |
| `make security` | Успешно: `pip-audit` не сообщил уязвимостей |
| `make docs` | Успешно; 27 существующих предупреждений Sphinx, без ошибок |
| `docker build --target api --tag sports-forecast-api:local-review .` | Успешно; runtime-пользователь образа — `sf` |
| `uv run pre-commit run mypy --all-files` | Неуспешно: 22 ранее существовавшие ошибки в 11 незатронутых файлах; follow-up: TASK-004-5 |

После завершения [TASK-004-5](../../backlog/tasks/TASK-004-5-mypy-baseline.md) полный mypy проходит успешно;
`make lint`, `make security` и `make production-check` также повторно пройдены.

Dockerfile также проверен с устанавливаемым package `1.0.0`: до копирования
исходного кода зависимости устанавливаются с `--no-install-project`, а после
копирования выполняется финальная установка самого проекта. Это сохраняет
воспроизводимость `uv.lock` и устраняет ошибку сборки на шаге зависимостей.

Операционная документация и README синхронизированы с контрактом трёх ключей
The Odds API, включая порядок использования и проброс в Airflow.

## Решение о выпуске

**CONDITIONAL GO.** Application-часть готова к передаче DevOps Operations Agent.
Git tag `v1.0.0`, publish immutable images, фиксация image digest и deployment
не выполнялись и требуют отдельного явного разрешения владельца.

Дополнительный blocker безусловного release gate — красный полный mypy baseline;
он выделен в [TASK-004-5](../../backlog/tasks/TASK-004-5-mypy-baseline.md).
