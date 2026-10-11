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

Для нового NHL/Pinnacle рынка сначала завершите локальную миграцию owner
master и seed по [инструкции](identity-registry-local.md), затем проверьте
`manifest.json`: `format_version=2`, `registry_schema_version=12`, в списке
файлов есть `market_rules.jsonl`. Название Object Storage prefix остаётся
`entity-registry/v1`, а ID пакета — `ir1:<sha256>`: версия формата явно
зафиксирована внутри manifest. Старые проверенные пакеты имеют format v1 /
schema 11 и остаются доступными. Публикация не является миграцией master
SQLite и не меняет установленный PostgreSQL snapshot сама по себе.

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

### Переход v1 → v2

Перед публикацией v2 убедитесь, что новый sync image с поддержкой обоих
форматов установлен и проверен в release gate. Production `registry-sync`
v1.3.1 принимает только v1/schema 11. Если опубликовать v2 при работающем
старом пятиминутном timer, следующие sync ticks будут завершаться ошибкой.
В контролируемом окне временно остановите старый sync timer, сохраните его
состояние для восстановления, подготовьте новый бинарник и только затем
публикуйте verified v2 package. До переключения strict reader подтвердите
server sync, active publication sequence/snapshot ID, market rule
NHL/Pinnacle `h2h → winner_withOT` и реальное присоединение линии. Новый
reader должен сначала безопасно прочитать действующий v1 snapshot, затем v2.
Другие runtime timers и старые immutable objects сохраняются до GO.

На 2026-10-11 после staged v1.3.4 active publication имеет sequence `3`,
snapshot `ir1:71897173e0ee72bb60f9038cc8570770b351d866a3f994e63ba26bf5bcfe03e2`
формата v2/schema 12. Предыдущая verified v1 publication с sequence `2`
сохранена для возврата. Следующая публикация получает возрастающую sequence;
не предполагайте её номер без повторного чтения `current.json`. После server
sync сверяйте pinned указатель read-only запросом к
`active_registry_installation` и код выхода `registry-sync.service`.

Начиная с v1.3.4, production Compose передаёт
`SF_REGISTRY_EVENT_READER_ENABLED` в API, Telegram bot, source-acquirer и
Worker. На текущем VPS единственный актуальный Compose profile —
`/etc/sports-forecast/refresh/nhl.env`: из него запускаются API/бот и
systemd Data Cycle с одноразовыми Worker/source-acquirer. Файл
`/etc/sports-forecast/runtime.env` устарел и не проходит полный Compose
render; не используйте его для релиза. На staged запуске задайте `false`;
после успешного v2 sync, market rule и smoke — `true`. Перед каждым switch
из каталога `/opt/sports-forecast` проверьте rendered Compose для
ожидаемого значения (`false` на stage, `true` при включении):

```bash
set -euo pipefail
expected=true
docker compose --env-file /etc/sports-forecast/refresh/nhl.env \
  -f docker-compose.prod.yml --profile worker --profile source-acquisition \
  config --format json \
  | jq --exit-status --arg expected "$expected" \
    '[.services.api, .services["telegram-bot"], .services["source-acquirer"], .services.worker]
     | all(.[]; .environment.SF_REGISTRY_EVENT_READER_ENABLED == $expected)' \
    >/dev/null
```

Для v1.3.5 также проверьте, что Worker и source-acquirer получают
одинаковый `SF_ENTITY_REGISTRY_INSTALLATION_ID` из этого profile: именно эти
процессы создают записи кандидатов при неизвестных обозначениях. Значение
должно быть UUID и совпадать с установленным registry. Проверка выполняется
через rendered Compose с подавлением полного вывода:

```bash
expected_id=$(sed -n 's/^SF_ENTITY_REGISTRY_INSTALLATION_ID=//p' /etc/sports-forecast/refresh/nhl.env)
docker compose --env-file /etc/sports-forecast/refresh/nhl.env \
  -f docker-compose.prod.yml --profile worker --profile source-acquisition \
  config --format json \
  | jq --exit-status --arg expected "$expected_id" \
    '(.services.worker.environment.SF_ENTITY_REGISTRY_INSTALLATION_ID == $expected)
     and (.services["source-acquirer"].environment.SF_ENTITY_REGISTRY_INSTALLATION_ID == $expected)' \
    >/dev/null
```

