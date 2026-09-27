# The Odds API — NHL: назначение и ограничения

Официальная документация API: [The Odds API v4](https://the-odds-api.com/liveapi/guides/v4/#overview).

## Зачем подключаем

**Сбор букмекерских коэффициентов** (в первую очередь Pinnacle: линия открытия и закрытия, где доступно) для:

- **валидации и бенчмаркинга** моделей на отложенных выборках;
- сравнения качества прогнозов с «рынком» (например, vs closing line), расчёта метрик в духе calibration / ROI на исторических ставках — **вне** обучающего контура признаков.

Для этих целей **достаточно историчности порядка 2–3 сезонов** NHL на тестовых/валидационных данных: отдельно гонять полную историю с 2000-х под Odds API не требуется.

## Почему кэфы не идут в фичи (training)

У The Odds API **ограниченная историческая глубина** по сборам линий букмекеров: сервис начал накапливать такие данные относительно недавно. Из-за этого **нельзя надёжно покрыть тем же источником всё train-окно** модели (которое для NHL опирается на длинную историю из NHL Web API).

**Политика проекта:** колонки с кэфами из The Odds API **не подмешиваются в feature pipeline** для обучения и прод-инференса. Они хранятся в слое `source` / clean (после merge) для **офлайн-анализа, отчётов и проверки модели против рынка**, а не как входы в `features`.

Если позже появится источник с полной исторической глубиной по линиям — ввод odds-фич отдельно обсуждается и оформляется новой задачей.

## Конфигурация в репозитории

Гидра-конфиг провайдера: [`conf/bookmaker/the_odds_api.yaml`](../../../conf/bookmaker/the_odds_api.yaml) (рядом с [`conf/bookmaker/fonbet.yaml`](../../../conf/bookmaker/fonbet.yaml)). Загрузка: `load_bookmaker_config("the_odds_api")` — см. `sports_forecast/config/loaders.py`. У возвращаемого `DictConfig` поля лежат под ключом `bookmaker` (как у fonbet), например `cfg.bookmaker.api`, `cfg.bookmaker.sport_keys`, `cfg.bookmaker.output_columns`. Формат отличается от fonbet: нет `base_mapping` / `odds_raw` dict — задаются ключи спорта в API, букмекер `pinnacle`, целевые имена колонок после merge.

## Ключ и квота

Ключ API — только из переменных окружения / секретов (например `ODDS_API_KEY`), не в репозитории. Запросы к API экономить: кэш ответов, идемпотентный backfill, приоритет окна 2–3 сезонов для валидации.

## Будущие NHL линии для Telegram readiness

Data Cycle запрашивает будущий календарный диапазон одним запросом
`GET /v4/sports/icehockey_nhl/odds` с параметрами `bookmakers=pinnacle`,
`markets=h2h`, `oddsFormat=decimal`, `dateFormat=iso` и UTC параметрами
`commenceTimeFrom` / `commenceTimeTo`. Для этого прохода дисковый cache выключен,
transport retries и redirects отключены, предел клиента — один реальный GET на
цикл. Для одного события верхняя граница расширяется на одну секунду, чтобы
соблюсти контракт API `commenceTimeTo > commenceTimeFrom`; linker всё равно
сопоставляет kickoff точно. Фильтр букмекера выбирается вместо
`regions`; сам response и API key не сохраняются в журнале попытки.

Наблюдение `winner_withOT` создаётся только при точной связи API события с
canonical event по нормализованным участникам и UTC kickoff, при одном
`pinnacle/h2h` рынке, ровно двух исходах участников и валидных decimal prices.
Дубликат provider event для одного canonical identity, как и дубли Pinnacle
bookmaker или `h2h` market, отклоняется как ambiguous.
Provider `market.last_update` записывается в `observed_at`, если timestamp есть
на market. В стандартном v4 odds response официальная схема показывает
`last_update` на bookmaker, поэтому fallback на него допустим только для
единственного запрошенного рынка `h2h`. Точный путь timestamp сохраняется как
provenance; отсутствующее или невалидное время не заменяется локальным `now`.
Provider timestamp не может опережать retrieval более чем на пять минут;
readiness также не выдаёт `ready`, пока provider timestamp находится в будущем.
Момент получения ответа и provider event ID хранятся отдельно. Отсутствующая линия остаётся
`missing`, в том числе для событий на дальнем горизонте. Ошибка, включая
ограничение квоты, отдельно фиксируется как результат попытки Data Cycle.
Draw/третьи исходы и отсутствующий provider timestamp не дают readiness.

Этот путь не использует prediction rows и не меняет historical V3 OddsStore.
Футбольного production adapter он не добавляет.

## Historical reference T−15

Утренний коэффициент, использованный для текущего прогноза, и исторический
эталон для betting-метрик — разные наблюдения. Для каждого завершённого матча
reference backfill ищет линию в окне `T−60…T−0`, выбирая доступный snapshot,
ближайший к `T−15`. Значения после начала матча не используются.

Прежние `*_close` не перезаписываются. Новый самостоятельный проход записывает
только `*_t15`, `t15_provider_observed_at` и `t15_retrieved_at`:

```bash
uv run python -m sports_forecast.data.providers.odds.backfill \
  --from 2025-10-07 --to 2026-06-30 --t15-reference --store
```

Команда может выполнять до 61 historical-запроса на матч, если T−15 недоступен;
поэтому запускать её следует небольшими диапазонами и наблюдать квоту API.
Сначала рекомендуется прогон на одном дне и проверка Parquet store. Данные
остаются локальными до отдельного verified archive sync по TASK-007-8.
