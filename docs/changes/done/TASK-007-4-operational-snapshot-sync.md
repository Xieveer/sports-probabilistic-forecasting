# TASK-007-4 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-15
> **Задача:** [TASK-007-4](../../backlog/tasks/TASK-007-4-operational-snapshot-sync.md)

## Реализованный результат

После successful full-refresh commit VPS экспортирует current canonical revisions
в partitioned Parquet immutable archive. Manifest содержит content-addressed
identity, size/checksum и безопасную run/config/source/data provenance. Local
контур проверяет и дедуплицирует artifact, затем создаёт явный training-input
descriptor перед ручным DVC workflow; DVC и training автоматически не запускаются.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/deploy/canonical_snapshot.py` | Canonical current-revision → Parquet export. |
| `sports_forecast/deploy/serving_data.py` | Provenance archive identity и training-input CLI. |
| `sports_forecast/orchestration/canonical_full_refresh.py` | Export после successful DB commit. |
| `docs/operations/serving-data.md` | Local sync и descriptor workflow. |
| `docs/operations/canonical-full-refresh.md` | VPS archive staging boundary. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_serving_data_archive.py -q` — новый provenance test падал из-за отсутствующего аргумента.
- **Green:** archive/export/import contract tests — успешно.
- **Refactor:** использован существующий verified archive protocol вместо второго формата manifest.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest tests/test_serving_data_archive.py tests/test_canonical_snapshot.py tests/test_canonical_full_refresh.py tests/test_canonical_full_refresh_cli.py -q` | 14 passed |
| `uv run ruff check …` | успешно |
| `git diff --check` | успешно |
| `mypy` | не запущен: executable отсутствует в окружении |

## Документация, review и follow-up

- Документация: [serving-data](../../operations/serving-data.md), [canonical full refresh](../../operations/canonical-full-refresh.md).
- Review / security: не выполнялись.
- Follow-up: Object Storage transport, credentials и IAM topology — TASK-007-5.

## Остаточные риски

- Network upload и least-privilege bucket policy не реализованы в runtime: staging layout и documented prefix являются входом TASK-007-5.
- Полный NHL archive требует resource measurement в TASK-007-6.
