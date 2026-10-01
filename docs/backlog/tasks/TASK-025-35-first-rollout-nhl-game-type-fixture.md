# TASK-025-35 — Исправить NHL game_type в first-rollout fixture

> **Статус:** done — v1.2.15 tag pipeline и production run успешны
> **Владелец:** Product Owner; реализация — Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)

## Дефект и цель

Tag pipeline v1.2.13 [Docker run 36921903369](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36921903369)
остановился на `first-rollout / production-first-rollout-contract`:
тестовый Worker завершился с кодом 1. Release gates и сборка образов прошли,
но публикация образов была пропущена. Production осталась на v1.2.12.

Fixture генерирует `game_type="R"`, тогда как NHL assembler записывает
`regular` и модельная граница допускает только `regular`/`playoffs`. Все 12
fixture-событий исчезают перед feature pipeline. Нужно привести fixture к
каноническому значению и тестом защитить его прохождение через clean.

## Критерии

- [x] Fixture использует тот же `game_type`, что и NHL source/canonical.
- [x] Адресный тест демонстрирует, что все 12 событий проходят фильтр NHL.
- [x] Локальные lint/unit/production gates и независимый review проходят.
- [x] Новый immutable tag проходит terminal first-rollout, image publish,
  scan и provenance. Tag v1.2.13 не передвигается.
- [x] Production switch и ручной цикл выполнены по immutable release
  evidence v1.2.15; dispatcher включён после успешной проверки.

Tag v1.2.15 прошёл [Docker pipeline](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36931948706),
включая clean first-rollout, публикацию, scan и provenance. На production
ручной run `72caf5de-0e1d-4f2a-8473-799025bcc7bb` завершился `success`.
Первый запуск по расписанию остаётся критерием TASK-025-9.

Отчёт Developer: [TASK-025-35](../../changes/done/TASK-025-35-first-rollout-nhl-game-type-fixture.md).
