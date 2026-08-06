---
name: prepare-release
description: Оценить готовность проверенного изменения к merge, сборке или production-выпуску и выдать go/no-go решение. Использовать перед релизом или подключением CD; не использовать как разрешение на deployment без явной авторизации и выбранной цели.
---

# Подготовка релиза

## Процесс

1. Зафиксировать состав релиза, версию, целевое окружение и владельца решения.
2. Проверить критерии приёмки и Definition of Done:
   `../../references/definition-of-done.md`.
3. Получить независимые отчёты code review, security и tests; параллелить только независимые
   read-only проверки по `../../references/orchestration.md`.
4. Проверить конфигурацию, migrations, совместимость, observability и runbook.
5. Определить rollout, health signals, rollback и критерии остановки.
6. Проверить artifact provenance, immutable version и отсутствие secrets.
7. Перевести `docs/operations/production-handoff.md` в статус `candidate`, заполнить его
   без секретов и выполнить `make production-check`.
8. Сформировать go/no-go; blockers нельзя заменить обещанием исправить после выпуска.

Дополнительно использовать `../../references/release-checklist.md`.

## Нельзя сокращать

- Не выполнять deployment без явного запроса и разрешения.
- Не считать зелёный CI полным release review.
- Не выпускать migration без rollback/forward-fix решения.
- Не публиковать mutable `latest` как единственный идентификатор.
- Не перекладывать исследование приложения на DevOps Operations Agent: runtime,
  healthcheck, зависимости и rollback должны быть явно переданы.

## Red flags

- Нет владельца rollback.
- Нельзя понять, успешен ли rollout.
- Security finding отложен без принятия риска.
- Production config не проверена отдельно от local.

## Результат

Вернуть `GO`, `NO-GO` или `CONDITIONAL GO`, доказательства, blockers, заполненный контракт
передачи, rollout, rollback и остаточные риски. Deployment остаётся отдельным
авторизованным действием DevOps Operations Agent.

## Проверка

- Все обязательные gates имеют ссылки/выводы.
- Rollback выполним в заданное время.
- Решение не скрывает непроверенные области.
