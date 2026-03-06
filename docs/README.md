# Документация проекта

## Структура

- **`instructor/`** — актуальные руководства и архитектурные документы
- **`source/`** — исходники Sphinx (RST-файлы)
- **`build/`** — собранная HTML-документация

## Сборка Sphinx

```bash
cd docs && uv run sphinx-build -b html source build
```

Результат: `docs/build/index.html`

## Актуальные документы (instructor/)

| Документ | Описание |
|----------|----------|
| [CURRENT_TRAINING_STATUS.md](instructor/CURRENT_TRAINING_STATUS.md) | Текущий статус обучения, метрики, инфраструктура |
| [HOW_TO_ADD_NEW_TOURNAMENT.md](instructor/HOW_TO_ADD_NEW_TOURNAMENT.md) | Пошаговое руководство по добавлению турнира |
| [HOW_TO_ADD_NEW_MARKET.md](instructor/HOW_TO_ADD_NEW_MARKET.md) | Пошаговое руководство по добавлению маркета |
| [service_orchestration_architecture.md](instructor/service_orchestration_architecture.md) | Архитектура сервиса (FastAPI, Airflow, мониторинг) |
