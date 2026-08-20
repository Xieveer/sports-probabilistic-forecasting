# NHL canonical full refresh

Runbook относится к `TASK-007-3`. Он описывает один bounded run после того,
как scheduler получил incremental NHL `source.csv`; topology, scheduler,
таймауты и credential boundaries определены в
[production-runtime-topology.md](production-runtime-topology.md) (`TASK-007-5`).

## Предусловия

- Versioned migrations применены до `0009_prediction_refresh_provenance`.
- `SF_CANONICAL_SOURCE_CSV` указывает на успешный текущий provider snapshot,
  а не на локальный historical backfill.
- `SF_MODEL_RUNTIME_ROOT/current` указывает на проверяемый immutable NHL model
  bundle, совместимый с `SF_APP_VERSION`.
- `SF_WORKER_RUN_ID` стабилен для одного scheduler logical run.

## Запуск

```bash
export SF_CANONICAL_SOURCE_CSV=/srv/sports-forecast/source/nhl/source.csv
export SF_WORKER_RUN_ID=nhl-20260815T100000Z
export SF_MODEL_RUNTIME_ROOT=/srv/sports-forecast/models
export SF_APP_VERSION=1.1.4
export SF_OPERATIONAL_ARCHIVE_ROOT=/srv/sports-forecast/archive-staging

uv run python -m sports_forecast.orchestration.canonical_full_refresh_cli \
  tournament=nhl market=winner_withOT market_spec=winner_withOT \
  algorithm=catboost features=basic
```

Run применяет source snapshot к canonical store, проверяет финальные результаты
прогнозов с истёкшим deadline, пересобирает full-history features/EWM во
временной директории и публикует predictions вместе с run/data/feature/model
provenance одной DB-транзакцией.

Только после успешного acquisition и canonical commit runner создаёт canonical
snapshot и полный source-state в
`$SF_OPERATIONAL_ARCHIVE_ROOT/operational-archive/nhl-source-state/v1/`.
Source-state содержит `source.csv`, OddsStore и checkpoint; `current.csv` не
архивируется. Затем scheduler вызывает отдельный `archive-sync`, который
remote-verify-ит каждый manifest/file. Failure provider/odds, canonical refresh
или upload оставляет предыдущий valid state и не заменяет последний verified
artifact.

Локальный read-only import последнего verified source-state выполняется
отдельным training-reader credential:

```bash
uv run python -m sports_forecast.deploy.archive_sync_cli pull-latest-source-state \
  --download-root /srv/sf-local/source-state-downloads \
  --import-root /srv/sf-local/training-inputs \
  --descriptor /srv/sf-local/training-inputs/latest.json \
  --prefix operational-archive/nhl-source-state/v1
```

Команда сначала получает manifest/files, проверяет checksum и только затем
создаёт local descriptor. DVC/training не запускаются автоматически; descriptor
содержит `odds/pinnacle_odds.parquet`, доступный betting-валидации.

## Failure и восстановление

- Non-zero exit code означает, что affected serving slice имеет `blocked`
  eligibility: API и Telegram его не выдают, а прежние prediction rows остаются
  для audit/recovery.
- Повтор того же `SF_WORKER_RUN_ID` или overlap не запускает второй rebuild.
- `canonical_freshness_failed` требует исправить provider snapshot; bundle или
  feature rebuild не запускаются.
- Для повреждённой модели используйте проверенный rollback bundle согласно
  `docs/operations/model-bundle.md`, затем создайте новый `run_id`.
- Для восстановления source-state выберите последний verified artifact через
  read-only local command, проверьте manifest/checksums и установите его
  командой из [canonical-bootstrap.md](canonical-bootstrap.md). Только после
  этого разрешается первый scheduler run.

Логи и DB state содержат только safe failure codes и identifiers; provider
payload, credentials и exception text не должны передаваться в Telegram.
