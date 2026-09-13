# ADR-021 — Отдельный пул клубного футбола для исследования 1X2

> **Статус:** proposed
> **Дата:** 2026-09-12
> **Связанное требование:** [REQ-021](../../product/requirements/REQ-021-top-football-winner-baseline.md)

## Контекст и критерии выбора

Нужен воспроизводимый Research Mode цикл для 1X2 девяти клубных турниров Smart Tables:
ENG1, SPA1, GER1, ITA1, FRA1, RUS1, RUS2, UCL и UEL. Пул не должен смешивать клубные
матчи с существующим `football_nationals`, а весь расчёт должен исключать post-event поля
из признаков текущего матча. Historical `odd_*` разрешены пользователем исключительно как
best-effort last-prematch proxy для backtest; их provenance ограничена.

Критерии: минимально изменить существующую Hydra/DVC архитектуру, хранить raw отдельно,
обеспечить temporal split и явный, воспроизводимый audit используемых полей/фич/гипотез.

## Рассмотренные варианты

1. **Status quo:** переиспользовать `football_nationals`. Отклонён: смешивает разную
   популяцию матчей, source/raw артефакты и затрудняет контроль holdout.
2. **Отдельный `football_top_leagues` ingest-slug и tournament config:** переиспользовать
   `SmartTablesSourceProvider`, clean и существующие generators, но создать независимые
   source/raw/interim/processed пути и whitelist competition codes. Выбранный вариант.
3. **Девять независимых ingest-slug и моделей:** повышает операционную стоимость и снижает
   объём данных для единого baseline; может быть пересмотрен только при доказанной
   нестабильности pooled validation.

## Решение

Создать `football_top_leagues` как отдельный клубный pool с конфигурационным whitelist
девяти турниров. Raw/backfill, clean и features выполняются существующими границами
провайдера, DVC и `features=advanced`. Winner — трёхклассовый 1X2; модель не получает
текущие score/stat/chart и не получает odds как predictive feature. Odds применяются только
в отдельном backtest-слое с явно заданным допущением источника.

## Последствия

- Положительные: чистая изоляция данных, повторное использование проверенных компонентов,
  однозначные competition/holdout filters.
- Отрицательные и стоимость: длительный rate-limited backfill, новое хранилище и отдельные
  tests/документация; API не имеет стабильного публичного контракта.
- Безопасность и эксплуатация: только read-only API с текущими задержками/retry; без cookies,
  обхода ограничений и deployment. Raw external payload не включается в отчёты.

## Проверка и пересмотр

Решение подтверждается fixture-тестами, clean/features quality gates, temporal training и
Research Harness с ROI ≥5% и coverage >20% на единожды раскрытом holdout 2025/26. Пересмотр:
неполное покрытие odds, дрейф схемы или отрицательная стабильность по турнирам. Откат —
остановить отдельный pool, не затрагивая `football_nationals`.

## Источники и неизвестное

- [REQ-021](../../product/requirements/REQ-021-top-football-winner-baseline.md).
- `docs/research/smart-tables-football-api-catalog.md`: `match-list`/`match-card` и
  temporal ограничения полей.
- Неподтверждено: bookmaker, точный timestamp и closing-статус `odd_*`.
