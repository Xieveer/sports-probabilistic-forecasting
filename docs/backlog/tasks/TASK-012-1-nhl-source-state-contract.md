# TASK-012-1 — NHL source-state bundle, sync и local import

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-012](../EPIC-012-nhl-source-state-archive.md)
> **Требование:** [REQ-012](../../product/requirements/REQ-012-nhl-source-state-archive.md)
> **ADR:** [ADR-012](../../architecture/adr/ADR-012-nhl-source-state-archive.md) (`accepted`)

## Результат и границы

Один source-state contract для initial NHL bootstrap, post-refresh export и
read-only local input. Existing canonical archive semantics не меняются;
Worker не получает Object Storage credentials.

## Критерии приёмки

- [x] Verified immutable bundle содержит source, OddsStore, checkpoint и
  manifest counts/provenance; install idempotent и atomic.
- [x] Successful acquisition + canonical refresh создаёт source-state artifact,
  а provider/odds failure сохраняет предыдущее current/verified state.
- [x] Remote verified export и local latest-read-only import не меняют local
  training input до checksum verification и включают odds history.

## План реализации

1. Написать failing contract tests для incomplete/tampered install, complete
   bootstrap → incremental refresh → export → local import и failure preserve.
2. Реализовать manifest/bundle/install/export/import APIs и CLI с `pathlib.Path`
   и safe logging.
3. Связать export с successful orchestration, добавить отдельные Compose/systemd
   commands без расширения Worker credential boundary.

## Затрагиваемые области и зависимости

- `sports_forecast/deploy/`, `sports_forecast/orchestration/`,
  `docker-compose.prod.yml`, `deploy/systemd/`, targeted tests.
- Требует принятия ADR-012 и выдачи DevOps нового prefix policy до external
  integration evidence.

## Проверка

- Targeted pytest, Ruff и mypy изменённых файлов; затем релевантные `make`
  gates и `docker compose ... config --quiet`.

## Handoff и отчёт

- Отчёт выполнения: [TASK-012-1 report](../../changes/done/TASK-012-1-nhl-source-state-contract.md).
- Follow-up / findings: нет.
- Review: независимый review после реализации.
- Commit/push: заполняет reviewer отдельным evidence-коммитом до release tag.
