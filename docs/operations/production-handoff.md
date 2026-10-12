# Передача сервиса в эксплуатацию: v1.3.7 candidate

- Статус подготовки: `candidate`
- Решение на 2026-10-12: `GO` — v1.3.7 включена, строгий controlled и плановый Data Cycle без odds завершились успешно, 20 последовательных минутных ticks и release gates прошли. Владелец перенёс непустой owner candidate gate на подключение нового турнира.
- Инициатива: [EPIC-039](../backlog/EPIC-039-v1-3-7-daily-cycle.md), исходные контракты [EPIC-025](../backlog/EPIC-025-bot-schedule-readiness.md) и [EPIC-026](../backlog/EPIC-026-entity-registry.md).
- Владелец выпуска: пользователь; rollout выполняет Operations Agent.
- Среда: production VPS `ops-prod-01`; установленная версия `1.3.7`.
- source_tag: `v1.3.7` — immutable annotated tag на exact merge после review, terminal CI и Security.
- source_commit: `e08452bc17b6d6bfab8fd97fd860f6df15fd56cd` (post-merge CI `38210285959` и Security `38210285974`: success).
- evidence_tag: `v1.3.7-evidence.1` — immutable annotated tag после проверки image/model evidence и manifest gate.
- Текущий server stage: exact v1.3.7 source `e08452bc17b6d6bfab8fd97fd860f6df15fd56cd`, registry v2 publication sequence 3, strict reader `true`, API/бот здоровы, три новых timers активны; outbox 0. Резервные v1.3.6/v1.3.5/v1.3.4/v1.3.1 образы сохранены.

## Выполненный rollout v1.3.7 и порядок остановки

Локальный red/green и независимый review, terminal CI/Security, exact source tag, четыре опубликованных OCI digest с scan/provenance, Worker/model wrapper и evidence workflow проверены. Operations Agent сверил grant, диск, backup/readback/isolated restore, source/env/registry/schema и отсутствие активного цикла. Exact v1.3.7 установлена со strict reader `true`; controlled Data Cycle прошёл calendar → quality → archive → features → predictions → publication, `data_odds=skipped`, без нового The Odds API acquisition attempt. Новые завершённые игры изменили последующие признаки и прогнозы; `/predict` отдельно проверен на текущей линии и edge. `sports-forecast-data-cycle-dispatcher.timer`, `sports-forecast-registry-sync.timer`, `sports-forecast-registry-feedback.timer` активированы; 20 минутных ticks, heartbeat, отсутствие start-limit-hit и лишних уведомлений подтверждены. Старый `sports-forecast-canonical-refresh@nhl.timer` оставлен выключенным: он дублирует цикл.

Scheduled NHL запуск в 10:00 Europe/Moscow (07:00 UTC) выполнен ровно один раз, следующий слот назначен на завтра. При P0/P1, новом odds attempt из цикла, неверных rolling features, ошибке backup/restore, устаревшем heartbeat или провале уведомлений — остановить dispatcher и вернуть сохранённый v1.3.6 exact image/env либо safe hold; strict reader выключать только при его собственной ошибке. Для повторной оценки применять `make acceptance-check` и эквивалентные безопасные GET/SELECT probes без раскрытия секретов.

Непустой owner candidate → local decision → publication/sync/ack остаётся открытым сценарием EPIC-026 до появления нового обозначения при подключении турнира; текущий NHL outbox 0. Нулевой feedback, работа таймеров и строгий reader проверяются в этом выпуске. Ручной refresh с явным `data_odds_enabled=true` остаётся диагностической возможностью, `/predict` запрашивает live odds по запросу пользователя.

## Release evidence v1.3.7

- CI: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38210285959 — terminal success на exact source commit.
- Security: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38210285974 — terminal success на exact source commit.
- Docker: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38210415506 — release gates, проверенный OCI, publish, scan и provenance success.
- first-rollout: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38210415506 — чистый first-rollout success.

