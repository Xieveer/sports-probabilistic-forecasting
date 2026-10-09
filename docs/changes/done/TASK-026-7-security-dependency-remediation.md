# TASK-026-7 — Результат обновления уязвимых Python-зависимостей

> **Статус:** done
> **Задача:** [TASK-026-7](../../backlog/tasks/TASK-026-7-security-dependency-remediation.md)

## Изменения

- Минимальная версия `hydra-core` в `pyproject.toml` поднята до `1.3.7`.
- В конфигурации uv задано ограничение `multidict>=6.9.1`, не добавляя
  транзитивную библиотеку в прямые зависимости приложения.
- `uv.lock` обновлён командой uv только для `hydra-core` и `multidict`.

## Доказательства

- `uv lock --directory .worktrees/epic-026-entity-registry --upgrade-package hydra-core --upgrade-package multidict` — Hydra обновлён с 1.3.6 до 1.3.7, multidict с 6.7.0 до 6.9.1.
- `uv lock --check` — lock-файл согласован с конфигурацией.
- `make security` — pip-audit завершился с `No known vulnerabilities found`.
- `make test-unit` — 1464 passed, 13 deselected, 40 warnings.
- `make lint` — все проверки Ruff прошли.

## Остаточные риски

- Полный CI после этих изменений должен быть выполнен в PR; здесь локально
  выполнены только перечисленные проверки.
