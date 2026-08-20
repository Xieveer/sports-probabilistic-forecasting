# REQ-012 — NHL source-state archive для production

> **Статус:** confirmed
> **Владелец продукта:** пользователь
> **Создано:** 2026-08-20
> **Продолжает:** [REQ-007](REQ-007-production-data-runtime.md) и [REQ-008](REQ-008-reliable-nhl-delivery.md)

## Результат и ценность

Production VPS и локальный контур получают проверяемое, воспроизводимое и
полное NHL source-state: историю матчей, исторические коэффициенты Pinnacle и
checkpoint инкрементального обновления. Это закрывает blocker rollout `v1.1.3`:
после восстановления VPS не теряет OddsStore, а локальные betting-метрики
работают с теми же коэффициентами, что и production.

## Scope

- Immutable initial NHL source-state bundle: `source.csv`,
  `odds/pinnacle_odds.parquet`, `odds/refresh_state.json` и manifest с
  SHA-256, schema version, record counts и безопасным provenance.
- Verify-before-install и идемпотентная установка в server source volume до
  первого scheduler run; `current.csv` создаётся только как проверяемая
  производная копия `source.csv` для существующего Worker contract.
- После каждого успешного acquisition и canonical refresh — отдельный
  content-addressed export полного source-state в Object Storage; partial или
  failed refresh не публикует и не заменяет последнее valid state.
- Local read-only поиск последнего verified artifact, проверка до любой локальной
  записи и явный descriptor для training/validation, включающий odds history.
- Runbooks, Compose/systemd topology, rollback/recovery, retention/IAM contract
  и release evidence; tag содержит весь статичный documentation scope, а
  появившиеся после tag image digests передаются только как CI/GHCR evidence и
  не создают post-tag commit.

## Non-scope

- Перенос DVC, MLflow, automatic training/promotion или локального control plane
  на VPS.
- Изменение существующих `dvc/*`, `production-models/*` и
  `production-backups/*` прав.
- Deployment, выдача реальных credentials, изменение bucket policy, выпуск Git
  tag либо публикация образов без отдельного разрешения.

## Сценарии

1. Локальный оператор собирает NHL bundle; VPS проверяет его до записи и
   идемпотентно устанавливает source, OddsStore и checkpoint до scheduler.
2. Успешный acquisition/refresh создаёт и remote-verify-ит source-state
   artifact; local read-only consumer получает последний verified artifact и
   готовит input с коэффициентами для betting validation.
3. Provider/odds failure либо failure export не меняет server current state и
   не публикует новый valid artifact; предыдущий verified artifact доступен для
   restore/import.
4. Следующий patch release содержит всю документацию до tag; CI публикует
   immutable digests/provenance как внешнее evidence без commit после tag.

## Критерии приёмки

- [ ] Bundle и server export содержат обязательные три NHL state-файла, manifest
  с checksum/schema/counts/provenance и проходят verify до install/import.
- [ ] Повторный verified install не изменяет source state; invalid artifact не
  создаёт partial install.
- [ ] Export запускается только после successful acquisition и canonical refresh;
  failure odds/provider не заменяет current source-state и latest artifact.
- [ ] Local command с read-only credential выбирает последний verified artifact,
  не меняет local input до verify и создаёт reproducible descriptor с odds
  history для betting metrics.
- [ ] Минимальные IAM права и immutable retention документированы; Worker не
  получает Object Storage credentials.
- [ ] Есть automated evidence initial bootstrap → install → incremental refresh,
  export → Object Storage → local import и failure preservation; handoff,
  Compose/systemd и restore/rollback актуальны.
- [ ] Новый release tag создаётся только после финального documentation commit;
  после tag не выполняется commit для фиксации digests/evidence.

## Ограничения, зависимости и риски

- Bucket `sports-probabilistic-forecasting` и существующие prefix boundaries
  подтверждены DevOps; доступ для нового source-state prefix ещё не выдан.
- `source.csv`, `pinnacle_odds.parquet` и `refresh_state.json` могут быть
  объёмными, поэтому immutable artifacts нельзя перезаписывать или очищать
  автоматически без утверждённого retention.
- Точный schema/record count для Parquet должен вычисляться кодом, а не
  угадываться из файла.

## Предположения и открытые вопросы

- Предлагаемый новый prefix: `operational-archive/nhl-source-state/v1/`.
  Он сохраняет уже работающий `operational-archive/*` контур, но изолирует
  source-state от canonical Parquet snapshots.
- Для initial bundle отдельный local publisher не нужен: оператор передаёт
  verified immutable directory на VPS по одобренному out-of-band каналу;
  `ops-prod-01-sports-forecast` публикует первый и последующие artifacts.
- DevOps подтвердил существующие IAM boundaries и lifecycle rule на 90 дней для
  `operational-archive/nhl-source-state/`; bucket/versioning/Object Lock не
  меняются.

## Подтверждение

Пользователь подтвердил REQ и согласованные prefix, IAM, lifecycle и release
проверки 2026-08-20.
