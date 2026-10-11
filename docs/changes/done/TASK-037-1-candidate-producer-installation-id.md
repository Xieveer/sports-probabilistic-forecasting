# TASK-037-1 — Передача installation ID: отчёт Developer

## Результат

Production Compose передаёт `SF_ENTITY_REGISTRY_INSTALLATION_ID` обоим процессам, которые могут создавать registry candidates: Worker и source-acquirer. `registry-feedback` уже получал этот идентификатор. Production Compose verifier требует, чтобы все три значения совпадали и представляли канонический UUID, как в runtime. API и Telegram-бот candidates не записывают.

Исходный strict Data Cycle v1.3.4 `0070c85e-90a2-4656-b14e-608d6745e312` завершился `source_fetch_failed` на календаре из-за отсутствующего installation ID у Worker. Дефект выявлен до возобновления timers. Новая версия 1.3.5 меняет только Compose/контракт проверки и release metadata; registry snapshot, matcher, grants и модельные веса не изменены.

## Red → green → refactor

- Новый rendered Compose test сначала падал: у Worker не было `SF_ENTITY_REGISTRY_INSTALLATION_ID`.
- После передачи ID Worker и source-acquirer contract tests прошли; отдельные mutations удаляют ID у каждого producer и требуют отказа verifier.
- Независимый Reviewer выявил P2: пустота/совпадение недостаточны, `not-a-uuid` проходил preflight, но runtime отказал бы при записи. Mutation test подтвердил red (`DID NOT RAISE`). Проверка канонического UUID исправила gate; targeted test стал green.

## Локальные проверки

- `UV_OFFLINE=1 make test-unit`: 1715 passed, 18 deselected.
- Developer: 58 production contract/topology tests passed до UUID follow-up; targeted rendered Compose test, Ruff и `git diff --check` прошли после него.
- Независимый Reviewer после UUID фикса: 72 targeted tests passed, `git diff --check` clean; call sites проверены.
- `uv lock --check --offline`, `UV_OFFLINE=1 make production-check`, `UV_OFFLINE=1 make docs`, `UV_OFFLINE=1 make ai-validate`: прошли. Sphinx сообщил 155 существующих предупреждений.
- После UUID follow-up `UV_OFFLINE=1 make pre-commit` прошёл полностью после автоматического форматирования одного Python файла первым запуском; `UV_OFFLINE=1 make lint`, `UV_OFFLINE=1 make type-check`, `UV_OFFLINE=1 make production-check` и 72 targeted tests прошли. Terminal CI/Security и серверный gate остаются отдельно.

## Release gate и остаток

Независимое review полного source+docs diff, окончательные локальные проверки, terminal CI/Security, immutable source/image/model evidence и полный strict NHL Data Cycle остаются обязательными. Production сейчас удерживается в v1.3.4 strict=false с установленным v2 snapshot; timers остановлены. При ошибке полного цикла выпуск остаётся NO-GO. Подробный сценарий — [production handoff](../../operations/production-handoff.md).
