# TASK-033-1 — Точечная диагностика логов

> **Задача:** [TASK-033-1](../../backlog/tasks/TASK-033-1-logging-diagnostics.md)
> **Требования:** [REQ-033](../../product/requirements/REQ-033-logging-diagnostics.md)
> **Статус:** локальная реализация завершена; повторное независимое review ожидается

## Изменено

- Повторный `configure_logging` применяет явный уровень без добавления обработчиков.
- Отказ бота больше не включает Telegram `user_id`.
- Ошибки Data Cycle CLI содержат доступные `run_id`, этап и код без текста
  исключения. Full refresh сопоставляет известные коды с фактическим этапом;
  неопределённый этап помечается `unknown`.
- Действующий локальный NHL-скрипт пишет в лог только код завершения digest и
  признак `stderr`, сохраняя прежний dry-run stdout и exit code.
- [Операционная инструкция](../../operations/observability.md) связывает историю
  запуска, systemd journal, container logs и release evidence.

## Red → green и проверки

- До исправлений пять новых проверок упали по ожидаемым причинам: игнорируемый
  уровень, Telegram ID, контекст двух ошибок цикла и полный `stderr` в логе.
- Первое review нашло неверный `stage=predictions` для ошибок quality/publication;
  расширенный тест упал на обоих кодах, затем прошёл после исправления.
- Дополнительный red/green проверил код terminal failure в lifecycle CLI.
  Повторное review нашло утечку произвольного отклонённого `--code`; отдельный
  red/green добавил проверку по существующему allowlist.
- Следующее review нашло такой же риск для `run_id` и `stage` в прямом вызове
  lifecycle CLI. Red воспроизвёл вывод произвольных значений; green ограничил
  `run_id` форматом UUID, а этап — перечнем Data Cycle stages.
- Целевой набор после исправлений: `uv run --offline --frozen pytest -q
  tests/test_log_config.py tests/test_bot.py tests/test_data_cycle_cli_logging.py
  tests/test_canonical_full_refresh_cli.py tests/test_run_nhl_refresh_notify.py`
  — 16 passed после третьего исправления.
- `UV_OFFLINE=1 make test-unit` — 1623 passed, 17 deselected до последних
  точечных исправлений; затронутые сценарии после них повторно прошли в целевом наборе.
- `UV_OFFLINE=1 make lint` и `UV_OFFLINE=1 make ai-validate` — прошли.
- `UV_OFFLINE=1 make type-check` — повторный запуск после последнего исправления прошёл.
- `UV_OFFLINE=1 make docs` — сборка успешна с 155 предупреждениями Sphinx.
- `git diff --check`, `ruff format --check` и проверка относительных ссылок
  пяти затронутых документов — прошли.

## Не менялось и остаточный риск

Формат всех логов, Alloy, БД, Docker logging driver, метрики, зависимости и
службы не менялись. Production-логи и фактическая конфигурация Alloy не
проверялись; сценарий расследования по известному failed run требуется проверить
после релиза. PR и deployment не выполнялись по просьбе пользователя.
