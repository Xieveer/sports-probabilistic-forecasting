# REQ-011 — Изолированная import-граница Worker для v1.1.3

> **Статус:** confirmed
> **Владелец продукта:** пользователь
> **Создано:** 2026-08-20

## Результат и ценность

Production Worker может импортировать и вызывать verifier immutable model bundle,
не устанавливая MLflow. Это устраняет production-blocker опубликованного v1.1.2
отдельным patch-релизом v1.1.3 и сохраняет непрерывный audit trail уже
опубликованных artefacts.

## Scope

- Устранить eager import MLflow-зависимого `ModelPromoter` при импорте
  `sports_forecast.deploy.model_bundle`.
- Добавить release-gate, запускающий import verifier внутри собранного target
  `worker` до публикации образов.
- Поднять package/release version до `1.1.3` и обновить handoff для Operations.

## Non-scope

- Перепубликация, перезапись или перенос Git tag/digest v1.1.2.
- Deployment, публикация tag или образов, изменение VPS, Object Storage policy
  либо reader access.
- Изменение состава model bundle, данных модели, MLflow promotion или training.

## Сценарии

1. Worker image без MLflow исполняет `python -c "from
   sports_forecast.deploy.model_bundle import verify_model_bundle"` успешно.
2. Local training/control plane по-прежнему может явно получить
   `ModelPromoter` из `sports_forecast.deploy` при установленном MLflow.
3. Release v1.1.3 создаёт новые immutable digests и provenance; Operations
   пересобирает прежний bundle из тех же трёх файлов с `app_version=1.1.3`.

## Критерии приёмки

- [x] Import `verify_model_bundle` не требует MLflow.
- [x] `ModelPromoter` загружается лениво только при явном обращении local control
  plane.
- [x] Docker release workflow до push собирает Worker target и выполняет точную
  проверку import verifier.
- [x] Package/API/release contract имеет версию `1.1.3`.
- [x] Operations handoff запрещает менять v1.1.2 и требует новые v1.1.3
  digests/provenance и compatibility bundle.

## Ограничения, зависимости и риски

- Runtime Worker намеренно не содержит MLflow; MLflow остаётся dev-зависимостью
  local training/control plane.
- Локальная проверка Docker gate зависит от доступности Docker Hub; tag CI
  обязан выполнить gate до push независимо от локального результата.
- Новые digests/provenance появятся только после authorised tag pipeline.

## Предположения и открытые вопросы

- Bundle, VPS reader access и Object Storage policy исправны; меняется только
  runtime import boundary.
- Открытых продуктовых вопросов нет.

## Подтверждение

Пользователь подтвердил production-blocker, версию v1.1.3 и запрет изменения
v1.1.2 в запросе от 2026-08-20.
