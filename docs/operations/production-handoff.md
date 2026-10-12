# Передача сервиса в эксплуатацию: v1.3.6 candidate

- Статус подготовки: `candidate`
- Решение на 2026-10-12: `HOLD` до решения владельца по отсутствующему реальному кандидату и проверки 20 ticks; кодовое исправление, immutable release gates и strict forecast cycle прошли.
- Инициатива: [EPIC-038](../backlog/EPIC-038-v1-3-6-candidate-scope.md), исходный контракт [EPIC-026](../backlog/EPIC-026-entity-registry.md).
- Владелец выпуска: пользователь; rollout выполняет Operations Agent.
- Среда: production VPS `ops-prod-01`; планируемая версия `1.3.6`.
- source_tag: `v1.3.6` — immutable annotated tag exact merge после review, terminal CI и Security.
- source_commit: `b06b544313b1915da3960670ddfbd836ad0a5b53` (post-merge CI `38184112119` и Security `38184112107`: success).
- evidence_tag: `v1.3.6-evidence.1` — отдельный tag после проверки image/model evidence.
- Текущий server stage: exact v1.3.6 source `b06b544313b1915da3960670ddfbd836ad0a5b53`, registry v2 publication sequence 3, strict reader `true`, API/бот здоровы, все три timers остановлены; outbox 0 после полного цикла и zero-work feedback. Резервные v1.3.5/v1.3.4/v1.3.1 образы сохранены.

## Идентификация и ответственность

Цель — ежедневный NHL/Pinnacle `winner_withOT` на подтверждённых словарях турниров, команд, рынков и исходов. Матчи сопоставляются по участникам, сторонам и UTC ±15 минут при взаимной уникальности; ID источников и связь конкретной котировки хранятся как provenance. Постоянная owner-связь для каждого матча не требуется. Неизвестные актуальные словарные обозначения идут владельцу; старые event relations сохраняются для истории/отката.

v1.3.5 прошла CI/Security, tag, Docker first-rollout/scan/provenance и release-evidence workflow `38182755480`. На VPS строгий Data Cycle `95169bca-160d-4a84-9f1f-58ecb10c8319` прошёл календарь, качество, архив, odds, прогнозы и публикацию: три будущие Pinnacle observations и 219 прогнозов. Однако календарь записал 22 656 pending candidates за весь исторический NHL источник: 21 963 event ID и 693 старые команды. Публикация feedback и timers остановлены; это NO-GO v1.3.5. Исправление [TASK-038-1](../backlog/tasks/TASK-038-1-bounded-registry-candidates.md) должно убрать event-ID задания и ограничить календарный capture UTC окном `now−1d … now+30d`.

## Release evidence

- CI: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38184112119 — success на exact source commit.
- Security: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38184112107 — success на exact source commit.
- Docker: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38184178356 — release gates, tested OCI, publish, scans и provenance success.
- first-rollout: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38184178356 — чистый first-rollout success.

- api: ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:2b205677248f732f3a7c74c9b7c52c3d39ed8281679653df679addd4618b635a — published; linux/amd64; scan; provenance.
- worker: ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:a3c474f4e5c50e126a1ddfe2ec3642dd69736675bc3d83cfa2df08546697c044 — published; linux/amd64; scan; provenance.
- telegram_bot: ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:ee4f3aefb67d3880479865d0a0f8d3dc116c3be20a82af60b16a2a60b8ffb478 — published; linux/amd64; scan; provenance.
- archive_sync: ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:6b1191d0c0199418e48027b65f1d0fde2f5babaf44ee9488dbad627f0793da28 — published; linux/amd64; scan; provenance.
- postgres: postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94 — проверенный базовый образ PostgreSQL.

## Фактический production gate v1.3.6

- Source `v1.3.6` и четыре exact digest установлены на VPS; локальный и серверный model runtime gate прошли под UID10001/read-only/network-none, bundle `sha256:175fc56bf79010892a4d817a222aacdbfc8ff6f6492aa64066c1b0a8618f15f5`, 489 ordered features.
- Strict Data Cycle `98a75688-50c3-4f07-822d-9fdbdcead0e2` завершился `partial_success` только по покрытию odds: calendar, quality, archive, predictions, publication успешны; fresh Pinnacle attempt provider 3/matched 3/rejected 0, три future observations, 218 опубликованных прогнозов. API/бот здоровы, в API доступны 49–50 будущих прогнозов и три двухсторонние линии.
- Outbox был 0 после календаря, odds и полного цикла. Zero-work feedback: published batches 0, acknowledged batches 0. Writer `INSERT … RETURNING id` проверен только на изолированной восстановленной БД с `ROLLBACK`; production outbox не менялся. Настоящего неизвестного обозначения среди текущих событий нет, поэтому непустой owner review не воспроизведён.
- После адресной очистки пяти старых Docker-образов без контейнерных ссылок свободно около 9,47 ГБ; сохранены все rollback refs. Post-cycle backup `/var/backups/sports-forecast/postgres/post-v1.3.6-strict-20261012T000844261240469.dump` (58 626 764 байт, SHA-256 `39872c5a5792c9185ebc5f0b7946ecc32d643707a1f2914e01b18102e908d723`) прошёл off-host readback/bytecmp и isolated restore на exact PostgreSQL image: schema `0025_real_bets_ledger`, outbox 0. Три timers остановлены до решения владельца по открытому gate и 20 ticks.
- Workflow Docker, вызванный на evidence tag `v1.3.6-evidence.1`, завершился ошибкой проверки `tag_version == project_version`: evidence tag не является source version. Исходный Docker `38184178356` и отдельный Release evidence `38185467879` завершились успешно.

