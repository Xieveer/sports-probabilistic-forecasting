# TASK-026-4 — Проверяемый локальный snapshot и provenance

> **Статус:** независимый review пройден
> **Задача:** [TASK-026-4](../../backlog/tasks/TASK-026-4-local-registry-snapshot.md)
> **Требование:** [REQ-026](../../product/requirements/REQ-026-entity-registry.md)
> **Решение:** [ADR-029](../../architecture/adr/ADR-029-local-entity-registry-and-snapshots.md)

## Изменения

- Полный локальный экспорт содержит `manifest.json` и пять детерминированных
  JSONL-файлов: сущности, обозначения и overlays, решения/audit/import ledger,
  финализированное bounded evidence owner decisions, event relations и
  memberships. Pending-only mutable queue в пакет не попадает и не меняет
  `ir1:<sha256>`; pending designation включается, если её conflict overlay
  влияет на resolver. ID включает стабильное содержимое,
  schema и policy versions; export timestamp, локальные пути и run ID не входят
  в digest. Проверка отвергает неполные, изменённые, лишние и слишком большие
  файлы до создания offline reader.
- `install_registry_snapshot()` проверяет package, копирует его во временный
  каталог, повторно проверяет, затем переключает выбранный package под
  interprocess lock. Ошибка оставляет прежний package на месте. Reader использует
  shared lock. Content-addressed archive сохраняет предыдущие версии.
- Offline reader разрешает точные designation с временными интервалами и
  conflict overlays, изолирован от меняющегося master. NHL и Smart Tables
  adapters используют только явно заданные колонки; unknown alias порождает
  pending candidate в локальном review queue и не назначает project event ID.
  NHL tournament alias не подтверждается автоматически seed-именем `NHL`.
- Identity rollout выбирается явным `enabled_tournaments`; для каждого
  перечисленного турнира проверяется полный adapter config до создания stage
  outputs. Остальные турниры обрабатываются в legacy режиме. Enabled ingest,
  clean и features fail closed при неверном adapter, missing input или ошибке
  identity/provenance.
- Схема локального master обновлена до версии 9. Каждое решение Review UI хранит
  FK на candidate и точный evidence revision; export включает двусторонние
  decision/evidence IDs, а verifier проверяет designation, revision и обе ссылки.
  Исторические ручные решения без candidate evidence остаются nullable и
  сохраняются как audit.
- Каждый data stage загружает selected current под lock один раз и работает с
  проверенным content-addressed archive в памяти. Следующая установка current
  не меняет snapshot pin текущего stage; sidecars сверяются с тем же archive ID.
- Ingest sidecar создаётся для raw Parquet и каждого split output. Clean проверяет
  raw sidecar и переносит identity в interim. Features проверяет interim и пишет
  sidecar для train/inference long/wide outputs, разрешая только одинаковые ID
  при long fan-out. Каждый sidecar привязан к SHA-256 и размеру exact Parquet.
- Обычный trainer сверяет выбранный processed file с установленным snapshot,
  добавляет snapshot ID в MLflow tag, записывает manifest/provenance metadata и
  сохраняет sidecar как MLflow artifact. Model-pool DataFrame в enabled mode
  отвергается, пока не появится проверяемая per-input provenance.
- DVC ingest/clean/features зависят от конфигурации, identity code и стабильного
  `data/registry/current/` package. `.gitkeep` обеспечивает существование пути
  в disabled режиме; master DB, selected package, архив и sidecars игнорируются
  Git. Локальный runbook описывает seed/export/install/review/training.

## Red → green

- Regression на temporal designation сначала завершался `AttributeError` из-за
  отсутствующего snapshot lookup API. После добавления exact/date-scoped lookup
  snapshot suite прошёл.
- Adapter regression сначала ожидал unresolved при неизвестном event key, хотя
  resolver законно находил уникальное событие по подтверждённым участникам и
  точному времени. Тест уточнён на неизвестный tournament alias; он остаётся
  unresolved и создаёт owner candidate для обоих adapters.
- Test tampered package до install завершался ошибкой проверки digest; current
  оставался на прежнем verified snapshot. Отдельно проверена смена content ID
  выбранного каталога и отказ corrupted current при загрузке.
