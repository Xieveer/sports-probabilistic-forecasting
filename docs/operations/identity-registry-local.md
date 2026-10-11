# Локальный identity registry и offline обучение

Identity registry хранится локально в `data/registry/master.sqlite3`. Полный
проверенный пакет снимка находится в `data/registry/snapshots/<sha256>/`; он
не зависит от сервера и сети во время DVC pipeline или обучения. Локальная БД,
пакеты снимков и parquet sidecars игнорируются Git.

## Первичная подготовка

Инициализируйте master, импортируйте trusted NHL team seed и экспортируйте
первоначальный snapshot:

```bash
uv run python -c 'from pathlib import Path; from sports_forecast.identity import EntityRegistry; from sports_forecast.identity.nhl_seed import import_nhl_yaml; from sports_forecast.identity.snapshot import export_registry_snapshot, install_registry_snapshot; registry=EntityRegistry(Path("data/registry/master.sqlite3")); registry.initialize(); import_nhl_yaml(registry, Path("conf/bookmaker/team_name_registry/nhl.yaml")); snapshot=export_registry_snapshot(registry, Path("data/registry/snapshots")); install_registry_snapshot(snapshot.path, Path("data/registry/current/package")); print(snapshot.snapshot_id)'
```

Затем внесите только проверенные адаптеры в `enabled_tournaments` и установите
`enabled: true` в `conf/identity_registry.yaml`. Пример частичного rollout:
`enabled_tournaments: [nhl]`; турниры вне списка продолжают работать в legacy
режиме. Для каждого указанного турнира обязателен полный adapter mapping; ошибка
его настройки останавливает enabled ingest до создания outputs. Выбранный
каталог содержит целый verified package, а не только строку ID. Установка
проверяется во временном каталоге и переключается под lock с rollback; DVC
зависит от `data/registry/current/` и конфигурации, поэтому другая выбранная
версия или изменение package bytes инвалидирует ingest, clean и features.

Для просмотра текущего registry и работы с очередью используйте loopback review UI.
Каталог открывает подтверждённые сущности и обозначения независимо от состояния
очереди; изменение имени или подтверждённой связи требует основания и свежей
ревизии формы. Новый проверенный snapshot нужно экспортировать и опубликовать
отдельно. Файл
`conf/bookmaker/team_name_registry/nhl.yaml` остаётся исходным seed и резервом
compatibility-режима. При включённом strict event reader odds-потребители не
открывают этот файл: связь берётся из подтверждённого registry. Выключенный
reader сохраняет старый путь для обратимого возврата на прежний выпуск; не
редактируйте YAML после импорта seed.

Перед локальным переключением выполните read-only сверку YAML → master →
проверенный snapshot:

```bash
uv run python -m sports_forecast.identity.nhl_parity \
  --yaml conf/bookmaker/team_name_registry/nhl.yaml \
  --master data/registry/master.sqlite3 \
  --snapshot data/registry/current/package
```

Команда завершится с кодом 1 и перечислит расхождения, если известные aliases
отсутствуют, не подтверждены, указывают на разные project ID или не вошли в
snapshot. Новые обозначения в master не считаются ошибкой автоматически. Не
включайте strict reader до сверки и контрольного цикла NHL; для rollback
используйте прежний проверенный выпуск вместе с его snapshot и YAML seed.

## Подтверждённые события NHL

Официальный NHL schedule можно импортировать для одного семидневного окна,
если обозначения турнира и обеих команд уже подтверждены, время матча задано
точно в UTC и в registry нет противоречивой связи. Перед применением создайте
консистентную копию master с помощью SQLite backup API; не копируйте открытый
файл обычной командой `cp`:

```bash
uv run python - <<'PY'
from pathlib import Path
import sqlite3

source = Path('data/registry/master.sqlite3')
backup = Path('data/registry/backups/pre-nhl-events.sqlite3')
if not source.is_file():
    raise SystemExit('Owner master отсутствует')
backup.parent.mkdir(parents=True, exist_ok=True)
if backup.exists():
    raise SystemExit('Резервная копия уже существует: выберите новое имя')
with sqlite3.connect(source) as origin, sqlite3.connect(backup) as target:
    origin.backup(target)
backup.chmod(0o600)
PY
uv run python -m sports_forecast.identity.nhl_event_bootstrap_cli \
  --master data/registry/master.sqlite3 --anchor 2026-10-11
```

