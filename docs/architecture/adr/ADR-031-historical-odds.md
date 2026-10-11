# ADR-031 — Неизменяемые исторические наблюдения коэффициентов

> **Статус:** accepted
> **Дата:** 2026-10-10
> **Связанное требование:** [REQ-027](../../product/requirements/REQ-027-historical-odds.md) (`confirmed`)
> **Инициатива:** [EPIC-027](../../backlog/EPIC-027-historical-odds.md)
> **Первый срез:** [TASK-027-1](../../backlog/tasks/TASK-027-1-local-historical-odds.md)

Product Owner принял решение 2026-10-10: отдельный SQLite журнал, раздельная
временная семантика, pinned `ir1`, отсутствие общей service migration.
Реализация разделена на два последовательных проверяемых TASK.

## Контекст и критерии выбора

Подтверждён импорт существующего historical cache The Odds API для NHL/Pinnacle
`winner_withOT`, локальный запрос на момент T и фактическое покрытие. V3 OddsStore
дедуплицирует дату/команды; сервисная `odds_observations` хранит текущую проекцию.
`OddsApiClient._get` записывает JSON ответа без локального retrieval envelope.
Ни wide-строка, ни время изменения файла не доказывают прошлую доступность цены.

ADR необходим: выбираются долговечная идентичность observation, смысл временного
запроса, хранилище и отделение исходного факта от изменяемого решения registry.
Критерии — один локальный владелец, повторяемый импорт без API-запросов, проверка
без production БД, отсутствие новых сервисов и независимость от EPIC-028.

## Рассмотренные варианты

| Вариант | Простота и проверка | Эксплуатация, безопасность и обратимость |
| --- | --- | --- |
| Status quo: читать cache при каждом запросе, wide store оставить | Минимум записи, жизнеспособно для разового исследования. Повторяются parsing, сопоставление и аудит пропусков; нет устойчивого каталога observation IDs. | Нет нового хранилища; зависимость от размещения файлов, труднее отличить пропущенный файл от отсутствующей линии. Не выбран для повторяемого REQ. |
| Отдельный локальный SQLite журнал (выбран) | Транзакции и unique constraints для повторного импорта, один файл и unit/integration tests на временном каталоге. Нужен небольшой repository. | Нет daemon/credentials, отдельная схема не конфликтует с service migrations. Один writer, backup файла и исходного cache; перенос через сохранённые IDs. |
| Parquet/JSONL журнал с manifest | Удобный обмен и пакетный анализ; нужно самостоятельно обеспечить атомарный manifest, поиск дублей и согласование нескольких файлов. | Не требует сервиса, переносим; повышает стоимость обработки прерванного импорта и индекса. Пригоден как будущий экспорт. |
| Новые таблицы в service DB | Уже есть SQLAlchemy/Alembic, проще будущие связи с прогнозами. | Для локального среза связывает импорт с serving schema, общей миграцией EPIC-028 и production lifecycle. Отложен до запроса production-интеграции. |

## Решение

### Локальная граница и хранение

Новый модуль в `sports_forecast/data/providers/odds/` принимает явные `Path`
источника, отдельной SQLite БД и проверенного registry snapshot. Стандартный
`sqlite3`, как в локальном registry, не требует новой зависимости. Схема
инициализируется явно и имеет собственную версию; service Alembic не меняется.
Один файл ответа импортируется одной короткой транзакцией: source facts,
обнаруженные проблемы и отметка успешной обработки фиксируются вместе.
Повтор после сбоя безопасен. Foreign keys включены; соединения закрываются;
writer занят — bounded timeout и явная ошибка, без потери результата.

Минимальные логические сущности: observation header с атомарным вектором цен,
outcomes, provenance receipts исходных файлов и факты отсутствия/ошибки разбора.
Физическое разбиение таблиц выбирает Developer, сохраняя эти инварианты.
Append-only repository не предоставляет изменения/удаления наблюдений.
Отдельный процесс, scheduler, online fetch и автоматическая очистка не нужны.

### Контракт исходного наблюдения

