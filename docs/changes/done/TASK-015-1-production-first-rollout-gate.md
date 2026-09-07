# TASK-015-1 — отчёт production first-rollout gate

> **Статус задачи:** reviewed; awaiting tag CI evidence
> **Дата:** 2026-09-06
> **Задача:** [TASK-015-1](../../backlog/tasks/TASK-015-1-runtime-bootstrap-and-rollout-gate.md)

## Результат

Runtime images используют installed environment без `uv run`; DB bootstrap создаёт
least-privilege roles до Alembic. Historical local JSON удалён: он не соответствовал
актуальной fail-closed schema. Официальный redacted evidence создаёт только tag CI.

## Подтверждённые этапы

- digest-only images, UID/GID `10001:10001` и read-only runtime;
- clean PostgreSQL bootstrap, Alembic `0009_prediction_refresh_provenance`;
- model/bootstrap/source-state, bounded Worker и idempotent run ID;
- MinIO archive-sync, API readiness, Telegram stub/heartbeat;
- no-secret logs и isolated logical restore pre-migration backup.

## Проверки

- Full PTY runner: exit code 0.
- Targeted pytest/Ruff и `git diff --check` — successful в ходе задачи.

## Review remediation

P1 remediation завершён: API/Worker grants стали whitelist-only с deny для
`alembic_version`; DB restore сверяет pre-migration schema/content sentinel;
model pointer проходит `current → previous → current`. Runner требует Docker
`healthy` для bot, сканирует stdout+stderr long-lived и one-shot containers,
сохраняет Worker peak RSS и disk evidence. CI строит OCI artifact один раз,
тестирует и публикует тот же digest; Actions закреплены SHA. Добавлен
воспроизводимый `make type-check`.

Последующее финальное independent review выявило P1: clean tree проверяется
после OCI artifacts, grants не покрывают реальные runtime queries, historical
JSON не соответствует новой evidence schema, handoff описывает secret values
вместо `*_FILE`. Remediation добавляет clean-tree gate до OCI download,
позитивные runtime DB probes, точные sequence grants и complete systemd Compose
profile. Full clean runner прошёл в изолированном clean Git clone за 128.914 с;
tag CI должен повторить его с реальным commit и OCI digests. TASK остаётся
`in_progress`; отчёт не является production approval до повторного review и CI.

## Проверки remediation

- `uv run pytest tests/test_production_first_rollout_contract.py tests/test_release_version_contract.py tests/test_production_topology.py -q` — 37 passed.
- `uv run mypy --follow-imports=skip --ignore-missing-imports scripts/run_production_first_rollout.py` — successful.
- `make type-check`, `make lint`, `make production-check`, `git diff --check` — successful.
- `make test-unit` — 974 passed, 8 deselected.

## Independent review evidence

Повторное independent review 2026-09-07 не выявило blocking findings.
Проверенный implementation diff зафиксирован в commit
`2772b93a198573f354643b242ae9a60493020f97`.

Независимо выполнены mypy, 48 targeted tests, `make production-check`,
`make lint`, `make docs` и `git diff --check`; все gates завершились
успешно. Sphinx сохранил одно существующее warning об `_static`.

## Остаточный внешний шаг

GitHub required check для release tags должен быть назначен владельцем репозитория;
это не изменяется локальным кодом.

## Security remediation candidate v1.1.7

После перепривязки `v1.1.6` запуск `34093047138` не прошёл dependency audit до
сборки OCI artifacts и публикации: `pip-audit` обнаружил `PYSEC-2026-113` для
`pyarrow 22.0.0`. Ранний запуск `33961438667` на прежнем binding `7f8b86f`
публиковал образы; оба binding и их артефакты quarantined и запрещены для
rollout. По явному одобрению владельца constraint повышен до `pyarrow>=23.0.1`;
lock обновлён resolver-ом до `pyarrow 25.0.1` и совместимых transitive
dependencies. Локальный `make security` завершился `No known vulnerabilities
found`. Новый candidate должен выпускаться только тегом `v1.1.7` после
независимого review.

### Review evidence security remediation

Повторное independent review 2026-09-07 не выявило blocking findings.
Проверенный security-release diff: commit
`7ab69362a5f55a7965b7b4398b748853ed5da09d`. Independently проверены
frozen lock и installed versions, `make security`, 988 unit tests, 10 release
contract tests, mypy, lint, production-check, docs и `git diff --check`.
Sphinx сохранил одно существующее warning об `_static`; tag CI ещё
не выполнялся.

