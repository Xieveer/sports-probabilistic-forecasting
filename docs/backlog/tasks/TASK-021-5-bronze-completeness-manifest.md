# TASK-021-5 — Manifest полноты bronze и поэтапный ingest

> **Статус:** done
> **Владелец:** implementer
> **Эпик:** [EPIC-021](../EPIC-021-football-1x2-research.md)
> **Требование:** [REQ-021](../../product/requirements/REQ-021-top-football-winner-baseline.md)
> **ADR:** [ADR-021](../../architecture/adr/ADR-021-football-1x2-research-pool.md)

## Результат и ценность

Сделать состояние bronze-кэша наблюдаемым на уровне отдельного матча и набора требуемых
API-компонентов. Это позволяет быстро собрать минимальный честный dataset для 1X2,
измерить coverage каждого поля и позднее докачать только недостающие optional-компоненты,
не повторяя успешные запросы.

## Границы

### В scope

- Версионируемый manifest полноты по `match_id` для локального bronze-кэша: наличие файла,
  размер, время записи, статус последней попытки и безопасный тип ошибки без payload.
- Профили required/optional компонентов. Для текущего CatBoost winner baseline:
  `card.json` и `stat_all.json` — required; `stat_first.json`, `stat_second.json`,
  `chart_all.json`, `chart_first.json`, `chart_second.json`, `similar.json` — optional.
- CLI/report с coverage по компонентам и списком `match_id`, пригодных для train,
  требующих докачки required или только optional частей.
- Resume: запросы выполняются только для отсутствующих либо явно повреждённых компонентов;
  валидный существующий файл не скачивается повторно.
- Unit-тесты manifest, классификации и idempotency; integration test на fixture bronze.

### Non-scope

- Изменение market/target, feature logic, CatBoost, betting policy или результатов текущего
  исследования.
- Массовое параллеливание запросов и изменение rate-limit: это отдельное решение после
  измерения baseline.
- Сохранение raw payload в manifest, обход ограничений API или удаление существующего cache.

## Критерии приёмки

- [x] Manifest однозначно показывает required/optional completeness каждого `match_id`.
- [x] Для winner-baseline отчёт вычисляет `train_ready_coverage` как долю матчей с полным
  required-набором и отдельно coverage каждого компонента.
- [x] Resume повторно не вызывает сеть для валидного required-компонента; отсутствующий
  required-компонент ставится в очередь докачки.
- [x] Повреждённый JSON или неуспешный ответ не отмечается как complete; причина безопасно
  фиксируется без тела ответа.
- [x] Fixture integration подтверждает, что матч без chart остаётся train-ready, а матч без
  `stat_all` — нет.
- [x] Пользовательская документация описывает состав профилей, команды отчёта и путь
  докачки; отчёт TASK перечисляет фактические coverage до/после.

## План и порядок

1. Написать red-тест классификации fixture bronze по required/optional profile.
2. Добавить typed manifest и scanner файлового cache без сетевых вызовов.
3. Добавить CLI coverage-report и targeted resume plan.
4. Интегрировать manifest с fetch boundary, не меняя текущий default backfill.
5. Проверить idempotency, документацию и фактический club-pool coverage.

## Риски и решения

- **Риск:** наличие файла не гарантирует semantic completeness. Решение: проверять
  JSON-envelope/`success`, а не только путь и размер.
- **Риск:** API меняет схему. Решение: manifest хранит версию profile и фиксирует только
  проверяемую completeness, не интерпретируя неизвестные поля.
- **Риск:** изменение текущего backfill во время длительного запуска. Решение: feature
  включается отдельным opt-in profile после зелёных tests; существующий resume не меняется.

## Проверка

- Targeted pytest для manifest и fetch boundary.
- Fixture ingest integration без сети.
- Реальный read-only coverage report на `football_top_leagues` после завершения текущего
  backfill; без повторной загрузки уже валидных компонентов.

## Фактический coverage

Read-only snapshot после остановки backfill (2026-09-12): 663 match-каталога,
`train_ready_coverage=100%`; `card.json` и `stat_all.json` — по 100%.
`stat_first.json` — 100%, а `stat_second.json`, `chart_first.json`,
`chart_second.json` и `similar.json` — по 99.8492%. До введения manifest сопоставимый
измеренный показатель отсутствовал. Единственный `optional_only_match_id` — `432714`;
required-докачка не нужна. Детали реализации и проверки — в
[отчёте выполнения](../../changes/done/TASK-021-5-bronze-completeness-manifest.md).