Наблюдение описывает **один рынок одного события в одном snapshot**. В ответе
по outcome возвращается его цена и общий `observation_id`; обе цены вектора
принимаются и выбираются вместе, поэтому разные snapshots не смешиваются.

| Поля | Смысл |
| --- | --- |
| `schema_version`, `observation_id` | Версия нормализации и стабильный `ho1:<sha256>` нормализованного факта |
| `source`, `source_sport_key`, `source_event_id` | Namespace `the_odds_api`, `icehockey_nhl` и provider event ID |
| `source_home`, `source_away`, `commence_time` | Исходные обозначения участников и UTC kickoff для строгого resolver |
| `bookmaker`, `source_market`, `market_key`, `market_rules_version` | `pinnacle`, исходный ключ, `winner_withOT`, версия правил |
| `period`, `includes_overtime`, `includes_shootout`, `outcomes` | Полный матч, ОТ и буллиты включены, `home_win / away_win`, ничьей нет |
| `prices` | Полный вектор конечных decimal prices строго больше 1; каноническая десятичная запись для hash |
| `observed_at`, `observed_at_path` | UTC `timestamp` historical envelope; путь происхождения обязателен |
| `provider_updated_at`, `provider_updated_at_path` | Необязательный market/bookmaker `last_update`; не заменяет `observed_at` |
| `origin` | `provider_history`; не утверждает прежнюю доступность нашей системе |

Hash включает перечисленные исходные факты, правила, timestamps и цены;
не включает абсолютный путь файла, время импорта, registry snapshot и project ID.
Цены и исходы сортируются канонически; порядок JSON и исходов не создаёт дубль.
Новый snapshot создаёт новый ID даже при той же цене. Изменённый payload при
том же provider event/bookmaker/market/snapshot timestamp сохраняется отдельным
фактом и отмечает конфликт; «последний импорт победил» запрещён. Запрос этой
временной точки возвращает конфликт, пока нет отдельного решения; порядок
обхода файлов не выбирает победителя.

Receipt содержит hash исходного файла, безопасную относительную ссылку,
связанные observation IDs, `imported_at` и `retrieved_at` с evidence либо null.
Первый receipt не переписывается повторным импортом. Разные файлы могут ссылаться
на один observation. Полный внешний ответ не копируется в БД/тесты/логи;
исходный cache сохраняется владельцем, фикстуры синтетические и минимальные.
Не сохраняются request URL, query, API key или непрозрачное имя legacy-файла,
если оно содержит чувствительные параметры: достаточно digest и безопасного locator.

### Временная семантика

Historical envelope `timestamp` — время наблюдения snapshot провайдером.
Старый `last_update` в более позднем snapshot не даёт права выбирать этот
snapshot до его `timestamp`. Невалидный/отсутствующий envelope timestamp
создаёт диагностический факт, но не допускаемую историческую цену. Все сравнения
в UTC; timezone-naive вход отклоняется, точность timestamp сохраняется.

`retrieved_at` — только доказанное время получения системой конкретного ответа.
У существующего cache без такого evidence оно **null**. `mtime`, имя файла,
`fetched_at` wide store и `imported_at` не служат заменой. Будущий sidecar receipt
с временем transport acquisition можно поддержать отдельно; новый network path
не требуется. Несколько доказанных receipts не меняют observation; запрос может
показать самое раннее доказанное получение с reference на receipt.

Ответ явно содержит `selection_mode=provider_as_of`, `observed_at`, nullable
`retrieved_at`, `retrieval_status=known/unknown`, `imported_at`, provenance и
`late_retrieval=true/false/null` относительно T. Null означает неизвестность,
а не своевременное получение. Поздний импорт не доказывает позднее получение.
Provider-as-of допускает `retrieved_at > T` по решению владельца и никогда сам
по себе не утверждает `locally_known_at_T`.

Отдельный режим local-known сейчас не реализуется. Его будущая необходимая
проверка — доказанное `retrieved_at <= T`; неизвестные времена исключаются.
Для утверждения локально доступной **сопоставленной** цены потребуется также
доказать доступность выбранного registry mapping к T. Текущий pinned snapshot
делает retrospective mapping воспроизводимым, но не доказывает прошлое знание.