Дата `--anchor` — первая дата возвращаемой API недели; выберите актуальный
горизонт. Dry-run по умолчанию показывает только счётчики. Проверьте число
`planned` и причины `needs_review`, затем повторите команду с `--apply`.
Неоднозначные случаи сохраняются в локальной веб-очереди для решения владельца;
повторный запуск идемпотентен. Импорт подтверждает только NHL game IDs, а не
The Odds API event IDs. Затем экспортируйте verified snapshot, установите его
отдельным действием и снова выполните parity checker:

```bash
uv run python -m sports_forecast.identity.nhl_event_bootstrap_cli \
  --master data/registry/master.sqlite3 --anchor 2026-10-11 --apply
uv run python - <<'PY'
from pathlib import Path
from sports_forecast.identity import EntityRegistry
from sports_forecast.identity.snapshot import export_registry_snapshot, install_registry_snapshot

root = Path('data/registry')
snapshot = export_registry_snapshot(EntityRegistry(root / 'master.sqlite3'), root / 'snapshots')
install_registry_snapshot(snapshot.path, root / 'current/package')
print(snapshot.snapshot_id)
PY
uv run python -m sports_forecast.identity.nhl_parity \
  --yaml conf/bookmaker/team_name_registry/nhl.yaml \
  --master data/registry/master.sqlite3 \
  --snapshot data/registry/current/package
```

Публикация нового snapshot в Object Storage выполняется отдельно по
[runbook публикации](entity-registry-publication.md), только после проверки
покрытия production горизонта и релизных gates.

Создайте локальный секрет и запустите UI на loopback:

```bash
uv run python -c 'import secrets; from pathlib import Path; p=Path("data/registry/review.secret"); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(secrets.token_urlsafe(32)); p.chmod(0o600)'
uv run python -m sports_forecast.identity.review_server --registry data/registry/master.sqlite3 --secret-file data/registry/review.secret
```

Откройте `http://127.0.0.1:8765`. Остановите процесс через `Ctrl+C`.
Версионированный NHL seed подтверждает известные designation турнира и команд
для `nhl_web_api` и `the_odds_api`. Новые либо противоречивые обозначения
останутся в очереди: проверьте их в локальном UI, экспортируйте новый snapshot
и замените pin до следующего enabled DVC прогона. Pending значения не получают
project ID.

## Pipeline и training

Enabled ingest требует существующий и инициализированный master DB, установленный
snapshot и документированный adapter. NHL использует `nhl_api`; сборные —
`smart_tables`. Неизвестные связи записываются в локальную очередь, а pinned
reader остаётся неизменным до выбора следующего снимка.

Каждый raw/interim/processed parquet получает соседний файл
`<имя>.parquet.identity.json`. Sidecar привязан к SHA-256 и размеру конкретного
parquet; изменение данных без повторной генерации sidecar приводит к ошибке.
Sidecars проходят clean и все train/inference long/wide выходы.
Режим `inference_only` также записывает sidecars для обычного и пустого
inference результата.

Локальный `identity_registry.yaml: enabled` пока не совмещайте с отдельным
server canonical full refresh: его временный raw parquet не получает локальный
identity sidecar и останавливается до feature stage. Локальные DVC
ingest/clean/features/training entrypoints используют контракт выше;
серверный PostgreSQL reader настраивается отдельно.

Обычный training runner проверяет sidecar выбранного processed файла по
content-addressed archive выбранного при старте snapshot и записывает ID и
manifest в MLflow. Model-pool
entrypoint пока не принимает произвольные DataFrame в enabled режиме: он
завершается ошибкой, пока каждый pool input не предоставляет проверенную
per-file provenance.

Для legacy режима оставьте `enabled: false`; существующий pipeline продолжает
работать без registry sidecars.
