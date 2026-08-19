# TASK-007-10 — отчёт о выделенной runtime-идентичности контейнеров

> **Статус задачи:** done
> **Дата:** 2026-08-19
> **Задача:** [TASK-007-10](../../backlog/tasks/TASK-007-10-runtime-container-identity.md)

## Реализованный результат

Dockerfile создаёт `sf` с UID/GID `10001:10001`; API, Worker, Telegram bot и
archive-sync остаются запущенными как `sf`. Static contract test фиксирует
числа и покрывает каждый runtime target. Production handoff передаёт Operations
обязательство создать `sf-runtime` с теми же UID/GID и не использовать старые
images/digests.

## Изменённые границы

| Путь | Назначение |
|---|---|
| `Dockerfile` | Fixed непривилегированная runtime identity `10001:10001`. |
| `Makefile` | Dependency audit передаёт `pip-audit` абсолютный путь, поэтому release CI не теряет exported requirements. |
| `tests/test_production_topology.py` | Контракт numeric UID/GID и четырёх runtime stages. |
| `tests/test_release_version_contract.py` | Контракт абсолютного requirements path для release dependency audit. |
| `docs/product/requirements/REQ-010-runtime-container-identity.md` | Подтверждённые security requirements. |
| `docs/backlog/EPIC-007-autonomous-production-data-runtime.md` | Security blocker добавлен в декомпозицию эпика. |
| `docs/backlog/tasks/TASK-007-10-runtime-container-identity.md` | Выполненный вертикальный срез. |
| `docs/operations/production-handoff.md` | Prerequisite host identity, mounts и release evidence. |

## Доказательство TDD

- **Red:** `uv run pytest tests/test_production_topology.py::test_runtime_images_use_fixed_non_root_identity -q` — ожидаемо упал: Dockerfile не содержал `groupadd --system --gid 10001 sf`.
- **Green:** `uv run pytest tests/test_production_topology.py -q` — 12 passed.
- **Red (release gate):** `uv run pytest tests/test_release_version_contract.py::test_release_dependency_audit_uses_an_absolute_requirements_path -q` — ожидаемо упал: `pip-audit` использовал относительный path, и `make security` не мог прочитать requirements.
- **Green (release gate):** `make security` — dependency audit завершён без known vulnerabilities после передачи абсолютного path.
- **Refactor:** не требовался; изменены одна команда создания identity и один путь security gate.

## Фактически выполненные проверки

| Команда / наблюдение | Результат |
|---|---|
| `uv run pytest tests/test_production_topology.py -q` | 12 passed. |
| `make lint` | `ruff check` passed. |
| `uv run pre-commit run mypy --all-files` | passed. |
| `make production-check` | `Production handoff is valid.` |
| `make security` | Сначала выявил относительный path defect; после исправления `pip-audit` прошёл для locked runtime dependencies без known vulnerabilities. |
| `docker build --target <api|worker|telegram-bot|archive-sync> -q .` | Не выполнено: Docker daemon не смог получить metadata `python:3.12-slim` из Docker Hub (`network is unreachable`); images не созданы. |
| Published image scan, provenance и immutable digest | Не выполнялись: tag/push отсутствуют. |

## Документация, review и follow-up

- Документация: [REQ-010](../../product/requirements/REQ-010-runtime-container-identity.md) и [production handoff](../../operations/production-handoff.md).
- Security review: устранён достижимый риск совпадения container UID/GID с host
  `zabbix:systemd-journal`. До замены image старые digests остаются небезопасными
  для bind mounts; CI image scan/provenance не заменяются локальным audit.
- Release review: **CONDITIONAL GO** для независимого review: PR
  [#22](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/22)
  готов к review и содержит `57b683a`; PR CI успешно прошёл lint/test, dependency audit и
  filesystem/secret scan. **NO-GO** для tag/rollout, пока reviewer не одобрит
  и не merge-ит PR, tag `v1.1.1` CI не создаст четыре новых digest/scan/provenance, а
  Operations не подтвердит host user/mount ownership.
- Commit/push: `57b683a` опубликован в `agent/release-1-0-1`; `main.py` не
  входит в commit, потому что это несвязанное пользовательское изменение.
- Review finding P2: синхронизация статуса TASK-007-10 в EPIC-007 исправлена
  отдельным documentation-only commit после комментария к PR #22.
- Follow-up: Operations создаёт `sf-runtime:10001:10001`, назначает права лишь
  source/archive mounts и использует только новые immutable digests.

## Остаточные риски

- Локально не подтверждён `Config.User` собранных images из-за отсутствия
  сетевого доступа к Docker Hub; это обязательный CI/Operations gate.
- Числовая identity снижает риск конкретной коллизии, но безопасность bind mounts
  также зависит от фактических owner/mode/ACL и отсутствия коллизии UID/GID на VPS.
