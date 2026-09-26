# TASK-025-6 — Будущие котировки от календаря NHL

> **Статус:** done — независимое повторное review пройдено
> **Владелец:** Developer
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат и границы

Стадия data/odds получает доступные будущие NHL линии из The Odds API по
canonical calendar events, не от существующих прогнозов. Сохраняет проверенное
наблюдение и отдельный результат попытки; отсутствие линии у источника не
означает отсутствие матча. Футбольный production adapter не включается.

## Критерии приёмки

- [x] Один ограниченный batch запрос на турнир и цикл, с контролем временного
  окна, quota headers и бюджета; нет запроса на каждый матч. Ошибка/истощение
  квоты сохраняется как результат стадии/попытки без ложного `ready`; future
  запрос отключает transport retries и redirects, cap ограничивает один GET,
  а окно всегда имеет `To > From`, включая batch с одним событием.
- [x] Для требуемого `winner_withOT` принимается только market с ровно двумя
  исходами `{home, away}` и валидными decimal prices. Если есть Draw или иные
  исходы, рынок не считается подтверждённым. Конфигурационная подпись рынка
  сама по себе не доказывает семантику линии.
- [x] Связь odds с canonical event однозначна по нормализованным участникам и
  точному UTC kickoff. Двойник, неопределённое время или перенос не допускают
  повторного использования прежнего наблюдения для нового события; повторный
  provider event, дубли Pinnacle или h2h market отклоняются как ambiguous.
- [x] Provider observed_at берётся из `market.last_update`, если поле присутствует;
  иначе — из `bookmaker.last_update` только при запрошенном единственном `h2h`
  рынке. Поле-источник сохраняется; отсутствующий/невалидный timestamp не
  заменяется локальным `now`; timestamp не может опережать retrieval более чем
  на 5 минут, а future timestamp не даёт readiness до наступления этого времени.
  Получение ответа отдельно как retrieved_at.
  Повторная попытка идемпотентна.
- [x] Calendar-only событие с подтверждённой двухисходной линией получает odds
  readiness без Prediction row; событие без линии остаётся `missing`/`pending`.
  Далёкие даты, для которых источник ещё не публикует odds, не считаются сбоем.
- [x] Failed acquisition сохраняет attempt отдельно от последнего успеха и
  переводит odds readiness в `failed` только для eligible событий, если
  последняя применимая попытка неуспешна. Успешный batch без линии оставляет
  `missing`; старое наблюдение не удаляется и не превращается в `ready`.
- [x] Результат подключён к Data Cycle и его summary/истории; fault injection,
  трёхисходная линия, ambiguity, stale, quota и перенос покрыты тестами.

## Источники и техническая граница

- [Официальный The Odds API v4](https://the-odds-api.com/liveapi/guides/v4/)
  и [NHL odds market semantics](https://the-odds-api.com/sports/nhl-odds.html).
  Стандартный v4 odds response показывает `last_update` на bookmaker; market
  endpoint отдельно показывает timestamps для market keys, но не сами prices.
  Поэтому batch без дополнительных market-запросов использует bookmaker время
  только для единственного запрошенного `h2h`, сохраняя точный путь поля.
- Текущий historical refresh ограничен `need_to=today`, а live poll получает
  только Prediction rows. Оба пути не выполняют этот контракт. Их нельзя
  считать доказательством будущего coverage.
- Существующий `OddsStore` V3 может потерять Draw и подставить локальное время
  вместо provider timestamp. До исправления legacy bridge в TASK-025-2 такие
  строки не должны давать `winner_withOT ready`.

## План и проверка

1. Red: двух- и трёхисходные payloads, calendar-only, ambiguity, перенос,
   отсутствие provider timestamp, quota/error и повторный запуск.
2. Green: строгий batch adapter, checked linker, observation/attempt и
   подключение к odds stage Data Cycle.
3. Refactor: единый контракт рынка и документация политики частоты/квоты.

Целевые unit/integration tests с fake provider и fixed clock, без production
ключа/запросов; регрессия существующих odds путей и lint.

## Handoff и отчёт

- Отчёт выполнения: [TASK-025-6](../../changes/done/TASK-025-6-future-odds.md).
- Review: три findings (P1/P2/P2) исправлены red→green; повторный независимый
  Reviewer не нашёл блокирующих findings и выполнил 51 целевой тест, настроенный
  mypy hook и `git diff --check`.
- Commit/push: ожидается после review.
