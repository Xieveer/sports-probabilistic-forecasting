# ADR-012 — Immutable NHL source-state archive

> **Статус:** accepted
> **Дата:** 2026-08-20
> **Связанное требование:** [REQ-012](../../product/requirements/REQ-012-nhl-source-state-archive.md)

## Контекст и критерии выбора

Существующий `operational-archive/<artifact-id>/` экспортирует canonical
PostgreSQL snapshot, но не NHL `source.csv`, OddsStore и
`odds/refresh_state.json`. Поэтому server restore и local betting validation
не имеют полной истории коэффициентов. Решение должно быть минимальным,
content-addressed, проверяемым до mutation, не выдавать Worker S3 credentials
и не смешивать DVC с production data.

## Рассмотренные варианты

1. **Status quo: только canonical archive.** Не выполняет REQ-012: OddsStore и
   checkpoint теряются при bootstrap/restore.
2. **Добавить state-файлы в каждый существующий canonical artifact.** Упрощает
   один layout, но связывает source-state с внутренним schema canonical export,
   ломает независимый initial bootstrap и делает local source input неявным.
3. **Отдельный versioned подпрефикс в существующем operational archive
   (выбран): `operational-archive/nhl-source-state/v1/<artifact-id>/`.** Один
   storage trust boundary, но самостоятельный manifest, lifecycle и contract
   source-state; старый canonical archive остаётся обратносуместимым.

## Решение

Добавить отдельный immutable artifact layout:

```text
operational-archive/nhl-source-state/v1/sha256:<content-id>/
  manifest.json
  source.csv
  odds/pinnacle_odds.parquet
  odds/refresh_state.json
```

Manifest schema `1` перечисляет каждый файл с SHA-256 и byte size, `schema_version`
каждого source-state contract, record counts (`source_rows`, `odds_rows`) и
safe provenance (`tournament`, `provider`, `refresh_run_id`, timestamps,
source schema identities). Artifact ID выводится из file entries и provenance.
Installer сначала верифицирует весь artifact, копирует его во временную
директорию внутри source volume и атомарно переключает `current` state; до
первого Worker run он создаёт `current.csv` из checked `source.csv`.

Отдельный `archive-sync` получает только `PutObject`, `GetObject` и
`ListBucket` для этого prefix; его remote verification выполняется до записи
local `verified` state. `DeleteObject` application accounts не получают.
Local training reader получает `ListBucket` c prefix-condition и `GetObject`,
выбирает maximum verified manifest по `created_at` и проверяет content до
создания descriptor. Initial bundle поступает на VPS out-of-band: отдельная
local write credential не требуется.

## Последствия

- Положительные: exact source/odds recovery, reproducible local betting input,
  least privilege и отсутствие зависимости VPS от DVC/MLflow.
- Отрицательные и стоимость: дополнительный artifact на refresh, manifest
  schema и persistent source-volume install/restore runbook. Lifecycle rule
  Object Storage удаляет только artifacts под `operational-archive/nhl-source-state/`
  старше 90 дней; перед включением Operations измеряет размер первого artifact
  и прогноз storage.
- Безопасность и эксплуатация: content-addressed objects не перезаписываются
  приложением; `DeleteObject` запрещён сервисным аккаунтам. Object Lock и
  versioning не включаются в shared bucket: настоящий WORM требует отдельного
  bucket и отдельного infrastructure ADR. Worker по-прежнему не получает S3
  credentials. `ops-prod-01-sports-forecast` получает `PutObject`, `GetObject`
  (remote verify) и `ListBucket` только для нового prefix; local reader —
  `GetObject` и `ListBucket`; ни одна другая account не получает этот prefix.

## Проверка и пересмотр

TDD доказывает initial build/install/idempotence, incremental refresh/export/
remote verify/local import и сохранение previous verified state при
provider/odds/export failure. Dry-run проверяет Compose/systemd commands и
Object Storage policy на prefix. Пересмотреть schema при добавлении второго
tournament либо при необходимости retention ниже 365 дней.

## Источники и неизвестное

- [REQ-012](../../product/requirements/REQ-012-nhl-source-state-archive.md).
- [ADR-007](ADR-007-autonomous-production-data-runtime.md) и
  [ADR-008](ADR-008-reliable-delivery-and-private-rollout.md) — существующие
  canonical/archive границы.
- DevOps подтвердил prefix, существующие IAM boundaries и lifecycle 90 дней;
  фактическая policy и lifecycle настраиваются вне репозитория.
