# TASK-015-1 — Runtime bootstrap и first-rollout gate

> **Статус:** in_progress
> **Владелец:** implementer
> **Эпик:** [EPIC-015](../EPIC-015-production-first-rollout-gate.md)
> **Требование:** [REQ-017](../../product/requirements/REQ-017-production-first-rollout-contract.md)
> **ADR:** [ADR-016](../../architecture/adr/ADR-016-first-rollout-runtime-contract.md)

## Результат и границы

Заменить runtime `uv run`, добавить least-privilege DB bootstrap и automated
clean Docker scenario. Не запускать production deployment/tag/publication.

## Критерии приёмки

- [x] Runtime API/Worker/bot/archive commands используют installed environment;
  Worker и bot default Hydra commands read-only-safe.
- [ ] DB roles/grants и secrets file contract покрыты targeted tests и clean local
  PostgreSQL bootstrap/migration scenario.
- [ ] Local runner и tag-only workflow сохраняют redacted evidence, включая
  isolated logical restore, service state и no-secret log gate.
- [x] Telegram fake endpoint и heartbeat добавлены в full runner.
- [x] Archive-sync проверен против isolated MinIO endpoint.
- [ ] Закрыть P1 review: least-privilege grants, health/resource evidence,
  complete rollback, immutable workflow inputs/provenance и type gate.

### Детализация remediation

- [x] DB catalog deny для Alembic/control tables.
- [x] Evidence health/restart/ports/RSS/disk и all-service redacted logs.
- [x] DB schema/content restore и verified model pointer rollback.
- [x] Pinned workflow inputs, tag-version/provenance policy test.
- [x] Reproducible mypy target и повторное independent review.

### Findings повторного review (2026-09-06)

- [x] Publication использует тот же OCI artifact и digest, который прошёл
  first-rollout; workflow больше не пересобирает image после gate.
- [x] DB restore проверяет pre-migration schema/content sentinel и catalog deny
  для API/Worker identities; bot обязан достичь Docker `healthy`.
- [x] Role bootstrap не передаёт DB URL или passwords через argv; `make type-check`
  воспроизводимо запускает полный mypy hook.
- [x] Закрепить полными SHA все GitHub Actions в caller build/publish chain.
- [x] Проверять stdout/stderr всех удаляемых one-shot контейнеров до discard.
- [x] Добавить fail-closed evidence Worker peak RSS и disk/free-space для
  runtime mounts; повторный independent review не выявил blocking findings.

### Findings финального review (2026-09-06) — P1

- [x] Проверить clean tree до скачивания OCI artifacts либо исключить только
  CI-generated `artifacts/release-oci` без ослабления контроля tracked files.
- [x] Сверить реальные API/Worker queries с table grants, добавить недостающий
  whitelist и позитивные DB-пробы runtime identities.
- [x] Повторить full clean runner; historical JSON удалён, а официальный
  redacted evidence создаёт tag CI с реальным commit/digest и новой schema.
- [x] Синхронизировать handoff с Compose и `.env.example`: передавать paths
  `*_FILE`, а не secret values в env.

P1 remediation прошла повторное independent review без blocking
findings. Проверенный diff зафиксирован в commit
`2772b93a198573f354643b242ae9a60493020f97`. TASK остаётся `in_progress`
до tag CI, создающего официальный evidence artifact.

### Security remediation candidate v1.1.7 (2026-09-07)

После перепривязки `v1.1.6` запуск `34093047138` остановился в `make security`
до OCI build/publish: audit зафиксировал `PYSEC-2026-113` для `pyarrow 22.0.0`.
Ранний запуск `33961438667` на прежнем binding `7f8b86f` публиковал образы;
обе версии binding и их артефакты quarantined и запрещены для rollout. По явному
решению владельца constraint повышен до `pyarrow>=23.0.1`, lock пересоздан
resolver-ом, а новый candidate выпускается только отдельным immutable tag
`v1.1.7`. Требуются повторные независимое review и tag CI.

Security remediation прошла повторное independent review без
blocking findings. Проверенный diff зафиксирован в commit
`7ab69362a5f55a7965b7b4398b748853ed5da09d`. Подтверждены frozen lock,
`pyarrow 25.0.1`, `make security`, 988 unit tests, release contract, mypy,
lint, production-check, docs и quarantine narrative для обоих binding
`v1.1.6`. TASK остаётся `in_progress` до tag CI `v1.1.7`.

Tag CI `v1.1.7` прошёл security и static gates, но остановился до OCI build,
first-rollout и publication: rendered Compose workflow включал runtime profiles,
но не профиль `migration`, хотя verifier требует полный service contract.
Workflow исправлен и покрыт release-contract test; новый immutable candidate —
`v1.1.8`. TASK остаётся `in_progress` до его tag CI.