### Рынок и подтверждённое событие

Версионированный allowlist адаптера задаёт `(source, sport_key, bookmaker,
source_market)` и явные правила. Для подтверждённого NHL/Pinnacle `h2h`
отображение — `winner_withOT`; проектное имя `winner_withOT` является вторым
именем того же смысла в локальном контракте. Не выдумывать второй API alias:
неизвестные provider keys отклоняются. Два исхода должны точно соответствовать
home/away, один Pinnacle и один целевой market на событие; duplicate keys,
третий исход/draw, regulation-only и неизвестный рынок дают диагностику.
Бинарность сама по себе не подтверждает правило ОТ для другого турнира.

Source observation сохраняется независимо от наличия registry mapping.
Запрос закрепляет один проверенный полный `ir1` snapshot и использует
`RegistrySnapshotReader`/strict event resolver по исходному namespace, event ID,
участникам и kickoff. UUID проектного события берётся только при `resolved`;
не вводится новый fuzzy matcher или независимый master mapping.
Для списка source events применяется batch resolution с проверкой конкурирующих
source IDs, как в `resolve_many`; отдельные успешные resolve не обходят collision.

Результат содержит `project_event_id`, `registry_snapshot_id` и версию правил.
Привязка — вычисляемая проекция по закреплённому snapshot, а не перезапись
observation. Повторный запрос с новым snapshot после решения владельца может
разрешить прежний факт; старый snapshot сохраняет прежний результат. Если нужен
локальный numeric key адаптера `CanonicalEventRef`, он имеет только внутренний
scope и не выдаётся за service `canonical_events.id`.

### Запрос и покрытие

Запрос задаёт project event UUID, bookmaker, market/outcome, T и pinned `ir1`.
Выбирается последний полный валидный snapshot с `observed_at <= T` среди
подтверждённо связанных наблюдений. Конфликт в самой поздней подходящей точке
возвращается явно, без отката на более старую цену. Отсутствие данных не
подменяется current odds; возраст выбранного snapshot возвращается пользователю.
Запрос воспроизводит последнюю наблюдавшуюся цену, не обещает её исполнимость
или непрерывную доступность между snapshots.

Coverage получает явный universe ожидаемых событий из pinned registry на
интервале UTC kickoff `[from, to)`, market, T (либо явный T для каждого события)
и fingerprint набора импортированных файлов. Это позволяет учесть события,
которых вообще нет в cache. Считает события, не число outcomes/файлов.
Взаимоисключающие категории для каждого ожидаемого события:

- `mapping_error`: доступный source event имеет неоднозначную/конфликтную связь
  либо целевой market не подтверждён; цена не выдаётся.
- `no_line`: source event подтверждённо связан, его импортированные snapshots
  явно не содержат Pinnacle/целевого рынка и нет ни одного целевого наблюдения.
- `no_snapshot`: нет source evidence для события или есть линия, но нет
  подходящего валидного snapshot к T; subreason отличает эти случаи и invalid data.
- `covered`: запрос вернул допустимый snapshot; provenance/unknown retrieval
  считаются дополнительными измерениями, не доказательством local-known.

Непривязанные source events нельзя произвольно приписать отсутствующему expected
UUID: они идут в отдельный счётчик `unmapped_source_events` с причинами, и не
прибавляются к знаменателю ожидаемых событий. Известные candidate IDs можно
показать отдельно, не подтверждая связь. Поэтому отсутствие линии означает
отсутствие **в импортированных данных**, а не у букмекера вообще. Отчёт показывает
числитель, знаменатель, все категории, ошибки импорта, нулевое покрытие и
использованные параметры; порога приёмки нет.

### Граница с EPIC-028

