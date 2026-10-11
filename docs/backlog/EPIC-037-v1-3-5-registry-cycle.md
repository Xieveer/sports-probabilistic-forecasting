# EPIC-037 — Исправляющий выпуск v1.3.5 для полного NHL Data Cycle

> **Статус:** in_progress — production gate v1.3.4 получил NO-GO
> **Приоритет:** critical
> **Владелец:** Product Owner
> **Ветка:** `initiative/epic-037-v1-3-5-release`
> **Предыдущий кандидат:** [EPIC-036](EPIC-036-registry-rollout.md)

## Цель

Довести согласованный владельцем NHL registry до рабочего production цикла: словари турниров, команд, рынков и исходов установлены; события автоматически сопоставляются по подтверждённым командам, сторонам и времени UTC ±15 минут; неизвестные обозначения попадают в очередь решения владельца; полный Data Cycle создаёт прогноз и актуальную линию в API и Telegram-боте. Для этого требуется устранить обнаруженный серверным gate дефект передачи идентификатора установленного registry в процессы, которые записывают кандидатов.

Владелец уже разрешил выпуск новой версии после всех review, CI и production gates. Старые теги и registry publications остаются неизменяемыми. Версия исправления — `v1.3.5`.

## Память Product Owner

- В v1.3.4 source tag, terminal CI/Security, Docker provenance, модельный wrapper и release evidence прошли проверки. На VPS установлен v2 snapshot `ir1:71897173e0ee72bb60f9038cc8570770b351d866a3f994e63ba26bf5bcfe03e2`, publication sequence 3; API/bot выдавали 50 NHL прогнозов, из них четыре с реальной двухсторонней линией Pinnacle при strict reader.
- Контрольный strict Data Cycle `0070c85e-90a2-4656-b14e-608d6745e312` завершился `source_fetch_failed`: `RegistryFeedbackError: SF_ENTITY_REGISTRY_INSTALLATION_ID не задан`. Переменная передавалась только `registry-feedback`; Worker, где выполнялась запись неизвестного обозначения, её не получил. Прогнозный/odds этапы того цикла не запускались. Это NO-GO v1.3.4.
- На VPS strict reader атомарно возвращён в `false`, API/bot пересозданы и здоровы; v2 snapshot и четыре действующие линии сохранены. Три таймера остановлены для контролируемой проверки. Ведётся fallback Data Cycle `370d1466-354a-4577-99c8-1cdf23c205e3`.
- Production DB backup `pre-v1.3.4-20261011T222118844681145.dump` (SHA-256 `bc4014b954f029b49242d9e4bba87b2b2c94a67ca8f871a142309c62701efb83`) прошёл off-host readback и isolated restore. Миграций в исправлении нет.
- Следующая роль: Developer [TASK-037-1](tasks/TASK-037-1-candidate-producer-installation-id.md) → независимый Reviewer → terminal CI/Security → exact tag/image/model evidence → Operations Agent.
- Блокеры: исправление Compose, полные release gates и успешный реальный strict Data Cycle с feedback, odds, прогнозом, линией, ботом и устойчивыми таймерами.
- Обновлено: 2026-10-12.

## Проверяемые критерии

1. Rendered production Compose передаёт один валидный `SF_ENTITY_REGISTRY_INSTALLATION_ID` из авторитетного `/etc/sports-forecast/refresh/nhl.env` во все процессы, которые могут писать registry candidates. Запись под фактической ролью Worker проходит в production.
2. Новые unit/contract tests показывают red до исправления, green после него. Не меняются алгоритм сопоставления, данные registry, grants и модельные веса.
3. Независимый Reviewer не находит P0–P2. `make production-check`, terminal CI/Security, immutable annotated source tag `v1.3.5`, scan/provenance exact образов и release-evidence gate проходят; bundle соответствует 1.3.5 и exact Worker image.
4. После проверенных backup/restore и stage/switch strict reader полный NHL Data Cycle проходит archive → odds → forecast → materialization; появляются новый odds attempt и будущие observations. В API и боте доступен полезный прогноз с живой Pinnacle линией. Реальный candidate проходит outbox → решение владельца → publication/sync/ack.
5. Dispatcher проходит 20 минутных ticks без `start-limit-hit` и stale heartbeat. При провале выполняется документированный возврат strict=false и, если нужно, образов/registry к проверенным точкам.

## Решение

До выполнения серверных критериев релиз `NO-GO`. Конкретные evidence и остаточный риск фиксируются в [production handoff](../operations/production-handoff.md). Legacy путь удаляется отдельной будущей инициативой.

## Независимое review исходного кандидата

- Reviewer проверил полный diff относительно `main`: Compose и все места записи кандидатов, rendered verifier, тесты, версию/lock, rollback, handoff, безопасность и документацию. Исходный P2 (невалидный UUID проходил preflight) устранён через проверку канонического UUID и mutation test. Открытых P0–P2 нет.
- Проверенный commit: `b420c6d723af864e7a582b41fe08ac7929ac5aa4`.
- Reviewer запустил 72 целевых production contract/topology/version tests (passed) и `git diff --check` (passed). Product Owner сообщил о 1715 passed unit tests, успешных lint/type/docs/AI/production-check/pre-commit и offline lock check; эти gates не заменяют terminal CI и серверный Data Cycle.
- Локальный `UV_OFFLINE=1 make security` остановился на bootstrap `pip-audit` (`Failed to upgrade pip`); аудит зависимостей не выполнялся. Terminal Security CI остаётся обязательным gate.
- Остаточный риск: код ещё не прошёл terminal CI/Security, immutable image/model evidence и полный strict NHL Data Cycle на VPS. До них статус выпуска остаётся `NO-GO`.
