# TASK-030-3 — Общий контракт OOS прогнозов

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-030](../EPIC-030-financial-research-validation.md)
> **Требование:** [REQ-030](../../product/requirements/REQ-030-financial-research-validation.md) (`confirmed`)
> **Решение:** [ADR-032](../../architecture/adr/ADR-032-reproducible-financial-research-evaluation.md) (`accepted`)
> **Протокол:** [NHL protocol](../../research/epic-030-nhl-protocol.md)

## Результат и границы

На закреплённом dataset [TASK-030-2](TASK-030-2-provider-as-of-dataset.md)
создать проверенный общий список NHL событий с пригодной линией, исходом и
предматчевыми признаками, а также OOS вероятности baseline и logistic candidate
для каждого события закрытого теста. Список событий и причины исключений
фиксируются **до** расчёта финансового результата. Прогноз связывается с
`project_event_id`, dataset ID и market rules; позиция строки не служит ID.

Исход и training labels брать только из raw NHL после точной проверки identity,
статуса `finished` и полного `winner_withOT` settlement. Не читать широкую
матрицу `train_wide` как доказанные предматчевые признаки и не подставлять её
odds. До первого открытия исходов теста подтвердить fingerprint raw, `ir1`,
historical dataset, allowlist и конфигурацию. Значения результата теста не
используются для смены признаков, окна, threshold или модели.

## Критерии приёмки

1. Версия формата входа/выхода, проверка fingerprints и точное соответствие
   `project_event_id ↔ NHL source ID ↔ kickoff ↔ home/away` предшествуют fit.
   Дубликаты, reverse mapping, несовпадение команд или времени дают явную
   причину исключения либо ошибку; их нельзя молча присоединить по индексу.
2. Единственный feature allowlist — UTC weekday/hour и one-hot подтверждённых
   команд из [протокола](../../research/epic-030-nhl-protocol.md). Для
   pre-2023 train отдельные event UUID не требуются, но уникальные NHL source
   IDs и team codes разрешаются через закреплённый NHL seed с проверкой
   соответствия `ir1`. Словарь one-hot строится на доступном прошлом до
   `2024-09-24T00:00:00Z` включительно;
   неизвестная команда обрабатывается заранее заданным правилом. Target,
   score, `match_end`, odds и `f_*` не допускаются в признаки.
3. Baseline и candidate используют одинаковые доступные train rows. Перед
   каждым тестовым месяцем обе модели обновляются по матчам со статусом
   `finished` и kickoff не позже `month_start − 7 суток`; для каждого шага
   проверяется фактическая training mask, а не только граница kickoff внутри
   `WalkForwardRunner`. Development и подбор параметров происходят только до
   `2024-10-01`; тест `[2024-10-01, 2026-05-01)` используется один раз.
4. Прогноз содержит dataset/model/config ID, event UUID, исходы `home_win` и
   `away_win`, вероятности в `[0,1]` с суммой 1, training cutoff, месяц,
   hash признаков и основание OOS. Baseline и candidate покрывают **один и
   тот же** заранее закреплённый список, без дублей и пропусков. Ретроспективное
   время запуска отделено от моделируемого `decision_at`.
5. Повторный запуск на одинаковых входах даёт тот же список event IDs и
   вероятности в объявленной точности. Артефакты сохраняют fingerprints,
   конфигурацию, число исключений по причинам и не содержат full provider
   payload. Старый training/runner API сохраняет поведение. Engineering smoke
   использует только synthetic/development данные; исходы закрытого теста
   открываются при единственном итоговом research run после review.

## Red → green → refactor

1. Synthetic проверки identity/target, перестановки home/away, unknown team,
   дополнительного столбца и training row с `kickoff + 7 суток > cutoff`.
2. Минимальный адаптер к `WalkForwardRunner` для месячных OOS прогнозов с
   явной проверкой масок; совместимое расширение runner допустимо, если
   обычная маска пропускает недоступную label. Отдельный baseline на том же
   verified train set.
3. Проверки адресной области, development smoke и
   [done](../../changes/done/TASK-030-3-oos-prediction-contract.md) с точными
   командами, manifest, числом пригодных событий и ограничениями.

## Handoff

Developer → Product Owner → независимый Reviewer. Следующая TASK оценивает
закреплённые OOS прогнозы, ставки, неопределённость и financial gates без
изменения списка событий или политики по результату теста.