- Data provenance regression изменяет Parquet bytes при неизменных row IDs/count;
  повторное чтение sidecar завершается ошибкой. Проверены duplicate/missing IDs,
  traversal digest, oversized sidecar и forged resolved UUID с пересчитанным
  checksum.
- Reviewer regressions первоначально показали: построчный resolver допускал два
  source IDs к одному event; stage мог использовать меняющийся `current`;
  незаявленный турнир обходил strict adapter, финальное candidate evidence не
  экспортировалось, а большой manifest читался до лимита. Сейчас adapter собирает
  batch через `resolve_many`, rollout и snapshot pin проверяются до обработки,
  экспорт включает только финализированные candidate revisions, manifest
  ограничивается `stat` и bounded read.
- Новый pending-only alias сначала менял `ir1`; после фильтрации проекции этот
  экспорт повторно использует тот же snapshot ID. Конфликтный pending alias с
  открытым overlay меняет ID и остаётся в resolver snapshot. Для цепочки
  confirm → reopen → reject → reopen → confirm проверены неизменность ID при
  одном лишь reopen, смена ID только после нового owner decision, сохранность
  prior evidence и отказ verifier при forged evidence revision и пересчитанном
  manifest digest.
- Дополнительные review regressions выявили разный лимит `facts` (write contract —
  1000 символов, verifier — 500) и необоснованное требование, чтобы каждый
  предложенный ID уже существовал как project entity. Теперь verifier принимает
  полный bounded evidence contract: confirm с фактом длиной 1000 и reject с
  несуществующим bounded proposed ID экспортируются и проверяются.

## Проверки

- `uv run pytest tests/test_registry_snapshot.py tests/test_entity_registry.py tests/test_entity_review.py tests/test_event_identity.py tests/test_identity_data_provenance.py tests/test_identity_ingest_adapters.py tests/test_identity_pipeline_contract.py tests/test_data_clean.py tests/test_trainer_integration.py tests/test_trainer_target_sort_alignment.py tests/test_model_pool.py tests/test_source_providers.py tests/test_smart_tables_provider.py tests/test_nhl_provider.py -q` — **187 passed, 6 warnings**.
- `uv run ruff check` по затронутым Python-модулям и тестам — **passed**.
- `uv run ruff format` по тем же файлам — **passed; изменений форматирования не требовалось при финальном запуске**.
- `uv run mypy --ignore-missing-imports --no-strict-optional --warn-return-any --follow-imports=silent sports_forecast/identity/snapshot.py sports_forecast/identity/review_service.py sports_forecast/identity/registry.py tests/test_registry_snapshot.py tests/test_entity_review.py tests/test_entity_registry.py` — **passed**.
- Общий pre-commit mypy gate при параллельной работе TASK-026-5 остановился на `sports_forecast/identity/installation.py:208` (`no-any-return`); этот файл принадлежит TASK-026-5 и не входит в TASK-026-4. Финальный общий gate запустить после завершения TASK-026-5.
- `uv run dvc stage list` — **passed**, DVC pipeline распознал все четыре stage.
- Изолированная DVC regression с dependency `data/registry/current/` — **passed**:
  после смены содержимого выбранного package `dvc status --json` пометил
  dependency как изменённую. `uv run dvc status --json` в рабочем репозитории
  также выполнен; он показывает изменённые зависимости и отсутствующие cache
  outputs для исторического pipeline, который здесь не запускался.
- `git diff --check` — **passed**.
- `git check-ignore -v` подтвердил ignore для master DB, selected package,
  content-addressed snapshots и raw parquet sidecar.

## Ограничения проверки

Проверки используют документированные schemas и synthetic fixtures через реальные
ingest, clean, features и trainer entrypoints. В тестах trainer MLflow вызовы и
model fit замоканы; полное обучение на пользовательских NHL/football history и
`dvc repro` не запускались, поскольку такая история не предоставлена в fixture
окружении. DVC dependency на selected package, смена current package и runtime
revalidation покрыты отдельным изолированным DVC regression и installer/loader
regressions. Публикация в Object Storage остаётся TASK-026-5.

Независимый Reviewer повторил целевой набор (**187 passed, 6 warnings**), Ruff и
scoped mypy и не нашёл P0–P2 после исправления двух последних P1.
