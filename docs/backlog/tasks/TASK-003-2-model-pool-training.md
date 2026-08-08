# TASK-003-2 — Обучение модельного пула и отчёт кандидата

> **Статус:** backlog
> **Владелец:** implementer
> **Эпик:** [EPIC-003](../EPIC-003-scalable-multisport-platform.md)
> **Требование:** [REQ-003](../../product/requirements/REQ-003-scalable-multisport-platform.md)
> **ADR:** [ADR-003](../../architecture/adr/ADR-003-configured-multisport-portfolio.md)

## Результат и границы

На основе каталога обучать один football model pool для бинарного winner на
нескольких совместимых турнирах, не смешивая их в выдаче. Сформировать
сопоставимый отчёт кандидата: ML-метрики, доходность, разброс симуляций и
покрытие value-ставок. Не выполнять автоматическое promotion, total или
трёхклассовый winner.

## Критерии приёмки

- [ ] Датасеты двух турниров одного пула объединяются только после проверки
  совместимости контракта и сохраняют tournament provenance каждой строки.
- [ ] Запуск winner создаёт один model identity пула и отчёт со всеми
  обязательными метриками REQ-003.
- [ ] Несовместимый формат/спорт не объединяется и не создаёт артефакт.

## План реализации

1. Добавить падающие unit и integration тесты объединения и состава отчёта.
2. Реализовать pool dataset builder и передачу model-pool identity в training
   metadata/MLflow без изменения текущего NHL production pointer.
3. Добавить минимальный формат отчёта кандидата и документацию его полей.
4. Запустить целевые тесты и `make test-unit`.

## Затрагиваемые области и зависимости

- `sports_forecast/training/`, `sports_forecast/betting/`, `sports_forecast/config/`,
  `tests/`, MLflow-теги и документация.
- Требует TASK-003-1; реальные футбольные данные и пороги promotion не входят.

## Проверка

- Unit/integration тесты pool builder, trainer metadata и report schema.
- `make test-unit`.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-003-2-model-pool-training.md`.
- Follow-up / findings: TASK-003-3 использует сформированную immutable model identity.
