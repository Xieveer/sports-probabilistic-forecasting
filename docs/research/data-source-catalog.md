# Data Source Catalog

Каноническая машинно-читаемая карточка источника хранится Research Mode v1 как
`<workspace>/data-sources/<source_id>.json` и валидируется `DataSourceRecord`. Документ
фиксирует схему, а не копирует данные конкретных провайдеров.

| Поле | Назначение |
|---|---|
| `source`, `access_method`, `documentation` | Идентификация и законный способ доступа |
| `known_endpoints`, `entities`, `available_fields` | Пространство доступной информации |
| `historical_depth`, `update_frequency`, `temporal_availability`, `coverage` | Пригодность для честного исследования |
| `missingness`, `pagination`, `rate_limits`, `authentication`, `observed_access_restrictions` | Ограничения получения |
| `reliability`, `data_quality`, `known_problems`, `last_verified` | Проверяемость и качество |
| `potential_leakage`, `potential_research_value` | Риски и исследовательская ценность |

Data Researcher документирует только разрешённые публичные наблюдения. Cookies, credentials,
HAR, полные HTTP-ответы и способы обхода ограничений в каталог не попадают.
