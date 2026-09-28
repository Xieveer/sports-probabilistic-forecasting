# TASK-025-26 — Убрать обучающие таблицы из refresh Worker

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Блокирует:** [TASK-025-22](TASK-025-22-local-quality-parity.md)

## Наблюдаемый дефект

Второй изолированный Data Cycle на свежем NHL source и весах production-модели
завершился `exit=137`, `OOMKilled=true` при лимите Worker 3 GiB. Генерация
489 признаков на 22 509 матчах и валидация `processed_long` и
`processed_wide` завершились; следующая операция — запись полных train Parquet.
В предыдущем цикле на 22 496 матчах она создала файлы примерно 159 и 231 MB
во временном tmpfs, который учитывается в том же memory cgroup.

## Причина

`process_tournament_new` всегда строил широкую таблицу для всей истории,
копировал train и inference срезы и сериализовал train-файлы, хотя
`materialize_predictions` читает только `inference_{format}.parquet`.
Пересечение лимита является пиком обработки и сериализации полной истории,
а не memory leak или неограниченным накоплением объектов. Точная доля
каждой временной копии в пике не измерена; полная запись не повторялась.

## Критерии исправления

- [x] Red-тест сравнивает файлы inference прежнего и нового пути и требует
  отсутствия train-файлов у refresh.
- [x] Признаки считаются на всей истории; refresh сохраняет только
  `inference_long` и `inference_wide`, обычная подготовка train не меняется.
- [x] Адресные тесты прошли под жёстким memory cgroup 2 GiB.
- [x] Свежий связанный локальный Data Cycle проходит при production-лимите
  Worker 3 GiB и обоих archive-sync 512 MiB.
- [x] Независимое review, документация и релевантные проверки завершены.

Исходный run `1d9130eb-c281-43d2-8bca-3100cc28a1fa` безопасно переведён в
terminal `failed/prediction_failed`; тестовый бот доставил уведомление о
неуспехе. Production не затронут.

Исправленный run `876f0523-3f8c-44b6-95a8-0234b4258fbd` завершился
`partial_success` только из-за явно выключенных odds: Worker `exit=0`,
`OOMKilled=false`, 1 847 прогнозов; оба archive-sync `exit=0`,
`OOMKilled=false`, state `verified` при `mem_limit=512m` и `/tmp=64m`.
Уведомление доставлено тестовому боту за одну попытку. Независимое review
не нашло P0–P2 замечаний. Release/CI/production gates остаются у EPIC-025.

Результат — в [отчёте](../../changes/done/TASK-025-26-refresh-inference-memory.md).
