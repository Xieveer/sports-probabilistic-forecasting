# TASK-002-2 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-07
> **Задача:** [TASK-002-2](../../backlog/tasks/TASK-002-2-nhl-notification-state.md)

## Реализованный результат

Добавлен tournament-neutral внутренний контракт состояния уведомлений. Он
нормализует валидную линию, сохраняет baseline без рассылки, создаёт одну
предметную delta на logical cycle и исключает начавшиеся матчи. Персистентный
delivery ledger не резервирует повторно уже успешную доставку тому же chat ID,
но разрешает повтор неуспешного получателя.

Схема дополнена таблицами `notification_line_states`, `notification_cycles` и
`notification_deliveries`; таблица `predictions` не изменялась.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/orchestration/notification_state.py` | Внутренний контракт снимка линии, delta и logical cycle |
| `sports_forecast/service/db/models.py` | ORM-модели baseline, агрегированного события и delivery ledger |
| `sports_forecast/service/db/repository.py` | Персистентные операции состояния и retry-доставки |
| `tests/test_notification_state.py` | Contract- и SQLite-интеграционные проверки |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_notification_state.py -q` — ожидаемо завершилась
  ошибкой `ModuleNotFoundError` для ещё отсутствующего
  `sports_forecast.orchestration.notification_state`.
- **Green:** `uv run pytest tests/test_notification_state.py -q` — 4 passed.
- **Refactor:** canonical JSON устраняет влияние порядка ключей линии; repository
  вынесен отдельным классом после `PredictionRepository`, сохранив его публичные методы.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest tests/test_notification_state.py tests/test_prediction_repository_upcoming.py -q` | 7 passed |
| `uv run ruff check sports_forecast/orchestration/notification_state.py sports_forecast/service/db/models.py sports_forecast/service/db/repository.py tests/test_notification_state.py` | Успешно |
| `uv run ruff format --check sports_forecast/orchestration/notification_state.py sports_forecast/service/db/models.py sports_forecast/service/db/repository.py tests/test_notification_state.py` | Успешно |
| `make test-unit` | 736 passed, 8 deselected, 29 warnings |

## Документация, review и follow-up

- Документация: этот отчёт; новый публичный API, конфигурация и эксплуатационный
  контракт не добавлялись.
- Review / security: не выполнялось.
- Follow-up: интегрировать контракт с notification-профилем, formatter и Telegram
  transport в зависимых TASK; таблицы на существующем production PostgreSQL потребуют
  согласованной процедуры миграции до rollout.

## Остаточные риски

- Уникальные ограничения защищают committed данные, но межпроцессная гонка на создании
  одного logical cycle требует обработки конфликта интегратором либо будущего outbox при
  нескольких scheduler/executor-hosts.
- Best-effort ledger не исключает дубликат при аварии после принятия Telegram сообщения
  и до фиксации результата в БД — это риск, зафиксированный ADR-002.

## Обновление security и delivery (2026-08-08)

Закрыты findings повторного review в границах notification delivery и кэша
The Odds API. После успешной или неуспешной попытки Telegram repository выполняет
commit до обработки следующего получателя; это используется как для poll, так и
для initial digest с устойчивым daily logical cycle. Интеграционные retry-тесты с
отдельными SQLite-сессиями подтверждают, что уже отправленный chat ID не вызывается
повторно.
Initial CLI теперь получает batch-котировки Pinnacle для baseline. Пустой admin
allowlist является ошибкой, ошибка одного администратора не останавливает fan-out,
а chat ID маскируется в логах. Линия валидна только для конечных decimal-значений
строго больше единицы. При `use_cache=False` клиент не создаёт каталог кэша, а
включённый кэш использует SHA-256 ключа в имени файла.

### Дополнительные изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/orchestration/initial_notification.py` | fail-closed admin fan-out и маскирование chat ID |
| `sports_forecast/orchestration/initial_digest_cli.py` | batch-котировки для initial baseline |
| `sports_forecast/orchestration/odds_poll_notification.py` | маскирование chat ID в логе delta-delivery |
| `sports_forecast/orchestration/notification_state.py` | валидация decimal-коэффициентов |
| `sports_forecast/service/db/repository.py` | durable commit per recipient |
| `sports_forecast/data/providers/odds/client.py` | lazy cache и непрозрачные имена файлов |
| `tests/test_notification_state.py`, `tests/test_initial_notification.py`, `tests/test_odds_poll_notification.py`, `tests/test_odds_client.py` | воспроизводящие contract/integration тесты |

### Доказательство TDD обновления

- **Red:** `uv run pytest tests/test_notification_state.py tests/test_initial_notification.py tests/test_odds_poll_notification.py tests/test_odds_client.py -q` — 8 expected failures: невалидные decimal-линии, пустой/хрупкий admin fan-out, раскрытие ID и небезопасный кэш.
- **Green:** та же команда — 25 passed.
- **Refactor:** отдельный helper маскирования и единая SHA-256 нормализация имени кэша; новых внешних API не добавлено.

### Дополнительные фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest tests/test_notification_state.py tests/test_initial_notification.py tests/test_odds_poll_notification.py tests/test_odds_client.py -q` | 25 passed, 1 warning |
| `uv run ruff check …` (10 затронутых Python-файлов) | Успешно |
| `uv run ruff format --check …` (10 затронутых Python-файлов) | 10 files already formatted |
| `git diff --check` | Успешно |

### Остаточный риск обновления

- Коммит после ответа Telegram всё ещё не устраняет окно аварии между принятием
  сообщения Telegram и commit; это исходное best-effort ограничение ADR-002.
