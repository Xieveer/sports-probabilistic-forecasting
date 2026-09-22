# REQ-019 — Совместимый model bundle для production v1.1.14

> **Статус:** confirmed
> **Владелец продукта:** пользователь
> **Создано:** 2026-09-08

## Цель

Переиздать immutable NHL model bundle из approved payload без обучения, чтобы Worker
release `v1.1.14` принял `manifest.app_version == SF_APP_VERSION`.

## Scope

- Использовать только `catboost_advanced_prod.cbm`, `features.txt` и `deploy.yaml`.
- Штатно создать bundle с `app_version=1.1.14`, `release=v1.1.14` и source commit
  `9daf2d5bb040a5b8860961a12cb81a48997eaeac`.
- Проверить checksums и exact Worker runtime digest в restricted container.
- Staging и атомарный install на ops-prod-01 выполнить только после успешной проверки.

## Non-scope

Переобучение, изменение source/release images, migrations, bootstrap import, запуск
application services, scheduler, Telegram, secrets и network changes.

## Критерии приёмки

- [ ] Новый manifest содержит exact compatibility metadata для v1.1.14.
- [ ] Payload checksums не изменились.
- [ ] Exact Worker digest проверяет bundle с `app_version="1.1.14"` при non-root,
  read-only и network-none.
- [ ] VPS `current` переключён только после staging validation; прежний bundle сохранён.
