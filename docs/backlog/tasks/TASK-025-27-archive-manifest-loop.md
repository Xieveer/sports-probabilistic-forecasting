# TASK-025-27 — Синхронизировать все manifest в Data Cycle

> **Статус:** in_progress
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Блокирует:** production rollout v1.2.10

## Наблюдаемый дефект

Изолированный запуск неизменённого `run-canonical-refresh.sh` v1.2.9
пометил `archive_sync` успешным с `artifacts=0`: host-пользователь не мог
прочитать каталог архивов, а проверка `[[ ! -e ]]` не отличила отказ доступа
от отсутствия каталога. После исправления прав только временного fixture
отдельный запуск того же archive loop нашёл три manifest, но синхронизировал
только первый: `docker compose run` прочитал оставшийся NUL-список из stdin.
Оба случая могут дать ложный успех без синхронизации всех архивов.

## Критерии исправления

- [x] Регрессионный red-тест воспроизводит чтение stdin первым Compose run и
  требует вызова archive-sync для каждого из трёх manifest.
- [x] Перечисление manifest завершается ошибкой при недоступном archive root;
  действительно отсутствующий `operational-archive` сохраняет прежнее пустое
  поведение helper, а успешный Worker не может завершить archive_sync с
  `artifacts=0`.
- [x] Исправление локально ограничено shell runner и manifest helper; при
  ошибке sync или перечисления runner возвращает nonzero, после чего host
  recovery подтверждает остановку executor и выполняет terminal transition.
- [ ] Адресные тесты проходят под жёстким лимитом памяти без полного pytest
  на ноутбуке; независимый Reviewer не находит P0–P2. Адресные тесты прошли;
  независимый review ожидается.
- [ ] Production-like локальный wrapper под общим cgroup 6 GiB/no swap
  перечисляет и remote-verify все ожидаемые архивы на отдельном S3 fixture
  после применения исправления.

## Текущее состояние

Реализация и адресные тесты готовы к независимому review. Предыдущий
production-like wrapper v1.2.9 завершил archive_sync с `artifacts=0` из-за
прав fixture; отдельная проверка archive loop после исправления прав
синхронизировала 1 из 3 manifest. Повтор полного wrapper для новой версии и
remote verification ожидают release gate; production не затронут.

## Граница

Не менять формат source-state, архивов, схему БД и production данные.
Тег `v1.2.9` не переписывать; исправление готовить как новую версию.

## Handoff

Результат и доказательства — в
[отчёте](../../changes/done/TASK-025-27-archive-manifest-loop.md).
