# ADR-011 — Ленивая загрузка MLflow control-plane API из deploy

> **Статус:** accepted
> **Дата:** 2026-08-20
> **Связанное требование:** [REQ-011](../../product/requirements/REQ-011-worker-import-boundary-v1-1-3.md)

## Контекст и критерии выбора

Worker runtime намеренно не содержит MLflow, но импорт подмодуля
`sports_forecast.deploy.model_bundle` сначала исполнял package `__init__`,
который eager-import'ил MLflow-зависимый `ModelPromoter`. Нужны совместимость
явного public API control plane, отсутствие MLflow на Worker import path и
проверка в реальном target image.

## Рассмотренные варианты

1. **Status quo:** eager import сохраняет удобный re-export, но блокирует
   production Worker.
2. **Удалить re-export:** Worker работает, но ломается существующий public API
   `from sports_forecast.deploy import ModelPromoter`.
3. **Ленивый module `__getattr__`:** сохраняет re-export для local control
   plane и не загружает `promoter` до явного обращения.

## Решение

Выбран вариант 3. `deploy.__init__` не импортирует MLflow при загрузке пакета;
он лениво возвращает `ModelPromoter` только при явном обращении. CI до push
собирает Worker target и исполняет import verifier внутри контейнера.

## Последствия

- Положительные: Worker остаётся без MLflow, а control-plane API совместим.
- Отрицательные и стоимость: ошибка отсутствующего MLflow для `ModelPromoter`
  теперь возникает в момент его явного использования, что соответствует его
  отдельной dependency boundary.
- Безопасность и эксплуатация: v1.1.2 не меняется; v1.1.3 получает новую
  version-to-commit-to-digest provenance и gate до публикации.

## Проверка и пересмотр

Unit test блокирует импорт MLflow и проверяет verifier; Docker release-gate
проверяет тот же import в Worker image. Решение пересматривается, если Worker
потребует MLflow-функции, что будет отдельным изменением runtime dependency
boundary.

## Источники и неизвестное

- Production incident из подтверждённого запроса владельца 2026-08-20.
