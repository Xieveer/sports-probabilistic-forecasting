# REQ-010 — Выделенная runtime-идентичность контейнеров

> **Статус:** confirmed
> **Владелец продукта:** пользователь проекта
> **Создано:** 2026-08-19

## Результат и ценность

Production-образы API, Worker, Telegram bot и archive-sync запускаются от
выделенной непривилегированной Linux-идентичности `sf` с UID/GID `10001:10001`.
Это исключает текущую коллизию с `zabbix:systemd-journal` (`999:999`) на
`ops-prod-01`, из-за которой bind-mounted source/archive каталоги могли быть
доступны процессу Zabbix хоста.

## Scope

- Зафиксировать UID/GID `10001:10001` при создании группы и пользователя `sf`
  в базовом Docker runtime-слое.
- Проверять числа и непривилегированность для всех четырёх runtime targets
  статическим тестом Dockerfile.
- Передать Operations требование создать на VPS отдельного host user
  `sf-runtime` с UID/GID `10001:10001` и открыть только необходимые mounts.

## Non-scope

- Изменение пользователей, групп, mounts, ACL или запущенных контейнеров на VPS.
- Deployment, создание Git tag, публикация образов и выпуск immutable digests.

## Сценарии

1. CI собирает каждый runtime target, в котором пользователь `sf` имеет
   UID/GID `10001:10001` и не является root.
2. Operations сопоставляет владельца только нужных host source/archive
   каталогов с `10001:10001`; посторонний host пользователь с UID/GID `999:999`
   не получает доступ из-за container identity.

## Критерии приёмки

- [x] Dockerfile создаёт группу и пользователя `sf` с UID/GID `10001:10001`.
- [x] API, Worker, Telegram bot и archive-sync используют непривилегированного
  пользователя `sf` во всех runtime stages.
- [x] Тест фиксирует числовые UID/GID `10001:10001`, а не только имя `sf`.
- [x] Release handoff требует новые четыре immutable digest, CI, image scan и
  provenance; до их получения release/rollout запрещён.

## Ограничения, зависимости и риски

- Operations создаёт host user `sf-runtime` и настраивает права mount-каталогов
  только после получения новых immutable images.
- Тест Dockerfile не доказывает фактическую identity опубликованного image;
  это проверяется tag-only CI и Operations перед rollout.

## Предположения и открытые вопросы

- Предположение: UID/GID `10001` не занят на production hosts; Operations
  подтверждает это до создания host user.
- Открытых вопросов нет.

## Подтверждение

Пользователь подтвердил требование и exact UID/GID в запросе от 2026-08-19.