## Runtime и конфигурация

Авторитетный profile всех production Compose/systemd процессов: `/etc/sports-forecast/refresh/nhl.env`. На staged switch заменить только `SF_APP_VERSION=1.3.6` и четыре exact image refs, сохранить `SF_REGISTRY_EVENT_READER_ENABLED=false` до проверки нового образа. Существующий валидный `SF_ENTITY_REGISTRY_INSTALLATION_ID` должен одинаково передаваться Worker, source-acquirer и registry-feedback; strict flag — API, боту, Worker и source-acquirer. Проверить rendered Compose без вывода secret paths. Только после code/image/model/data gates переключить strict=true, пересоздать API/бот, выполнить один контролируемый Data Cycle с остановленными timers. При провале вернуть strict=false атомарно и пересоздать API/бот.

Установленный verified snapshot v2 `ir1:71897173e0ee72bb60f9038cc8570770b351d866a3f994e63ba26bf5bcfe03e2`, manifest SHA-256 `2885685f95086013f1cbe9c92325acedfb17e2201d043b9e0c5b770865087c3d`, publication sequence 3. Verified v1 snapshot `ir1:e0070e397775a9227300d3edb061b20a15744f5317ccd7e56752e6ab67e196ce` сохранён. Новый sync читает v1/v2, старый v1.3.1 sync — только v1. Правило NHL/Pinnacle `h2h → winner_withOT` включает ОТ/буллиты и два исхода.

Compose secrets передаются как `*_FILE` paths; обычные API/Worker/бот не получают Object Storage credentials. Для 1.3.6 создан новый immutable model wrapper `sha256:175fc56bf79010892a4d817a222aacdbfc8ff6f6492aa64066c1b0a8618f15f5` (manifest SHA-256 `ba57d4d5ba8f948c4b80342a9fe3c18875ac545ee19b2a81e0fde810220c05c5`) из тех же approved payload SHA-256 и 489 признаков; exact Worker image gate на опубликованном digest `sha256:a3c474f4e5c50e126a1ddfe2ec3642dd69736675bc3d83cfa2df08546697c044` под UID10001/read-only/network-none прошёл: bundle verified, CatBoost загрузился, 489 ordered features совпали. Текущий v1.3.5 wrapper `sha256:2262cbb4f439ee65f3a8efd811b250f9b41e5c74f8d7562d304435b46d61bde0` несовместим с новой версией; предыдущий v1.3.4 wrapper `sha256:6ca7e2d6fefb0f64f892aba73a4a44e9b23c3e9e0ea5557c0196ea534ed77271` сохранён.

## Healthcheck и smoke-проверка

До switch сверить source tag/commit, image/model refs, Compose render, schema `0025_real_bets_ledger`, Worker candidate grants, v2 sequence, disk/RAM, zero active runs и rollback artifacts. Проверить `/health`, `/ready`, `/docs`, `/openapi.json`, реальные NHL прогнозы и двухстороннюю Pinnacle линию в API и Telegram-боте. Один strict Data Cycle должен пройти calendar → quality → archive → `data_odds` → predictions → publication, создать свежий odds attempt и будущие observations. Ожидаемые `partial_success` только по фактическому покрытию линии не являются ошибкой цикла.

Перед возобновлением feedback timer сверить post-remediation outbox и подтвердить, что новый strict Data Cycle создаёт только bounded актуальные неизвестные словарные обозначения. Ошибочный batch v1.3.5 уже адресно удалён после backup/readback/restore: транзакция сверила 22 656 pending rows с exact ID 2–22657, одним installation ID, null batch и ожидаемым payload digest; `DELETE ... RETURNING` подтвердил тот же count/range, postcheck outbox — 0. Никакие другие таблицы и registry snapshot не менялись. Новый реальный актуальный candidate должен пройти outbox → feedback publish → local owner review → publication/sync/ack. Если требуется неоднозначное решение владельца, представить ему короткую таблицу с evidence; не угадывать. После GO возобновить timers и проверить 20 последовательных минутных ticks без `start-limit-hit`, stale heartbeat и лишних уведомлений. `make acceptance-check` применять только с безопасно переданными secret files и без DB URL в аргументах процесса; разрешены эквивалентные GET/SELECT probes без полного provider payload.

