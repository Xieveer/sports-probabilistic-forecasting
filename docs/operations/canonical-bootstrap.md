# Initial canonical bootstrap NHL

Этот runbook относится к `TASK-007-1` и будущему release `1.1.0`. Он позволяет
один раз доставить уже собранную локальную NHL-историю на VPS без повторного
обращения к NHL API. Выполнение не является разрешением на deployment.

## Граница и безопасность

- В bundle входят только строки документированного NHL `source.csv`, canonical
  envelope и manifest/checksum. Features, models, DVC cache, MLflow state,
  secrets и provider payload-логи не входят.
- Локальный оператор создаёт artifact; VPS импортирует только уже переданный
  immutable каталог. Перед import должен быть выполнен versioned database
  migration и сделан backup production DB по
  [database-migrations.md](database-migrations.md).
- Bundle проверяется до первой DB-записи. Повтор того же artifact ID безопасен
  и не дублирует события/revisions.

## Локальная сборка

Полный локальный файл должен отвечать NHL source contract из
`docs/cursor/source_data/nhl.md` и содержать как минимум `id`, `datetime` и
`match_is_end`.

```bash
uv run python -m sports_forecast.deploy.canonical_bootstrap build-nhl \
  --source-csv data/source/nhl/source.csv \
  --bundle-root /srv/sf-bootstrap-staging
```

Команда выводит content-addressed `sha256:<id>`. Перед передачей на VPS оператор
проверяет artifact штатным Object Storage/SCP процессом, не передавая `.env`,
DVC remote credentials или модельные файлы.

## VPS import

После успешной миграции и доставки immutable каталога задаётся только обычный
`DATABASE_URL` из secret environment и выполняется:

```bash
uv run python -m sports_forecast.deploy.canonical_bootstrap import-nhl \
  --bundle /srv/sf-bootstrap/operational-archive/sha256:<id>
```

Успех записывает canonical events, immutable revisions, bootstrap audit и NHL
watermark одной транзакцией. При ошибке checksum или схемы DB не получает
partial history. Следующие source refresh и full-history feature rebuild
выполняются только задачами `TASK-007-2` и `TASK-007-3`.
