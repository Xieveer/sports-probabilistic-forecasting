# Передача сервиса в эксплуатацию: v1.3.3 candidate

- Статус подготовки: `candidate`
- Решение на 2026-10-12: `NO-GO`; release evidence и серверные gates ещё проверяются.
- Инициатива: [EPIC-036](../backlog/EPIC-036-v1-3-3-registry-rollout.md), словари [EPIC-026](../backlog/EPIC-026-entity-registry.md).
- Владелец решения о выпуске: пользователь; исполнитель rollout: Operations Agent.
- Среда: production VPS `ops-prod-01`; планируемая версия: `1.3.3`.
- source_tag: `v1.3.3` — планируемый annotated tag после merge, review и terminal CI.
- source_commit: будет закреплён по exact merge commit `v1.3.3`; текущий commit ветки не является release source.
- evidence_tag: `v1.3.3-evidence.1` — планируемый отдельный tag после проверки immutable образов.
- Текущий production: exact `v1.3.1`, source commit `757d3af338bb2bb36304cb3e81c0f2c93a0834e5`, strict reader выключен.
- Предыдущий кандидат `v1.3.2` получил [NO-GO](../backlog/EPIC-035-v1-3-2-registry-rollout.md); его image/model evidence не доказывает готовность `v1.3.3`.

## Идентификация и ответственность

Цель — рабочий NHL/Pinnacle `winner_withOT` на словарях турниров, команд,
рынков и исходов. Котировка сопоставляется с календарным матчем по
подтверждённым участникам, сторонам и UTC в пределах 15 минут при взаимной
уникальности. ID источников и вычисленная связь сохраняются как provenance,
без постоянной owner-связи каждого матча. Неизвестный или неоднозначный матч
остаётся без коэффициента. Будущие словари игроков учитывают принадлежность
команде во времени. Legacy путь сохраняется для явного отката по
[ADR-035](../architecture/adr/ADR-035-registry-dictionaries-and-derived-event-matching.md).

В выпуск также входят исправления PostgreSQL grants для реального candidate
`INSERT ... RETURNING`, пропуска `data_odds` после подготовленного архива и
минутного лимита dispatcher. Независимый review, terminal CI/security, точный
source tag и tag pipeline пока не завершены. Решение GO возможно только по
фактическим критериям [EPIC-036](../backlog/EPIC-036-v1-3-3-registry-rollout.md).

## Runtime и конфигурация

Локальный owner master схемы 11 требует консистентного SQLite backup,
миграции 11→12, проверенного NHL/Pinnacle market seed и экспорта snapshot v2.
В production установлен verified v1 snapshot
`ir1:e0070e397775a9227300d3edb061b20a15744f5317ccd7e56752e6ab67e196ce`
как publication sequence `2`. Его прежние event rows сохраняются для истории
и отката. Старый v1.3.1 `registry-sync` не читает формат v2: публикацию v2
выполнить только после подготовки нового sync image и временной остановки
старого sync timer. Новый reader должен принять установленный v1, затем v2.
Strict reader включать после проверки словарей и реальной линии.

`SF_APP_VERSION=1.3.3`, package, source tag, Compose и новый immutable model
wrapper должны совпасть. Три approved payload и веса не менять: собрать новый
bundle под exact source commit, проверить SHA-256, CatBoost и порядок 489
признаков в точном Worker image под UID `10001`. ID нового bundle и manifest
SHA записать после сборки. Bundle v1.3.2 с `app_version=1.3.2` несовместим.
Compose secrets передаются как `*_FILE` paths; server sync и feedback получают
отдельные DB/Object Storage credentials. Обычные API, Worker и бот не получают
Object Storage credentials.

## Healthcheck и smoke-проверка

До switch сверить exact source/image/model refs, Compose render, schema,
ролевые grants, Docker/DB, место, active runs и rollback artifacts. После
установки v2 проверить publication sequence, snapshot ID, правило NHL/Pinnacle
`h2h → winner_withOT` с ОТ/буллитами и двумя исходами, покрытие свежего NHL
горизонта. На реальных котировках проверить сдвиг +10 минут и отказы при
неоднозначности или несовместимом рынке.

