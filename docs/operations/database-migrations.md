# Versioned migrations Prediction Store

Schema PostgreSQL изменяет только Alembic. API и Worker не вызывают DDL при
старте. Все revision additive; destructive downgrade не поддерживается.

## Порядок production-операции

1. Убедитесь, что `db` healthy и сохраните проверяемый backup вне VPS:

   ```bash
   docker compose -f docker-compose.prod.yml exec -T db \
     pg_dump -U sf_user -Fc sports_forecast > sports_forecast-pre-migration.dump
   ```

2. Примените migration одноразовым API-контейнером до запуска API и Worker:

   ```bash
   docker compose -f docker-compose.prod.yml run --rm --no-deps api \
     uv run alembic -c alembic.ini upgrade head
   ```

   Для локальной базы эквивалентная команда: `make db-migrate`.

3. Запустите API, дождитесь `curl -sf http://127.0.0.1:8000/ready`, затем
   разрешайте одноразовый Worker. `/health` проверяет только liveness процесса.

## Проверка и recovery

Перед изменением или после прерванной операции узнайте состояние revision:

```bash
docker compose -f docker-compose.prod.yml run --rm --no-deps api \
  uv run alembic -c alembic.ini current
```

Alembic хранит revision в `alembic_version`: отсутствие expected revision или
ошибка `upgrade head` означает частично применённую migration. Не выполняйте
`downgrade`. После устранения причины (например, свободного места или
недоступности БД) повторите `upgrade head`: уже применённые revisions будут
пропущены, а незавершённые завершены forward-fix migration.

Если forward-fix невозможен, Operations Agent восстанавливает pre-migration
backup в изолированном окне, проверяет `alembic current`, применяет `upgrade
head` и только затем возвращает API/Worker. Для legacy schema, созданной до
Alembic через `init_db()`, сначала сравните schema с revision `0001` на
disposable PostgreSQL и только после этого вручную выполните `alembic stamp
0001_prediction_store_baseline`; без этой проверки stamping запрещён.