EPIC-027 владеет `ho1` и выбором provider-as-of; EPIC-028 владеет prediction
revision и bundle metadata по ADR-030. Рынок согласован как `winner_withOT`,
исходы `home_win / away_win`, ОТ/буллиты явно включены. Первый срез не меняет
service models, migration head, prediction repository или revisions.
Будущая связь хранит отдельный факт `(revision_id, observation_id, ir1,
selection_mode, T)` и проверяет bridge UUID ↔ service event ID и market rules;
она не переписывает probability revision и не выводится из `odds_raw`.
Отсутствие odds не делает сохранённый прогноз невалидным. Добавление этой связи
потребует отдельной TASK и согласования migration head после обеих инициатив.

## Последствия

- Положительные: история и текущая линия независимы, raw facts переживают
  исправление mapping, импорт воспроизводим без network/API quota.
- Стоимость: дополнительный локальный файл, schema/repository, backup cache и
  registry snapshots; отчёт обязан честно показывать неполное сопоставление.
- Риски: SQLite сериализует writers; потеря исходного cache ограничивает повторный
  аудит; исторические provider corrections могут дать конфликт; перенос матча
  может потребовать решения registry. Наличие 4144 source events не гарантирует
  столько же confirmed mappings. Retrospective provider data не подтверждают
  реальную возможность сделать ставку или прошлую локальную доступность.
- Безопасность: только явные локальные пути, bounded parsing файлов, никаких
  секретов/full responses в логе; raw cache и текущие stores не переписываются.

## Проверка и пересмотр

[TASK-027-1](../../backlog/tasks/TASK-027-1-local-historical-odds.md) даёт
минимальный цикл import → pinned query на synthetic fixture и одном реальном
событии с двумя изменившимися снимками после подтверждения mapping.
[TASK-027-2](../../backlog/tasks/TASK-027-2-historical-odds-coverage.md) добавляет
coverage, диагностику отсутствий, полный реальный acceptance и регрессии старых
close/T−15/current odds. Каждый TASK проходит собственный red → green и review.
Совокупно требуются duplicate/reorder/retry, прерванная транзакция,
unknown retrieval, late retrieval, future envelope/old last_update, конфликт
одного timestamp, неизвестный рынок, отсутствие линии/снимка и смена registry.

После green Developer записывает фактический local evidence и done; независимый
Reviewer проверяет границы и временную семантику; после второго TASK — итоговый
acceptance и review инициативы перед PR/CI. ADR принят Product Owner.
Если подтвердить реальный mapping пока нельзя, synthetic успех не закрывает
реальный acceptance gate: Product Owner фиксирует конкретный блокер.

Пересмотреть хранение при измеренных lock timeouts, необходимости concurrent
writers или production query. Переход в PostgreSQL/экспорт сохраняет `ho1`,
исходные UTC facts и provenance; не требует изменения service ID в истории.
Откат — прекратить чтение отдельного журнала, сохранив данные; прежние API/бот
и wide store продолжают свой существующий путь. Deployment здесь не разрешён.

## Источники и неизвестное

- [The Odds API v4 historical response](https://the-odds-api.com/liveapi/guides/v4/#get-historical-odds):
  envelope timestamp описывает ближайший доступный snapshot не позже requested
  date. Проверено 2026-10-10; схема не доказывает local retrieval time.
- [SQLite: appropriate uses](https://www.sqlite.org/whentouse.html): один writer;
  локальный файл выбран для одного владельца. Проверено 2026-10-10.
- Код: `odds/client.py`, `store.py`, `backfill.py`, `snapshot_discovery.py`;
  tests `test_odds_client`, `test_odds_store`, `test_odds_backfill`, `test_event_identity`.
- [ADR-029](ADR-029-local-entity-registry-and-snapshots.md),
  [описание источника](../../cursor/source_data/the_odds_api.md).
- ADR-030 изучен в параллельном worktree EPIC-028; в этой ветке файл появится
  после интеграции. Прямую относительную ссылку добавить тогда.
- Неизвестны фактическое confirmed coverage, объём/время нового импорта и
  доля timestamp conflicts. Их измеряет реализация; новый платный API доступ
  для первого среза не предполагается и не проверяется.
