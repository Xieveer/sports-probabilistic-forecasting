# TASK-036-3 — Минутный запуск Data Cycle dispatcher

> **Статус:** done — шаблон и локальный контрактный тест; production gate ожидается
> **Владелец:** Operations Agent
> **Эпик:** [EPIC-036](../EPIC-036-v1-3-3-registry-rollout.md)

## Дефект

На production dispatcher timer рассчитан на запуск раз в 60 секунд, а service
разрешал лишь пять запусков за 15 минут. Unit достигал `start-limit-hit`,
после чего heartbeat устаревал и ежедневный цикл не получал надёжной
диспетчеризации.

## Критерии

1. Шаблон service допускает каждый штатный минутный запуск timer без
   накопительного rate limit; настройки таймера и DB active-run gate сохранены.
2. Контрактный тест фиксирует сочетание `OnUnitActiveSec=60s` и отсутствия
   ограничивающего burst в service.
3. После установки релиза наблюдаются 20 последовательных минутных ticks,
   успешные service invocations и свежий heartbeat без `start-limit-hit`.

Локальные доказательства и остаточный gate — в
[отчёте](../../changes/done/TASK-036-3-dispatcher-minute-cadence.md).

## Границы

Это изменение systemd release template. Production unit и timer меняются
только вместе с проверенным выпуском v1.3.3. Логика Data Cycle и расписание
в БД не меняются.
