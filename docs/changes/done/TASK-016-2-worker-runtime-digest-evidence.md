# TASK-016-2 — отчёт о runnable Worker digest

> **Статус задачи:** done
> **Дата:** 2026-09-08
> **Задача:** [TASK-016-2](../../backlog/tasks/TASK-016-2-worker-runtime-digest-evidence.md)

## Результат

Причина сбоя подтверждена: `sha256:c963edaa5ff6fa98d8871ad615faa85fcaec2250a0d108201bbb93a849dba79f`
является Sigstore/SLSA provenance referrer с пустым OCI config. Его `subject` —
runnable Worker manifest
`sha256:3f802d34f6673afa7a3df74e6fa89554a77170856108ef2347306e752ee89325`.

В `deploy/release-manifest.json` для evidence.2 заменён только `images.worker`.
Application `v1.1.14`, source commit `9daf2d5bb040a5b8860961a12cb81a48997eaeac`
и остальные четыре runtime references не изменены. Deployment не выполнялся.

## Изменённые границы

- `.github/workflows/docker.yml` получает digest из remote tagged manifest и проверяет
  runtime platform для каждого application image.
- `.github/workflows/release-evidence.yml` перед evidence tag повторяет remote platform
  gate для manifest references и выполняет Worker smoke.
- `scripts/verify_release_evidence.py` допускает следующую immutable revision того же
  application release.
- Handoff, REQ-018 и ADR-017 фиксируют incident и recovery path.

## Доказательства

- **Red:** `uv run pytest tests/test_release_evidence.py::test_evidence_accepts_next_immutable_revision_for_same_application_release -q` — 1 failed: validator был жёстко привязан к `evidence.1`.
- **Green:** `uv run pytest tests/test_release_evidence.py tests/test_release_version_contract.py -q` — 17 passed.
- **Registry/runtime:** `docker buildx imagetools inspect` exact Worker digest показал
  `application/vnd.docker.distribution.manifest.v2+json`; `docker image inspect` —
  `linux/amd64`; non-root `docker run --platform linux/amd64 --network none --read-only
  --user 10001:10001 --entrypoint python …` выполнил imports archive sync, canonical
  bootstrap и source state с exit 0.
- **Evidence:** fixture Compose render и `scripts/verify_release_evidence.py` завершились
  без ошибок.
- **Quality:** `make lint`, `make type-check` и `git diff --check` прошли.

## External finalization и риски

Новый GitHub manual evidence run, annotated tag `v1.1.14-evidence.2`, remote protection tag
и final CI/Security/Docker/scan/provenance URLs ещё не созданы этой рабочей копией: GitHub CLI
не смог получить credentials из keyring (`Timeout trying to log in`). Нельзя создавать tag до
успешного manual gate. Production deployment, migrations, bootstrap import, scheduler и secrets
не затрагивались.
