# Передача сервиса в эксплуатацию: v1.1.18 candidate

- Статус подготовки: `candidate`
- Сервис: `sports-probabilistic-forecasting`
- Canonical repository: `Xieveer/sports-probabilistic-forecasting`
- Владелец приложения и решения о rollout: пользователь.
- source_tag: `v1.1.18`
- source_commit: разрешается Operations из annotated tag `v1.1.18` непосредственно перед rollout.

Этот handoff относится только к выпуску Epic 23: расписание NHL в Telegram. Тег создаётся
на commit, содержащем весь код, версию и этот статический контракт; self-reference SHA в
commit намеренно не записывается. После успешного tag pipeline Operations получает exact
commit, immutable image digests, scan и provenance из GitHub Actions и сверяет их со своим
allowlist. До этого любые image reference и deploy запрещены.

`v1.1.15` не прошёл isolated first-rollout contract: Docker отклонил MinIO fixture с
network alias на default bridge (exit 125). `v1.1.16` и `v1.1.17` также остановились на
MinIO startup (exit 125) до публикации GHCR и изменения production-сервера. `v1.1.18`
передаёт MinIO как prebuilt OCI artifact: first-rollout не делает скрытый Docker Hub pull.

## Идентификация и ответственность

Выпуск заменяет только Telegram-бот, добавляя `/upcoming`: выбор NHL и горизонт `0–30`
календарных дней МСК. Модели, data/odds pipeline, value-формула, ingress, DNS, TLS,
firewall, scheduler и секреты не меняются. Пользователь разрешил ограниченный production
rollout и rollback при неуспехе technical health-check; пользовательская проверка Telegram
после rollout остаётся за владельцем.

## Runtime и конфигурация

Compose получает только pinned references из verified manifest и server-side secrets через
`*_FILE` paths. Значения DB URL, token и паролей не передаются в Git, handoff, логи или чат.
Runtime services используют UID/GID `10001:10001`. Первый контур остаётся private,
Telegram-only: base Compose не публикует host ports.

## Healthcheck и smoke-проверка

Operations после отдельного preflight запускает только `/health`, `/ready`, `/docs` и
выбранную known prediction с `live_pinnacle=false`; ожидается HTTP 200 не позднее 90 секунд.
Он проверяет restart count, безопасные логи, dependency health и deployment telemetry.
Acceptance-команда `make acceptance-check` выполняется Operations только с approved runtime
inputs после успешного запуска сервисов.
Автоматизированное сообщение production-боту и чтение token запрещены.

## Данные и совместимость

Перед migration Operations проверяет source-state, canonical bootstrap и current model bundle,
создаёт verified PostgreSQL backup, затем при необходимости последовательно выполняет
`role-bootstrap` и отдельный `migrator`. API и Worker не выполняют DDL при старте.
Изменение Epic 23 не требует migration; этот порядок сохраняется как обязательная граница
первого production rollout.

## Наблюдаемость

До запуска Operations проверяет доступность telemetry, отсутствие active incidents, ресурсы,
metadata server-side secrets без чтения значений и безопасные логи. Stop criteria: crash loop,
DB failure, missing verified backup, manifest/wrapper mismatch или не-200 readiness/health.

## Артефакт и откат

Docker workflow на tag `v1.1.18` обязан успешно завершить CI, Security, first-rollout,
publication linux/amd64 images, image scan и provenance. Operations принимает только
`IMAGE@sha256:DIGEST` из результата этого workflow, а не SemVer tag.

После публикации release owner запускает manual evidence gate с
`--handoff docs/operations/production-handoff.md`; его успех подтверждает evidence, но не
заменяет отдельный ограниченный rollout Operations.

Root-owned wrapper принимает только:

```text
deploy sports-probabilistic-forecasting v1.1.18
```

Он сверяет service, tag-resolved commit и все digests с локально установленным verified
manifest; не принимает image references, paths, environment values или дополнительные
аргументы. До migration допустим rollback только к предыдущим compatible immutable references;
после additive migration применяется forward-fix либо verified backup restore. Destructive
downgrade запрещён.

## Нерешённые вопросы

Exact image digests, workflow URLs, tag-resolved commit, фактический deployed digest и
результат health/log checks появляются только после release pipeline и ограниченного rollout.
Их фиксирует Operations в своём production change record; до этого статус этого handoff —
candidate, а не подтверждение deployment.
