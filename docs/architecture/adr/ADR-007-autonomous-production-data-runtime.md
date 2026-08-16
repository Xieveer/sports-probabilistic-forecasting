# ADR-007 — Автономный production data-runtime и синхронизация training data

> **Статус:** accepted
> **Дата:** 2026-08-14
> **Связанное требование:** [REQ-007](../../product/requirements/REQ-007-production-data-runtime.md)

## Контекст и критерии выбора

`v1.0.1` подготовил serving-контур, но его Worker материализует только заранее
созданный `processed/inference_long.parquet`, а VPS хранит не более семи дней
runtime data. Это несовместимо с самостоятельным production refresh и EWM,
которому доступна полная история. После initial bootstrap VPS должен стать
единственным источником истины данных поставщиков; перед каждым локальным
обучением нужен проверяемый immutable snapshot VPS.

Первый релиз обслуживает NHL, но архитектура должна изолировать профили
турниров с периодичностью от утренней до 15-минутной. Критерии: независимость
от устройства разработчика, корректность при поздних исправлениях, отсутствие
прямого доступа local development к production DB, provenance, rollback,
минимальная новая эксплуатационная нагрузка и обратимый путь к масштабу.

## Рассмотренные варианты

1. **Status quo: seven-day Parquet runtime и Worker materialization.**
   Сохраняет небольшую VPS, но не имеет полной EWM-истории, не обновляет её
   автономно и не выполняет подтверждённый REQ-007.
2. **Общая PostgreSQL для VPS и локальной разработки.** Локальный контур мог бы
   читать общую базу, но получает сетевую/credential-зависимость от production,
   риск случайной записи и не создаёт воспроизводимого training snapshot.
3. **VPS PostgreSQL как canonical operational store + immutable Parquet
   snapshots в Object Storage + local DVC imports (выбран).** VPS применяет
   provider updates транзакционно, выполняет refresh и выдачу. После успешного
   commit создаётся content-addressed manifest с partition-файлами; локальный
   контур читает только его и фиксирует в DVC/MLflow provenance. Прямого общего
   mount и прямого доступа local development к production DB нет.

## Решение

Выбран вариант 3.

- VPS хранит полную canonical историю, расписание, результаты, watermark и
  execution state в PostgreSQL; prediction store остаётся отдельной витриной в
  той же production DB. Initial NHL history доставляется один раз локальным
  immutable bootstrap bundle без повторного API-backfill.
- Один tournament-scoped refresh job выполняет ingest → validate → canonical
  commit → features → materialize → publish. Успех требует результатов всех
  ранее спрогнозированных матчей с истёкшим configurable deadline. При failure
  affected predictions скрыты от публичного API и Telegram, alert получает
  только администратор.
- После каждого successful commit VPS публикует immutable operational snapshot
  manifest в Object Storage. Файлы данных — versioned Parquet partitions;
  manifest содержит только относительные пути, размеры, hashes, версии схемы,
  run/config/source provenance. Локальное обучение импортирует последний
  проверенный snapshot и строит features самостоятельно.
- Модели доставляются отдельно как immutable bundles. Training и promotion
  остаются ручными и локальными; drift, champion--challenger и stateful EWM
  не входят в `1.1.0`.
- Для `1.1.0` NHL features/EWM пересчитываются по всей canonical истории.
  Stateful EWM допускается лишь следующим ADR после измерений: оно требует
  per-feature-contract checkpoints и replay хвоста при коррекции результата.

## Последствия

- Положительные: production автономен, история и provenance контролируемы,
  local training воспроизводим, а refresh не зависит от DVC или устройства.
- Отрицательные и стоимость: нужны DB migration, безопасный import/export,
  новые volumes/Object Storage permissions, resource measurements полной
  истории и более сложный runbook. Полный NHL rebuild может не подойти для
  будущих 15-минутных профилей.
- Безопасность и эксплуатация: разделить S3 credentials VPS/local по prefix;
  manifests и logs не содержат secrets/payloads; scheduler получает timeout,
  retry, per-tournament lock и durable last-success status. Предыдущая
  витрина сохраняется для audit/recovery, но не доступна пользователям при
  freshness failure.

## Проверка и пересмотр

Решение подтверждается integration tests canonical refresh/quality gate,
bootstrap и archive round-trips, API visibility tests, `docker compose config`,
measurement на полном NHL dataset и DevOps dry-run runbook без deployment.
Пересмотреть storage topology, если PostgreSQL объём/IO или полный rebuild не
укладываются в подтверждённый budget; пересмотреть EWM strategy с появлением
первого 15-минутного турнира и фактических измерений.

## Источники и неизвестное

- [REQ-007](../../product/requirements/REQ-007-production-data-runtime.md) —
  подтверждённые владельцем продуктовые границы.
- [Текущая EWM-реализация](../../../sports_forecast/features/generators/ewm_generator.py)
  — full-history Pandas calculation без persistent state.
- Точные RPO/RTO, объём initial NHL dataset и production resource budget
  неизвестны; они должны быть измерены, а не приняты на веру.
