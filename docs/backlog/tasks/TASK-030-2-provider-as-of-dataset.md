# TASK-030-2 — Закреплённый набор исторических цен на момент решения

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-030](../EPIC-030-financial-research-validation.md)
> **Требование:** [REQ-030](../../product/requirements/REQ-030-financial-research-validation.md) (`confirmed`)
> **Решение:** [ADR-032](../../architecture/adr/ADR-032-reproducible-financial-research-evaluation.md) (`accepted`)
> **Протокол:** [NHL protocol](../../research/epic-030-nhl-protocol.md)

## Результат и границы

Из полного закреплённого universe [TASK-030-1](TASK-030-1-pinned-nhl-universe.md)
построить локальный отсортированный набор NHL/Pinnacle `winner_withOT` цен на
момент `T_event = kickoff − 15 минут`. Использовать только immutable
historical observations и существующий `query_provider_as_of` с pinned `ir1`;
возраст допустимой цены на `T_event` не превышает 24 часа. Current и wide
close odds не являются fallback.

Результат включает manifest и по одной записи для каждого ожидаемого NHL
матча, включая отсутствие цены. На этой TASK не читаются исходы тестовых
матчей, признаки и прогнозы; ставки/ROI не считаются. Raw cache, registry и
старые артефакты не изменяются.

## Критерии приёмки

1. Проверка pinned `ir1`, fingerprint historical набора, NHL universe и
   resolved конфигурации предшествует выводу dataset. Изменение любого входа
   не переиспользует прежний dataset ID. ID зависит от канонического
   содержимого, а не от абсолютного пути или времени запуска.
2. Для каждого события выбирается полный вектор `home_win/away_win` из
   последнего snapshot с `observed_at ≤ T_event`; конфликт в этой точке
   отклоняет событие без отката на более старый snapshot. Выбранные
   `ho1`, `ir1`, timestamp, nullable `retrieved_at`, receipt/provenance и
   возраст сохраняются вместе с ценой. Будущий, конфликтный и слишком старый
   snapshot не выдаётся как пригодный.
3. Coverage отдельно считает полный expected universe, сопоставленные
   события, пригодную линию, отсутствие Pinnacle линии, отсутствие snapshot,
   ошибку mapping, конфликт и просроченную цену. Причины исключения
   взаимно исключаются в итоговом dataset; unknown retrieval не превращается
   в известное локальное получение. Одинаковое правило работает для разных
   `T_event` без второго конкурирующего алгоритма классификации.
4. Старый `historical_cli coverage --at` и существующие query/coverage тесты
   сохраняют поведение; новый локальный путь не меняет API/бота.
5. Повторный запуск с теми же входами воспроизводит отсортированные event IDs,
   observation IDs, категории и manifest. Реальный offline smoke на выбранном
   окне записывает фактическое покрытие без раскрытия исходов.

## Результат

Добавлен локальный CLI `sports_forecast.research.provider_dataset`. По умолчанию
он строит dataset на всём pinned universe; `--start/--end` задают
вложенное полуоткрытое окно и входят в resolved config/dataset ID. Перед
записью проверяются canonical `run_id`, fingerprints NHL parquet/team seed/
historical inputs, окно/policy, структура и полнота resolved+timed-diagnostic
строк относительно повторно прочитанного identity-only NHL parquet, pinned
`ir1`, NHL source UUID/kickoff/teams и подтверждённые Odds API source links.
Untimed diagnostics не входят в expected universe. Неразрешённые timed model matches сохраняются отдельными
`mapping_error` rows с source key, kickoff и decision time. Batch query использует `query_provider_as_of_many` в read-only
режиме; цены и конфликт на последнем допустимом timestamp возвращаются без
fallback. Старый scalar query и CLI coverage сохранены.

Для каждого матча сохраняются kickoff и `decision_at`, категория и причина;
для цены — `ho1`, `ir1`, полный outcome-вектор, observed/retrieved/imported
provenance и возраст. `retrieved_at=null` остаётся unknown. Просроченная цена
доступна как `price_candidate`, но не как пригодная `price`. Outcomes, признаки,
прогнозы и ROI не загружаются.

Offline smoke, подробные счётчики, fingerprints, команды и ограничения:
[отчёт TASK-030-2](../../changes/done/TASK-030-2-provider-as-of-dataset.md).

## Red → green → refactor

1. Synthetic тесты per-event T, отсутствующей линии, snapshot позже T,
   конфликтов и stale цены; сначала зафиксировать красный результат.
2. Переиспользовать historical query/coverage; расширить существующий coverage
   контракт совместимо для per-event T. Добавить минимальный dataset manifest
   и валидацию fingerprint, без нового хранилища или scheduler.
3. Запустить адресные regression tests, локальный real smoke и оформить
   [done](../../changes/done/TASK-030-2-provider-as-of-dataset.md) с точными
   командами, счётчиками и ограничениями.

## Handoff

Developer → Product Owner → независимый Reviewer. Следующая TASK использует
только verified dataset и проверенные предматчевые признаки для OOS
прогнозов, не подменяя историю wide OddsStore.
