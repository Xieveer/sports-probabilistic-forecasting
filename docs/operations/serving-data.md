# Serving-data archive и sync protocol

VPS не запускает DVC и не получает полный training dataset. Он формирует
runtime snapshots, архивирует их в Object Storage, а локальный контур только
после проверки забирает staging в DVC workflow. Обратный поток передаёт на VPS
только compact serving-data bundle с необходимым lookback state.

## Object Storage contract

Один bucket Yandex Object Storage разделяется префиксами:

```text
operational-archive/sha256:<content-hash>/manifest.json
operational-archive/sha256:<content-hash>/<runtime-files>
serving-data-bundles/sha256:<content-hash>/manifest.json
serving-data-bundles/sha256:<content-hash>/<lookback-files>
```

`manifest.json` содержит только schema version, immutable ID, UTC timestamp,
относительные пути, размеры и SHA-256. В нём нет ключей, URL с credential или
содержимого snapshot. Bucket policy: VPS имеет write только в
`operational-archive/` и read только в `serving-data-bundles/`; локальный
оператор имеет обратные права. DVC remote (`dvc/`) остаётся отдельным prefix.

Нужные имена окружения без значений: `SF_OBJECT_STORAGE_ENDPOINT`,
`SF_OBJECT_STORAGE_BUCKET`, `SF_OBJECT_STORAGE_ACCESS_KEY_ID`,
`SF_OBJECT_STORAGE_SECRET_ACCESS_KEY`, `SF_OPERATIONAL_ARCHIVE_PREFIX` и
`SF_SERVING_DATA_PREFIX`. Их выдаёт secret store; в `.env`, логи и manifests
значения не записываются.

## Операторский путь

На VPS соберите snapshot в отдельной директории, затем создайте immutable
локальный staging artifact:

```bash
uv run python -m sports_forecast.deploy.serving_data archive \
  --source /var/lib/sf/runtime/snapshot-20260809 \
  --archive-root /var/lib/sf/archive-staging
```

После проверки manifest отдельный sync process с write-only service account
загружает и remote-verify-ит получившийся `operational-archive/` prefix:

```bash
docker compose -f docker-compose.prod.yml --profile operational-sync run --rm archive-sync \
  sync \
  --archive /app/archive/operational-archive/sha256:<content-hash> \
  --state-root /app/sync-state \
  --prefix operational-archive
```

Он сохраняет durable `<artifact-id>.json` со статусом `failed` или `verified`.
Только `verified` разрешает cleanup staging/старых runtime snapshots; failure
оставляет artifact для retry. Cloud archive не удаляется автоматически.

Service account sync получает только `PutObject`/`GetObject` в
`operational-archive/*`; он не получает DVC prefix, DB, Telegram или model
bundle secrets. Эти четыре Object Storage переменные задаются только profile
sync process, не Worker: endpoint, bucket, access key ID, secret access key.

Локально сначала верифицируйте и дедуплицируйте archive:

```bash
uv run python -m sports_forecast.deploy.serving_data import \
  --archive /srv/archive/operational-archive/sha256:<content-hash> \
  --import-root data/archive-imports
```

Для read-only pull прямо из Object Storage используйте отдельную локальную
учётную запись и CLI `pull-training-input`: он создаёт тот же descriptor, но
не вызывает DVC.

```bash
uv run python -m sports_forecast.deploy.archive_sync_cli pull-training-input \
  --artifact-id sha256:<content-hash> \
  --download-root data/archive-downloads \
  --import-root data/archive-imports \
  --descriptor data/training-inputs/nhl-latest.json
```

Лишь успешно созданный staging может стать входом явной DVC-команды оператора;
невалидный archive не меняет `data/`, DVC cache или DVC revision.

Для зафиксированного training input используйте descriptor: команда повторно
проверяет archive, дедуплицирует import и только затем атомарно записывает
artifact ID, provenance и список partitions. Она не запускает DVC или training.

```bash
uv run python -m sports_forecast.deploy.serving_data training-input \
  --archive /srv/archive/operational-archive/sha256:<content-hash> \
  --import-root data/archive-imports \
  --descriptor data/training-inputs/nhl-latest.json
```

Оператор передаёт этот descriptor в DVC/experiment provenance перед ручным
обучением. Содержимое provider payload и Object Storage credentials в descriptor
не попадают.

Для обратного пути соберите только заранее доказанные lookback/state files,
загрузите bundle в `serving-data-bundles/`, затем на VPS выполните `install`.
Installer проверяет manifest до записи и поддерживает links `current` и
`previous`; контейнеры должны получать каталог bundle read-only. Rollback —
атомарно заменить `current` на проверенный `previous`, без удаления bundle.
