# TASK-004-1 — Контракт версии релиза 1.0.0

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-004](../EPIC-004-nhl-release-readiness.md)
> **Требование:** [REQ-004](../../product/requirements/REQ-004-nhl-readiness-and-release-versioning.md)
> **ADR:** [ADR-004](../../architecture/adr/ADR-004-release-version-and-odds-api-key-failover.md)

## Результат и границы

Package metadata, FastAPI и Docker release workflow используют один SemVer
`1.0.0`. Workflow валидирует `v<version>` и публикует version/SHA теги образов
по утверждённой release-операции. Не создавать Git-тег, не публиковать образы и
не менять версии ML-моделей.

## Критерии приёмки

- [x] `pyproject.toml` — единственный исходник версии, равной `1.0.0`.
- [x] API отдаёт эту же версию без литерала, расходящегося с package metadata.
- [x] CI-контракт отклоняет release-тег, не совпадающий с package version, и
  определяет теги Docker `<version>` и commit SHA.
- [x] Документация описывает, что tagging/push выполняются только отдельной
  авторизованной release-операцией.

## План реализации

1. Добавить падающие unit/static tests для единства metadata/API и release-tag
   validation.
2. Ввести центральный accessor версии, обновить FastAPI, Docker workflow и
   release-документацию; зафиксировать `1.0.0` в metadata.
3. Запустить затронутые тесты и линтер; не выполнять remote release actions.

## Затрагиваемые области и зависимости

- `pyproject.toml`, `sports_forecast/service/app.py`, `.github/workflows/docker.yml`,
  `Dockerfile`, `.env.example`, docs release/deploy.
- Внешняя граница: GitHub Actions/GHCR; фактическая публикация вне scope.

## Проверка

- Целевые pytest, `make lint`, статическая проверка workflow/tag templates.
- Наблюдение: локально собранный image label/tag plan содержит `1.0.0` и SHA,
  без push.

## Handoff и отчёт

- Отчёт выполнения: [TASK-004-1](../../changes/done/TASK-004-1-release-version-contract.md).
- Follow-up / findings: нет.
