# EPIC-038 — Ограниченная очередь registry candidates и выпуск v1.3.6

> **Статус:** in_progress — v1.3.6 strict production cycle прошёл; реальный candidate и 20 ticks ожидают решения владельца
> **Приоритет:** critical
> **Владелец:** Product Owner
> **Ветка:** `initiative/epic-038-v1-3-6-candidate-scope`
> **Предыдущий кандидат:** [EPIC-037](EPIC-037-v1-3-5-registry-cycle.md)

## Цель и решение

Выпустить NHL registry со словарями команд, турниров, рынков и исходов, автоматическим сопоставлением матчей по подтверждённым участникам и UTC ±15 минут, полезными прогнозами и линией в API/боте, а также работоспособной очередью неизвестных обозначений. Массовые задачи на создание owner-связи для каждого календарного события противоречат согласованному контракту [ADR-035](../architecture/adr/ADR-035-registry-dictionaries-and-derived-event-matching.md).

Владелец ранее разрешил довести выпуск новой версии до production после review/CI/gates. Исправление получает новый immutable tag `v1.3.6`; v1.3.5 и его evidence tag не меняются.

## Память Product Owner

- v1.3.5 прошла review, postmerge CI/Security, tag, Docker/first-rollout, image scan/provenance и release-evidence workflow `38182755480`. Exact Worker image и модельный wrapper проверены под UID10001/read-only/network-none с 489 признаками.
- На VPS v1.3.5 strict=true дала здоровые API/бот и 49 NHL прогнозов, из них три с реальной двухсторонней Pinnacle линией. Полный strict Data Cycle `95169bca-160d-4a84-9f1f-58ecb10c8319` прошёл calendar/quality/archive/predictions/publication; `data_odds` partial_success из-за покрытия, три новые observations, 219 опубликованных прогнозов. Дефект отсутствующего installation ID исправлен.
- Но calendar записал 22 656 pending candidates за один проход всего исторического NHL `source.csv`: 21 963 `kind=event` за 2010–2026 и 693 `kind=team`, преимущественно PHX/ATL и старые обозначения. Это не ограниченное owner review. Feedback publication/import и timers не запускались. Решение v1.3.5 — NO-GO. После цикла strict возвращается в false; v2 snapshot seq3 и immutable образы сохраняются.
- [TASK-038-1](tasks/TASK-038-1-bounded-registry-candidates.md) убирает event-ID candidates при отсутствии постоянной owner-связи, оставляет явный конфликт уже подтверждённой связи, а календарный capture неизвестных словарных обозначений ограничивает UTC `now−1 день … now+30 дней`. 30 дней совпадают с NHL calendar coverage и будущим odds batch; нижняя граница исключает исторический backfill. Реальные неоднозначные котировки по-прежнему остаются неприсоединёнными и диагностируются matcher.
- Накопленные 22 656 pending rows не опубликованы. Новый root-only backup `/var/backups/sports-forecast/postgres/pre-v1.3.6-outbox-20261011T231706104990022.dump` с SHA-256 `d379d32d8f11e7191e76bc692efc500e48ecb54febd0ffe8c0c20f990a2d8dfe` прошёл off-host full readback и isolated restore. Адресная транзакция после exact predicate/count/digest gate удалила только batch ID 2–22657: `DELETE RETURNING` 22 656, postcheck outbox 0; registry snapshot/остальные таблицы не менялись. Код исправления не требует миграции БД.
- Следующая роль: Product Owner — решение о переносе непустого реального candidate gate; Operations Agent — после решения 20 минутных ticks, проверка уведомлений/heartbeat и фиксация GO либо safe hold. Review, CI/Security, Docker, evidence, model gate, strict forecast/odds/API/бот и zero-work feedback уже прошли; открыты только настоящий owner cycle и расписание.
- Production evidence v1.3.6: PR #93/94, source tag `v1.3.6` на `b06b544313b1915da3960670ddfbd836ad0a5b53`, release-evidence workflow `38185467879` green. Strict Data Cycle `98a75688-50c3-4f07-822d-9fdbdcead0e2` опубликовал 218 прогнозов, три будущие Pinnacle observations (matched 3/rejected 0), outbox 0 после calendar/odds/цикла; нулевой feedback прошёл. Настоящего актуального кандидата нет, timers остановлены; владелец решает, переносить ли непустой gate до появления данных.
- Обновлено: 2026-10-12.

## Критерии GO

1. При полном историческом `source.csv` строгий календарь создаёт кандидатов только для неизвестных турниров/команд оперативного окна `now−1d … now+30d`; отсутствие постоянной event owner-связи не создаёт `kind=event`. Явный конфликт существующей подтверждённой связи не скрыт. При повторном наблюдении сохраняется стабильный idempotency key для дедупликации владельцем; outbox хранит отдельные наблюдения.
2. Red/green тест воспроизводит прежнюю массовую очередь на малой репрезентативной выборке (исторические PHX/ATL, текущий неизвестный alias и матч с известными командами). Не меняются matcher, рынок, модельные веса и registry snapshot.
3. Накопленная ошибочная очередь изолирована и адресно устранена после свежего backup/restore и проверки counts. Feedback publisher не переносит исторические event IDs/старые команды в owner master. Один настоящий актуальный candidate проходит outbox → publish → local owner review → publication/sync/ack; неоднозначное решение запрашивается у владельца.
4. Независимый review без P0–P2, terminal CI/Security, `make production-check`, exact annotated tag `v1.3.6`, scan/provenance/first-rollout, model wrapper на exact Worker image и release-evidence workflow проходят.
5. На production с strict=true полный Data Cycle, API и Telegram дают полезный NHL прогноз и реальную Pinnacle линию; 20 минутных ticks без `start-limit-hit`, stale heartbeat и лишних уведомлений. При провале — strict=false safe hold с остановленными timers или проверенный rollback.

## Решение

До выполнения всех критериев статус `NO-GO`. Факты и откат фиксируются в [production handoff](../operations/production-handoff.md). Legacy код и старые event relations сохраняются для истории и отката; их удаление — отдельная задача.
