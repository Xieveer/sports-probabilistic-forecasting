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
