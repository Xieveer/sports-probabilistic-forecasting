# Передача сервиса в эксплуатацию: v1.3.5 candidate

- Статус подготовки: `candidate`
- Решение на 2026-10-12: `NO-GO` до полного strict Data Cycle и release gates.
- Инициатива: [EPIC-037](../backlog/EPIC-037-v1-3-5-registry-cycle.md), исходные словари [EPIC-026](../backlog/EPIC-026-entity-registry.md).
- Владелец выпуска: пользователь; rollout выполняет Operations Agent.
- Среда: production VPS `ops-prod-01`; планируемая версия `1.3.5`.
- source_tag: `v1.3.5`, annotated object `da25b3dcb83a90f14e58a1a082667982bf458414`, указывает на exact merge commit.
- source_commit: `e630a7c929720cd1585b2af825c43dacff444f85`.
- evidence_tag: `v1.3.5-evidence.1` — отдельный tag на этом evidence commit после его review/gate.
- CI: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38181374573
- Security: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38181374570
- Docker: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38181489680
- first-rollout: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38181489680/job/114595982815
- Текущий серверный stage: образы v1.3.4, registry v2 publication sequence 3, strict reader `false`, API/бот здоровы, три scheduler таймера остановлены после NO-GO strict Data Cycle. Последний полностью действующий rollback — exact v1.3.1.

## Идентификация и ответственность

Цель — ежедневный NHL/Pinnacle `winner_withOT`: подтверждённые словари турниров, команд, рынков и исходов; автоматическое сопоставление календаря и линии по участникам, сторонам и UTC ±15 минут при взаимной уникальности. Source event ID и вычисленная связь хранятся как provenance. Неизвестные обозначения попадают в очередь владельца. Legacy путь сохраняется до отдельной задачи удаления. В v1.3.5 исправляется только передача registry installation ID процессам, создающим кандидатов; бизнес-правила, модельные веса и данные registry не меняются.

v1.3.4 прошла CI/Security, image provenance и stage. Strict API/бот показали 50 NHL прогнозов, из них четыре с живой двухсторонней линией Pinnacle. Но Data Cycle `0070c85e-90a2-4656-b14e-608d6745e312` остановился на календаре с `RegistryFeedbackError: SF_ENTITY_REGISTRY_INSTALLATION_ID не задан`. Поэтому v1.3.4 получила NO-GO и strict был возвращён в `false`. Исправление и повторные gates описывает [EPIC-037](../backlog/EPIC-037-v1-3-5-registry-cycle.md).

## Runtime и конфигурация

Production Compose и systemd Data Cycle используют один авторитетный profile `/etc/sports-forecast/refresh/nhl.env`. Сейчас в нём `SF_APP_VERSION=1.3.4` и `SF_REGISTRY_EVENT_READER_ENABLED=false`; при staged переключении нужно выставить `SF_APP_VERSION=1.3.5`, сохранить strict=false и существующий валидный `SF_ENTITY_REGISTRY_INSTALLATION_ID`. Перед switch нужно проверить rendered Compose: один и тот же installation ID получают все процессы, записывающие candidates; API, бот, source-acquirer и Worker получают согласованный strict flag. После проверки v2 snapshot и preflight выставить `true`, пересоздать API/бот и запустить контролируемый Worker Data Cycle. Неверное значение strict flag вызывает ошибку. При откате сначала вернуть `false`, сверить rendered Compose и пересоздать API/бот.

Установленный v2 snapshot: `ir1:71897173e0ee72bb60f9038cc8570770b351d866a3f994e63ba26bf5bcfe03e2`, manifest SHA-256 `2885685f95086013f1cbe9c92325acedfb17e2201d043b9e0c5b770865087c3d`, publication sequence 3. Предыдущий verified v1 snapshot `ir1:e0070e397775a9227300d3edb061b20a15744f5317ccd7e56752e6ab67e196ce` сохранён. Новый sync читает v1 и v2; старый v1.3.1 sync не читает v2. Правило NHL/Pinnacle `h2h → winner_withOT` означает полный матч с ОТ/буллитами и двумя исходами.

Compose secrets передаются как `*_FILE` paths. Обычные API, Worker и бот не получают Object Storage credentials. Model wrapper для 1.3.5 собран из тех же трёх утверждённых payload SHA-256 и 489 признаков: `sha256:2262cbb4f439ee65f3a8efd811b250f9b41e5c74f8d7562d304435b46d61bde0`, manifest SHA-256 `1c09ac796b04e282ee751574e5bfa4d5e1599a94b176e393b6e655dabbf7d8ab`. Он прошёл проверку на exact published Worker image `sha256:55dde895f0aec7e5b4785c5614813373e916e2877a5f81c6f030ea0cd41bf3a9` под UID `10001`, read-only rootfs/model, network none, cap-drop ALL, no-new-privileges, RAM 1 GiB/pids 128: CatBoost загрузился, все 489 имён и порядок признаков совпали. Wrapper v1.3.4 `sha256:6ca7e2d6fefb0f64f892aba73a4a44e9b23c3e9e0ea5557c0196ea534ed77271` нельзя использовать как `app_version=1.3.5`.

## Healthcheck и smoke-проверка

