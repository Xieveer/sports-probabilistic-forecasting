# TASK-025-26 — Ограничение памяти refresh Worker

> **Статус:** done; release gates остаются в EPIC-025.

## Диагностика

Новый NHL source сформирован внешним source-acquirer на копии каталога
без изменения production и оригинального локального источника. Снимок содержит
22 509 матчей; Worker под лимитом 3 GiB завершил генерацию 489 признаков и
валидацию train таблиц (41 324 × 665 и 20 662 × 1 591). Сразу после этого
контейнер остановлен cgroup (`exit=137`, `OOMKilled=true`, swap не использован).
В успешном предыдущем цикле на 22 496 матчах следующая операция записала
train Parquet около 159 и 231 MB в `/tmp` с tmpfs 512 MiB. Код держал копии
полной истории и широкую таблицу одновременно. Materialization читает только
inference Parquet, поэтому train-файлы для refresh не нужны.

Отдельный инцидент pytest с 14.3 GB RSS был ошибкой fixture/mock и исправлен
в [TASK-025-23](../../backlog/tasks/TASK-025-23-pytest-memory-guard.md).
Здесь причина — ограниченный пик памяти на полной истории, не leak.

## Исправление и проверки

`process_tournament_new(..., inference_only=True)` вычисляет признаки на
полном наборе, затем формирует широкую таблицу и Parquet только для будущих
матчей. Обычный путь подготовки train не меняется. Red-тест до правки упал
на неизвестном параметре; после неё `inference_long` и `inference_wide`
совпадают с прежними файлами, train-файлы отсутствуют. 18 адресных тестов
прошли под `MemoryMax=2G`, `MemorySwapMax=0`, timeout 60 s.

Связанный локальный Data Cycle `876f0523-3f8c-44b6-95a8-0234b4258fbd`
на свежем source и весах production-модели завершился `partial_success` только
из-за явно выключенных odds. Worker: `exit=0`, `OOMKilled=false`, лимит 3 GiB,
1 847 прогнозов; стадии calendar/quality/predictions/publication — success.
Оба archive-sync: `exit=0`, `OOMKilled=false`, лимит 512 MiB, `/tmp=64m`,
durable state `verified`; стадия archive_sync — success. Один outbox item
доставлен тестовому боту за одну попытку. Независимый Reviewer не нашёл
P0–P2 замечаний. Production не затронут; release/CI gates ещё открыты.
