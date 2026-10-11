# EPIC-035 — Выпуск v1.3.2 с работающим NHL registry

> **Статус:** blocked — подтверждённые NHL events и временный серверный доступ
> **Приоритет:** critical
> **Владелец:** Product Owner

## Память Product Owner

- Инициатива: `EPIC-035`; ветка `initiative/epic-035-v1-3-2-release`, worktree `.worktrees/epic-035-v1-3-2-release`.
- Решение владельца: выпустить следующую production-версию после завершения новых эпиков, проверить [EPIC-026](EPIC-026-entity-registry.md) и оставить строгий registry в работе. Legacy-код и YAML сохранить для явного отката; удалить позднее отдельным изменением.
- Версия-кандидат: `v1.3.2` согласно ранее подтверждённому release intent; цель — `ops-prod-01`, текущий исправный выпуск — `v1.3.1`.
- Состав: текущий `main` после [EPIC-034](EPIC-034-telegram-bets-ux.md) и [PR #83](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/83) по EPIC-026; дальнейшие изменения только по подтверждённым release blockers.
- Проверено: PR #83 прошёл terminal CI и security; объединён с `main`. В интегрированной ветке перед PR прошли 1663 unit-теста, lint, docs и `ai-validate`. Доступный v1.3.1 master/snapshot содержит 0 событий; строгий reader ещё выключен.
- Следующая роль: Developer/Data Researcher — доверенная загрузка однозначных NHL API events по решению владельца; Reviewer — новая реализация и полный release candidate; Operations Agent — ограниченный серверный rollout, backup, health и бизнес-smoke после восстановления временного доступа.
- Блокеры: подтвердить покрытие ближайшего NHL горизонта и bookmaker связей новым snapshot; выполнить реальный непустой кандидатный цикл и NHL прогноз после strict switch; проверить влияние отключённого legacy `source.csv` odds merge; получить временный privileged VPS access; свежие backup/restore и immutable release artifacts.
- Обновлено: 2026-10-11.

## Критерии GO

1. Новый проверенный owner master хранит подтверждённые NHL события ближайшего горизонта, связи команд и source event IDs; неоднозначности остаются кандидатами. Есть защищённая копия master и воспроизводимое provenance загрузки.
2. Паритет известных NHL команд и событий проверен против текущих данных; strict reader не читает YAML. На реальных данных успешно проходят календарь, расчёт и выдача прогноза, доступность линии и непустой кандидат → решение владельца → publication/sync.
3. Точное изменение `v1.3.2` проходит review, terminal CI/security, `make production-check`, tag pipeline, image scan/provenance и release-evidence gate. Модельный bundle обёрнут для точной версии без переобучения.
4. Перед серверным switch проверены свежая копия БД, off-host readback, isolated restore, права ролей, место и план отката на exact `v1.3.1`; после switch — health, NHL цикл, Telegram выдача и первые плановые ticks.
5. Legacy-код остаётся в выпуске как явный rollback path. Его удаление не является условием EPIC-035.

## Решение и остановка

До выполнения всех критериев статус выпуска — `NO-GO`: тег и production switch не выполнять. При недостаточном покрытии registry, потере прогнозов/линии, ошибке публикации или неуспешном backup вернуть прежний reader mode/версию по runbook и зафиксировать evidence. Финальное решение и точные артефакты записать в [production handoff](../operations/production-handoff.md).
