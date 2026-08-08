# TASK-004-2 — Приоритетный key-ring The Odds API

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-004](../EPIC-004-nhl-release-readiness.md)
> **Требование:** [REQ-004](../../product/requirements/REQ-004-nhl-readiness-and-release-versioning.md)
> **ADR:** [ADR-004](../../architecture/adr/ADR-004-release-version-and-odds-api-key-failover.md)

## Результат и границы

Клиент The Odds API использует `ODDS_API_KEY_FREE`, затем `ODDS_API_KEY_20K`,
затем `ODDS_API_KEY_100K`; legacy `ODDS_API_KEY` сохраняется как fallback, если
новые переменные не заданы. Переключение допускается только на доказанном
quota/rate-limit сигнале. Не менять рынки, модели или способ хранения odds.

## Критерии приёмки

- [x] `.env.example` содержит три пустые переменные с пояснением приоритета и
  запретом коммитить реальные значения.
- [x] Пустые и повторяющиеся ключи пропускаются; первый запрос с тремя ключами
  использует free tier.
- [x] `429` или подтверждённый zero remaining переводит запрос на следующий
  tier; `5xx`, timeout, `401/403`, ошибка схемы и отсутствие quota-header не
  переводят его на платный ключ.
- [x] Логи, exceptions, cache-key и тестовые fixtures не содержат значения ключей.
- [x] Существующая конфигурация только с `ODDS_API_KEY` продолжает работать.

## План реализации

1. Написать красные unit-тесты выбора tier, условий failover и redaction.
2. Добавить внутренний key-ring и минимально адаптировать `OddsApiClient`;
   сохранить retry только в пределах активного tier согласно ADR.
3. Обновить env/docs и выполнить targeted tests/lint без сетевых вызовов.

## Затрагиваемые области и зависимости

- `sports_forecast/data/providers/odds/client.py`, его callers/tests,
  `.env.example`, Odds API documentation и compose/Airflow env pass-through.
- Внешняя граница: The Odds API response headers и HTTP status.

## Проверка

- `pytest` тестов клиента и интеграции odds с mocked responses; `make lint`.
- Проверка diff: ни один секрет не появляется в файлах или лог-assertions.

## Handoff и отчёт

- Отчёт выполнения: [TASK-004-2](../../changes/done/TASK-004-2-odds-api-key-ring.md).
- Follow-up / findings: нет.