## Compose remediation candidate v1.1.8

Tag CI `v1.1.7` прошёл lint, unit tests, dependency audit, documentation и
filesystem/secret scan, но fail-closed остановился на rendered Compose contract:
workflow активировал `worker`, `source-acquisition` и `operational-sync`, не
активировав `migration`, хотя verifier ожидает полный набор services. OCI build,
first-rollout и publication не запускались. Workflow теперь добавляет профиль
`migration`; воспроизводящий release-contract test и локальная rendered Compose
verification прошли. Новый immutable candidate — `v1.1.8`; предыдущий tag
запрещён для rollout.

Tag CI `v1.1.8` прошёл Compose gate, но Worker image gate остановился до OCI
build: read-only container не получил writable `/tmp` для Matplotlib. В
candidate `v1.1.9` gate получает `--tmpfs /tmp:rw,noexec,nosuid,size=512m`,
как production Worker; локальная проверка runtime image и release-contract прошли.

### Local release evidence v1.1.9

Проверка 2026-09-07 на candidate worktree завершилась успешно:

- targeted release/rollout/topology contracts — 43 passed;
- rendered Compose gate с profiles `migration`, `worker`, `source-acquisition`,
  `operational-sync` и final Worker image gate — successful;
- `make lint`, `make test-unit` (988 passed), `make security`, `make type-check`,
  `make production-check`, `make docs` и `git diff --check` — successful.

`make docs` сохранил 155 существующих предупреждений Sphinx; ни одно не связано
с v1.1.9. Tag CI, OCI digests, scans, provenance и production rollout не
выполнялись и остаются обязательными внешними gates.

### CI remediation candidate v1.1.10

Tag CI `v1.1.9` ([run 34102058697](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/34102058697)) прошёл release gates и собрал
все четыре prebuilt image artifact, но fail-closed остановился на first-rollout:
`docker load` не принимает OCI layout (`blobs/json` отсутствует). Никакие image
digest, provenance или publication не были созданы. Candidate `v1.1.10`
использует Docker archive от build до first-rollout и exact publication; contract
test не допускает рассинхронизации exporter-а и consumer-ов.

Локально для v1.1.10 прошли 43 targeted release/rollout/topology tests,
`make lint`, `make type-check`, `make production-check`, `make docs`,
`make test-unit` (988 passed) и `git diff --check`.

### CI remediation candidate v1.1.11

Tag CI `v1.1.10` ([run 34104153452](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/34104153452)) прошёл release gates и загрузил все
четыре Docker archive; следовательно, несовместимость OCI layout устранена.
Runner затем fail-closed остановился до rollout с `release evidence требует clean
Git worktree`: `git status --porcelain` свернул untracked artifact directory и
не выдал имена archive для строгого whitelist. Candidate `v1.1.11` добавляет
`--untracked-files=all`; разрешены только exact `artifacts/release-oci/*.docker.tar`,
а tracked и прочие untracked paths по-прежнему являются ошибкой. Никакие image
digest, provenance или publication для `v1.1.10` не были созданы.

Локально для `v1.1.11` прошли 43 targeted release/rollout/topology tests,
`make lint`, `make type-check`, `make production-check`, `make test-unit`
(988 passed), `make docs` и `git diff --check`. `make docs` сохранил 155
существующих предупреждений Sphinx; exact Buildx exporter и внешний tag CI
пока не выполнялись.

### CI remediation candidate v1.1.12

Tag CI `v1.1.11` ([run 34109926618](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/34109926618)) прошёл все release gates, собрал четыре
Docker archive, загрузил их в local registry и выполнил first-rollout до
teardown. Он fail-closed завершился при удалении temporary root: runtime
containers оставили файлы с UID, недоступным GitHub runner. Publication,
provenance и image digests поэтому не созданы. Candidate `v1.1.12` после
`compose down` запускает root one-shot только для temporary bind mount и
возвращает ownership UID/GID runner; public runtime boundary не меняется.

Локально для `v1.1.12` прошли 44 targeted release/rollout/topology tests,
`make lint`, `make type-check`, `make production-check`, `make test-unit`
(989 passed), `make docs` и `git diff --check`. `make docs` сохранил 155
существующих предупреждений Sphinx; внешний tag CI пока не выполнялся.

### Immutable tag CI chronology v1.1.7–v1.1.12

