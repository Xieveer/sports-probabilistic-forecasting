# TASK-025-16 — Secret files Odds API и stdout-логи Worker

> **Статус:** код и независимое review завершены; runtime gate открыт
> **Задача:** [TASK-025-16](../../backlog/tasks/TASK-025-16-odds-secret-files-and-stdout-logging.md)

## Граница

Общий клиент получает ключи Odds API из ограниченных secret files, Worker
монтирует их без передачи значений в environment. Hydra CLI использует
console-only logging и не пишет файлы в read-only `/app`.

## Доказательство

Red-тесты на file-backed tier и отсутствующий файл упали до исправления.
Green: 72 целевых теста вместе с TASK-025-17 и полный unit suite
(1207 passed, 13 deselected), `make lint`, `make production-check` и
`make docs` (155 warnings) прошли 2026-09-27. Независимый Reviewer не нашёл
P0–P2 в коде; release CI и production gate открыты. Изолированный replay
подтвердил отдельную причину publication failure в TASK-025-17.
