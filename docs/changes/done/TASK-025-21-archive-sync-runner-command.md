# TASK-025-21 — Команда archive-sync production runner

> **Статус:** in_progress — код/review/локальный runtime подтверждены; production gate открыт
> **Задача:** [TASK-025-21](../../backlog/tasks/TASK-025-21-archive-sync-runner-command.md)

## Граница

Исправление вызова archive-sync в production runner и обязательный
предрелизный тест того же Compose-пути с локальным Object Storage fixture.
Контракт данных, весов модели и Telegram API не меняется.

## Доказательство

Production v1.2.7: стадии calendar/quality/predictions/publication прошли;
`archive_sync` вызвала системный `sync` с неподдерживаемым `--archive`.
Официальный owner-fenced terminal outcome — `failed/archive_sync_failed`,
active0, outbox один delivered. Записано 1 834 прогнозов, будущие события
ready 187/187, odds attempts0. API/bot healthy, календарь 0/7/30 =
0/34/187, оба timer disabled. Полный raw log сохранён только root-only у
Operations; в Git нет секретов или полного внешнего ответа.

Runner теперь явно вызывает `/app/.venv/bin/python -m
sports_forecast.deploy.archive_sync_cli sync` через Compose service
`archive-sync` для каждого immutable manifest, с соответствующим
`--archive`, `--state-root` и `--prefix`. First-rollout использует тот же
Compose service и CLI против локального MinIO fixture, требует оба вида
архива до загрузки и проверяет upload обратным чтением байтов. Старый
вызов системного `sync` воспроизведён красным тестом; отсутствие одного
типа архива также было красным до исправления.

Developer: 68 целевых тестов прошли после исходного исправления, затем
41 целевой тест после проверки обоих типов архива; `bash -n`, Ruff и
`git diff --check` прошли. Independent Reviewer: P0–P2 нет, 54 целевых
теста, `bash -n` и diff-check прошли. Product Owner: `make lint`,
`make production-check`, 13 release-version тестов и `make docs`
(155 предупреждений) прошли. PR и tag CI/Security, Docker pipeline с
first-rollout, scan и provenance прошли; evidence CI и production manual
run пока открыты.

Первый full first-rollout на clean SHA `3522811` остановился **до MinIO**:
host harness не мог обойти временные архивные каталоги mode 0700,
принадлежащие runtime UID 10001. Все пять image targets собрались, а
cleanup завершился без оставшихся контейнеров. Перечисление manifest
перенесено внутрь того же Compose service под UID 10001 и read-only mount;
права архивов не ослаблялись. Developer подтвердил красный тест старого
host-side вызова и 41 прошедший целевой тест, Reviewer — P0–P2 нет,
29 first-rollout contract тестов и Ruff. Повторный full first-rollout
на clean SHA `61e201eaea47e88c1bb656386b3f1de5a84af8d9` прошёл:
оба вида archive-sync через Compose/MinIO, Worker, API calendar 0/7/30,
бот, role-grants и isolated PostgreSQL restore. Обезличенный evidence
SHA-256 `0eb39b4a15adae32633b7e18e55a1368ee4b66868be43288162799c76dd8877c`
проверен независимым Reviewer без P0–P2. Его caveat: fixture данные
пересоздавались между попытками; повторно использованы те же exact images,
поскольку входы Docker build не менялись.
