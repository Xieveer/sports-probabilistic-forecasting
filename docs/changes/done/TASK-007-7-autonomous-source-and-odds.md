# TASK-007-7 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-16
> **Задача:** [TASK-007-7](../../backlog/tasks/TASK-007-7-autonomous-source-and-odds.md)

## Реализованный результат

Production scheduler теперь запускает отдельный `source-acquirer`: NHL facts и
обязательные odds обновляются до canonical refresh, после проверки CSV с
обязательными полями snapshot атомарно публикуется как `current.csv`. При
ошибке provider/odds предыдущий valid snapshot остаётся доступен, а Worker не
запускается.

Historical betting-reference вынесен в отдельный CLI-режим `--t15-reference`.
Для каждого матча он выбирает доступный snapshot из `T−60…T−0`, ближайший к
`T−15`, и записывает новые `*_t15`, `t15_provider_observed_at`,
`t15_retrieved_at`. Специальный field-level upsert сохраняет старые `*_close`.
Утренние forecast odds и historical reference не смешиваются.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `sports_forecast/orchestration/source_snapshot*.py` | Атомарная публикация и CLI acquisition. |
| `deploy/systemd/run-canonical-refresh.sh`, `docker-compose.prod.yml` | Порядок source acquisition → canonical Worker и scoped source mount. |
| `sports_forecast/data/providers/odds/` | Per-event T−15 selection, отдельные поля и безопасный reference upsert. |
| `docs/cursor/source_data/the_odds_api.md` | Команда отдельного historical прогона и квотные ограничения. |

## Фактически выполненные проверки

- `uv run pytest tests/test_source_snapshot.py tests/test_source_snapshot_cli.py tests/test_production_topology.py tests/test_source_refresh_odds.py tests/test_odds_backfill.py tests/test_snapshot_discovery.py tests/test_odds_store.py tests/test_odds_refresh.py` — 94 passed.
- `uv run ruff check …` и `uv run pre-commit run mypy --files …` — успешно.
- `docker compose -f docker-compose.prod.yml config --quiet` с фиктивными secret/image inputs — успешно.
- `curl -L https://api-web.nhle.com/v1/schedule/now` (без записи) — HTTP 200, 70 160 байт.
- `git diff --check` — успешно.

## Не выполнялось и риски

- Реальный historical T−15 backfill не запускался: он расходует квоту API и должен идти небольшими диапазонами.
- VPS deployment, scheduler enable и production migrations не выполнялись.
- Verified Object Storage sync и private ingress/tag-only images остаются в [TASK-007-8](../../backlog/tasks/TASK-007-8-verified-archive-sync.md) и [TASK-007-9](../../backlog/tasks/TASK-007-9-private-ingress-and-tag-release.md).
