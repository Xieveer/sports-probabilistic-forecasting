# Композиция feature pipeline (спорт → пресет → турнир)

Краткий контракт **R29**: как из пресета `features` (например `advanced`) и конфигов
`conf/sport/*.yaml` / `conf/tournament/*.yaml` получается итоговый узел `generators`
для `FeaturePipeline` и `materialize_features_config`.

---

## Слои (порядок применения)

1. **Пресет `features=*`** — каркас: `_common`, порядок и плотность **общих** блоков
   (`time`, `form`, `rolling`: `ewm_diff` / `ewm_total` / `count` с `context_source: library`).
   Пресет **не** должен навязывать всем спортам NHL pre-gen и `streak` (они задаются спортом).
2. **`conf/sport/<sport>.yaml`** (через merge в турнир: `defaults: - /sport@_here_: …`) —
   канонические **группы** optional-огенераторов в `feature_pipeline.groups`.
3. **`conf/tournament/<tournament>.yaml`** — только **диффы**: узел
   `feature_pipeline_overrides` (переключение групп, явное исключение ключей).

При конфликте **переключателей групп** выигрывает более поздний слой:
**спорт → турнирный override**.

---

## Группы генераторов

| Группа           | Ключи в `generators`                          | Смысл |
|-----------------|-------------------------------------------------|-------|
| `nhl_boxscore`  | `nhl_schedule`, `nhl_standings`, `nhl_roster` | Пре-генераторы wide (плотность, таблица, ростер NHL API) |
| `streak`        | `streak`                                        | Серии / win-rate (контракт FE R27, ориентир на хоккейные колонки) |
| *(в пресете)*   | `time`, `form`, `ewm_*`, `count`               | Время, форма, rolling library → не группы R29, всегда из пресета |

`rolling` не выключается через R29-группы: плотность и контексты задаются спортом
(`rolling_context_names`, `ewm_metrics`, …) и `materialize_features_config`.

---

## Операции merge (не только «добавить»)

- **Включить группу** (`groups.<name>: true`): подмешать фрагменты YAML из
  `conf/features/generators/{schedule,standings,roster,streak}/`.
- **Выключить группу** (`groups.<name>: false`): удалить соответствующие ключи из `generators`,
  даже если старый пресет их содержал.
- **`exclude_generators`**: список имён ключей (`streak`, `nhl_schedule`, …) для удаления
  после разрешения групп (туманный турнирный дифф без новой группы).
- **Замена «группы целиком»**: выключить группу и при необходимости добавить свои ключи
  через отдельный пресет features или будущее расширение; в R29 достаточно `false` + `exclude_generators`.

Реализация: `compose_feature_pipeline` в `sports_forecast/features/feature_pipeline_compose.py`
(вызывается в начале `materialize_features_config`).

---

## Смысл `features=advanced` vs спорт

- **`advanced`** задаёт **общий** каркас качества: стандартный rolling (`spans`,
  library contexts), `form`, `time`; описание в `conf/features/advanced.yaml`.
- **Хоккей-специфичные** блоки (NHL pre-gen, `streak`) живут в **`feature_pipeline.groups`**
  для `ice_hockey`, а не в глобальном default пресета для всех турниров.
- **`features=basic`** — тот же принцип: меньше rolling (minimal), опциональные группы
  всё равно с **спорта**.

---

## Opt-in `streak` для киберхоккея

По умолчанию у `cyberhockey` в `conf/sport/cyberhockey.yaml`: `streak: false`.
Включение без смены продакшен-дефолта: в турнире (или тестовой фикстуре):

```yaml
feature_pipeline_overrides:
  groups:
    streak: true
```

---

## Логирование

При композиции пишется уровень **INFO**: спорт, эффективные группы, факт наличия
tournament overrides и список активных ключей `generators` (после merge, до rolling expand).

---

## Связанные документы

- Добавление турнира: `docs/cursor/context/HOW_TO_ADD_NEW_TOURNAMENT.md`
- Контекст фичей: `docs/cursor/context/context_feature.md`