Проверка не выводит rendered Compose: он содержит secret paths и другую
конфигурацию. После изменения пересоздайте API/бот и запустите новый
одноразовый цикл Worker/source-acquirer. Значения принимаются только как
явные `true`/`false`; неверное значение вызывает ошибку при чтении.
Для rollback сначала верните `false` в актуальный profile, проверьте Compose
render и пересоздайте API/бот, затем публикуйте verified v1 snapshot как
новую sequence и возвращайте v1.3.1.

Для отката **сначала** новым publisher опубликуйте этот сохранённый verified
v1 snapshot как новую publication с ещё большей sequence, выполните sync
новым бинарником и убедитесь, что PostgreSQL pinned на v1. Лишь затем
возвращайте v1.3.1 source/images и старый sync timer. Уменьшать sequence,
переписывать `current.json` вручную, удалять v2 package или его publication
нельзя. Возврат старого приложения без возврата v1 snapshot оставит его sync
несовместимым с v2.

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

Для production migration profile создаёт отдельную DB role `sf_registry_sync` с
`SELECT` на `canonical_events` и registry projection, `INSERT` на immutable
registry tables, publication history и первую строку
`active_registry_installation`, `UPDATE` только active pointer и lock.
Таблицы lock, active pointer, publications и event bridge также требуют
явного `SELECT`; права на другие application tables не нужны.
API получает только нужный `SELECT` на установленную проекцию. Worker дополнительно
создаёт event mapping и кандидатов обратной очереди, поэтому получает узкие
`INSERT` на bridge/outbox и sequence usage, но не права на переключение active
publication. Отдельная роль `sf_registry_feedback` читает и отмечает только
outbox/batch sequence; она не читает `canonical_events` и не получает права
на prediction/data-cycle tables. Фактические права проверяются под каждой
ролью после миграции.
Локальный publisher не получает DB credential. Для bucket требуются отдельные prefix
grants: локальный publisher — условные `GetObject`/`PutObject` на
`entity-registry/v1/snapshots/`, `publications/`, `current.json`; server sync —
только `GetObject` на эти ключи. `DeleteObject` не нужен. Старые
`operational-archive/` grants и 90-дневный lifecycle не должны захватить этот
prefix. На 2026-10-09 live endpoint probe, IAM grants и lifecycle текущего
bucket проверены. Релиз v1.3.1 подтвердил доставку выделенных server credentials,
PostgreSQL grants, первую публикацию, sync, zero-work feedback и плановые ticks;
см. [EPIC-026](../backlog/EPIC-026-entity-registry.md). Strict reader остаётся
выключенным до проверки покрытия NHL горизонта, непустого кандидатного цикла и
отката в релизное окно по
[TASK-026-10](../backlog/tasks/TASK-026-10-strict-reader-rollout.md).

Контейнерные one-shot команды используют явные Compose профили
`registry-sync` и `registry-feedback`. Их DB URL и Object Storage credentials
передаются отдельными secret files; обычный `docker compose up` их не запускает.
До вызова sync Operations Agent подготавливает доступный UID 10001 каталог
`SF_REGISTRY_SYNC_DOWNLOAD_ROOT`, проверяет свободное место и предоставляет
`SF_REGISTRY_SYNC_DATABASE_URL_FILE`,
`SF_REGISTRY_SYNC_OBJECT_STORAGE_ACCESS_KEY_ID_FILE` и
`SF_REGISTRY_SYNC_OBJECT_STORAGE_SECRET_ACCESS_KEY_FILE`.
После `role-bootstrap` и `migrator` одноразовый sync запускается так:

```bash
docker compose --env-file /etc/sports-forecast/refresh/nhl.env -f docker-compose.prod.yml \
  --profile registry-sync run --rm registry-sync
```

Команда не означает включения расписания. Его настраивают только после
проверенного первого sync и обратного цикла.

Обратная доставка кандидатов находится в [TASK-026-6](../backlog/tasks/TASK-026-6-registry-candidate-feedback.md);
полный контракт описан в [ADR-029](../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md).

## Обратная очередь и решение владельца

