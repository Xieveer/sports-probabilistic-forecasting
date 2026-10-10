# TASK-028-2 — Проверяемый manifest v2 и legacy compatibility

> **Статус:** backlog
> **Владелец:** Developer
> **Эпик:** [EPIC-028](../EPIC-028-production-model-contract.md)
> **Требование:** [REQ-028](../../product/requirements/REQ-028-production-model-contract.md)
> **ADR:** [ADR-030](../../architecture/adr/ADR-030-production-model-contract.md), accepted

## Результат и границы

Локальный builder создаёт immutable bundle с manifest v2 для одной managed-пары.
Verifier возвращает проверенный контракт модели, рынка, исходов, признаков и
entrypoint; это готовый вход для активации в TASK-028-3. Явный legacy-профиль
по-прежнему читает manifest v1 и прежний NHL bundle.

Не менять registry DB pointer, Worker, materialize, схему БД, API или production
bundle. Для этого TASK достаточно локальной проверки bundle до активации.

## Критерии приёмки

- [ ] Content hash manifest v2 охватывает `model_pool`, `market_spec`, явные
  правила рынка и outcomes, `feature_contract_id`, описание порядка/типов
  признаков и версии преобразований, algorithm, точный относительный model
  entrypoint, app version и checksums файлов.
- [ ] Verifier отвергает повреждённый файл, path traversal, пустой/неизвестный
  algorithm, неоднозначный model entrypoint, несовместимую app version,
  несоответствие `deploy.yaml`/`features.txt` и неверные правила/outcomes.
- [ ] Для `winner_withOT` контракт явно задаёт овертайм и ровно два исхода
  `home_win / away_win`; бинарные правила не применяются к рынку с ничьей.
- [ ] Существующий manifest v1 verifier и legacy NHL loader проходят прежние
  тесты; manifest v1 не выдаётся за managed v2 и не получает придуманных полей.

## Red → green → refactor

1. **Red:** unit-тесты строят v2 candidate и проверяют стабильный ID,
   roundtrip, изменение любого нового поля, malformed path/algorithm/outcomes,
   mismatch совместимых файлов и v1 regression.
2. **Green:** добавить v2 builder/verifier и typed verified contract в
   `sports_forecast/deploy/model_bundle.py`. Поддерживать оба schema version
   только как явно различимые форматы.
3. **Refactor:** вынести общий checksum код без изменения v1 hash/installer;
   описать формат v2 и legacy-путь в `docs/operations/model-bundle.md`.

## Затрагиваемые области и зависимости

- Ownership Developer: только `sports_forecast/deploy/model_bundle.py`,
  `tests/test_model_bundle.py` и `docs/operations/model-bundle.md`; новые
  небольшие helper-модули допустимы внутри `sports_forecast/deploy/`, если
  нужны для читаемого контракта. Не менять код EPIC-027/029.
- Вход: reviewed [TASK-028-1](TASK-028-1-bundle-registry-guard.md) и
  [ADR-030](../../architecture/adr/ADR-030-production-model-contract.md).
  Веса модели для schema unit-тестов не нужны; маленький тестовый файл допустим.
- Rollback: прежний v1 builder/verifier/installer остаётся доступен;
  production pointer этим TASK не переключается.

## Проверка

- Red: новый `tests/test_model_bundle.py` test падает на отсутствии v2.
- Green: `uv run pytest -q tests/test_model_bundle.py` и существующие
  `tests/test_worker.py` — ожидается success; `make lint`, `make test-unit` и
  независимый review после реализации.
- Наблюдение: изменение market/outcomes/features меняет bundle ID или
  отклоняется verifier-ом; v1 NHL bundle загружается прежним способом.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-028-2-bundle-manifest-v2.md`.
- Следующий TASK: [TASK-028-3](TASK-028-3-managed-pointer-activation.md)
  после независимого review.
