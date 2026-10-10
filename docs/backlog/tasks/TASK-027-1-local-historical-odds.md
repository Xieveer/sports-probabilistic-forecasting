# TASK-027-1 — Локальный импорт и запрос истории Pinnacle

> **Статус:** done
> **Владелец:** Developer
> **Эпик:** [EPIC-027](../EPIC-027-historical-odds.md)
> **Требование:** [REQ-027](../../product/requirements/REQ-027-historical-odds.md) (`confirmed`)
> **ADR:** [ADR-031](../../architecture/adr/ADR-031-historical-odds.md) (`accepted`)

## Результат и границы

Один локальный вертикальный срез: существующий cache The Odds API → отдельный
SQLite журнал → запрос NHL/Pinnacle `winner_withOT` по pinned registry и T.
ADR принят Product Owner 2026-10-10. Срез закрывает критерии 1–4 REQ на synthetic
fixture и одном реальном событии. Покрытие и итоговая проверка критериев 5–6 —
[TASK-027-2](TASK-027-2-historical-odds-coverage.md).

Область Developer: новые локальные модули/CLI в
`sports_forecast/data/providers/odds/`, focused tests, описание источника и usage,
TASK/done. Не менять service DB/Alembic, prediction revisions, runtime acquisition,
старый OddsStore, online backfill, модель и API/бот. Использовать существующий
registry contract чтением; изменение его поведения вернуть Product Owner.

## Критерии приёмки

- [x] Два snapshots сохраняют две цены и два ID; повтор файла/перестановка
  outcomes/другой путь не создают дубль. Сбой транзакции не оставляет частичный импорт.
- [x] Between/after/before query выбирает правильный snapshot/отсутствие;
  old last_update в будущем envelope не допускает утечку. Несовпадающие факты
  одного provider timestamp дают конфликт, не зависят от порядка файлов.
- [x] Legacy retrieval остаётся null; известное позднее retrieval явно отмечено,
  imported_at не подменяет retrieval. Provider-as-of не заявляет local-known.
- [x] Source h2h и проектное winner_withOT имеют согласованные правила,
  home_win/away_win и ОТ/буллиты. Regulation/draw/unknown/дубликаты отвергаются.
- [x] Pinned ir1 strict resolution исключает unresolved/ambiguous/conflict и
  конкурирующие source IDs. Новое решение registry разрешает старый факт без
  изменения observation ID; старый snapshot сохраняет прежний результат.
- [x] Минимальный реальный пример двух изменившихся Pinnacle snapshots прошёл
  confirmed mapping и запрос до/между/после для одного события.
  Evidence содержит IDs/digests/времена/счётчики, без полного provider response.
- [x] Локальный import/query entrypoint работает без API key и сетевых обращений
  и не изменяет входной cache/старые stores. Вход читается с лимитом 32 MiB + 1:
  размер проверяется через открытый дескриптор, а рост файла после проверки
  приводит к отказу. Отчёт покрытия пока не требуется.

## Red → green → refactor

1. Red: synthetic historical envelopes, временный SQLite и минимальный
   verified registry fixture; поведенческие tests по критериям выше.
2. Green: immutable facts/receipts, атомарный importer и pinned query через
   один domain/repository contract; минимальный локальный entrypoint.
   Сохранить исходные факты отсутствия рынка и коды ошибок, необходимые будущему
   coverage; агрегацию, expected universe и report CLI выполняет TASK-027-2.
3. Проверить повтор interrupted import и реальный локальный пример без копирования
   больших артефактов в Git. Refactor только внутри новых модулей при зелёных тестах.
4. Обновить usage/канонические статусы и создать
   `docs/changes/done/TASK-027-1-local-historical-odds.md` с точными командами,
   результатами red/green, IDs локального evidence и остаточными ограничениями.
5. Reviewer P2 по TOCTOU устранён отдельным red→green тестом роста файла после
   проверки размера: проверяется `fstat` открытого дескриптора и фактический
   ограниченный `read(MAX + 1)`.

## Evidence

Подтверждённый владельцем mapping: NHL API game `2023020180` ↔ The Odds API
event `b42367c52f8c596d01199dd31258cc62`, CAR–BUF, kickoff
`2023-11-08T00:00:00Z`. Проверенный локальный snapshot:
`ir1:ef9cc3818aeb73dcbe68dbebd1bd912ea30b68a30ea898167676f4cd8dcce210`.
Evidence bundle находится вне репозитория в
`/tmp/sports-forecast-epic-027-evidence-final2`; source cache hashes, observation
IDs и результаты запросов перечислены в отчёте done. Raw ответы и SQLite в Git
не добавлялись.

## Проверка и handoff

Минимум: новые focused tests, применимые identity tests и lint изменённых Python.
Регрессии запускать по фактическому diff; итоговую совместимость close/T−15/current
odds подтверждает TASK-027-2. Реальный пример одного события не заменять mocks.

Developer → Product Owner → независимый Reviewer; finding запускает исправление.
После review — актуальная документация и переход к зависимой TASK-027-2.
PR и terminal CI инициативы следуют после итогового acceptance/review.
Production rollout не запрошен. Для продолжения достаточно этого TASK, REQ и ADR;
изменение временной семантики или общей схемы возвращается Architect через PO.
