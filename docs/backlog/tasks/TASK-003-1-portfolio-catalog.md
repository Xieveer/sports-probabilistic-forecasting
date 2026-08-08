# TASK-003-1 — Конфигурационный каталог портфеля

> **Статус:** in_progress
> **Владелец:** implementer
> **Эпик:** [EPIC-003](../EPIC-003-scalable-multisport-platform.md)
> **Требование:** [REQ-003](../../product/requirements/REQ-003-scalable-multisport-platform.md)
> **ADR:** [ADR-003](../../architecture/adr/ADR-003-configured-multisport-portfolio.md)

## Результат и границы

Добавить версионируемый конфигурационный каталог с явными профилями
`tournament`, `model_pool` и `deployment_profile`, загрузчик и fail-fast
валидацию ссылок. Каталог позволяет описать NHL legacy и минимум один
футбольный candidate без статических списков в новом коде. Не меняются обучение,
пути моделей, БД и Airflow runtime.

## Критерии приёмки

- [ ] Валидный профиль связывает sport, tournament, model pool, market/spec и
  lifecycle; его можно загрузить через публичный typed API.
- [ ] Отсутствующая ссылка, несовместимый sport, дублирующее участие или
  production без immutable model reference завершаются понятной ошибкой.
- [ ] Канонические документы описывают границы сущностей, конфигурационное
  подключение типового турнира и различают реализованный контракт от roadmap.

## План реализации

1. Написать падающие unit-тесты валидной композиции и каждого нарушения
   инварианта.
2. Добавить минимальные YAML-профили, typed loader и валидатор без изменения
   старых Hydra consumers.
3. Обновить README и руководства по турниру с новым контрактом и legacy
   ограничениями.
4. Выполнить целевые тесты и `make test-unit`.

## Затрагиваемые области и зависимости

- `conf/`, `sports_forecast/config/`, `tests/`, README и `docs/cursor/context/`.
- Не включать секреты, URL с ключами или реальный production inventory.

## Проверка

- Новые unit-тесты loader/validator и Hydra composition.
- `make test-unit`.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-003-1-portfolio-catalog.md`.
- Follow-up / findings: TASK-003-2, TASK-003-3 и TASK-003-4 используют только
  публичный контракт каталога.
