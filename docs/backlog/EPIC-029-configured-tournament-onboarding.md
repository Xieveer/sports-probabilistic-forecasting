# EPIC-029 — Подключение типового турнира конфигурацией

> **Статус:** done — кандидат `ENG1` принят и PR #67 слит после зелёного CI
> **Приоритет:** medium
> **Владелец:** Product Owner
> **Требование:** [REQ-029](../product/requirements/REQ-029-premier-league-candidate.md), [REQ-003](../product/requirements/REQ-003-scalable-multisport-platform.md)
> **ADR:** [ADR-030](../architecture/adr/ADR-030-local-candidate-cycle.md), [ADR-003](../architecture/adr/ADR-003-configured-multisport-portfolio.md)

## Память Product Owner

- Инициатива: `EPIC-029`.
- Ветка инициативы: `initiative/epic-029-configured-tournament-onboarding`; отдельный worktree `.worktrees/epic-029-configured-tournament-onboarding`.
- Workflow / этап: `engineering / complete`; [TASK-029-1](tasks/TASK-029-1-premier-league-candidate.md) завершена, независимый review пройден, [PR #67](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/67) слит в `main` 2026-10-10 после зелёных CI/security checks на окончательном HEAD `dcb6d10`.
- Исходная цель: проверить на реальном вертикальном примере принцип «новый турнир поддерживаемого спорта — данные и конфигурация».
- Критерии и DoD: пользователь подтвердил [REQ-029](../product/requirements/REQ-029-premier-league-candidate.md): `ENG1` из локального CSV → отчёт кандидата, без регулярной выдачи. Тесты, независимый review, PR и зелёный CI обязательны для завершения.
- Релиз: production-развёртывание не запрошено.
- Выполнено: подготовительный review `290c4ce` без P0–P2; сетевой GET upcoming ранее завершился таймаутом. 2026-10-10 локальный кандидатный цикл обработал 4 138 матчей `ENG1`, обучил модель и создал [отчёт кандидата](../changes/candidates/premier_league-winner-225af497fb37.json). Raw/interim/processed validation и 128 целевых тестов прошли; полный suite остановлен на зависшем integration-тесте, подробности в [done](../changes/done/TASK-029-1-premier-league-candidate.md). На окончательном HEAD PR #67 `dcb6d10` прошли CI `lint-test (3.12)` и две security-проверки; merge commit `c8d5244`.
- Решения: первый кандидат — Premier League (`ENG1`, Smart Tables `competition_id=13`); локальный файловый путь из каталога отделён от регулярных DVC/Airflow запусков по [ADR-030](../architecture/adr/ADR-030-local-candidate-cycle.md). Отчёт не меняет production pointer.
- Evidence: [каталог соревнований](../cursor/source_data/smart-tables/competition_catalog.json), [source-контракт футбола](../cursor/source_data/football.md), [разведка JSON API Smart Tables](../cursor/source_data/smart_tables.md), `conf/source/football_top_leagues.yaml`, `data/source/football_top_leagues/source.csv`. Локальный CSV на 2026-10-10 содержит 4 138 завершённых матчей `ENG1` (2015-09-13—2026-09-06), у всех есть тройка `odd_home`/`odd_draw`/`odd_away`, у 4 121 заполнены голы, угловые и удары в створ обеих команд. Для `SPA1`: 4 185 завершённых матчей (2015-08-21—2026-09-11), тройка odds у всех, указанные поля статистики у 4 174. Это проверка структуры и непустоты локального файла, не оценка временной корректности odds или готовности модели.
- Источник: существующий неофициальный JSON backend Smart Tables через HTTP API; WebSocket-контракт не подтверждён. Документированная альтернатива — [football-data.org](https://www.football-data.org/coverage), но его [API требует токен](https://www.football-data.org/documentation/quickstart) и отдельную проверку схемы/покрытия. Аккаунт, прокси, разбор HTML и права на регулярное использование источника — решения Product Owner; секреты не сохранять.
- Артефакты: [TASK-029-1](tasks/TASK-029-1-premier-league-candidate.md), [REQ-029](../product/requirements/REQ-029-premier-league-candidate.md), [ADR-030](../architecture/adr/ADR-030-local-candidate-cycle.md), [отчёт кандидата](../changes/candidates/premier_league-winner-225af497fb37.json).
- Предыдущая роль: Reviewer — после исправления двух P2 повторное review без P0–P2, 75 независимых целевых тестов зелёные; проверенный коммит `c189f5baed382b6c6dd66b50225a1539a2c44b8c`.
- Следующая роль: Product Owner — только при отдельном решении о регулярном refresh или публикации.
- Открытые вопросы / блокер: для candidate-среза блокера нет. Будущий регулярный refresh и публикация заблокированы до отдельного решения владельца и не входят в REQ-029; публичный контракт/production-лицензия Smart Tables, время и букмекер исторических odds неизвестны.
- Research: не применяется.
- Обновлено: 2026-10-10.

## Цель и границы

Один новый турнир уже поддерживаемого спорта проходит загрузку совместимого источника, подготовку данных, обучение и отчёт кандидата. После отдельного решения о публикации он доступен через расписание и прогнозы. Новый вид спорта, новый provider или фактический выпуск production-версии сюда не входят.

## Проверяемый результат

1. Для выбранного совместимого турнира путь от входных данных до отчёта кандидата выполняется без изменения Python-кода платформы.
2. Состав запуска и отображение турнира выводятся из проверяемого каталога, без ручного добавления slug в несколько независимых списков.
3. Если данные или модель не готовы, система показывает проверяемую причину и не публикует пустой успех.
4. NHL продолжает проходить существующие контрактные проверки.

## Зависимости и следующий gate

Зависимости [EPIC-026](EPIC-026-entity-registry.md) и [EPIC-028](EPIC-028-production-model-contract.md) слиты в `main`. Пользователь подтвердил ограниченный candidate-срез в [REQ-029](../product/requirements/REQ-029-premier-league-candidate.md); [PR #67](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/67) прошёл terminal CI и слит. Следующий product gate нужен только для отдельного решения о регулярной выдаче.

## Риски и rollout

Не включать новый турнир в production автоматически по факту успешного обучения или CI. Ручное решение владельца о регулярной выдаче сохраняется.
