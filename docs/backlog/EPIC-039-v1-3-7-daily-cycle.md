# EPIC-039 — Ежедневный Data Cycle без сбора коэффициентов, выпуск v1.3.7

> **Статус:** in_progress — исправление и release gates
> **Приоритет:** critical
> **Владелец:** Product Owner
> **Ветка:** `initiative/epic-039-v1-3-7-daily-odds`
> **Контракт:** [REQ-025](../product/requirements/REQ-025-bot-schedule-readiness.md#граница-ежедневного-цикла-и-predict-уточнение-владельца-2026-10-01)

## Цель и решение владельца

Вернуть ежедневному циклу последовательность: получить новые результаты и календарь, проверить и архивировать canonical данные, пересчитать признаки с влиянием новых результатов, сохранить прогноз. Коэффициенты The Odds API нужны при обращении к `/predict` для актуальной линии и edge. Вызовы провайдера в ежедневном цикле расходуют квоту без пользы для этого результата. Исправление выпускается новым immutable tag `v1.3.7`.

Владелец разрешил включить все три новых таймера после release gates. Проверка непустого owner candidate → review → sync → ack переносится на подключение нового турнира: в актуальном NHL все команды известны, outbox пуст. Нулевой feedback, строгий registry и работа расписания проверяются сейчас. Этот перенос не означает, что непроверенный сценарий считается пройденным.

## Критерии

1. Ежедневный runner не делает запросов к The Odds API ни в source snapshot, ни в Worker `data_odds`; стадия odds явно `skipped`, квота/attempt не растут от цикла.
2. Подготовленный проверенный снимок поступает в расчёт; добавление завершённого результата меняет последующие скользящие и иные релевантные признаки. Итоговый прогноз записывается в БД и доступен через API/бот.
3. `/predict` при запросе продолжает получать live Pinnacle и рассчитывать edge; отсутствие линии не скрывает прогноз. Прямой ручной refresh с явным `data_odds_enabled=true` сохраняет прежнюю возможность диагностики.
4. Независимый review, terminal CI/Security, release evidence, exact model/Worker gate, production backup/readback/restore и strict Data Cycle пройдены. Три таймера активны, минутный dispatcher даёт 20 последовательных ticks без `start-limit-hit`; feedback/sync работают без лишних публикаций.
5. Реальный непустой candidate и owner decision остаются открытым gate [EPIC-026](EPIC-026-entity-registry.md) для нового турнира. Legacy путь сохраняется для отдельного удаления.

## Память Product Owner

- Основание: v1.3.6 strict Data Cycle `98a75688-50c3-4f07-822d-9fdbdcead0e2` опубликовал 218 NHL прогнозов и из-за `data_odds_enabled=true` вызвал The Odds API; outbox 0. На сервере strict registry работает, три таймера остановлены до исправления.
- Дефект: source snapshot передаёт `--odds-enabled false`, но Worker берёт Hydra default `data_odds_enabled: true`. [TASK-039-1](tasks/TASK-039-1-daily-cycle-odds.md) выключает odds только в ежедневном runner.
- Предыдущая роль: Product Owner зафиксировал подтверждённый контракт REQ-025 и решение владельца 2026-10-12. Следующие роли: Developer → независимый Reviewer → Product Owner/Operations Agent.
- Release intent: production `v1.3.7`, strict reader остаётся включён; после gates возобновить data-cycle-dispatcher, registry-sync, registry-feedback. Rollback — проверенный v1.3.6 с остановленным dispatcher либо safe hold по [handoff](../operations/production-handoff.md).
- Review/merge gate: независимый Reviewer проверил `a12668883fcb6c552052b0c3dea507f5b22337ae` без P0–P2 после исправления handoff. PR [#96](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/96) слит в `e08452bc17b6d6bfab8fd97fd860f6df15fd56cd`; post-merge CI `38210285959` и Security `38210285974` — success. Annotated tag `v1.3.7` опубликован на exact merge; Docker `38210415506` прошёл release gates, first-rollout, четыре опубликованных образа, scan и provenance.
- Evidence gate: пять exact refs внесены в `deploy/release-manifest.json`; локальные `verify_release_evidence.py --handoff docs/operations/production-handoff.md`, `make production-check` и `git diff --check` прошли. Exact published Worker/model gate прошёл под UID10001/read-only/network-none с 489 ordered features. Post-merge evidence workflow и production switch ещё открыты.
- Обновлено: 2026-10-12.
