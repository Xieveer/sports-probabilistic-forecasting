# Production materialization Worker

Worker — одноразовый bounded контейнер для NHL `winner_withOT`. Он не запускает
training, Optuna, MLflow, DVC или migration. До inference он читает только
`current` immutable model bundle, проверяет manifest/checksum/версию приложения
и завершает запуск без записи predictions при ошибке проверки.

## Scheduler contract

Scheduler в инфраструктурном репозитории ежедневно в 10:00 МСК генерирует
безопасный уникальный `SF_WORKER_RUN_ID` (например, `daily-20260809`), задаёт
`SF_APP_VERSION` ровно равной application version release и запускает:

```bash
timeout 20m docker compose -f docker-compose.prod.yml --profile worker run --rm worker
```

Значение `20m` — внешний hard timeout scheduler; Compose также ограничивает
Worker `2.0` CPU и `2048m` памяти. Не использовать `up` для Worker: повторный
run с тем же ID не публикует витрину второй раз.

| Итог | `worker_executions.status` | Действие scheduler |
|---|---|---|
| Успех | `succeeded` | Сохранить безопасный run_id/count, затем разрешить digest. |
| Bundle или materialization error | `failed` | Не запускать digest; alert владельцу без payload и secrets. |
| Timeout/no fresh success | `failed` или stale по monitoring | Не изменять предыдущую витрину; alert и разбор. |

`worker_executions` содержит только run ID, timestamps, счётчик predictions и
allow-listed failure code. Тексты исключений, ключи и payload внешних источников
в state не записываются.

## Порядок запуска и откат

Перед Worker Operations Agent выполняет backup, migration и `/ready` согласно
[database-migrations.md](database-migrations.md). Bundle устанавливается
отдельной явной командой из [model-bundle.md](model-bundle.md); Worker имеет
только read-only mount `/app/models`.

Если любой шаг до DB publish неуспешен, последняя валидная API-витрина остаётся
активной. Stale+upsert одного tournament/market/spec выполняются в одной
транзакции. Реальная периодичность, фактическое измерение и alert routing
остаются evidence TASK-005-6 и Operations Agent; этот документ не разрешает
deployment.
