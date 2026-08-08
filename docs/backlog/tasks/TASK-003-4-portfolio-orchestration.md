# TASK-003-4 — Оркестрация портфеля без статических списков

> **Статус:** backlog
> **Владелец:** implementer
> **Эпик:** [EPIC-003](../EPIC-003-scalable-multisport-platform.md)
> **Требование:** [REQ-003](../../product/requirements/REQ-003-scalable-multisport-platform.md)
> **ADR:** [ADR-003](../../architecture/adr/ADR-003-configured-multisport-portfolio.md)

## Результат и границы

Production heavy path получает активные турниры и market/spec из каталога, а
не из захардкоженных строк DVC/DAG. Независимые турниры получают bounded fan-out
и lock по tournament/source; ошибка одного не портит состояние других. DVC
сохраняется для dev/CI воспроизводимости. Не включать составы и не поднимать
конкурентность без измерений.

## Критерии приёмки

- [ ] Добавление активного поддерживаемого турнира в каталог обнаруживается
  orchestration contract без изменения Python/DAG списка.
- [ ] Команда/DAG строит изолированную heavy-цепочку для одного турнира;
  повтор и конфликтующий refresh одного ключа не создают гонку.
- [ ] Dev/CI DVC путь остаётся воспроизводимым и не подменяется production DAG.

## План реализации

1. Написать падающие command/DAG contract-тесты обнаружения, изоляции и locks.
2. Заменить статические списки на публичный каталог и выбрать совместимый с
   установленным Airflow bounded fan-out.
3. Адаптировать DVC/dev documentation и добавить наблюдаемые логи model pool,
   tournament и run identity.
4. Запустить целевые интеграционные тесты и `make test-unit`.

## Затрагиваемые области и зависимости

- `airflow/dags/`, `sports_forecast/orchestration/`, `dvc.yaml`, `conf/`,
  documentation и integration tests.
- Требует TASK-003-1 и TASK-003-3. Изменение Airflow executor/deployment не входит.

## Проверка

- DAG parsing/command integration tests и DVC config contract.
- `make test-unit`.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-003-4-portfolio-orchestration.md`.
- Follow-up / findings: TASK-003-5 использует fast path отдельно от heavy path.
