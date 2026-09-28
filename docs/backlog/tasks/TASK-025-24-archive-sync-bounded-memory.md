# TASK-025-24 — Ограничить память archive-sync на большом source-state

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Блокирует:** [TASK-025-22](TASK-025-22-local-quality-parity.md)

## Наблюдаемый дефект

На изолированном локальном стенде source-state archive размером около 181 MiB
загрузил все четыре объекта в S3 fixture, после чего archive-sync CLI
завершился `exit=137`, `OOMKilled=true` при production-лимите 512 MiB.
Canonical archive на том же стенде синхронизировался успешно. В коде remote
verification одновременно вызывает `read_bytes()` для скачанного и локального
файла, создавая две полные копии большого файла в памяти.

## Критерии исправления

- [x] Адресный red-тест воспроизводит запрет чтения большого файла целиком.
- [x] Remote verification сравнивает файлы потоково, сохраняя проверку каждого
  объекта и прежнюю семантику failed/verified state.
- [x] Оба локальных архива проходят sync на S3 fixture при лимите 512 MiB;
  повреждённый remote object по-прежнему отклоняется.
- [x] Независимое review и релевантные проверки завершены.

Red-тест упал на попытке `Path.read_bytes()` для большого файла. После замены
сравнения на блоки по 1 MiB все девять тестов `test_operational_archive_sync.py`
прошли под лимитом 1 GiB, включая повреждение remote object без изменения
размера. Повторные sync обоих локальных архивов завершились
`exit=0`, `OOMKilled=false` под лимитом 512 MiB; durable state содержит два
`verified`. Данные и архивы остаются в `/tmp`; production не затронут.
Независимый Reviewer подтвердил отсутствие P0–P2 findings и согласованность
результатов проверок в TASK, отчёте и EPIC.

Результат — в [отчёте](../../changes/done/TASK-025-24-archive-sync-bounded-memory.md).
