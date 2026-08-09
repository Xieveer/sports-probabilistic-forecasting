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

После проверки manifest синхронизируйте получившийся `operational-archive/`
prefix штатным S3-инструментом Operations Agent. Только после подтверждённой
загрузки допустим cleanup: `prune --older-than-days 7`. Cloud archive не
удаляется автоматически.

Локально сначала верифицируйте и дедуплицируйте archive:

```bash
uv run python -m sports_forecast.deploy.serving_data import \
  --archive /srv/archive/operational-archive/sha256:<content-hash> \
  --import-root data/archive-imports
```

Лишь успешно созданный staging может стать входом явной DVC-команды оператора;
невалидный archive не меняет `data/`, DVC cache или DVC revision.

Для обратного пути соберите только заранее доказанные lookback/state files,
загрузите bundle в `serving-data-bundles/`, затем на VPS выполните `install`.
Installer проверяет manifest до записи и поддерживает links `current` и
`previous`; контейнеры должны получать каталог bundle read-only. Rollback —
атомарно заменить `current` на проверенный `previous`, без удаления bundle.
