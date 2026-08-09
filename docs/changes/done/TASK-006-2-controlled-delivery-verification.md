# TASK-006-2 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-09
> **Задача:** [TASK-006-2](../../backlog/tasks/TASK-006-2-controlled-delivery-verification.md)

## Реализованный результат

Добавлена отдельная операторская команда
`python -m sports_forecast.orchestration.delivery_verification`. Она не делает
внешних вызовов без обязательного `--send`; при явном запуске обращается к
Telegram ровно один раз, только к `SF_DELIVERY_VERIFICATION_CHAT_ID` из secret
environment. Сообщение содержит identity release image и модели, но не является
прогнозом или регулярным digest.

Команда не подключена к CI, Airflow scheduler или non-mutating acceptance.
При ошибке нет автоматического retry: повтор возможен только после проверки
причины и нового явного запуска оператора. В stdout и логах не выводятся token,
chat ID или тело ответа Telegram.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/orchestration/delivery_verification.py` | Явный одноразовый CLI-сценарий и безопасные статусы результата. |
| `tests/test_delivery_verification.py` | Контракты opt-in, одного recipient, redaction, failure и отсутствия автоматического запуска. |
| `.env.example`, `docs/operations/production-handoff.md` | Имя secret-конфигурации и безопасный операторский runbook. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_delivery_verification.py -q` до реализации
  завершался ошибкой импорта отсутствующего модуля.
- **Green:** после реализации контрактные tests прошли; transport вызывается
  только с `--send`, а неуспешный ответ не объявляется доставкой.
- **Refactor:** transport остался изолирован в существующем adapter; CLI не
  добавляет scheduler, retry или хранение секретов.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest tests/test_delivery_verification.py tests/test_acceptance_check.py -q` | Успешно: 7 passed. |
| `uv run ruff format sports_forecast/orchestration/delivery_verification.py tests/test_delivery_verification.py && uv run ruff check sports_forecast/orchestration/delivery_verification.py tests/test_delivery_verification.py` | Успешно. |
| `uv run pre-commit run mypy --all-files` | Успешно. |
| `make docs` | Успешно; текущий запуск сообщил одно предупреждение об отсутствующем `_static`. |
| `make test-unit` | Успешно: 848 passed, 8 deselected. |
| `make security` | Успешно: `No known vulnerabilities found`. |
| `make production-check` | Успешно: `Production handoff is valid.` |

## Не выполнено и handoff

Внешняя Telegram-отправка, rollout и подтверждение владельца намеренно не
выполнялись. Они остаются в [TASK-006-3](../../backlog/tasks/TASK-006-3-authorized-rollout-and-first-delivery.md)
и требуют immutable image evidence из TASK-006-1 и отдельного разрешения на
deployment/отправку.

## Остаточные риски

- CLI доказывает технический ответ Telegram, но не заменяет подтверждение
  владельца о фактическом получении сообщения.
- Фактический запуск возможен только в разрешённом production environment с
  secret environment; секреты и VPS в этой задаче не использовались.
