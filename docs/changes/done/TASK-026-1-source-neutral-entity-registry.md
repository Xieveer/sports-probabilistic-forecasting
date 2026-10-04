# TASK-026-1 — Результат локального реестра идентичности

> **Статус:** выполнено, независимое review пройдено
> **Требование:** [REQ-026](../../product/requirements/REQ-026-entity-registry.md)
> **Решение:** [ADR-027](../../architecture/adr/ADR-027-local-entity-registry-and-snapshots.md)
> **Задача:** [TASK-026-1](../../backlog/tasks/TASK-026-1-source-neutral-entity-registry.md)

## Результат

Добавлен локальный `sports_forecast.identity` поверх отдельного SQLite-файла.
Создание схемы выполняется только явным `EntityRegistry.initialize()`; обычное
чтение не создаёт файл и таблицы. Проектные сущности получают UUID, имя можно
изменить без смены ID с записью прежнего и нового имени, автора и основания в
entity audit. Решения владельца защищены expected revision и сохраняют
прежнюю revision для аудита. Внешние обозначения хранят источник, тип, обязательный
scope, исходное и нормализованное значение, период и состояние.

Resolver работает только по точному нормализованному ключу источника и scope.
Он возвращает `resolved`, `unresolved`, `ambiguous` или `conflict`; сходство
строк не связывает сущности. Обозначения можно принять, отклонить, отложить и
явно разрешить конфликт. Решения владельца сохраняются с actor, действием,
основанием, прежним состоянием и временем. Для игроков добавлена отдельная
таблица временных полуоткрытых связей с командами и проверкой пересечения.

Отдельный `identity.nhl_seed` импортирует доверенный
`conf/bookmaker/team_name_registry/nhl.yaml` одной write-транзакцией. Стабильный
seed ID не зависит от содержимого файла; SHA-256 хранится как provenance версии
источника. NHL team UUID привязан к стабильному `nhl_api` source ID и переживает
переименование canonical name в YAML. Перед созданием сущности импорт ищет
существующие NHL source IDs, поэтому добавление alias сохраняет UUID. Если
известные IDs одной canonical команды связаны с разными project ID, импорт
останавливается с ошибкой для ручного решения. Импорт создаёт canonical team
entities и designation для NHL API и The Odds API. Изменение файла добавляет
новые обозначения, но не изменяет существующие строки и принятые решения.
Синтетический турнир использует тот же общий registry API.

Проверки и изменения designation выполняются внутри SQLite транзакции с
`BEGIN IMMEDIATE`; connection всегда закрывается. Состояние конфликта и
дедупликация учитывают полуоткрытые временные интервалы. Конфликт хранится
отдельным overlay на интервале пересечения: исходные confirmed designation
сохраняют заданные state и entity ID, а open overlay блокирует разрешение только
на периоде пересечения. В частности, confirmed designation с началом внутри
overlap становится разрешимой после конца overlap; pending designation остаётся
pending и за его границами не даёт подтверждённого результата. Owner resolve
выбирает сущность только для этого
интервала и аудирует затронутых peers. Reject переводит связанный overlay в
`dismissed`, defer оставляет конфликт открытым; решение по одному из нескольких
кандидатов сохраняет нерешённые overlays. `conflict_period` позволяет выбрать
часть overlay, оставляя невыбранные временные остатки открытыми. Dismissed
overlays игнорируются resolver-ом как с датой, так и без неё. Timestamp входы
должны иметь timezone и сохраняются канонически в UTC. Если владелец отклоняет
designation, участвовавший в уже resolved overlay, overlay помечается
`dismissed`, ранее выбранный ID сохраняется для истории, а resolver возвращается
к оставшимся confirmed base. В журнале остаются исходное resolve и новое reject.
Схема обновлена до v5 с миграциями из v3 и v4.

## Red → green → refactor

- Red: первоначальный пакет тестов остановился при collection на отсутствующем
  `sports_forecast.identity`. В цикле findings collection повторно остановилась
  на отсутствующем `sports_forecast.identity.nhl_seed`. После появления importer
  тест конфликта потребовал явного `state="confirmed"` в fixture: новый
  безопасный default для недоверенного designation — `pending`.
