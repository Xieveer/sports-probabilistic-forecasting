# TASK-025-29 — Идемпотентный verified archive-sync

> **Статус:** независимое review кода и документации без блокирующих findings; release gate открыт.

## Причина

Production Data Cycle v1.2.10 записал 1 834 прогноза и создал архивы, после чего
archive-sync завершился `ReadTimeoutError`. Wrapper вызывает sync для всех
локальных manifest; прежняя реализация повторно загружала и скачивала каждый
архив, даже если durable state уже фиксировал успешную remote verification.
Так старые большие source-state архивы повторно занимали сеть и увеличивали
вероятность таймаута.

## Исправление

- После `verify_archive` sync читает durable запись для content-addressed ID.
  Только точная тройка `artifact_id`, нормализованный prefix и
  `status=verified` завершает повтор без S3 операций. Отсутствующая или
  повреждённая запись, а также отметка из другого prefix не считается успехом.
- Production v1.2.10 записывал legacy JSON без prefix. Для миграции legacy
  записи разрешены только два штатных production prefix. Sync подтверждает
  точный полный список ожидаемых remote key под конкретным prefix без лишних
  объектов и скачивает только небольшой manifest для побайтовой сверки. Если набор ключей/manifest не
  совпадает или подтверждение временно недоступно, выполняется прежняя полная
  upload и remote verification. Любой другой prefix всегда проходит полный путь.
- S3 client ограничивает connect timeout 5 секундами, read timeout 20 секундами
  и использует стандартный режим до трёх попыток на запрос.
- Остальной путь по-прежнему загружает каждый объект и скачивает его обратно для
  потоковой побайтовой сверки. Ошибка сохраняет staging и пишет `failed` state.

## Проверки

- Red: новый `test_sync_reuses_durable_verified_state_without_remote_roundtrip`
  упал ожидаемо: прежняя реализация вызвала upload у storage, который запрещал
  любую сеть для уже отмеченного архива.
- Green: тесты идемпотентности в одном и разных prefix, retry после
  `failed`-состояния, legacy state обоих production prefix, отказ миграции для
  неизвестного prefix и ограниченные настройки S3 клиента проходят.
- Релевантный модуль: `16 passed`.
- Ruff для изменённых Python файлов: `All checks passed!`.
- Обе pytest команды выполнены через `systemd-run` с `MemoryMax=768M`,
  `MemorySwapMax=0` и timeout (30/45 секунд). Полный pytest не запускался.
- Первичная попытка `uv run pytest` остановилась на сетевой загрузке setuptools
  (`Network is unreachable`); для тестов использован существующий Python 3.12
  venv.

Production не изменялся. Повторная проверка одного уже verified artifact в том
же prefix полагается на content-addressed immutable remote object и durable
state. Legacy переход ограничен production prefix, подтверждён точным набором
ключей и побайтовой сверкой manifest; неизвестные prefix, новая запись или
любое несовпадение проходят полную remote verification.