| Tag | Изменение и цель | Фактический итог CI | Почему тег запрещён для rollout |
|---|---|---|---|
| `v1.1.7` | Обновить dependency resolution для `PYSEC-2026-113`. | Dependency/static gates прошли; Compose остановился до build. | Нет artifacts, first-rollout или publication. |
| `v1.1.8` | Включить обязательный Compose profile `migration`. | Compose прошёл; Worker gate остановился до build. | Read-only Worker не получил writable `/tmp`. |
| `v1.1.9` | Передать Worker ограниченный tmpfs `/tmp`. | Все release gates и OCI build прошли; first-rollout остановился. | OCI layout несовместим с `docker load`; publication/digests нет. |
| `v1.1.10` | Перевести build, rollout и publication на Docker archive. | Archive загрузились; clean-tree gate остановил rollout. | Short porcelain скрывал имена archive; publication/digests нет. |
| `v1.1.11` | Перечислять untracked files поимённо для strict whitelist. | Clean-tree и Docker load прошли; teardown остановился. | Runtime UID оставил неудаляемые temporary files; publication/digests нет. |
| `v1.1.12` | Вернуть ownership temporary mount runner после `compose down`. | Все gates, archive, `docker load` и clean scenario прошли до teardown; teardown снова завершился `Permission denied`. | Root cleanup не доказал удаляемость фактических bind paths; `build-push`, scans, provenance и publication пропущены. |

### CI result v1.1.12 and required next remediation

Tag CI `v1.1.12` ([run 34112802577](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/34112802577)) подтвердил выпускные gates, четыре Docker archive,
local-registry `docker load` и запуск first-rollout. В финальном cleanup он
снова не смог удалить файлы `runtime_models`, `source`, `archive` и
`sync-state` из temporary root (`Permission denied`). Добавленный root one-shot
не является подтверждённым исправлением. `v1.1.12` нельзя использовать ни как
runtime tag, ни как handoff artifact: published image digest, image scan,
provenance и release evidence не созданы.

Следующая remediation должна: (1) воспроизвести UID/GID и permissions всех
дочерних bind paths после `compose down`; (2) проверить удаляемость, а не только
состав cleanup-команды; (3) ограничить cleanup exact temporary paths; (4)
создать новый immutable candidate только после зелёных локальных проверок.

### Cleanup topology remediation (2026-09-07)

Исправлена доказанная причина teardown failure: cleanup `v1.1.12` монтировал
внутренний temporary root runner, тогда как runtime ownership менял четыре
отдельных fixture bind mounts. Новый cleanup монтирует и рекурсивно возвращает
ownership только `runtime_models`, `canonical_source`, `operational_archive`
и `archive_sync_state`; после runner явно удаляет fixture root в самом шаге
workflow. Unit-контракт фиксирует exact mounts, а workflow-контракт — явное
удаление до exit, поэтому разрешение на cleanup измеряется CI, а не зависит от
срабатывания shell trap.

Выполненные проверки: targeted first-rollout/topology tests — 35 passed;
`make test-unit` — 990 passed; `make lint`, `make type-check`,
`make production-check`, `make security`, `make docs`, `git diff --check` —
passed. `make docs` имеет одно существующее предупреждение об `_static`.
Полный Docker rollout не запускался локально, поскольку ему необходимы exact
immutable images из tag CI. Решение для rollout остаётся **NO-GO** до нового
candidate tag с успешными first-rollout, image scans, provenance и publication.

После локальной сборки всех четырёх runtime images был начат полный isolated
runner на commit `2c6941a`. Он остановился до Compose-сценария, потому что
Docker не смог скачать pinned PostgreSQL image из Docker Hub: `network is
unreachable`. Созданный local registry остановлен, JSON evidence не создан.
Это external failure не является зелёным cleanup evidence и не меняет verdict.

### Review evidence Compose remediation

Independent review 2026-09-07 не выявило blocking findings.
Проверенный candidate diff: commit
`c6c258bf3d6f9c9cad1e33d75dd38ea9666d6648`. Независимо выполнен
exact rendered Compose workflow gate со всеми четырьмя profiles и
verifier, release contract — 10 passed, mypy, docs, frozen lock и
`git diff --check`. Sphinx сохранил одно существующее warning об `_static`;
tag CI ещё не выполнялся.

## Необходимая следующая remediation

Канонический список P1 и критерии повторного review:
[TASK-015-1](../../backlog/tasks/TASK-015-1-runtime-bootstrap-and-rollout-gate.md).
