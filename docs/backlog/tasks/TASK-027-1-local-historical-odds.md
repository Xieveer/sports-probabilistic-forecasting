# TASK-027-1 — Локальный импорт и запрос истории Pinnacle

> **Статус:** backlog
> **Владелец:** Developer
> **Эпик:** [EPIC-027](../EPIC-027-historical-odds.md)
> **Требование:** [REQ-027](../../product/requirements/REQ-027-historical-odds.md) (`confirmed`)
> **ADR:** [ADR-031](../../architecture/adr/ADR-031-historical-odds.md) (`proposed`)

## Результат и границы

Один локальный вертикальный срез: существующий cache The Odds API → отдельный
SQLite журнал → запрос NHL/Pinnacle `winner_withOT` по pinned registry и T →
отчёт покрытия. Реализовать после принятия ADR Product Owner. Scope включает
шесть подтверждённых критериев REQ; synthetic tests дополняет реальный пример.

Область Developer: новые локальные модули/CLI в
`sports_forecast/data/providers/odds/`, focused tests, описание источника и usage,
TASK/done. Не менять service DB/Alembic, prediction revisions, runtime acquisition,
старый OddsStore, online backfill, модель и API/бот. Использовать существующий
registry contract чтением; изменение его поведения вернуть Product Owner.

## Критерии приёмки

- [ ] Два snapshots сохраняют две цены и два ID; повтор файла/перестановка
  outcomes/другой путь не создают дубль. Сбой транзакции не оставляет частичный импорт.
- [ ] Between/after/before query выбирает правильный snapshot/отсутствие;
  old last_update в будущем envelope не допускает утечку. Несовпадающие факты
  одного provider timestamp дают конфликт, не зависят от порядка файлов.
- [ ] Legacy retrieval остаётся null; известное позднее retrieval явно отмечено,
  imported_at не подменяет retrieval. Provider-as-of не заявляет local-known.
- [ ] Source h2h и проектное winner_withOT имеют согласованные правила,
  home_win/away_win и ОТ/буллиты. Regulation/draw/unknown/дубликаты отвергаются.
- [ ] Pinned ir1 strict resolution исключает unresolved/ambiguous/conflict и
  конкурирующие source IDs. Новое решение registry разрешает старый факт без
  изменения observation ID; старый snapshot сохраняет прежний результат.
- [ ] Coverage использует явный expected universe и T, считает отдельно
  no_line/no_snapshot/mapping_error/covered, неприписанные source events,
  import failures и unknown retrieval; нулевое покрытие допустимо и честно.
- [ ] Минимальный реальный пример двух изменившихся Pinnacle snapshots прошёл
  confirmed mapping, запрос до/между/после и контрольное отсутствие линии.
  Evidence содержит IDs/digests/времена/счётчики, без полного provider response.
- [ ] Прежние close/T−15 и current odds тесты проходят; CLI работает без API key
  и сетевых обращений и не изменяет входной cache/старые stores.

## Red → green → refactor

1. Red: synthetic historical envelopes, временный SQLite и минимальный
   verified registry fixture; поведенческие tests по критериям выше.
2. Green: immutable facts/receipts, атомарный importer с diagnostics,
   pinned query и coverage через один domain/repository contract; локальный CLI.
3. Проверить повтор interrupted import и реальный локальный пример без копирования
   больших артефактов в Git. Refactor только внутри новых модулей при зелёных тестах.
4. Обновить usage/канонические статусы и создать
   `docs/changes/done/TASK-027-1-local-historical-odds.md` с точными командами,
   результатами red/green, IDs локального evidence и остаточными ограничениями.

## Проверка и handoff

Минимум: новые focused tests и затронутые существующие odds/client/store/backfill
и identity tests; lint изменённых Python. Полные gates выбирать по фактическому
риску, не заявлять непроведённые команды. Реальный acceptance не заменять mocks.

Developer → Product Owner → независимый Reviewer; finding запускает исправление.
После review — документация, финальные проверки, PR и terminal CI.
Production rollout не запрошен. Для продолжения достаточно этого TASK, REQ и ADR;
изменение временной семантики или общей схемы возвращается Architect через PO.