- api: ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:fc21a3598ac27463c3c0ea03371ad1ffc671f1fb6d8462da7e10fe3c8db36838 — published; linux/amd64; scan; provenance.
- worker: ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:054a36bc11690820438ccdb8b03feddad24d32719d5ed10e70b8ae729799ad54 — published; linux/amd64; scan; provenance.
- telegram_bot: ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:3ca2dbf90b3b65d42457995f4d7f9286a58fa5d9801f1fe6cc1a0ab889eba793 — published; linux/amd64; scan; provenance.
- archive_sync: ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:7cb4c6b24a069a712719a6928d738cf1d4bf0fea42754ab3c5064839063d33bd — published; linux/amd64; scan; provenance.
- postgres: postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94 — проверенный базовый образ.

Evidence PR [#97](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/97) слит в `d11a2ad50ba59129aa0d70c3a2a545065e05655b`; terminal CI `38212033903` и Security `38212033894` прошли. Annotated evidence tag `v1.3.7-evidence.1` указывает на этот commit; [Release evidence workflow](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38212187109) прошёл. Source tag `v1.3.7` остаётся неизменным на `e08452bc17b6d6bfab8fd97fd860f6df15fd56cd`.

Для v1.3.7 из прежних approved model payload собран immutable wrapper `sha256:ad967f34ec37060eec3388a90e94af23f00d85f9534e30a46407db661959b543` (manifest SHA-256 `b3f30be712cb0e024024a50a9aad400da19c28d798b61a24b8c73278634bf192`). Локальная проверка manifest, SHA payload и 489 ordered features прошла. Exact опубликованный Worker digest `sha256:054a36bc11690820438ccdb8b03feddad24d32719d5ed10e70b8ae729799ad54` проверен с этим wrapper под UID:GID10001:10001, network none, read-only rootfs/model mount, cap-drop ALL, no-new-privileges, RAM 1 GiB, pids 128: bundle verified, CatBoost и 489 ordered features совпали. Тот же wrapper установлен и проверен в серверном mount под exact Worker image.

Pre-switch backup `/var/backups/sports-forecast/postgres/pre-v1.3.7-20261012T060418522429569.dump` (58 626 998 байт, SHA-256 `8de021721b00ccba4871afd73062f7061ef666e6a025ba22f5ef07c81d17a9da`) прошёл full off-host readback/bytecmp и isolated restore на exact PostgreSQL image: schema `0025_real_bets_ledger`, 22 581 events, 1 919 predictions, 5 odds observations, 8 odds acquisition attempts, outbox 0. В момент backup strict reader был `true`, timers inactive; release source/unit templates v1.3.7 были staged отдельно до live switch.

До переключения в старом verified canonical архиве `sha256:1c0c66f6f5a2d7bd7445b5a3d3080a25605016a788413157e942b05c5df66adb` матчи `2026020085` (VAN–NYR) и `2026020086` (CAR–PHI) ещё не были завершены. Официальный NHL API уже показывал оба `OFF`. Offline baseline на старом pinned архиве и реальном approved feature pipeline воспроизвёл contract `sha256:cea3521e8f7ba866dfc47128047646aa86f0a472885b1d715639f7fb1ecf759f`: для будущего CAR `2026020093` `f_pl_global_diff_ewm_5=2.432152504331492`, для будущего VAN `2026020097` `f_pl_global_diff_ewm_5=-2.1936840179919486`. Эти поля сравнены с новым pinned архивом в production gate ниже; odds acquisition attempts до цикла — 8.

## Фактический production gate v1.3.7

Точный source commit `e08452bc17b6d6bfab8fd97fd860f6df15fd56cd`, четыре digest refs и model wrapper `sha256:ad967f34ec37060eec3388a90e94af23f00d85f9534e30a46407db661959b543` установлены на VPS; API/бот/БД healthy, restart 0, OOM false, strict reader `true`, registry v2 sequence 3. До switch адресно удалены только четыре старых Docker image ID без ссылок из контейнеров и вне protected rollback refs, каждый с повторной проверкой перед удалением; выигрыш 7 189 835 776 байт. После загрузки новых образов и wrapper оставалось 9 354 588 160 байт свободно.

Контролируемый цикл `4202cb11-9b72-4874-8503-75668c931e06` завершился `success` 2026-10-12 06:34:47 UTC: calendar, quality, archive, predictions и publication успешны; `data_odds=skipped` (`disabled=1`), счётчик The Odds API acquisition attempts до/после 8/8. NHL игры `2026020085` и `2026020086` перешли из `started` в `finished`; новый проверенный canonical artifact `sha256:9ee3a1eaae05cbe5f8315b429af1258bc0c396b62175cc0d0663117fabda3006`, source-state `sha256:9015475d8d35bb38a6f2d4bd2ad38dc485caa29a671ad5418a0a7424d25491d0`. Цикл записал 216 прогнозов, 206 future predictions готовы, errors 0, outbox 0. У будущего CAR–WSH `f_pl_global_diff_ewm_5` изменился 2.4321525043→2.6214350029, EWM15 1.5823073909→1.7595189670; у будущего NYI–VAN EWM5 −2.1936840180→−2.7957893453, EWM15 −1.5091534874→−1.8205093015. Сравнение выполнено тем же approved feature pipeline на двух verified pinned canonical архивах, feature contract `sha256:cea3521e8f7ba866dfc47128047646aa86f0a472885b1d715639f7fb1ecf759f` неизменен. Новые prediction probabilities: CAR home .637506/.362494, NYI home .580449/.419551, обе записи с новым canonical provenance. `/predict` HTTP 200, 50 upcoming, три двухсторонние live Pinnacle quotes при отдельном запросе (47 без линии); он не относится к ежедневному odds acquisition stage.

Ручные registry-sync и zero-work feedback успешны, outbox 0. Три новых timer включены: dispatcher выполнил ровно 20 успешных starts/finishes с 06:36:34 до 06:55:34 UTC, все 19 интервалов — ровно 60 секунд, heartbeat свежий; registry-sync и feedback ticks успешны, warning/error нет. Старый NHL canonical-refresh timer выключен.

Плановый цикл `514cee55-1905-4d0d-a131-3da0e49a605e` за слот 2026-10-12 07:00 UTC создан ровно один раз и завершился `success` в 07:07:20 UTC: calendar 22 581 events/changed 3, quality success, archive_sync success 2, predictions и publication success, 216 прогнозов записаны, 206 будущих готовы, ошибок 0. `data_odds=skipped` (`disabled=1`); The Odds API acquisition attempts 8/8 и odds observations 5/5 до/после. Outbox 0; registry v2 sequence 3, strict reader `true`; API/бот/БД healthy, restart 0, OOM false, три timers активны. Следующий слот 2026-10-13 07:00 UTC, missed slots 0. Notification delivered 28→29: новая запись id 29 относится к этому scheduled run, отправлена с первой попытки без ошибки, лишних уведомлений нет. Post-run `/health`, `/ready`, `/predict` вернули HTTP 200, 50 будущих матчей и три двухсторонние live Pinnacle линии; свободно 8 833 802 240 байт.

Post-cycle backup `/var/backups/sports-forecast/postgres/post-v1.3.7-20261012T063705565320489.dump` (58 634 124 байт, SHA-256 `6ff0bcbbcffc102faa52ea325801f6a2018f9857b4e695552b25f943bc1813b2`) прошёл off-host full readback/bytecmp и isolated restore на exact PostgreSQL image: schema `0025_real_bets_ledger`, 22 581 events, 1 919 predictions. После проверки было свободно 9 069 019 136 байт, API/бот/БД здоровы.

## Исторические evidence v1.3.6

Следующие разделы — историческая запись v1.3.6, не текущие инструкции запуска и не gates v1.3.7. Release evidence, source/image/model refs и измерения ниже относятся только к точке отката; для v1.3.7 действуют «Выполненный rollout v1.3.7 и порядок остановки» и «Фактический production gate v1.3.7» выше.

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

Авторитетный profile всех production Compose/systemd процессов: `/etc/sports-forecast/refresh/nhl.env`. Установлены `SF_APP_VERSION=1.3.6`, четыре exact image refs из manifest и `SF_REGISTRY_EVENT_READER_ENABLED=true`; валидный `SF_ENTITY_REGISTRY_INSTALLATION_ID` одинаков для Worker, source-acquirer и registry-feedback. Rendered Compose, model mount, API/бот и полный strict Data Cycle проверены. При новом сбое до GO вернуть strict=false атомарно и пересоздать API/бот; timers пока остановлены.

Установленный verified snapshot v2 `ir1:71897173e0ee72bb60f9038cc8570770b351d866a3f994e63ba26bf5bcfe03e2`, manifest SHA-256 `2885685f95086013f1cbe9c92325acedfb17e2201d043b9e0c5b770865087c3d`, publication sequence 3. Verified v1 snapshot `ir1:e0070e397775a9227300d3edb061b20a15744f5317ccd7e56752e6ab67e196ce` сохранён. Новый sync читает v1/v2, старый v1.3.1 sync — только v1. Правило NHL/Pinnacle `h2h → winner_withOT` включает ОТ/буллиты и два исхода.

Compose secrets передаются как `*_FILE` paths; обычные API/Worker/бот не получают Object Storage credentials. Для 1.3.6 создан новый immutable model wrapper `sha256:175fc56bf79010892a4d817a222aacdbfc8ff6f6492aa64066c1b0a8618f15f5` (manifest SHA-256 `ba57d4d5ba8f948c4b80342a9fe3c18875ac545ee19b2a81e0fde810220c05c5`) из тех же approved payload SHA-256 и 489 признаков; exact Worker image gate на опубликованном digest `sha256:a3c474f4e5c50e126a1ddfe2ec3642dd69736675bc3d83cfa2df08546697c044` под UID10001/read-only/network-none прошёл: bundle verified, CatBoost загрузился, 489 ordered features совпали. Rollback v1.3.5 wrapper `sha256:2262cbb4f439ee65f3a8efd811b250f9b41e5c74f8d7562d304435b46d61bde0` несовместим с новой версией; предыдущий v1.3.4 wrapper `sha256:6ca7e2d6fefb0f64f892aba73a4a44e9b23c3e9e0ea5557c0196ea534ed77271` сохранён.

## Healthcheck и smoke-проверка

Для планировавшегося v1.3.6 включения требовалась повторная сверка source/image/model refs, schema `0025_real_bets_ledger`, v2 sequence, disk/RAM, zero active runs и rollback artifacts. `/health`, `/ready`, `/docs`, `/openapi.json` вернули HTTP 200; реальные NHL прогнозы и двухсторонняя Pinnacle линия были в API, бот здоров. Контрольный strict Data Cycle v1.3.6 прошёл calendar → quality → archive → `data_odds` → predictions → publication; `partial_success` относился только к фактическому покрытию линии.

Для планировавшегося v1.3.6 включения feedback timer требовалось проверить post-remediation outbox и bounded capture. Ошибочный batch v1.3.5 адресно удалён после backup/readback/restore: транзакция сверила 22 656 pending rows с exact ID 2–22657, одним installation ID, null batch и ожидаемым payload digest; `DELETE ... RETURNING` подтвердил тот же count/range, postcheck outbox — 0. Никакие другие таблицы и registry snapshot не менялись. Тогда непустой актуальный candidate → owner review → publication/sync/ack оставался release gate; владелец 2026-10-12 перенёс его на подключение нового турнира. Таймеры v1.3.6 не запускались. Проверка 20 ticks перенесена в v1.3.7.

## Данные и совместимость

Резервные копии: до адресной remediation — `/var/backups/sports-forecast/postgres/pre-v1.3.6-outbox-20261011T231706104990022.dump` (59 868 177 байт, SHA-256 `d379d32d8f11e7191e76bc692efc500e48ecb54febd0ffe8c0c20f990a2d8dfe`, 22 656 outbox); после remediation и до switch — `/var/backups/sports-forecast/postgres/pre-v1.3.6-clean-20261011T233055414377080.dump` (58 625 067 байт, SHA-256 `c9c9b6b5e9eb57d1eab50edd0c18259d3a9fba9f6fd6d03510fdb98a95bfce77`, outbox 0); после полного strict цикла — `/var/backups/sports-forecast/postgres/post-v1.3.6-strict-20261012T000844261240469.dump` (58 626 764 байт, SHA-256 `39872c5a5792c9185ebc5f0b7946ecc32d643707a1f2914e01b18102e908d723`, outbox 0). У всех прошли off-host full readback/bytecmp и isolated restore на exact PostgreSQL image, schema `0025_real_bets_ledger`. v1.3.6 не потребовала миграцию БД; owner master, snapshots, audit/cursor и immutable objects сохранены.

После staged v1.3.6 pulls адресно удалены пять старых orphan Docker images без контейнерных ссылок; refs v1.3.1/v1.3.4/v1.3.5/v1.3.6 сохранены, после post-cycle backup было свободно около 9,47 ГБ. Безопасная точка ожидания перед v1.3.7 — v1.3.6 strict=true, timers paused, v2 seq3. Проверенный rollback к v1.3.5 strict=false доступен по refs ниже; полный возврат к v1.3.1 требует новую publication verified v1 snapshot с возрастающей sequence и sync новым бинарником до возврата старого.

## Наблюдаемость

Evidence v1.3.6 зафиксировало UTC, source tag/commit, CI/Security/Docker/evidence workflows, пять digest refs и provenance, model bundle, backup hash/readback/restore, snapshot sequence, outbox counts, stage/attempt counts, future odds/predictions, API/bot smoke, disk/RAM/restart/OOM. На тот момент оставались настоящий candidate/owner review/ack и 20 ticks. Владелец 2026-10-12 перенёс первый сценарий на новый турнир, второй — на v1.3.7.

## Артефакт и откат

Source tag `v1.3.6` поставлен на exact merge commit `b06b544313b1915da3960670ddfbd836ad0a5b53` после независимого review и terminal CI/Security. Docker `38184178356` прошёл release gates, first-rollout, scan/provenance и публикацию четырёх exact образов; Release evidence `38185467879` прошёл. Отдельный evidence commit содержит пять refs в `deploy/release-manifest.json`; локальный release gate `--handoff docs/operations/production-handoff.md` прошёл. Staged switch и strict Data Cycle выполнены; старые immutable tags и publications не менять.

Rollback safe hold: exact v1.3.5 source `e630a7c929720cd1585b2af825c43dacff444f85`, API `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:3db18b51535ff4631fa3be8e8bcffe5909babf6940ff51cd1fd9890dfc30c39f`, Worker `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:55dde895f0aec7e5b4785c5614813373e916e2877a5f81c6f030ea0cd41bf3a9`, bot `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:97c16bb8488e1ea189b1cd34e58e6931afc8d4b8d3da7d91c36c9c24be7371e2`, archive-sync `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:238713203781709e5e56d5841c1801f429d865a0c28b20f10f04f36f98676e78`, PostgreSQL `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`, model wrapper `sha256:2262cbb4f439ee65f3a8efd811b250f9b41e5c74f8d7562d304435b46d61bde0`, registry v2 seq3. При возврате к v1.3.1 сначала опубликовать verified v1 snapshot как новую возрастающую publication и sync новым бинарником; затем вернуть прежние образы.

## Нерешённые вопросы

1. Код, review, terminal CI/Security, `make production-check`, Docker, exact Worker model gate и отдельный evidence workflow прошли.
2. Адресная remediation, post-cycle backup/readback/restore, полный strict цикл, API/бот и zero-work feedback прошли; outbox 0.
3. Настоящий актуальный candidate с owner решением не появился в текущих NHL данных; владелец 2026-10-12 перенёс этот gate на подключение нового турнира. Таймеры v1.3.6 оставались выключенными; проверка 20 ticks входит в v1.3.7.
