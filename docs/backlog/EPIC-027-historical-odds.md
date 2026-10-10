# EPIC-027 — История букмекерских коэффициентов

> **Статус:** in_progress — ADR принят, подготовлены два последовательных TASK
> **Приоритет:** high
> **Владелец:** Product Owner
> **Требование:** [REQ-027](../product/requirements/REQ-027-historical-odds.md) (`confirmed`)
> **ADR:** [ADR-031](../architecture/adr/ADR-031-historical-odds.md) (`accepted`)

## Память Product Owner

- Инициатива: `EPIC-027`.
- Ветка инициативы: `initiative/epic-027-historical-odds`, отдельный worktree `.worktrees/epic-027-historical-odds`.
- Workflow / этап: `engineering / TASK-027-1 reviewed; TASK-027-2`.
- Исходная цель: воспроизводить реально наблюдавшиеся коэффициенты и смысл рынка на момент решения.
- Критерии и DoD: подтверждённые критерии 1–6 в [REQ-027](../product/requirements/REQ-027-historical-odds.md): импорт существующего кэша The Odds API, локальный point-in-time запрос, отчёт покрытия и сохранение текущей выдачи. TASK-027-1 закрывает импорт/query и критерии 1–4, TASK-027-2 — coverage, критерии 5–6 и итоговый реальный acceptance. Далее независимый review, PR и terminal CI.
- Релиз: production-развёртывание не запрошено.
- Выполнено: направление зафиксировано 2026-10-04. 2026-10-10 подтверждён REQ, принят ADR-031; локально проверены 1790 historical cache файлов, 4144 события Pinnacle h2h, 3767 событий с несколькими снимками и 3742 с изменением цен. [TASK-027-1](tasks/TASK-027-1-local-historical-odds.md) завершён на `a33f82f`: реальный импорт/query на подтверждённом CAR–BUF и ir1 прошли, 25 адресных тестов зелёные; finding по лимиту чтения исправлен, повторное независимое review без P0–P2.
- Решения: первый срез — импорт существующего кэша The Odds API для NHL/Pinnacle `winner_withOT`, локальный point-in-time запрос и отчёт покрытия без API/бота и без числового порога. Для ретроспективного бэктеста разрешены historical provider snapshots, полученные позднее, при явной пометке происхождения и раздельном хранении `observed_at`/`retrieved_at`; они не считаются локально известными к прошлому `T`. Принят отдельный SQLite журнал: immutable source observation `ho1`, receipts с nullable retrieval, pinned `ir1` при запросе. Historical envelope timestamp задаёт observed_at; provider last_update хранится отдельно. Общие service migrations не затрагиваются.
- Артефакты: [REQ-027](../product/requirements/REQ-027-historical-odds.md), [ADR-031](../architecture/adr/ADR-031-historical-odds.md), [TASK-027-1](tasks/TASK-027-1-local-historical-odds.md), [отчёт TASK-027-1](../changes/done/TASK-027-1-local-historical-odds.md), [TASK-027-2](tasks/TASK-027-2-historical-odds-coverage.md), [описание источника](../cursor/source_data/the_odds_api.md), [долгосрочный план](index.md#долгосрочные-инициативы-платформы).
- Предыдущая роль: Reviewer — повторная проверка TASK-027-1 на `a33f82f` без P0–P2.
- Следующая роль: Developer — TASK-027-2 coverage и полный локальный acceptance; затем независимый Reviewer.
- Открытые вопросы / блокер: Архитектурный gate закрыт решением Product Owner 2026-10-10. Legacy retrieved_at остаётся неизвестным; реальное confirmed coverage и timestamp conflicts измерить в TASK. EPIC-028 владеет revisions; будущую связь observation/revision согласовать отдельно, первый срез не меняет общую схему.
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
Следующий gate — [TASK-027-2](tasks/TASK-027-2-historical-odds-coverage.md)
(`backlog`): coverage, диагностика отсутствий и полный реальный
acceptance/regressions поверх проверенного импорта и pinned query TASK-027-1.
Production-подключение истории требует сначала
выполнить серверные gates registry. EPIC-027 обеспечивает вход для
[EPIC-030](EPIC-030-financial-research-validation.md) и
[EPIC-031](EPIC-031-real-bets-ledger.md).

## Риски и rollout

Старый wide OddsStore и текущий `odds_observations` сохраняются до проверки новой истории и обратной совместимости. Историческое отсутствие данных нельзя заменять текущей котировкой.
