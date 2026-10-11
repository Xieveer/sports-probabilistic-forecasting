# EPIC-035 — Выпуск v1.3.2 с работающим NHL registry

> **Статус:** cancelled — source/image gates выполнены, production rollout получил NO-GO и заменён EPIC-036
> **Приоритет:** critical
> **Владелец:** Product Owner

## Память Product Owner

Реальный preflight 2026-10-11 остановил выпуск: strict reader теряет шесть
живых Pinnacle котировок из-за сдвига времени +10 минут, а ORM запись
кандидата под `sf_refresh_writer` откатывается с `InsufficientPrivilege`.
Snapshot опубликован и установлен; 51/51 NHL событий разрешены. Production
остаётся на v1.3.1 со strict reader off. Неизменяемый тег v1.3.2 и образы
остаются release evidence, но на сервер не устанавливаются. Исправляющий
выпуск ведётся в [EPIC-036](EPIC-036-registry-rollout.md). Ниже
сохранён план прежнего кандидата как история, он не является текущей командой
на rollout.

- Инициатива: `EPIC-035`; ветка `initiative/epic-035-v1-3-2-release`, worktree `.worktrees/epic-035-v1-3-2-release`.
- Решение владельца: выпустить следующую production-версию после завершения новых эпиков, проверить [EPIC-026](EPIC-026-entity-registry.md) и оставить строгий registry в работе. Legacy-код и YAML сохранить для явного отката; удалить позднее отдельным изменением.
- Версия-кандидат: `v1.3.2` согласно ранее подтверждённому release intent; цель — `ops-prod-01`, текущий исправный выпуск — `v1.3.1`.
- Состав: exact `main` commit `38d59dc7ffaa16f805dc5a0c3700c56c59800f53` после [EPIC-034](EPIC-034-telegram-bets-ux.md), [PR #83](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/83), [PR #84](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/84) и [PR #85](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/85); annotated `v1.3.2` закреплён на нём.
- Проверено: PR #84 и #85 прошли terminal CI/security и объединены с `main`; post-merge CI/Security exact commit прошли. Локальный owner master защищён копией, содержит 51 NHL event; verified snapshot `ir1:e0070e397775a9227300d3edb061b20a15744f5317ccd7e56752e6ab67e196ce` разрешает 51/51 официальных game IDs. 100 team aliases совпадают с legacy seed. В EPIC-026 и release branch прошло по 1679 unit-тестов; lint, docs, `make production-check`, `make ai-validate`, `uv lock --check` и независимое review чистые. [Tag pipeline](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38168245261) прошёл release gates, first-rollout, четыре image scan/provenance. Wrapper модели v1.3.2 локально прошёл checksum/CatBoost/489 features без переобучения. Strict reader на VPS ещё выключен.
- Предыдущая роль: независимый Reviewer проверил release candidate; два P2 в handoff/порядке gates исправлены, повторное review чистое.
- Следующая роль: Reviewer — immutable evidence; Operations Agent — ограниченный серверный rollout, backup, health и бизнес-smoke после временного доступа.
- Блокеры: подтвердить покрытие фактического production NHL горизонта и bookmaker связей новым snapshot; выполнить реальный непустой кандидатный цикл и NHL прогноз после strict switch; проверить отдельную текущую линию при отключённом legacy `source.csv` merge; получить временный privileged VPS access; свежие backup/restore и release-evidence gate.
- Обновлено: 2026-10-11.

## Критерии GO

1. Новый проверенный owner master хранит подтверждённые NHL события ближайшего горизонта, связи команд и source event IDs; неоднозначности остаются кандидатами. Есть защищённая копия master и воспроизводимое provenance загрузки.
2. Паритет известных NHL команд и событий проверен против текущих данных; strict reader не читает YAML. На реальных данных успешно проходят календарь, расчёт и выдача прогноза, доступность линии и непустой кандидат → решение владельца → publication/sync.
3. До тега точное изменение `v1.3.2` проходит review, terminal PR CI/security и `make production-check`. Затем annotated tag ставится на exact merge commit; tag pipeline публикует образы с scan/provenance, после чего проходит release-evidence gate. Модельный bundle обёрнут для точной версии без переобучения.
4. Перед серверным switch проверены свежая копия БД, off-host readback, isolated restore, права ролей, место и план отката на exact `v1.3.1`; после switch — health, NHL цикл, Telegram выдача и первые плановые ticks.
5. Legacy-код остаётся в выпуске как явный rollback path. Его удаление не является условием EPIC-035.

## Решение и остановка

До review, terminal PR CI/security и локальных проверок тег не создавать. После
этих gates тег и immutable артефакты можно выпустить для серверной проверки;
это ещё не решение о production switch. До выполнения всех критериев GO
production switch запрещён, статус — `NO-GO`. При недостаточном покрытии
registry, потере прогнозов/линии, ошибке публикации или неуспешном backup
вернуть прежний reader mode/версию по runbook и зафиксировать evidence.
Финальное решение и точные артефакты записать в
[production handoff](../operations/production-handoff.md).
