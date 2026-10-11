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
ревизии формы. Фильтры `market` и `outcome` показывают словари рынка и исходов.
Карточка рынка показывает aliases с областью действия, действующее правило и
историю изменений. Владелец может изменить период, учёт ОТ/буллитов/ничьей и
допустимые исходы с ключами `home_win`, `away_win`, `draw`; форма требует
основание, CSRF-токен и актуальную ревизию. Правка master сама по себе не
переключает установленный пакет: новый snapshot нужно экспортировать и
опубликовать отдельно. Файл
`conf/bookmaker/team_name_registry/nhl.yaml` остаётся исходным seed и резервом
compatibility-режима. При включённом strict event reader odds-потребители не
открывают этот файл: участники и рынок разрешаются через подтверждённые
словари, а матч выбирается из календаря с проверкой времени и уникальности.
Выключенный
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

## Переход master на схему 12 и рынок NHL/Pinnacle

Работайте из checkout, где находится действующий owner master
`data/registry/master.sqlite3`. Игнорируемый Git каталог `data/registry/`
у каждого worktree свой; пустую БД соседнего worktree нельзя считать master.
Остановите локальный review UI на время миграции. Сначала сделайте
консистентную копию через SQLite backup API и проверьте её; `cp` открытой БД
не подходит. Имя backup должно быть новым при каждом запуске:

```bash
uv run python - <<'PY'
from datetime import UTC, datetime
from pathlib import Path
import sqlite3

source = Path('data/registry/master.sqlite3')
if not source.is_file():
    raise SystemExit('Owner master отсутствует в этом checkout')
root = Path('data/registry/backups')
root.mkdir(parents=True, exist_ok=True)
backup = root / f'pre-schema12-{datetime.now(UTC):%Y%m%dT%H%M%S%f}.sqlite3'
if backup.exists():
    raise SystemExit('Backup уже существует')
with sqlite3.connect(source) as origin, sqlite3.connect(backup) as target:
    origin.backup(target)
    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise SystemExit('Backup не прошёл integrity_check')
backup.chmod(0o600)
print(backup)
PY
```

После независимого review кода схемы 12 примените миграцию и идемпотентный
seed. ID NHL берётся из **действующей подтверждённой** tournament entity,
а не из фиксированной строки или ID события. Seed ограничен `ice_hockey`,
этим турниром и `bookmaker=pinnacle`; `the_odds_api:h2h` означает
`winner_withOT` за полный матч с ОТ и буллитами, исходы `home_win` и
`away_win` без ничьей. Он не перезаписывает решение владельца:

```bash
uv run python - <<'PY'
from pathlib import Path
from sports_forecast.identity import EntityRegistry
from sports_forecast.identity.nhl_market_seed import seed_nhl_pinnacle_market
from sports_forecast.identity.snapshot import (
    export_registry_snapshot,
    install_registry_snapshot,
    verify_registry_snapshot,
)

root = Path('data/registry')
registry = EntityRegistry(root / 'master.sqlite3')
registry.initialize()
tournaments = [
    item for item in registry.list_entities(kind='tournament')
    if item.project_name == 'NHL' and item.sport == 'ice_hockey'
]
if len(tournaments) != 1:
    raise SystemExit('Требуется ровно один подтверждённый турнир NHL')
market_id = seed_nhl_pinnacle_market(registry, tournament_id=tournaments[0].id)
rule = registry.get_market_rule(market_id)
if (rule.period, rule.overtime, rule.shootout, rule.draw) != ('game', True, True, False):
    raise SystemExit('Правило NHL/Pinnacle не соответствует принятому контракту')
if set(rule.valid_outcome_keys) != {'home_win', 'away_win'}:
    raise SystemExit('Правило NHL/Pinnacle требует ровно два исхода без ничьей')
snapshot = export_registry_snapshot(registry, root / 'snapshots')
verified = verify_registry_snapshot(snapshot.path)
if (verified.manifest['format_version'], verified.manifest['registry_schema_version']) != (2, 12):
    raise SystemExit('Ожидался snapshot format 2 / schema 12')
install_registry_snapshot(snapshot.path, root / 'current/package')
print(snapshot.snapshot_id)
PY
uv run python -m sports_forecast.identity.nhl_parity \
  --yaml conf/bookmaker/team_name_registry/nhl.yaml \
  --master data/registry/master.sqlite3 \
  --snapshot data/registry/current/package
```

Сохраните ID и проверенный пакет для публикации. Формат v2 добавляет
`market_rules.jsonl`, сохраняя старые event rows; ID пакета по-прежнему имеет
префикс `ir1:`. Читатель нового выпуска принимает v1/schema 11 и
v2/schema 12. Старый production `registry-sync` v1.3.1 формат v2 не принимает:
порядок публикации и отката указан в
[runbook](entity-registry-publication.md). Обычные NHL матчи теперь
сопоставляются по словарям и календарю; seed не создаёт постоянные связи
The Odds API event ID с каждым матчем.

## Исторические связи событий NHL

Официальный NHL schedule можно импортировать для одного семидневного окна,
если обозначения турнира и обеих команд уже подтверждены, время матча задано
точно в UTC и в registry нет противоречивой связи. Этот путь сохраняется для
истории и старого reader; он не является условием присоединения котировок в
новом matcher. Показанная дата `2026-10-11` — пример прежнего выпуска, для
нового запуска выберите актуальный anchor. Перед применением создайте
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
