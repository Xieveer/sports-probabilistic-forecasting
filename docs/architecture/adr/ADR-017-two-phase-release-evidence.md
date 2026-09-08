# ADR-017 — Двухфазная фиксация application и release evidence

> **Статус:** accepted
> **Дата:** 2026-09-08
> **Связанное требование:** [REQ-018](../../product/requirements/REQ-018-immutable-release-evidence-v1-1-14.md)

## Контекст и критерии выбора

Exact commit SHA и published image digests появляются в разные моменты: SHA зависит от
содержимого commit, а digests/provenance — от успешного tag pipeline. Требуется immutable,
проверяемый и не содержащий secrets контракт для Operations.

## Рассмотренные варианты

1. **Один application tag с evidence:** невозможен для self-referential commit SHA и dynamic digests.
2. **Evidence только в GitHub Release:** не даёт versioned source artifact для server-side wrapper.
3. **Отдельный evidence commit/tag:** сохраняет source tag неизменяемым и фиксирует post-publication facts.

## Решение

Использовать annotated `v1.1.14` для application source и отдельный annotated
`v1.1.14-evidence.1` после успешного pipeline. Evidence commit содержит candidate handoff и
`deploy/release-manifest.json`; gate сверяет его с source tag и rendered Compose до создания tag.

## Последствия

- Положительные: нет self-reference, Operations получает immutable manifest.
- Отрицательные и стоимость: release owner выполняет второй контролируемый шаг и сохраняет URLs runs.
- Безопасность и эксплуатация: manifest не содержит environment values или credentials; оба tags должны
  быть protected от delete/force-update в repository settings.

## Проверка и пересмотр

`scripts/verify_release_evidence.py` должен завершиться без ошибок на evidence commit. Если
политика GitHub не позволяет защитить оба tags, rollout остаётся NO-GO.

## Источники и неизвестное

- ТЗ `sports-probabilistic-forecasting-v1.1.14-tz.md`, переданное владельцем 2026-09-08;
  исходный файл находится в отдельном Operations workspace и не копируется в application repo.