- Green: regression tests доказывают стабильность seed ID и owner решения после
  изменения YAML, rollback частично выполненного seed, state/interval-aware
  дедупликацию, аудит superseded peers, проверку конкурирующих привязок, фильтр
  конфликтов по event timestamp, canonical UTC и отказ от auto-confirm.
- Refactor: reviewer цикл добавил revision optimistic locking, атомарные
  `BEGIN IMMEDIATE` writer transactions с гарантированным закрытием, отдельный
  seed importer и schema upgrade v2→v3.

## Проверки

- Red после двух P1: `uv run pytest tests/test_entity_registry.py -q` — два
  новых behavior test упали: исходное confirmed designation теряло доступность
  до интервала нового конфликта; переименование canonical name меняло UUID.
- Red после следующего review: три regression test упали на глобальном изменении
  base entity ID, незакрытом overlay после reject и смене seed identity при
  добавлении нового lexicographically меньшего NHL source ID.
- Red для частичного решения: regression упал на неподдерживаемом `conflict_period`
  до реализации выбора подинтервала.
- Red последнего review: три regressions выявили потерю state `confirmed`/`pending`
  на пересекающемся designation и `ambiguous` после dismiss unbounded overlay.
- Red исправления owner-решения: bounded и unbounded regressions показали, что
  последующий reject не инвалидацировал уже resolved выбор сущности.
- `uv run ruff check --fix --unsafe-fixes sports_forecast/identity tests/test_entity_registry.py` —
  7 автоматических lint/style исправлений.
- `uv run ruff format sports_forecast/identity tests/test_entity_registry.py` —
  4 файла без дополнительных изменений после format.
- `uv run ruff check sports_forecast/identity tests/test_entity_registry.py` —
  пройдено.
- `uv run pre-commit run mypy --all-files` — пройдено.
- `git diff --check` — пройдено.
- `uv run ruff format sports_forecast/identity tests/test_entity_registry.py` —
  3 files reformatted.
- `uv run ruff format sports_forecast/identity tests/test_entity_registry.py` —
  2 files reformatted after v5 fixes.
- `uv run ruff format sports_forecast/identity tests/test_entity_registry.py` —
  1 file reformatted after correction audit changes.
- `uv run pytest tests/test_entity_registry.py tests/test_team_name_registry.py tests/test_live_nhl_pinnacle.py tests/test_calendar_api.py -q` —
  51 passed, 3 warnings.
- `uv run ruff check sports_forecast/identity tests/test_entity_registry.py` —
  пройдено.
- `git diff --check` — пройдено.

В identity regression-набор входят 30 тестов; общий запускаемый набор содержит
также 21 тест NHL registry, live odds и calendar API. Новые проверки подтверждают
rollback seed, schema v2→v5 upgrade, ожидаемую revision, аудит resolved и
dismissed overlays, сохранение base за пределами conflict interval, reject и
defer с несколькими кандидатами, частичное решение с открытым остатком,
разрешение confirmed base после overlap, pending state в любом порядке загрузки,
соседние интервалы, no-date resolution после dismiss, correction resolved choices
при reject для bounded и unbounded интервалов с сохранением истории, стабильность UUID после
переименования canonical name и добавления NHL source ID, а также UTC сравнения
с различными offset.

## Границы и риски

Независимый Reviewer проверил полный diff, REQ/ADR/EPIC/TASK и повторно выполнил
целевой pytest (**51 passed, 3 warnings**), Ruff и `git diff --check`.
Блокирующих P0–P2 замечаний нет.

Текущий NHL matcher, календарный ingest, API и server DB не переключались.
Очередь кандидатов и веб-интерфейс, snapshot export/publication, серверная
проекция и обучение с закреплённой версией остаются последующими TASK эпика.
SQLite schema version 5 имеет upgrade migration с версии 2 через v3 и v4. Downgrade не
предусмотрен. Resolver и SQLite тесты не включают измерение конкурентной writer
нагрузки или публикацию snapshot. Database access остаётся sqlite3 за локальным
repository contract; Architect согласовал уточнение этого решения в ADR-027.
