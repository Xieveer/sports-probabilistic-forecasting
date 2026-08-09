# ADR-005 — Изолированный production serving-контур

> **Статус:** accepted
> **Дата:** 2026-08-09
> **Связанное требование:** [REQ-005](../../product/requirements/REQ-005-production-serving-release.md)

## Контекст и критерии выбора

Текущий Compose объединяет training-зависимости и локальный monitoring с
runtime-сервисами; Worker включает `data/` и `models/` в Docker image; schema
создаётся API при старте. Это не даёт доказуемого состава production release,
малого объёма runtime data и управляемого rollback. Решение должно сохранить
локальный development-контур, не раскрыть метрики наружу, позволить безопасный
одноразовый Worker и дать DevOps наблюдаемые rollback signals.

## Рассмотренные варианты

1. **Сохранить единый Compose и startup `create_all()`.** Быстро для локальной
   разработки, но переносит training/monitoring в production и не даёт
   документируемой migration/recovery процедуры.
2. **Отдельный production profile с immutable runtime bundle (выбран).**
   Production Compose содержит только serving-сервисы; модель доставляется
   отдельным versioned manifest/bundle с checksum, Worker запускается
   scheduler-ом как job, миграция — отдельной командой. Локальный stack остаётся
   development-инструментом.
3. **Отдельный model registry/control plane.** Масштабируемее, но вводит новую
   production-систему, авторизацию и эксплуатационную нагрузку вне scope.

## Решение

Выбран вариант 2 со следующими инвариантами:

- production topology: API, PostgreSQL, bot, Caddy и одноразовый Worker; Alloy
  остаётся инфраструктурным агентом вне application Compose;
- release config фиксирует `image@sha256`, application version/commit и model
  manifest с checksum; `latest` и SemVer tag не используются как runtime ID;
- `/health` не проверяет зависимости, `/ready` проверяет PostgreSQL, Caddy не
  проксирует `/metrics`;
- migrations являются versioned, additive и выполняются до API/Worker после
  backup; startup не меняет schema;
- model pointer меняется только явным promotion, хранит текущий и предыдущий
  совместимые bundles; MLflow Model Registry служит control plane ручного
  approval/provenance, а immutable bundle и deployment manifest хранятся в
  `production-models/` Object Storage; это расширяет, а не обходит ADR-003;
- DVC — local source of truth для исторических training data. VPS архивирует
  фактически полученные raw/snapshot/prediction data в Object Storage, локальный
  контур валидирует и импортирует их в DVC; в обратную сторону поставляется
  только компактный serving-data bundle с нужным feature lookback context;
- VPS хранит максимум семь дней runtime data и получает read-only доступ к
  approved model/serving bundles; облачный archive не удаляется автоматически;
- Worker делает bounded job, пишет через транзакционный/идемпотентный контракт
  и публикует только безопасный execution state.

## Последствия

- Положительные: ясный supply chain, меньшая поверхность VPS, измеримый rollout
  и выполнимый rollback.
- Отрицательные и стоимость: нужны migration framework, модельный manifest,
  scheduler contract и дополнительные integration tests.
- Безопасность и эксплуатация: secrets остаются в secret store; метрики,
  heartbeat и errors не содержат tokens, PII, тел сообщений или API responses.
- Откат: до schema change — вернуть предыдущие image/model digests; после
  additive migration — forward-fix или восстановление backup, но не downgrade
  destructive schema.

## Проверка и пересмотр

Решение подтверждается contract/integration tests, `docker compose config` для
production profile, dry-run migration и prod-like Worker measurement. Оно
пересматривается, если Alloy не может безопасно собирать требуемые signals или
один VPS не обеспечивает resource budget Worker.

## Источники и неизвестное

- [Сообщение DevOps](../../deploy/devops_message.md) — источник обязательных
  release, runtime и observability условий.
- Конкретный scheduler и backup RPO/RTO ещё должен подтвердить DevOps
  Operations Agent; daily job запускается в 10:00 МСК.
