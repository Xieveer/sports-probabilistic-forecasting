# TASK-025-14 — Публиковать будущий календарь без closing line

> **Статус:** done — код, review и публикация source snapshot подтверждены
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)

## Наблюдаемый дефект

Первый ручной Data Cycle v1.2.2 `b4e312c2-59c2-4917-8e06-8483cd06a3b3`
завершился `failed/source_fetch_failed`. Provider создал 22 496 строк, из них
1 899 будущих матчей без closing line. Исторический odds refresh завершился
`merged_source=True`, `quota_hit=False`, однако валидатор snapshot требовал
closing line у каждого будущего матча и не публиковал календарь. Unit и
контейнеры были остановлены и проверены до terminalization; итоговое
уведомление отправлено один раз. Оба NHL timer остались выключенными.

## Критерии исправления

- [x] Source snapshot с будущим матчем без closing line публикуется после
  успешного merge исторических odds. Факты матча и статус `missing` остаются
  доступны до получения текущей линии на отдельной стадии `data_odds`.
- [x] Пустой source, отсутствие базовых колонок, отсутствие odds-колонки после
  merge, quota hit и неуспешный merge по-прежнему отклоняются.
- [x] Reproduction test падает на v1.2.2 и проходит после исправления;
  соседние source/canonical тесты проходят.
- [x] Независимый Reviewer проверил source→snapshot→canonical path, безопасность,
  версию и документы без P0–P2; целевой набор дал 37 passed.
- [x] Terminal PR/tag/evidence CI v1.2.3 прошли. Ручной run v1.2.3
  опубликовал source snapshot 181 826 590 bytes; дальнейший Worker отказал
  на файловом логировании Hydra. 30-дневный canonical календарь и безопасное
  завершение полного цикла остаются runtime gate TASK-025-9/15.

## Handoff

Кодовый результат описан в [отчёте](../../changes/done/TASK-025-14-future-close-odds-snapshot.md).
Runtime acceptance остаётся в [TASK-025-9](TASK-025-9-release-readiness.md).
