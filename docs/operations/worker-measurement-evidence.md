# Evidence измерения production Worker

Этот шаблон заполняется только после запуска на локальной production-like NHL
fixture с approved immutable model bundle и serving-data bundle. Он не является
свидетельством production deployment.

## Входные артефакты

| Поле | Фактическое значение |
|---|---|
| Model bundle ID | `sha256:7463e7dd0935f6f3138cad67078efad0f63072315e3077b9ad968e2c942efbf1` |
| Model identity | `legacy:nhl:winner_withOT:local-measurement` |
| Serving-data bundle ID | Не создавался: разрешённый локальный inference fixture. |
| Application image digest | Не создавался: локальный `uv run` без image. |
| Commit / release | `local-legacy` / `development-like` |
| Fixture match count / inference rows | 1 624 / 3 248 |

## Команда и результат

```bash
/usr/bin/time -f 'elapsed=%E max_rss_kb=%M exit=%x' \
  timeout 20m docker compose -f docker-compose.prod.yml --profile worker run --rm worker
```

| Показатель | Результат |
|---|---|
| UTC start/finish | 2026-08-09 19:43:17–19:43:20 (локально) |
| Exit code | 0 |
| Elapsed | 4.48 сек. |
| Max RSS | 409 152 KiB (≈399.6 MiB) |
| `worker_executions` safe outcome | `local-measurement-20260809 / succeeded / 1624 / null` |
| SQLite prediction count до/после | 0 / 1 624 |
| Повтор того же run_id | Подтверждён unit-тестом `test_completed_run_is_not_materialized_twice`. |
| Fail-path (tampered bundle) | Подтверждён unit-тестом `test_worker_verifies_bundle_before_materialization`. |

## Решение

Измерение не превысило 20 минут и осталось ниже `2048m` container limit. Это
локальное development-like evidence по явному разрешению владельца, а не
production deployment, image evidence или проверка Object Storage mount.
