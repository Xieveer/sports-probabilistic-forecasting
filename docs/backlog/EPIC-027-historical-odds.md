# EPIC-027 — История букмекерских коэффициентов

> **Статус:** done — локальный результат и полное EPIC review; PR/terminal CI ожидаются
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-027](../product/requirements/REQ-027-historical-odds.md) (`confirmed`)
> **ADR:** [ADR-031](../architecture/adr/ADR-031-historical-odds.md) (`accepted`)

## Память Product Owner

- Инициатива: `EPIC-027`.
- Ветка инициативы: `initiative/epic-027-historical-odds`, отдельный worktree `.worktrees/epic-027-historical-odds`.
- Workflow / этап: `engineering / review завершён; PR и terminal CI ожидаются`.
- Исходная цель: воспроизводить реально наблюдавшиеся коэффициенты и смысл рынка на момент решения.
- Критерии и DoD: подтверждённые критерии 1–6 в [REQ-027](../product/requirements/REQ-027-historical-odds.md): импорт существующего кэша The Odds API, локальный point-in-time запрос, отчёт покрытия и сохранение текущей выдачи. TASK-027-1 закрывает импорт/query и критерии 1–4, TASK-027-2 — coverage, критерии 5–6 и итоговый реальный acceptance. Далее независимый review, PR и terminal CI.
- Релиз: production-развёртывание не запрошено.
- Выполнено: направление зафиксировано 2026-10-04. 2026-10-10 подтверждён REQ, принят ADR-031; локально проверены 1790 historical cache файлов, 4144 события Pinnacle h2h, 3767 событий с несколькими снимками и 3742 с изменением цен. [TASK-027-1](tasks/TASK-027-1-local-historical-odds.md) завершён на `a33f82f`: реальный импорт/query и 25 адресных тестов; повторное review без P0–P2. [TASK-027-2](tasks/TASK-027-2-historical-odds-coverage.md) завершён на `82c0e62`: реальный отчёт на pinned ir1 дал 2 ожидаемых события, 1 covered CAR–BUF и 1 no_line ANA–STL, повторный импорт без дублей; 104 регрессионных теста и повторное независимое review без P0–P2. Финальные `make lint` и `make test-unit` прошли: 1481 passed, 13 deselected.
- Решения: первый срез — импорт существующего кэша The Odds API для NHL/Pinnacle `winner_withOT`, локальный point-in-time запрос и отчёт покрытия без API/бота и без числового порога. Для ретроспективного бэктеста разрешены historical provider snapshots, полученные позднее, при явной пометке происхождения и раздельном хранении `observed_at`/`retrieved_at`; они не считаются локально известными к прошлому `T`. Принят отдельный SQLite журнал: immutable source observation `ho1`, receipts с nullable retrieval, pinned `ir1` при запросе. Historical envelope timestamp задаёт observed_at; provider last_update хранится отдельно. Общие service migrations не затрагиваются.
- Артефакты: [REQ-027](../product/requirements/REQ-027-historical-odds.md), [ADR-031](../architecture/adr/ADR-031-historical-odds.md), [TASK-027-1](tasks/TASK-027-1-local-historical-odds.md), [отчёт TASK-027-1](../changes/done/TASK-027-1-local-historical-odds.md), [TASK-027-2](tasks/TASK-027-2-historical-odds-coverage.md), [отчёт TASK-027-2](../changes/done/TASK-027-2-historical-odds-coverage.md), [описание источника](../cursor/source_data/the_odds_api.md), [долгосрочный план](index.md#долгосрочные-инициативы-платформы).
- Предыдущая роль: Reviewer — итоговая проверка TASK-027-2 на `82c0e62` без P0–P2, включая реальный offline coverage.
- Следующая роль: Product Owner — открыть PR и дождаться terminal CI; при красном результате вернуть исправление Developer и повторное review.
- Открытые вопросы / блокер: для локального среза нет. Legacy retrieved_at остаётся неизвестным по контракту; production registry gate EPIC-026 и связь observation/revision EPIC-028 остаются за будущими отдельными решениями.
- Research: не применяется.
- Обновлено: 2026-10-10.

## Цель и границы

Для первого рынка NHL `winner_withOT` и букмекера Pinnacle получить единый контракт `event / bookmaker / market / outcome / price / observed_at / retrieved_at` и историю наблюдений из существующего кэша The Odds API. Локально запрашивать историю на момент `T` и выводить фактическое покрытие. Сохранить текущую выдачу коэффициентов API/бота. Не обещать сравнение всех букмекеров или исполнимость лучшей цены без данных о доступности и лимитах.

## Проверяемый результат

1. Два последовательных снимка одного outcome сохраняются раздельно; ретроспективный запрос «какой снимок провайдера действовал к T» возвращает допустимый снимок с явным `retrieved_at`/статусом позднего импорта.
2. Два названия одного и того же рынка приводятся к одному смысловому ключу; рынок победителя в основное время и с ОТ остаётся разными ключами.
3. Неизвестный рынок и неоднозначное событие не получают автоматически подтверждённый mapping.
4. Отчёт о покрытии различает отсутствие линии, отсутствие исторического снимка и ошибку сопоставления.

## Зависимости и следующий gate

Инженерный контракт [EPIC-026](EPIC-026-entity-registry.md) уже слит в `main`;
его отложенный серверный release gate не блокирует локальную разработку.
[ADR-031](../architecture/adr/ADR-031-historical-odds.md) принят.
Оба TASK и полное EPIC review завершены. Следующий gate — PR и terminal CI.
Production-подключение истории требует сначала
выполнить серверные gates registry. EPIC-027 обеспечивает вход для
[EPIC-030](EPIC-030-financial-research-validation.md) и
[EPIC-031](EPIC-031-real-bets-ledger.md).

## Риски и rollout

Старый wide OddsStore и текущий `odds_observations` сохраняются до проверки новой истории и обратной совместимости. Историческое отсутствие данных нельзя заменять текущей котировкой.

## Полное EPIC review

2026-10-10: независимый Reviewer проверил полный diff `main...82c0e62` и
подготовленные Product Owner изменения статусов. P0–P2 findings нет. Критерии
REQ-027 1–6 покрыты TASK-027-1/2: pinned `ir1` и неизменяемый `ho1` дают
provider-as-of запрос; локальный реальный контроль с шестью файлами дал
`expected=2`, `covered=1` (CAR–BUF), `no_line=1` (ANA–STL, `no_pinnacle`),
`no_snapshot=0`, `mapping_error=0`. Fingerprint набора —
`sha256:20e0ff034f6a5c095d8910df1979acce11bada3ae8202534d70f88743956a962`;
подробные ID, времена, повторный импорт и команды находятся в
[отчёте TASK-027-2](../changes/done/TASK-027-2-historical-odds-coverage.md).
Проверены разделение `observed_at`/nullable `retrieved_at`, диагностика
непривязанных source IDs, отсутствие сетевого вызова в локальном CLI,
неизменность старого API/бота и отсутствие cache/SQLite/snapshot в Git.
Адресно повторены 104 regression tests, Ruff check/format и реальный coverage
CLI; финальные `make lint` и `make test-unit` выполнены Product Owner
(1481 passed, 13 deselected). Остаточный риск: legacy retrieval неизвестен;
production-подключение и terminal CI остаются отдельными gates. Проверенный
content commit: `82c0e62`.
