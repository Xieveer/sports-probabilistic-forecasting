# Передача сервиса в эксплуатацию: v1.3.2 candidate

- Статус подготовки: `candidate`
- Решение на 2026-10-11: `NO-GO`; подготовка приложения идёт, серверные и artifact gates ещё не пройдены.
- Инициатива: [EPIC-035](../backlog/EPIC-035-v1-3-2-registry-rollout.md), registry gate [EPIC-026](../backlog/EPIC-026-entity-registry.md).
- Владелец решения о rollout: пользователь; исполнитель: Operations Agent.
- Целевая среда: production VPS `ops-prod-01`; версия: `1.3.2`.
- source_tag: `v1.3.2` — запланирован; создаётся на exact merge commit после review, terminal PR CI/security и локальных pre-tag gates.
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
для exact source commit v1.3.2 требуется новый immutable wrapper старых
утверждённых payload с проверкой checksum, CatBoost и 489 признаков.

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

До GO нужны terminal PR CI/security, annotated source tag `v1.3.2`, успешный
tag pipeline с scan/provenance, immutable release manifest и отдельный
release-evidence tag/gate (`--handoff docs/operations/production-handoff.md`).
Откат: остановить dispatcher, вернуть exact `v1.3.1` image refs, прежний
model wrapper, reader mode и прежний verified registry snapshot; при
несовместимой схеме использовать проверенный forward-fix либо восстановить
подтверждённый backup в окно простоя. Старые артефакты не удалять.

## Нерешённые вопросы

1. PR #84 с доверенным NHL bootstrap прошёл terminal CI/security и вошёл в
   `main`; release candidate v1.3.2 ещё требует собственного review и CI.
2. Требуются временный privileged VPS access, свежие backup/restore и
   подтверждение фактической production конфигурации.
3. Нужно проверить bookmaker event coverage, реальные прогнозы и линию после
   strict switch, а также полный непустой feedback цикл с решением владельца.
4. Исторический merge OddsStore в `source.csv` отключён в strict режиме по
   ADR-029. Штатный daily source acquisition использует `--odds-enabled false`,
   а текущую линию собирает отдельный data_odds этап; проверить реальный цикл.
5. Exact source/image/model/evidence идентификаторы и итоги server smoke
   добавляются только после фактического прохождения соответствующих gates.

Статус `candidate` означает заполненный контракт подготовки. Решение о
production switch остаётся `NO-GO` до закрытия перечисленных gates.