## Данные и совместимость

Новый проверенный post-strict-cycle PostgreSQL backup до outbox remediation: `/var/backups/sports-forecast/postgres/pre-v1.3.6-outbox-20261011T231706104990022.dump`, 59 868 177 байт, SHA-256 `d379d32d8f11e7191e76bc692efc500e48ecb54febd0ffe8c0c20f990a2d8dfe`; полный off-host GET readback и isolated restore на exact PostgreSQL image прошли: 22 581 events, 22 656 outbox, 1 919 predictions, 5 odds, schema `0025_real_bets_ledger`. Этот backup позволяет восстановить состояние до адресной remediation. После неё создан свежий clean backup `/var/backups/sports-forecast/postgres/pre-v1.3.6-clean-20261011T233055414377080.dump` (58 625 067 байт, SHA-256 `c9c9b6b5e9eb57d1eab50edd0c18259d3a9fba9f6fd6d03510fdb98a95bfce77`): off-host GET/readback/bytecmp и изолированное восстановление на exact PostgreSQL образе прошли, outbox 0, schema `0025_real_bets_ledger`. Перед новым switch сверить текущую схему и backup; при новых записях после этого момента обновить backup. v1.3.6 не планирует миграцию. Owner master, v1/v2 snapshots, audit/cursor и старые immutable objects сохраняются. Не выполнять общую очистку Docker или данных.

После staged v1.3.5 pulls адресно удалены четыре old orphan Docker image без контейнерных ссылок; v1.3.1/v1.3.4/v1.3.5 refs сохранены. Последний измеренный свободный объём после strict цикла около 8.08 GB; измерить заново до v1.3.6 pull, остановиться при недостатке места. Точка безопасного удержания — v1.3.5 strict=false, timers paused, v2 seq3; полный возврат к v1.3.1 требует новую publication verified v1 snapshot с возрастающей sequence и sync новым бинарником до возврата старого.

## Наблюдаемость

Release evidence фиксирует UTC, source tag/commit, CI/Security/Docker/evidence workflows, пять digest refs и provenance, model bundle, backup hash/readback/restore, snapshot sequence, outbox counts до/после адресной remediation, реальный candidate/ack, stage/attempt counts, future odds/predictions, API/bot smoke, 20 ticks, disk/RAM/restart/OOM и итог GO/NO-GO. Секреты, персональные данные и полные внешние ответы не сохранять.

## Артефакт и откат

Source tag `v1.3.6` поставлен на exact merge commit `b06b544313b1915da3960670ddfbd836ad0a5b53` после независимого review и terminal CI/Security. Docker tag pipeline `38184178356` прошёл release gates, first-rollout, scan/provenance и публикацию четырёх exact образов. В отдельном evidence commit записаны пять refs в `deploy/release-manifest.json`; этот handoff обновлён и release gate `--handoff docs/operations/production-handoff.md` проверен локально. После green evidence workflow Operations Agent выполняет staged switch. Старые immutable tags и publications не менять.

Rollback safe hold: exact v1.3.5 source `e630a7c929720cd1585b2af825c43dacff444f85`, API `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:3db18b51535ff4631fa3be8e8bcffe5909babf6940ff51cd1fd9890dfc30c39f`, Worker `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:55dde895f0aec7e5b4785c5614813373e916e2877a5f81c6f030ea0cd41bf3a9`, bot `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:97c16bb8488e1ea189b1cd34e58e6931afc8d4b8d3da7d91c36c9c24be7371e2`, archive-sync `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:238713203781709e5e56d5841c1801f429d865a0c28b20f10f04f36f98676e78`, PostgreSQL `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`, model wrapper `sha256:2262cbb4f439ee65f3a8efd811b250f9b41e5c74f8d7562d304435b46d61bde0`, registry v2 seq3. При возврате к v1.3.1 сначала опубликовать verified v1 snapshot как новую возрастающую publication и sync новым бинарником; затем вернуть прежние образы.

## Нерешённые вопросы

1. TASK-038-1, независимый review, terminal CI/Security, `make production-check`, Docker и exact Worker model gate прошли; ожидается отдельный evidence workflow.
2. Свежий backup и точная адресная remediation ошибочного outbox подтверждены; feedback публиковать только после bounded queue проверки.
3. Подтвердить полный strict cycle, реальный кандидат с owner решением, NHL API/бот и 20 ticks. До этого — `NO-GO`.