Проверить непустой цикл candidate под Worker identity → feedback publish →
локальный import и решение владельца → новый snapshot → server sync и ack.
Контрольный source-first NHL Data Cycle должен пройти archive gate, затем
записать новый odds acquisition attempt и ненулевые будущие
`odds_observations`; прогноз и действующая линия должны быть доступны в API и
Telegram-боте. Проверить `/health`, `/ready`, `/docs`, `/openapi.json`, выдачу
прогноза/линии, отсутствие лишних уведомлений и 20 последовательных минутных
ticks dispatcher без `start-limit-hit` и stale heartbeat. В production до
исправления `data_odds` пропускался, последняя попытка odds датирована
2026-10-01, будущих NHL observations не было. `make acceptance-check` не
запускать с DB URL в аргументах процесса; применять безопасные GET/SELECT
probes без вывода секретов и полных provider payload.

## Данные и совместимость

До изменения production сделать свежий root-only PostgreSQL custom-format
backup, проверить catalog/SHA-256, off-host readback и isolated restore на
exact PostgreSQL image. Backup v1.3.2 от 2026-10-11 20:04 UTC с SHA-256
`4d2635ba52f11795bb3365514e761b622613f7e5da43e835fd9c4caba72957d3`
прошёл эти проверки как прежняя репетиция, но не заменяет новую точку отката.
Сохранить также backup owner master, старый v1 snapshot и локальный audit/cursor.
На прошлом gate production schema — `0025_real_bets_ledger`; до switch
повторить проверку schema и фактический ORM `INSERT ... RETURNING` под
`sf_refresh_writer`. При несовместимой миграции нужен проверенный forward-fix
или restore в окне простоя, без автоматического downgrade.

На read-only preflight 2026-10-11 около 20:50 UTC оставалось 12 ГБ на корневом
разделе; повторно измерить перед pull и backup. Старые образы, данные,
Object Storage publications и секреты не удалять в этом rollout.

## Наблюдаемость

В release evidence записать UTC, exact source tag/commit, CI/security/tag
pipeline, image digests/provenance, model bundle ID, schema/grants, backup
hash/readback/restore, старый и новый registry snapshot/publication, outbox/ack,
Data Cycle stage/attempt counts, число будущих прогнозов и котировок, bot/API
smoke, timer heartbeat, disk/RAM, restart/OOM и итог GO/NO-GO. Секреты,
персональные данные и полные внешние ответы в evidence не сохранять.

## Артефакт и откат

Новый source tag `v1.3.3` ставить только на прошедший review и terminal CI
merge commit. После успешного tag pipeline внести exact пять image refs в
`deploy/release-manifest.json` отдельного evidence commit, обновить handoff и
ссылки `CI`, `Security`, `Docker`, `first-rollout`, затем проверить
release-evidence gate (`--handoff docs/operations/production-handoff.md`) и
model wrapper в exact Worker image. До этого ни один
v1.3.2 digest не считать образом кандидата v1.3.3.

Точка отката — exact `v1.3.1` source
`757d3af338bb2bb36304cb3e81c0f2c93a0834e5`, API image
`ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:4bf7c27dbd25ec88d14183704a076b5a9ac824003de754fe49fb344a69fcda8c`,
Worker image
`ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:80de5332a5e7b5431cac5089bd6af27e6b70a50d758485f3e39105f2081196e3`,
бот image
`ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:8232f8643968694a50b2dbe5c96f33683592bff18952b98af08c64d89b577add`,
archive-sync image
`ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:622bca60a525ee820e25483e9033ef09603fa85ea596c1aaa42a18490cbbbf17`,
PostgreSQL image `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`,
model bundle `sha256:956edb47e9737516ce8a29ed42a6cea08af6522fed1b9510a614201c20daad09`
и `registry_event_reader_enabled: false`. Для возврата registry к v1
опубликовать verified snapshot `ir1:e0070e397775a9227300d3edb061b20a15744f5317ccd7e56752e6ab67e196ce`
как новую publication с возрастающей sequence и выполнить sync до возврата
старого бинарника. Immutable objects не переписывать и не удалять.

## Нерешённые вопросы

1. Завершить EPIC-026 и исправления EPIC-036, независимый review, terminal
   CI/security и `make production-check`.
2. Зафиксировать source commit/tag `v1.3.3`, пять image digests, provenance,
   новый model wrapper и успешный release-evidence gate.
3. Подтвердить backup/restore, совместимость v1→v2, реальный candidate feedback,
   NHL odds/forecast/bot smoke и 20 минутных ticks на production.

До закрытия всех пунктов deployment и strict switch остаются `NO-GO`.
