# TASK-017-1 — Переиздать совместимый model bundle

> **Статус:** in_progress
> **Владелец:** implementer
> **Эпик:** [EPIC-017](../EPIC-017-v1-1-14-compatible-model-bundle.md)
> **Требование:** [REQ-019](../../product/requirements/REQ-019-v1-1-14-compatible-model-bundle.md)

## Выполнено локально

- Approved payload собран штатной `build_model_bundle()` без retraining.
- Получен `sha256:a9e19d3deee08af5aefe8eed1d4c45b1ca971dda88c5637baff92faba67a253b`.
- Manifest содержит exact v1.1.14 metadata; checksums payload совпали.
- Exact Worker digest `sha256:3f802d34…` принял bundle при `linux/amd64`, UID/GID
  `10001:10001`, `--read-only` и `--network none`.

## Оставшийся scoped шаг

Перенести bundle в отдельный VPS staging path, повторить Worker verification и только затем
штатной `install_model_bundle()` atomically переключить `current`; previous bundle не удалять.
На момент фиксации `ops-prod-01` не разрешается DNS, поэтому staging/activation не выполнялись.