Начиная с v1.3.6, календарный NHL capture создаёт словарные candidates
только для матчей с UTC стартом от суток до текущего времени до 30 дней
вперёд. Отсутствие постоянной owner event-связи не создаёт заявку: конкретные
матчи сопоставляются по подтверждённым командам и времени. Конфликт ранее
подтверждённой event-связи остаётся отдельным кандидатом для расследования.
Перед первой публикацией после включения strict проверьте агрегаты outbox по
`kind`, source и датам матчей: массовые исторические `event` либо `team`
означают NO-GO для feedback timer. Ошибочный batch v1.3.5 из 22 656 строк
был адресно удалён после полного backup/readback/restore; подробный след —
[EPIC-038](../backlog/EPIC-038-v1-3-6-candidate-scope.md).

Задайте один стабильный `SF_ENTITY_REGISTRY_INSTALLATION_ID` для серверной
установки и сохраните его при перезапусках. Для текущей Object Storage
конфигурации выбран `e8608691-baf7-46fb-ae0e-594cb86f1fcf`; смена этого ID
требует отдельного изменения prefix grants и миграции очереди. Для процесса
обратной доставки выделите отдельный DB credential с доступом к outbox/sequence
и отдельный
Object Storage account: `PutObject`/`GetObject` только в
`entity-registry/v1/candidates/<installation-id>/`, `GetObject` только в
соответствующем `candidate-acks/`. Runtime ingestion пишет кандидатов в DB без
Object Storage credential. Ошибка доставки оставляет строки outbox для retry.
Задайте этому процессу `DATABASE_URL_FILE` с отдельной PostgreSQL ролью,
`SF_REGISTRY_FEEDBACK_SERVER_ACCESS_KEY_ID_FILE` и
`SF_REGISTRY_FEEDBACK_SERVER_SECRET_ACCESS_KEY_FILE`. Команды ограничивают
число batch за запуск:

```bash
uv run python -m sports_forecast.deploy.registry_feedback_publish_cli publish --max-batches 10
uv run python -m sports_forecast.deploy.registry_feedback_publish_cli collect-acks --max-batches 100
```

В production Compose для feedback используются
`SF_REGISTRY_FEEDBACK_DATABASE_URL_FILE` и отдельные Object Storage secret
files. Одноразовый профиль запускает `publish`; для `collect-acks` переопределите
команду, сохранив тот же профиль, identity и лимит:

```bash
docker compose --env-file /etc/sports-forecast/refresh/nhl.env -f docker-compose.prod.yml \
  --profile registry-feedback run --rm registry-feedback \
  /app/.venv/bin/python -m sports_forecast.deploy.registry_feedback_publish_cli collect-acks --max-batches 100
```

Запускайте обе команды периодически с раздельным от server sync расписанием;
повтор после сбоя безопасен. Публикация сверяет удалённые bytes перед отметкой
batch в БД. `collect-acks` отмечает только корректные ack своей установки.

Локальному importer задайте `SF_REGISTRY_FEEDBACK_ACCESS_KEY_ID_FILE` и
`SF_REGISTRY_FEEDBACK_SECRET_ACCESS_KEY_FILE` либо их значения без `_FILE`.
Его account имеет `ListBucket` с ограничением собственного candidates prefix,
`GetObject` для batches и `PutObject`/`GetObject` для собственного ack prefix.
Он не получает права на `current.json`, snapshots или чужие установки.

Импорт очереди запускается на локальной машине с доступом к master SQLite:

```bash
uv run python -m sports_forecast.deploy.registry_feedback_cli \
  --registry data/registry/master.sqlite3 \
  --installation-id <stable-installation-uuid> \
  --max-batches 100
```

Команда проверяет формат/порядок batch, переносит кандидатов и cursor в одной
локальной транзакции, затем публикует ack. После сбоя повторите команду: уже
принятые batches не продублируют задания. Ack подтверждает только доставку,
решение по словарному обозначению остаётся за владельцем в локальной
веб-очереди. Неоднозначный матч сам по себе не создаёт постоянную owner-связь
по event ID; проверьте обозначения и календарные данные. После решения
экспортируйте и опубликуйте новый полный snapshot обычной командой publisher,
затем запустите server sync. До установки новой версии неизвестные odds не
прикрепляются к событию. Очередь, cursor и audit входят в backup локальной БД.

Строгий reader включается только после установки проверенного снимка и
подтверждения обратной доставки. В нём старый merge коэффициентов в
`source.csv` пропускается: для обучения на historical odds нужен отдельный
проверенный materialization по словарям и сохранённому результату
сопоставления. Старый режим
остаётся включённым в `conf/identity_event.yaml` до эксплуатационного gate.
