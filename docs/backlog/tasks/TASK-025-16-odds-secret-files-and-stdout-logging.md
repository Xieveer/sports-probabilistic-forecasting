# TASK-025-16 — Secret files для Odds API и stdout-логи Worker

> **Статус:** cancelled — оставшиеся критерии сняты решением владельца 2026-10-03
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)

## Наблюдаемый дефект

Ручной Data Cycle v1.2.4 `dcd54406-7b88-4061-85b0-c60d76aef127`
импортировал NHL календарь: 34 матча за 7 дней, 187 за 30 дней,
coverage `complete`. Стадия `data_odds` завершилась
`odds_acquisition_failed`: сохранённая попытка содержит
`provider_not_configured`, 0 запросов и 187 событий без линии.
Production Compose передаёт пути `ODDS_API_KEY_*_FILE`, тогда как общий
`OddsApiClient` читает только значения `ODDS_API_KEY_*`; основной Worker
не монтирует odds secret files.

При последующем отказе публикации прогнозов не оказалось прикладного
diagnostic marker: `hydra/job_logging=disabled` подавляет существующие логгеры.
Встроенный `hydra/job_logging=stdout` даёт логи в stdout без записи в
read-only `/app`. Изолированный replay установил отдельную причину
`materialization_failed`: [TASK-025-17](TASK-025-17-promoted-feature-contract.md).

## Критерии исправления

- [x] Общий Odds API client читает file-backed tiers и legacy fallback без
  раскрытия значений ключей; явная ошибка отсутствующего/нечитаемого файла
  не приводит к молчаливой смене credential.
- [x] Production Worker получает только file paths и read-only secret mounts,
  доступные UID/GID runtime; значения секретов не попадают в Compose/env/log.
- [x] Canonical Worker пишет прикладные логи в stdout без файлов Hydra;
  root filesystem остаётся read-only.
- [x] Red→green тесты проверяют поведение клиента и Compose/runner; соседние
  тесты и независимое review проходят без P0–P2.
- [ ] v1.2.5 release candidate проходит tag/evidence и production gates;
  один ручной цикл измеряет odds/quota, календарь, прогнозы и уведомление.
  Runtime acceptance и включение timer остаются в TASK-025-9.

## Handoff

[Отчёт выполнения](../../changes/done/TASK-025-16-odds-secret-files-and-stdout-logging.md)
заполняется фактически выполненными проверками. Publication failure
воспроизведён и исправляется в TASK-025-17; production gate остаётся в
TASK-025-9.

## Итог закрытия EPIC-025

Реализация включена в выпущенную v1.2.15. Неотмеченные выше критерии отдельного релиза/проверки не подтверждены в этой TASK и сняты при принятии итогового результата EPIC-025 владельцем. Это не отметка об их успешном выполнении.

Контракт secret files/stdout выпущен; прежний runtime-критерий будущих odds заменён TASK-025-34.