До switch сверить exact source/image/model refs, Compose render, schema `0025_real_bets_ledger`, роль Worker и реальный `INSERT ... RETURNING`, Object Storage sequence, disk/RAM, active runs, backup и rollback artifacts. После switch проверить `/health`, `/ready`, `/docs`, `/openapi.json`; полезные прогнозы и живую Pinnacle линию в API/боте. Контрольный strict NHL Data Cycle должен пройти календарь, archive gate, `data_odds`, forecast и materialization, создать odds acquisition attempt и ненулевые будущие observations. Проверить неизвестное обозначение: outbox под Worker identity → local owner review → publication/sync/ack. Если среди текущих данных нет безопасного кандидата, зафиксировать это и проверить реальный вызов записи отдельно без фиктивного owner решения.

После успешного полного цикла возобновить timers. Dispatcher должен пройти 20 последовательных минутных ticks без `start-limit-hit`, stale heartbeat и лишних уведомлений. `make acceptance-check` запускать только с безопасно переданными secret files и без DB URL в аргументах процесса; допустимы эквивалентные GET/SELECT probes без вывода секретов и полных provider payload. При ошибке strict цикла, потере линии, forecast, feedback или health — остановить rollout и восстановить safe hold либо rollback.

## Данные и совместимость

Свежий root-only PostgreSQL custom-format backup после fallback Data Cycle `/var/backups/sports-forecast/postgres/pre-v1.3.5-20261011T224737764056.dump` размером 58 623 827 байт, SHA-256 `c54fd2cfacb5fd4b16b625e6a9c327b4fbd1ebe098c586f5372edcb021f46967`, прошёл полный off-host GET readback и isolated restore на exact PostgreSQL image: 22 581 events, 1 919 predictions, 5 odds observations, schema `0025_real_bets_ledger`. Перед switch повторить проверку доступности backup и текущей schema. v1.3.5 не содержит миграций. Owner master backup, старый v1 snapshot и audit/cursor сохранять. Не удалять данные, snapshots или секреты.

Проверка места на VPS после fallback цикла и свежего backup дала 8 311 431 168 свободных байт; перед pull новых образов измерить вновь и не удалять protected refs v1.3.1/v1.3.4. При нехватке места остановить rollout и согласовать конкретную очистку.

## Наблюдаемость

Release evidence фиксирует UTC, exact source tag/commit, CI/Security/Docker pipeline, пять digests и provenance, model bundle ID, schema/grants, backup hash/readback/restore, registry snapshot/sequence, candidate outbox/ack, Data Cycle stage/attempt counts, будущие прогнозы/линии, API/bot smoke, 20 ticks, disk/RAM и итог GO/NO-GO. Секреты, персональные данные и полные ответы провайдера не сохранять.

## Артефакт и откат

Source tag `v1.3.5` создан на exact merge commit после независимого review и terminal CI/Security. Docker pipeline `38181489680` завершился успешно: release gates, пять image build jobs, first-rollout, публикация четырёх образов, scan/provenance. Пять exact refs записаны в `deploy/release-manifest.json` отдельным evidence commit. Выполнить release gate `--handoff docs/operations/production-handoff.md` и независимое review evidence до evidence tag. Старые immutable tags и публикации не менять.

- image postgres: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`
- image api: `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:3db18b51535ff4631fa3be8e8bcffe5909babf6940ff51cd1fd9890dfc30c39f`
- image worker: `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:55dde895f0aec7e5b4785c5614813373e916e2877a5f81c6f030ea0cd41bf3a9`
- image telegram_bot: `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:97c16bb8488e1ea189b1cd34e58e6931afc8d4b8d3da7d91c36c9c24be7371e2`
- image archive_sync: `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:238713203781709e5e56d5841c1801f429d865a0c28b20f10f04f36f98676e78`
- api: published linux/amd64; scan и provenance прошли в Docker run `38181489680`.
- worker: published linux/amd64; scan и provenance прошли в Docker run `38181489680`.
- telegram_bot: published linux/amd64; scan и provenance прошли в Docker run `38181489680`.
- archive_sync: published linux/amd64; scan и provenance прошли в Docker run `38181489680`.

Ближайший safe hold — v1.3.4 с strict=false, registry v2 seq3, здоровыми API/ботом и остановленными timers. Полный rollback — exact v1.3.1 source `757d3af338bb2bb36304cb3e81c0f2c93a0834e5`, API `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:4bf7c27dbd25ec88d14183704a076b5a9ac824003de754fe49fb344a69fcda8c`, Worker `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:80de5332a5e7b5431cac5089bd6af27e6b70a50d758485f3e39105f2081196e3`, bot `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:8232f8643968694a50b2dbe5c96f33683592bff18952b98af08c64d89b577add`, archive-sync `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:622bca60a525ee820e25483e9033ef09603fa85ea596c1aaa42a18490cbbbf17`, PostgreSQL `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`, model `sha256:956edb47e9737516ce8a29ed42a6cea08af6522fed1b9510a614201c20daad09`. Для возврата к v1 сначала опубликовать verified v1 snapshot как новую publication с возрастающей sequence и выполнить sync новым бинарником; затем вернуть прежние образы. Immutable objects не менять.

## Нерешённые вопросы

1. TASK-037-1, независимый review, terminal CI/Security и `make production-check` прошли.
2. Exact source/image refs, Docker provenance и model wrapper на exact Worker image проверены; завершить независимый review и release-evidence gate.
3. На VPS подтвердить полный strict Data Cycle, feedback, odds/forecast/bot smoke и 20 ticks. До этого решение — `NO-GO`.
