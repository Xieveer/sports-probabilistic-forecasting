# TASK-032-1 — Production роли registry и prediction revisions

## Результат

После предпродового аудита добавлены отдельные PostgreSQL роли
`sf_registry_sync` и `sf_registry_feedback`, secret file contracts и явные
Compose профили для одноразового sync/publish. Worker получил только права,
которые нужны для runtime bridge, candidate capture и неизменяемых
`prediction_revisions`; API — чтение установленной registry projection.
First-rollout contract проверяет разрешённые и запрещённые права каждой роли.
Новые профили не запускаются при обычном production `up`.

## Проверки

- `uv run --offline pytest tests/test_production_first_rollout_contract.py tests/test_production_topology.py tests/test_readiness_and_migrations.py -q` — 63 passed.
- На disposable PostgreSQL 16: синтетический dump схемы `0017` восстановлен в отдельную БД, `alembic upgrade head` дошёл до `0025_real_bets_ledger`, `grant_runtime_roles()` выполнился успешно.
- `tests/test_runtime_db_role_privileges.py` с тестовыми DB URLs — 2 passed; `tests/test_registry_runtime_role_privileges.py` под отдельными ролями — 1 passed. Нулевые `INSERT`/`UPDATE` и `SELECT` под sync, feedback и Worker завершились без ошибок; отрицательные права проверены PostgreSQL catalog функциями.
- Пять тестовых файлов с live disposable PostgreSQL для Data Cycle race, managed activation и prediction revisions — 40 passed.
- Полный `uv run --offline pytest -q` после исправления — 1624 passed, 9 skipped; пропущенные PostgreSQL сценарии отдельно проверены выше, кроме локального цикла EPIC-028, которому нужен approved bundle.
- `make lint`, `make type-check`, `make production-check`, `make ai-validate`, `make docs`, `make pre-commit`, `sh -n deploy/postgres/init-roles.sh`, `git diff --check` — успешно. `make docs` выдал 155 предупреждений.
- `docker compose ... config` со всеми профилями и fixture `1.3.0`, затем `verify_production_compose_contract.py` — успешно.
- Повторное независимое review после исправления первичного P1 не нашло открытых P0–P2. Замечания к handoff и порядку bootstrap/migration в runbook исправлены и повторно проверены до commit.

## Ограничения

Тестовый dump синтетический; свежая production копия и server credentials не
использовались. Реальные публикация/sync/feedback и расписание относятся к
серверному gate [TASK-026-5](../../backlog/tasks/TASK-026-5-registry-publication.md).
`make security` не завершился: локальный доступ к PyPI для `pip-audit` отсутствовал.
Terminal PR/CI, tagged release и production rollout ещё не выполнялись.
