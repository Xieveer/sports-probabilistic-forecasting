# TASK-032-2 — Профили registry в release gates

> **Статус:** done — исправление проверено локально; повторный release CI ожидается
> **EPIC:** [EPIC-032](../EPIC-032-v1-3-0-release.md)
> **Приоритет:** high

## Причина

Теговый [CI v1.3.0](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38142671658)
завершился ошибкой на шаге `Verify rendered production Compose contract`:
workflow не включал новые opt-in профили `registry-sync` и
`registry-feedback`, а verifier ожидал оба сервиса. Та же ошибка была в
workflow проверки release evidence. Образы не публиковались, rollout не
начинался.

Дополнительная локальная проверка показала, что evidence verifier тоже
ожидал прежний состав сервисов и отклонил бы полный render после первой правки.

## Проверяемый результат

1. Оба workflow явно включают новые профили во всех командах, которые
   строят полный production Compose для verifier.
2. Регрессионный тест падает на исходном workflow и проходит после
   исправления; реальный rendered Compose проходит оба verifier, а отсутствие
   любого registry сервиса отклоняется.
3. Исправленный source commit проходит новый PR CI и tag pipeline до
   рассмотрения production rollout. Тег `v1.3.0` остаётся неизменным;
   дальнейшая версия требует решения владельца.

## Результат

Команды обновлены в обоих workflow; [отчёт](../../changes/done/TASK-032-2-release-compose-profiles.md)
содержит локальные проверки. Независимый review и новый CI для исправленного
commit остаются gate EPIC-032.
