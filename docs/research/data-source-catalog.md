# Data Source Catalog

Каноническая машинно-читаемая карточка источника хранится как
`<workspace>/data-sources/<source_id>.json` и валидируется `DataSourceRecord`. Карточка —
результат Data Researcher, а не заметка в чате: она должна позволить scientist и engineer
найти происхождение и допустимое применение каждого описанного поля.

## Уровень полноты

`catalog_completeness="partial"` сохраняет обратную совместимость со старой краткой
карточкой. Она пригодна только как указатель на источник и **не** доказывает его схему.

`catalog_completeness="complete"` — обязательный результат глубокой API-разведки. Такая
карточка не проходит validation без `api_endpoints` и `api_fields`; каждое поле обязано
ссылаться на существующий endpoint. Версия структуры задаётся `catalog_schema_version`.

## Карточка источника

| Поле | Назначение |
|---|---|
| `source`, `access_method`, `documentation` | Идентификация и законный способ доступа |
| `known_endpoints`, `entities`, `available_fields` | Короткий индекс для поиска и compatibility; не заменяет detailed contract |
| `historical_depth`, `update_frequency`, `temporal_availability`, `coverage` | Пригодность для честного исследования |
| `missingness`, `pagination`, `rate_limits`, `authentication`, `observed_access_restrictions` | Ограничения получения |
| `reliability`, `data_quality`, `known_problems`, `last_verified` | Проверяемость и качество снимка |
| `potential_leakage`, `potential_research_value` | Сводные риски и исследовательская ценность |

## Endpoint contract

Каждый `api_endpoints[]` содержит:

| Поле | Смысл |
|---|---|
| `endpoint_id`, `method`, `path`, `purpose` | Стабильная ссылка внутри карточки и назначение метода |
| `parameters[]` | Имя, location (`path`, `query`, `header`, `body`), required, тип, смысл и допустимые значения |
| `response_root`, `pagination` | Корень JSON и способ обхода страниц либо явное `Нет.` |
| `access_restrictions`, `evidence` | Законные условия доступа и проверяемый источник наблюдения |

`evidence` указывает только безопасное доказательство: официальный URL, дату и путь
read-only проверки или ссылку на сохранённое описание. В нём нет raw response, cookie,
секрета или инструкции обхода ограничений.

## Field-level data dictionary

Каждый `api_fields[]` — строка словаря данных, а не просто имя ключа.

| Поле | Смысл для scientist |
|---|---|
| `field_id`, `endpoint_id`, `entity`, `json_path` | Откуда извлекается значение и к какой сущности относится |
| `data_type`, `nullable`, `description` | Физический тип, допустимость пропуска и предметный смысл |
| `key_role` | `primary`, `foreign`, `natural` или `none` |
| `usage` | `feature`, `target`, `label`, `odds`, `metadata` или `unknown` |
| `temporal_availability` | `pre_event`, `pre_event_if_timestamp_checked`, `live`, `post_event` или `unknown` |
| `leakage_risk`, `evidence` | Условие безопасного применения и основание описания |

Поле с `post_event` не используется в предматчевой гипотезе как feature. Для
`pre_event_if_timestamp_checked` research-scientist обязан включить timestamp-проверку в
`DataRequirement`; наличие значения в ответе само по себе не является доказательством, что
оно было известно до события.

## Human-readable dictionary

Для каждого `complete` источника рядом с JSON-card создаётся Markdown data dictionary. В нём
те же `endpoint_id`/`field_id` группируются таблицами по методу и сущности, чтобы им можно
было пользоваться без чтения JSON. Markdown не является вторым независимым источником
истины: изменение начинается с validated card, а dictionary синхронизируется в той же TASK.

Data Researcher документирует только разрешённые публичные наблюдения. Cookies, credentials,
HAR, полные HTTP-ответы и способы обхода ограничений в каталог не попадают.
