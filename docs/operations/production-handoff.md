# Передача сервиса в эксплуатацию: v1.3.2 candidate

- Статус подготовки: `candidate`
- Решение на 2026-10-11: `NO-GO`; source и image gates пройдены, серверные gates ещё не пройдены.
- Инициатива: [EPIC-035](../backlog/EPIC-035-v1-3-2-registry-rollout.md), registry gate [EPIC-026](../backlog/EPIC-026-entity-registry.md).
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- Целевая среда: production VPS `ops-prod-01`; версия: `1.3.2`.
- source_tag: `v1.3.2` — annotated tag на exact merge commit `38d59dc7ffaa16f805dc5a0c3700c56c59800f53`.
- source_commit: `38d59dc7ffaa16f805dc5a0c3700c56c59800f53`.
- evidence_tag: `v1.3.2-evidence.1` — запланирован после review immutable evidence.
- Post-merge [CI](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38168060519) и [Security](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38168060529) — success на source commit.
- [Tag pipeline](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38168245261) — success: release gates, first-rollout contract, publish, scan, provenance.
- CI: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38168060519
- Security: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38168060529
- Docker: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38168245261
- first-rollout: https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38168245261
- postgres: `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`.
- api: published linux/amd64, scan, provenance; `ghcr.io/xieveer/sports-probabilistic-forecasting-api@sha256:34eb983a56e445c8506dedaecf7abecc6b742d43ac99984b92a9aa0819fbc846`.
- worker: published linux/amd64, scan, provenance; `ghcr.io/xieveer/sports-probabilistic-forecasting-worker@sha256:e87db2b0e02018e39f0ef0b864d3a1a45dea522c1fd3c42d54eab3b9b7cacdbd`.
- telegram_bot: published linux/amd64, scan, provenance; `ghcr.io/xieveer/sports-probabilistic-forecasting-telegram-bot@sha256:5f9a43369854e82b4011e9083cb55a468d046bdc26d385954a82f9d057d0d454`.
- archive_sync: published linux/amd64, scan, provenance; `ghcr.io/xieveer/sports-probabilistic-forecasting-archive-sync@sha256:daed5f1ebdc0a25f53efa10271a728211fd4449fc4178b7b58e5e50a6d764ffe`.
- Текущий production выпуск: exact `v1.3.1`, его исходный handoff доступен в истории Git до этого изменения.

## Идентификация и ответственность

Выпуск должен включить завершённые изменения после v1.3.1 и включить строгий
NHL registry reader. Код совместимости и legacy YAML сохраняются для явного
отката, как решил владелец. Новый owner master сформирован из проверенного
staging master v1.3.1 и дополнен по официальному NHL schedule через
[TASK-026-11](../changes/done/TASK-026-11-nhl-event-bootstrap.md).
Локальный snapshot `ir1:e0070e397775a9227300d3edb061b20a15744f5317ccd7e56752e6ab67e196ce`
содержит 51 event relation; 51/51 официальных game IDs разрешились строгим
reader. Он ещё не опубликован и не установлен на сервер.

## Runtime и конфигурация

`SF_APP_VERSION=1.3.2`, package, source tag, модельный bundle и `/health`
должны совпасть. Compose secrets передавать как `*_FILE` paths, не значениями
секретов в окружении. Строгий reader включать только после установки и проверки
нового snapshot и покрытия фактического production горизонта. Раздельные
credentials и PostgreSQL grants из v1.3.1 сохранить. Не передавать Object
Storage credential обычным API, Worker или боту. Старый режим reader и exact
v1.3.1 должны оставаться доступными для rollback. Модельные веса не менять:
для exact source commit v1.3.2 подготовлен новый immutable wrapper старых
утверждённых payload: `sha256:76d9a22470e9d36ea15a6f0a9c0aac78a6940eac4bd8be62838342169589fb0f`,
manifest SHA-256 `7560b631eb13153fc65063bde60a3b27f246864468aba9292e53a28ca8c48220`.
Три payload SHA совпали с v1.3.1; локально прошли verify/install/load, CatBoost
и точное совпадение 489 признаков. В exact Worker image локальная проверка
прошла под UID 10001 без сети, с read-only rootfs и mount, cap-drop ALL:
CatBoost загрузился, порядок всех 489 признаков совпал. Для серверного staging
bundle нужны права каталогов 755 и файлов 644, чтобы runtime UID мог их читать.

