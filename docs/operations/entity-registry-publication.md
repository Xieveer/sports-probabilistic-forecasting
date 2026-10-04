# Публикация локального registry

Publisher запускается на доверенной локальной машине. Worker и API не получают
Object Storage credentials и не читают storage во время запроса.

Установите дополнительную группу зависимостей для отдельного процесса:

```bash
uv sync --group archive-sync
```

Задайте в окружении процесса `SF_OBJECT_STORAGE_ENDPOINT`,
`SF_OBJECT_STORAGE_BUCKET`, `SF_OBJECT_STORAGE_ACCESS_KEY_ID` и
`SF_OBJECT_STORAGE_SECRET_ACCESS_KEY`. Опционально задайте
`SF_OBJECT_STORAGE_REGION` (по умолчанию `ru-central1`) и
`SF_ENTITY_REGISTRY_ACTOR`. Не передавайте секреты в аргументах CLI и не
включайте shell tracing. Для контейнерных secrets задайте
`SF_OBJECT_STORAGE_ACCESS_KEY_ID_FILE` и
`SF_OBJECT_STORAGE_SECRET_ACCESS_KEY_FILE`; для каждой credential допускается
только один способ передачи. Загрузка использует connect timeout 5 секунд,
read timeout 120 секунд и до трёх стандартных попыток SDK.

Перед публикацией проверьте поддержку conditional writes на отдельном тестовом
bucket/prefix:

```bash
uv run python -m sports_forecast.deploy.registry_publish_cli probe \
  --prefix entity-registry-contract-probe
```

Probe проверяет создание через `If-None-Match: *`, сохранение исходных bytes при
конфликте, замену через `If-Match: <ETag>` и отказ для устаревшего ETag. Он пишет
уникальный объект в `<prefix>/probes/` и не удаляет его; задайте короткоживущий
отдельный prefix с правилами хранения для probe-объектов. Код завершения 0 подтверждает только
проверенные здесь условные PUT и GET для выбранного endpoint/bucket. Probe не
проверяет IAM grants на production prefix, lifecycle, отказоустойчивость,
server-side encryption или PostgreSQL installation.

Документация Yandex описывает оба заголовка для загрузки объекта:
[If-Match и If-None-Match в S3 API](https://yandex.cloud/en/docs/storage/s3/api-ref/object/upload)
и [условная загрузка объекта](https://yandex.cloud/en/docs/storage/operations/objects/upload).
Это подтверждает заявленный контракт сервиса; probe отдельно проверяет фактический
endpoint и bucket с используемыми настройками.

Публикация принимает путь к уже проверенному локальному immutable snapshot:

```bash
uv run python -m sports_forecast.deploy.registry_publish_cli publish \
  data/registry/snapshots/<sha256>
```

Publisher проверяет пакет локально, условно создаёт content-addressed объекты,
читает их обратно и сравнивает bytes с локальным пакетом, затем создаёт
immutable publication record. Только после этих шагов он условно меняет
`current.json`. Объекты старых snapshots и publications не удаляются.
Публикация ранее использованного snapshot создаёт новую возрастающую sequence и
тем самым оформляет rollback.

Immutable publication record содержит `publication_id`, `sequence`, `snapshot_id`,
`snapshot_sha256`, `previous_publication_id`, `published_at` (UTC) и `actor`.
Current pointer содержит эти идентификаторы без audit-полей `published_at` и
`actor`. Server sync может прочитать историю через `read_publication_by_id` и
скачать версию через `download_publication_snapshot`; каждый snapshot сохраняется
по digest и проходит полную проверку manifest и JSONL до установки.

Если ответ PUT `current.json` потерян, процесс перечитывает указатель. При
совпадении publication ID операция считается успешной; иначе команда сообщает
неизвестный результат и завершается без повторной безусловной записи. Publisher
сохраняет локальное pending intent рядом с lock; повторный запуск сверяет тот
же publication ID и удалённые bytes, затем завершает или возвращает явный
конфликт. Не удаляйте pending intent до успешного восстановления. Конкурирующая
запись приводит к ошибке CAS и не перезаписывается.
Endpoint без подтверждённых conditional writes закрывает публикацию ошибкой.

## Серверная установка

Отдельному sync-процессу задайте read-only Object Storage account через те же
имена переменных или `_FILE`, а PostgreSQL URL — через `DATABASE_URL_FILE`.
Не передавайте эти credentials в API, Worker или Telegram bot. Используйте
каталог скачивания, доступный только sync identity. Команда отказывает в работе
с неявной SQLite БД:

```bash
uv run python -m sports_forecast.deploy.registry_sync_cli \
  --download-root /var/lib/sports-forecast/registry-downloads
```

Sync закрепляет удалённый `current` один раз, проверяет непрерывную цепочку
publication records и скачивает недостающие пакеты. После проверки он
устанавливает всю цепочку одной PostgreSQL транзакцией. Ошибка оставляет
прежнюю active publication, в том числе при повреждении позднего пакета.
Повтор команды для уже установленной версии не меняет БД. Откат выполняется
локальной новой публикацией старого verified snapshot: её sequence выше, а
содержимое пакета остаётся прежним.

По умолчанию один sync ограничен 100 publication records, 2 GiB проверенных
пакетов и 300 секундами. Пределы задаются флагами `--max-chain-length`,
`--max-download-bytes` и `--max-duration-seconds`; превышение требует разбора
истории и явного запуска с обоснованным лимитом. Рекомендуемая эксплуатационная
cadence — раз в пять минут с jitter и без параллельных запусков. Runtime читает
установленный `ir1` из PostgreSQL и не ждёт Object Storage.

Для production Operations Agent должен создать отдельную DB role sync с
`SELECT` на `canonical_events` и registry projection, `INSERT` на immutable
registry tables, publication history и первую строку
`active_registry_installation`, `UPDATE` только active pointer и lock.
Таблицы lock, active pointer, publications и event bridge также требуют
явного `SELECT`; права на другие application tables не нужны.
API/Worker получают только нужный `SELECT` на установленную проекцию;
publisher не получает DB credential. Для bucket требуются отдельные prefix
grants: локальный publisher — условные `GetObject`/`PutObject` на
`entity-registry/v1/snapshots/`, `publications/`, `current.json`; server sync —
только `GetObject` на эти ключи. `DeleteObject` не нужен. Старые
`operational-archive/` grants и 90-дневный lifecycle не должны захватить этот
prefix. Проверка фактических IAM/DB grants, live endpoint probe и включение
расписания остаются эксплуатационными gates; в рабочем окружении credentials
для них не заданы. До этих gates production registry mode не включать.

Обратная доставка кандидатов находится в [TASK-026-6](../backlog/tasks/TASK-026-6-registry-candidate-feedback.md);
полный контракт описан в [ADR-027](../architecture/adr/ADR-027-local-entity-registry-and-snapshots.md).
