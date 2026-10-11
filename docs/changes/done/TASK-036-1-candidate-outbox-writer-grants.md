# TASK-036-1 — Права Worker на запись кандидата registry

> **Статус:** done — исправление подготовлено; production gate ожидается
> **Задача:** [TASK-036-1](../../backlog/tasks/TASK-036-1-candidate-outbox-writer-grants.md)

## Изменения

- Идемпотентные runtime grants выдают Worker `SELECT` только на поля,
  возвращаемые ORM `INSERT` кандидатной очереди: `id`, `attempts`, `created_at`.
- Release probe теперь вставляет реальную строку через `INSERT ... RETURNING`
  внутри rollback-транзакции.
- Добавлен интеграционный тест реальной ORM записи под ролью Worker.
- Runbook миграций описывает причину и способ проверки.

## Доказательства

- Production preflight v1.3.2 до исправления: ORM `flush()` завершился
  `InsufficientPrivilege`, транзакция откатилась; это red case.
- Disposable PostgreSQL 16 с Alembic head и runtime grants: оба теста
  `test_registry_runtime_role_privileges.py` прошли под четырьмя runtime
  ролями, включая реальный ORM `flush()` и запрет чтения `payload_json` Worker.
- На той же disposable БД прямой `INSERT ... VALUES ... RETURNING` под Worker
  прошёл, а после `ROLLBACK` в outbox осталось 0 строк.
- `PYTHONPATH=. ../epic-035-v1-3-2-release/.venv/bin/pytest -q tests/test_registry_runtime_role_privileges.py tests/test_production_first_rollout_contract.py tests/test_readiness_and_migrations.py`:
  39 passed, 2 skipped без URL disposable PostgreSQL для этого запуска.
- `../epic-035-v1-3-2-release/.venv/bin/ruff check sports_forecast tests`:
  passed. `make lint` в новом worktree не смог создать `.venv` из-за временной
  ошибки DNS при запросе `setuptools`; проверка выполнена тем же установленным
  окружением соседнего worktree.
- `PYTHONPATH=. ../epic-035-v1-3-2-release/.venv/bin/sphinx-build -q -b html docs/source docs/build`:
  exit 0; сборка сообщает прежние предупреждения Sphinx.
- `../epic-035-v1-3-2-release/.venv/bin/python scripts/validate_ai_layer.py`:
  exit 0. Commit hook `ai-layer` с `uv run` не смог загрузить `setuptools`
  из PyPI из-за временной ошибки DNS; остальные commit hooks прошли.

## Остаточный gate

На production повторить migration/grants из проверенного образа и непустой
цикл кандидат → решение владельца → publication/sync. До него EPIC-036 и
EPIC-026 остаются открытыми.

## Независимый review

Reviewer повторно проверил полный diff TASK-036-1 и связанные изменения
EPIC-035/036, runbook и backlog: блокирующих findings нет. Проверенный
commit: `1e6675db67cddf5ae473a1d2aa0c35e59480985a`.