Независимый Reviewer повторил model gate 2026-10-11 19:50:18–19:50:46 UTC
по локальному content-addressed bundle
`/home/xieveer/Документы/codex_projects/operations-agent/tmp/v1.3.2-model-stage/bundles/sha256:76d9a22470e9d36ea15a6f0a9c0aac78a6940eac4bd8be62838342169589fb0f`:
`sha256sum manifest.json` дал `7560b631eb13153fc65063bde60a3b27f246864468aba9292e53a28ca8c48220`;
`verify_model_bundle(path, app_version="1.3.2")` вернул указанный bundle ID,
`nhl:winner_withOT:canonical-measurement` и source commit
`38d59dc7ffaa16f805dc5a0c3700c56c59800f53`. Payload SHA-256 совпали с
утверждённым v1.3.1: модель `4042e85367a9d3c493a15ef45d0d9dcba9c78004833761224e379c360b0b5cda`,
`features.txt` `ef9903eebcd26fb9c98d732e0de7e0d84b86102153788ecaf780c7979b8472fb`,
`deploy.yaml` `b908d72e03ad073686dd8cdf46016cdfbff5b2a577a3c1d37836b249238a0d00`.
В exact Worker image `e87db2b0...7cacdbd` повторный `docker run` с UID 10001,
`--network none`, `--read-only`, `--cap-drop ALL` и read-only mount завершился
успешно: `load_current_model_bundle`, CatBoost и порядок 489 признаков прошли.
Production activation модели не выполнялась.

## Healthcheck и smoke-проверка

До GO выполнить `/health`, `/ready`, `/docs`, `/openapi.json`, контрольный NHL
Data Cycle, выдачу прогноза и линии в `/predict/{match_id}` и Telegram,
проверить первые плановые ticks без дублей, публикацию/sync registry и
непустой кандидат → локальное решение владельца → новый snapshot → server
resolution. `make acceptance-check` не запускать с закрытым DB URL в
аргументах процесса; использовать безопасные GET/SELECT/health probes без
вывода секретов или полного payload. Результаты и UTC должны быть внесены
перед GO.

## Данные и совместимость

Перед switch нужны свежий root-only PostgreSQL backup, off-host readback,
изолированный restore, проверка целостности owner master и rollback копии
предыдущего registry snapshot. Проверить PostgreSQL schema revision и grants
под runtime ролями. Текущая v1.3.1 схема — `0025_real_bets_ledger`; downgrade
append-only миграций запрещён. Доступное место на VPS до нового pull ранее
оценивалось в 14 ГБ, поэтому повторить измерение. Автоматическое удаление
образов, данных или секретов не входит в этот выпуск.

## Наблюдаемость

В release evidence записать UTC, exact source commit/tag, image digests и
provenance, model bundle ID, schema revision, backup hash и restore result,
container restarts/OOM, RAM/disk, Data Cycle stage/failure codes, количество
прогнозов и доступной линии, Object Storage verification, registry snapshot ID,
feedback/ack и уведомление владельцу. Секреты, персональные данные и полные
внешние ответы в evidence не сохранять.

## Артефакт и откат

Terminal PR CI/security, annotated source tag `v1.3.2` и tag pipeline с
scan/provenance пройдены. Exact digests зафиксированы в release manifest;
до GO нужны отдельный release-evidence tag/gate
(`--handoff docs/operations/production-handoff.md`) и серверные проверки.
Автоматический release-evidence validator сверяет source и image references;
модельный bundle проходит отдельную проверку Reviewer по immutable manifest,
payload hashes и загрузке в exact Worker image. Operations Agent повторяет
проверку после доставки bundle на VPS перед переключением active model pointer.
Откат: остановить dispatcher, вернуть exact `v1.3.1` image refs, прежний
model wrapper, reader mode и прежний verified registry snapshot; при
несовместимой схеме использовать проверенный forward-fix либо восстановить
подтверждённый backup в окно простоя. Старые артефакты не удалять.

## Нерешённые вопросы

1. PR #84 с доверенным NHL bootstrap и PR #85 с release candidate прошли
   terminal CI/security и вошли в `main`.
2. Требуются временный privileged VPS access, свежие backup/restore и
   подтверждение фактической production конфигурации.
3. Нужно проверить bookmaker event coverage, реальные прогнозы и линию после
   strict switch, а также полный непустой feedback цикл с решением владельца.
4. Исторический merge OddsStore в `source.csv` отключён в strict режиме по
   ADR-029. Штатный daily source acquisition использует `--odds-enabled false`,
   а текущую линию собирает отдельный data_odds этап; проверить реальный цикл.
5. Exact source/image/model идентификаторы получены. Evidence tag и итоги
   server smoke добавляются только после фактического прохождения этих gates.

Статус `candidate` означает заполненный контракт подготовки. Решение о
production switch остаётся `NO-GO` до закрытия перечисленных gates.
