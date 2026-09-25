# TASK-023-1 — отчёт о выполнении

> **Статус задачи:** in_progress, готова к финальному release gate
> **Дата:** 2026-09-22
> **Задача:** [TASK-023-1](../../backlog/tasks/TASK-023-1-nhl-schedule-agent-pilot.md)
> **Требование:** [REQ-023](../../product/requirements/REQ-023-nhl-schedule-agent-pilot.md)
> **ADR:** [ADR-023](../../architecture/adr/ADR-023-minimal-agent-pilot-with-operations-agent.md)

## Результат

Откатан непринятый scope EPIC-022 без переписывания Git history. В Telegram-бот добавлен
минимальный сценарий расписания: `/upcoming` предлагает единственный турнир NHL, затем
принимает целое `N` от 0 до 30. `N=0` означает остаток текущего дня МСК, последующие
значения — период до конца соответствующего дня. Ответ группирует матчи по дате и содержит
время МСК, команды, существующие прогноз, коэффициенты и value; каждое отсутствующее поле
показывается как «нет данных».

Не менялись модели, data/odds pipeline, расчёт value, production-конфигурация или секреты.
Пользовательский `/help` синхронизирован с новым синтаксисом команды.

## Реальный E2E

В авторизованной Telegram Web-сессии владельца, только с test bot и без production token,
успешно пройдены пустой и форматированный сценарии. Форматированный сценарий на коде
`93d0d0a`: `/upcoming` → NHL → `1` → будущий матч, сгруппированный по дате МСК, с
прогнозом, обоими коэффициентами, обоими value и решениями. Для него использовалась
краткоживущая локальная HTTP-fixture; после проверки она и локальный polling остановлены.
Production endpoint не использовался. Снимки браузера, временные профили, chat IDs, токены и
payload в evidence не сохранялись.

## Проверки

- `uv run pytest tests/test_bot_predict_format.py tests/test_bot_commands.py tests/test_bot.py -q` — 25 passed.
- `uv run ruff check sports_forecast/bot/handlers/predict.py sports_forecast/bot/handlers/start.py tests/test_bot_predict_format.py tests/test_feature_generators.py` — успешно.
- `uv run pre-commit run mypy --all-files` — успешно.
- `make test` — 1033 passed, 37 warnings.
- `make lint` — успешно.
- `make docs` — инкрементальная сборка завершилась с кодом 0 и вывела 58 предупреждений и
  ошибок docutils в незатронутых docstrings feature-подсистемы. Контрольная чистая команда
  `uv run sphinx-build -E -b html docs/source /tmp/sf-task-023-docs` также завершается с
  кодом 0, но выводит 155 warnings; documentation target не использует `-W`. Это известный
  baseline, а не зелёный quality gate данной TASK.
- `make ai-validate` — успешно.
- `make security` — успешно после обновления транзитивного `anyio` до 4.14.2 через `uv lock`.
- `git diff --check` — успешно.

## Изменённые границы и риски

- Изменены bot handler, help-текст, targeted tests и канонические REQ/ADR/EPIC/TASK/README.
- Отдельная [TASK-023-2](../../backlog/tasks/TASK-023-2-ewm-optional-metric-contract.md)
  приводит старое test-ожидание к уже принятому optional-metric контракту генератора EWM;
  runtime-код не менялся. Она принята отдельным commit `8a30825`.
- CI и Security implementation commit `7bedfe8` успешны:
  https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/35774317354 и
  https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/35774317402.
  Formatting commit `ef8ace6` также имеет успешные CI и Security:
  https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/35776276169 и
  https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/35776276293.
- Tag pipeline `v1.1.15` остановился до publication: isolated first-rollout contract не смог
  запустить MinIO fixture с network alias на default bridge (Docker exit 125). `v1.1.16`
  также остановился на MinIO startup (exit 125). Production server и GHCR images не менялись.
  `v1.1.17` также остановился на MinIO startup (exit 125). Candidate `v1.1.18`
  остановился до first-rollout: Docker Hub отклонил MinIO digest. Regression fix оформлен
  как новый candidate `v1.1.19` с project-owned S3-compatible Moto OCI artifact (ADR-024).
- Не завершены final tag pipeline `v1.1.19` и operations-agent rollout. До их успешного
  завершения задача не считается принятой, а deployment запрещён.
- Remediation `v1.1.19`: независимый review одобрил project-owned Moto S3 fixture;
  `uv lock --check`, 48 контрактных тестов, `make production-check`, `make lint`,
  `make security`, `git diff --check` и Docker read-only S3 smoke успешны. Полный mypy
  для затронутых scripts остаётся красным из-за 156 существующих ошибок в транзитивных
  модулях вне этого diff; scoped mypy reviewer прошёл.

## Review

Независимый reviewer выполнил два цикла review. Первый выявил и второй подтвердил устранение
ошибок окна МСК/UTC, полей away, безопасного разбиения сообщений, malformed JSON и
синхронизации evidence. Вердикт последнего review: `approve-with-external-blockers`.
Функциональный commit reviewer: `93d0d0a`. Browser E2E formatted fixture завершён.
Candidate handoff фиксирует version/tag contract без фиктивного self-reference SHA;
обязательными внешними gates остаются final tag pipeline и operations rollout.

### Review release remediation v1.1.17

Независимый reviewer не обнаружил findings P0/P1/P2 в исправлении isolated first-rollout.
Проверенный implementation commit: `5145142440d4be58b18b6137eb6c6ab0307ddcde`.
Подтверждены выделенная user-defined сеть MinIO, последующее подключение к Compose-сети,
cleanup контейнера и сети, согласованность версии и release-документов. Выполнены 47
целевых тестов, полный `make test` (1034 tests), `make lint`, `make security`, обязательный
`uv run pre-commit run mypy --all-files`, `uv lock --check`, `make production-check`,
Docker smoke и `git diff --check`; все проверки успешны. Остаточный внешний gate — полный
first-rollout на Docker daemon GitHub hosted runner в tag pipeline `v1.1.17`.
