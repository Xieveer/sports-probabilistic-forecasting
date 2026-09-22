# ADR-018 — Previous model bundle как межрелизный recovery artifact

> **Статус:** accepted
> **Дата:** 2026-09-08
> **Связанное требование:** [REQ-020](../../product/requirements/REQ-020-post-rollout-runtime-corrections.md)

## Контекст и критерии выбора

Installer до активации проверяет bundle against target `app_version`. При смене
приложения это же условие ошибочно применяется к старому `current`, из-за чего promotion
не может сохранить rollback pointer. Нужны immutable, checksum-verified recovery
artifact и сохранение fail-fast проверки текущего runtime bundle.

## Рассмотренные варианты

1. **Status quo:** проверять старый `current` against target version. Просто, но
   cross-version promotion всегда блокируется.
2. **Проверять старый current только на целостность:** читать manifest и checksums без
   compatibility against target, сохранять verified path как `previous`.
3. **Удалять previous при смене версии:** promotion возможна, но исчезает recovery path.

## Решение

Выбран вариант 2. Candidate проверяется `verify_model_bundle(..., app_version=target)`;
старый `current` проверяется отдельной integrity-проверкой без expected app version и
только затем записывается в `previous`. `load_current_model_bundle` и rollback сохраняют
compatibility-check against явно переданной runtime version.

## Последствия

- Положительные: cross-version activation атомарно сохраняет прошлый verified bundle;
  worker/API не могут загрузить несовместимый `current`.
- Отрицательные и стоимость: откат model pointer сам по себе недостаточен после смены
  application version; нужен rollback приложения до версии manifest `previous`.
- Безопасность и эксплуатация: повреждённый previous/current не становится recovery
  pointer; manifest и checksum продолжают проверяться.

## Проверка и пересмотр

Unit-тест доказывает сохранение cross-version `previous`, а existing loader test —
отказ загрузки несовместимого current. Решение пересматривается, если runtime получит
поддержку нескольких совместимых model schema/version ranges.

## Источники и неизвестное

- Внутренний contract `sports_forecast.deploy.model_bundle`; внешний протокол не меняется.
