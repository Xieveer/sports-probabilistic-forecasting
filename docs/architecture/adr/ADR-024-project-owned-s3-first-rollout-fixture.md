# ADR-024 — Project-owned S3 fixture для first-rollout

> **Статус:** accepted
> **Дата:** 2026-09-25
> **Связанное требование:** [REQ-023](../../product/requirements/REQ-023-nhl-schedule-agent-pilot.md)

## Контекст и критерии выбора

Release candidates `v1.1.15`–`v1.1.17` завершались до публикации образов на запуске
MinIO fixture. Candidate `v1.1.18` перенёс image в OCI artifact, но его build job
не смог получить неизменяемый `minio/minio` digest: образ стал недоступен в Docker Hub.
First-rollout должен оставаться изолированным, воспроизводимым и не зависеть от
доступности стороннего runtime image после создания tag.

## Рассмотренные варианты

1. **Status quo:** повторять pull `minio/minio`; неприемлемо, так как upstream image
   уже недоступен и повторяемость не доказана.
2. **Другой внешний registry:** переносит supply-chain и availability risk в другой
   непроверенный registry.
3. **Project-owned fixture:** собрать S3-compatible Moto server из version-locked
   dependency group вместе с остальными OCI artifacts.

## Решение

Принят вариант 3. Docker target `s3-fixture` собирается из `uv.lock`, передаётся в
first-rollout как `release-oci-s3-fixture`, загружается в локальный registry и
адресуется только digest. Runner запускает его read-only в Compose network с alias
`minio`, а bucket создаёт одноразовым вызовом `boto3` из archive-sync runtime.
Production Compose и production object storage не меняются.

## Последствия

- Положительные: tag pipeline больше не pull'ит MinIO/MC; fixture и зависимости
  версионированы в репозитории и проверяются до публикации runtime images.
- Отрицательные и стоимость: образ CI тяжелее из-за Moto; fixture моделирует S3,
  а не является совместимостью с конкретной реализацией production storage.
- Безопасность и эксплуатация: fixture доступен только в изолированной Docker network,
  работает read-only и использует file-backed test credentials; новые secrets не нужны.

## Проверка и пересмотр

Контрактные тесты проверяют отсутствие MinIO pull и наличие project artifact. Сборка
target и first-rollout должны пройти на чистом GitHub runner. Решение пересматривается,
если Moto перестаёт покрывать используемый archive-sync S3 API или pipeline снова
получит registry-dependent failure.

## Источники и неизвестное

- GitHub Actions run `36039806139`, job `107769918443`: `minio/minio` pull получил
  `denied: requested access to the resource is denied`.
- `uv.lock` — зафиксированный набор зависимостей fixture.
