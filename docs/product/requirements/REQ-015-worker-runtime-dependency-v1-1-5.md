# REQ-015 — runtime dependency Worker для v1.1.5

> **Статус:** confirmed
> **Владелец продукта:** пользователь
> **Создано:** 2026-09-03
> **Продолжает:** [REQ-012](REQ-012-nhl-source-state-archive.md)

## Результат и ценность

Patch release `v1.1.5` устраняет blocker `v1.1.4`: опубликованный Worker image
может штатно импортировать и валидировать NHL source-state и canonical bootstrap
на VPS без dev/control-plane зависимостей. Immutable staged artifacts не
пересобираются, если их контракт не изменён.

## Scope

- Явно зафиксировать `omegaconf` в production dependency set и сделать uv-venv
  доступным для bare `python` в runtime image.
- До публикации release digest собрать final Worker image и проверить imports,
  identity и fixture source-state/canonical-bootstrap bundles внутри него.
- Выпустить единую release identity `v1.1.5` для API, Worker, Telegram bot и
  archive-sync через существующий matrix pipeline.

## Non-scope

- Переписывание tag/digest `v1.1.4`, публикация образов, deployment или доступ
  к VPS.
- Запуск PostgreSQL, migrations, source-state install, canonical bootstrap
  import либо scheduler.
- Добавление MLflow, DVC, Optuna или development tools в production image.

## Сценарии

1. CI запускает bare `python` как `10001:10001` в read-only, network-less final
   Worker image и импортирует четыре operational modules.
2. CI монтирует content-addressed fixture bundles через `--mount type=bind` и
   выполняет штатные source-state и canonical-bootstrap validators без записи в БД.
3. Operations повторяет проверку уже staged immutable artifacts после получения
   новых image digests; rollout остаётся отдельным разрешением.

## Критерии приёмки

- [ ] `omegaconf` входит в production dependencies; bare runtime `python` видит
  uv-venv, без MLflow/dev tools в base image.
- [ ] Worker CI gate использует `--read-only --network none --user 10001:10001`,
  подтверждает UID/GID и импортирует source_state, canonical_bootstrap,
  model_bundle и archive_sync.
- [ ] Gate создаёт и bind-монтирует маленькие content-addressed source-state и
  canonical-bootstrap fixtures, вызывает их validators и не использует short
  `-v` syntax.
- [ ] Package version, tag validation и production handoff указывают `1.1.5`;
  `v1.1.4` остаётся immutable historical blocker.

## Ограничения, зависимости и риски

- Локальная Docker build может быть недоступна из-за внешнего registry/network;
  окончательный image gate выполняет GitHub Actions до push.
- Проверка staged VPS artifacts и все production-операции выполняются только
  Operations после отдельного разрешения пользователя.

## Подтверждение

Пользователь подтвердил release blocker, границы и acceptance criteria в задаче
от 2026-09-03.
