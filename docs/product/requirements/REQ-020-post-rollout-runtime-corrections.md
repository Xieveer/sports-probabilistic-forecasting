# REQ-020 — Исправления runtime после первого rollout

> **Статус:** confirmed
> **Владелец продукта:** пользователь
> **Создано:** 2026-09-08

## Результат и ценность

Оператор и команда разработки получают корректные сигналы готовности, единый способ
передачи DB credentials в bootstrap, безопасный recovery bundle при смене release и
доступное меню Telegram-команд без выпуска новой версии или изменения `/health`.

## Scope

- `/status` администратора использует dependency-aware `/ready` и не раскрывает детали
  HTTP-ошибок или исключений.
- CLI canonical bootstrap использует `DATABASE_URL_FILE` с тем же приоритетом, что API,
  Worker и Migrator.
- Installer проверяет candidate по target `app_version`, а verified старый `current`
  сохраняет в `previous` при cross-version activation.
- При старте bot вызывает Telegram `setMyCommands`: public-команды доступны всем
  разрешённым пользователям, admin-команды — только администраторам.

## Non-scope

- Изменение liveness-контракта `/health`, запуск production workload, deployment, теги,
  миграции, изменение секретов и переобучение моделей.

## Сценарии

1. Администратор запрашивает `/status`: при готовом API видит readiness; при отказе или
   сетевой ошибке получает безопасное общее сообщение.
2. Bootstrap запускается в production с `DATABASE_URL_FILE` и подключается к той же БД,
   не выбирая SQLite fallback.
3. Installer активирует bundle нового приложения, сохраняя проверенный bundle прежнего
   релиза в `previous`; runtime нового приложения не пытается загрузить его как current.
4. Разрешённый пользователь видит `/start`, `/help`, `/predict`, `/upcoming`, `/edge`;
   администратор дополнительно видит существующие `/status`, `/refresh`, `/models`.

## Критерии приёмки

- [ ] `/status` вызывает `/ready`, обрабатывает non-2xx и transport/parse error без
  вывода исключений, URL, body или секретов.
- [ ] `DATABASE_URL_FILE` работает для `canonical_bootstrap import-nhl`; file value имеет
  тот же приоритет и валидацию, что в остальных runtime entry points.
- [ ] Cross-version install сохраняет checksum-verified `current` в `previous` без
  compatibility-check against target; candidate остаётся проверенным against target.
- [ ] `setMyCommands` вызывается до polling и регистрирует команды в соответствии с
  existing allowed/admin access model.

## Ограничения, зависимости и риски

- Telegram Bot API недоступен в unit-тестах и должен быть замокирован на границе клиента.
- `previous` является recovery artifact; его запуск требует rollback application release
  к совместимой версии.

## Подтверждение

Пользователь явно передал scope и запретил выпуск/теги в сообщении от 2026-09-08.