Tag CI `v1.1.8` прошёл Compose gate, но остановился до OCI build на read-only
Candidate `v1.1.9` подтвердил writable `/tmp`, но first-rollout остановился:
OCI layout не загружается через `docker load`. Candidate `v1.1.10` заменяет
его единым Docker archive для проверки и publication; TASK ожидает review/tag CI.

Tag CI `v1.1.10` успешно прошёл `docker load`, но fail-closed остановился на
clean-tree gate до запуска rollout: default `git status --porcelain` свернул
untracked artifact directory. Candidate `v1.1.11` использует
`--untracked-files=all`, поэтому whitelist проверяет точные имена четырёх
`*.docker.tar`, не разрешая посторонние файлы или tracked изменения.

Tag CI `v1.1.11` прошёл этот clean-tree gate, загрузил archive и выполнил
сценарий до teardown, но runner не смог удалить UID-owned файлы temporary root.
Candidate `v1.1.12` после `compose down` запускает одноразовый root cleanup
только для этого temporary bind mount и возвращает ownership UID/GID runner;
runtime images и Compose services не получают root.

Tag CI `v1.1.12` ([run 34112802577](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/34112802577)) прошёл все release gates, archive,
local-registry `docker load` и запуск clean scenario, но снова остановился при
teardown: дочерние temporary bind paths остались неудаляемыми (`Permission
denied`). Root one-shot не является доказанным исправлением фактической
ownership/mount topology. `v1.1.12` immutable и запрещён для rollout; publication,
provenance и published image digests не создавались. TASK остаётся `in_progress`
до воспроизводящего теста удаляемости дочерних mount paths и нового candidate.

Candidate diff прошёл independent review 2026-09-07 без blocking
findings и зафиксирован в commit
`c6c258bf3d6f9c9cad1e33d75dd38ea9666d6648`. Reviewer повторил exact
fixture → Compose `migration/worker/source-acquisition/operational-sync` →
verifier gate, release contract, mypy, docs, frozen lock и `git diff --check`.

### Remediation cleanup topology (2026-09-07)

Локальная remediation исправляет подтверждённую причину `v1.1.12`: прежний
root one-shot возвращал ownership внутреннего `TemporaryDirectory` runner, а
не четырёх дочерних fixture bind mounts, которые фактически изменяют runtime
containers. Cleanup теперь получает только exact mounts `runtime_models`,
`canonical_source`, `operational_archive` и `archive_sync_state`, возвращает
их ownership UID/GID runner после `compose down`, а workflow явно выполняет
`rm -rf` временного fixture root до завершения шага. Таким образом удаляемость
проверяется как часть CI-команды, а не неявным `trap` после неё.

Локально выполнены: targeted first-rollout/topology tests (35 passed),
`make test-unit` (990 passed), `make lint`, `make type-check`,
`make production-check`, `make security`, `make docs` и `git diff --check`.
Sphinx сохранил одно известное предупреждение об отсутствующем `_static`.
Полный сценарий намеренно не запускался локально: он требует exact immutable
runtime images, создаваемые tag CI. TASK остаётся `in_progress` до нового
immutable candidate и его успешного first-rollout, scan, provenance и
publication evidence.

Попытка local full runner после сборки всех четырёх runtime images была начата
на commit `2c6941a`, но остановилась до Compose-сценария: Docker не смог
получить pinned PostgreSQL image из Docker Hub (`network is unreachable`).
Local registry был остановлен, JSON evidence не создан. Это внешнее ограничение
не считается подтверждением cleanup и не меняет статус `NO-GO`.

### Independent review (2026-09-07)

- Blocking findings: не обнаружены.
- Проверены correctness, least-privilege grants, OCI provenance,
  file-backed secrets, operations profile, tests и каноническая документация.
- Independent gates: mypy passed; targeted pytest — 48 passed;
  `make production-check`, `make lint`, `make docs`, `git diff --check` — passed.
- `make docs` сохранил одно существующее warning об отсутствующем
  `html_static_path` `_static`.

## План реализации

1. Добавить static contract test, подтверждающий отсутствие `uv run` и secret/role contract (red).
2. Изменить Docker/Compose/bootstrap CLI и получить green targeted tests.
3. Добавить clean rollout runner, workflow and canonical Operations runbook.
4. Выполнить available local Docker scenario и relevant checks.
5. Добавить controlled external test endpoints и закрыть оставшиеся runtime checks.

## Проверка

- `uv run pytest tests/test_production_first_rollout_contract.py tests/test_production_topology.py -q`
- `make lint`, `make docs`, `make production-check`; Docker scenario при наличии images/network.

## Handoff и отчёт

- Отчёт выполнения: [TASK-015-1-production-first-rollout-gate.md](../../changes/done/TASK-015-1-production-first-rollout-gate.md).
- Review: remediation commit
  `2772b93a198573f354643b242ae9a60493020f97` прошёл independent review без
  blocking findings. GitHub required check/tag protection и tag CI evidence
  остаются незавершёнными внешними шагами.
