# EPIC-032 — Подготовка и выпуск v1.3.0

> **Статус:** in_progress — предпродовая проверка
> **Приоритет:** high
> **Владелец:** Product Owner

## Память Product Owner

- Инициатива: `EPIC-032`; ветка `initiative/epic-032-v1-3-0-release`, worktree `.worktrees/epic-032-v1-3-0-release`.
- Workflow / этап: release engineering → независимое review → CI → immutable release evidence → Operations rollout.
- Исходная цель: выпустить v1.3.0 на `ops-prod-01`, выявив исправимые проблемы до переключения production.
- Решение владельца: выпуск v1.3.0 запрошен 2026-10-11; это разрешение действует только после всех release gates. При блокирующей находке — `NO-GO`, исправление и повторная проверка до deployment.
- Состав: интегрированные EPIC-026–031; EPIC-026 сохраняет открытый серверный gate [TASK-026-5](tasks/TASK-026-5-registry-publication.md). Исследовательский STOP EPIC-030 не означает promotion модели. EPL/ENG1 из EPIC-029 не включать в регулярный production цикл автоматически.
- Критерии и DoD: приведены ниже; [release checklist](../../references/release-checklist.md), [Definition of Done](../../references/definition-of-done.md) и [handoff](../operations/production-handoff.md).
- Выполнено: ветка создана от `main` `1520b73`; EPIC-026 — `blocked`, EPIC-027–031 — `done`. Версия проекта и lock обновлены `uv version` до 1.3.0. `uv sync --offline --frozen --group dev` восстановил локальное окружение после первоначального DNS-сбоя. Полный pytest после исправления: 1624 passed, 9 skipped; отдельные PostgreSQL роли, race tests, managed activation и revision tests прошли на disposable PostgreSQL (43 passed). Синтетическая схема `0017` сохранена, восстановлена и успешно обновлена до `0025`; свежая production копия не использовалась. `make lint`, `make type-check`, `make docs` (155 предупреждений), `make ai-validate`, `make production-check`, `make pre-commit` прошли; rendered Compose со всеми профилями прошёл verifier. `make security` не завершён: недоступен PyPI для `pip-audit`.
- Предыдущая роль: Reviewer — повторное независимое review исправленного TASK-032-1 и release-документов не нашло открытых P0–P2; замечание P2 о порядке bootstrap/migration исправлено и проверено.
- Следующая роль: Product Owner — PR и terminal CI; Operations Agent — server preflight при доступном SSH, до deployment.
- Открытые вопросы: точный текущий production revision, свежий backup/restore, server credentials и sync/feedback EPIC-026, модельный wrapper `app_version=1.3.0`, полный production-подобный цикл и security audit. Первичный P1 об отдельных ролях sync/feedback исправлен локально в [TASK-032-1](tasks/TASK-032-1-registry-production-roles.md), серверное подтверждение остаётся открытым. Первый read-only осмотр VPS показал 14 ГБ свободного места; следующие SSH подключения завершились тайм-аутом. Все пункты требуют evidence до GO.
- Обновлено: 2026-10-11.

## Проверяемый результат

1. Версия `1.3.0` однозначно связана с exact commit, annotated tag, immutable image digests, model bundle и release evidence. В runtime, manifest, handoff и package version нет расхождений.
2. На изолированном контуре, близком к production, пройдены upgrade с восстановленной копии БД, миграции до head, проверка ролей и grants, API/бот, ручной NHL Data Cycle, Object Storage, registry publication/sync/feedback и сценарий rollback либо проверенный forward-fix. Production данные и секреты не попадают в артефакты.
3. Поведение EPIC-027/028/029/031 и прежний NHL путь проверены в применимых API, DB и Telegram сценариях; реальные ставки сохраняют ссылку на исходную версию прогноза и финансовые итоги. Неактивированные рынки, турниры и модели не включаются незаметно.
4. Полные применимые локальные gates, независимое review, terminal PR CI, tag pipeline, security scan, image provenance и `make production-check` успешны; блокирующие findings устранены и повторно проверены.
5. До переключения подтверждены свежий backup с изолированным restore и off-host копией, точный rollback target, совместимость данных, ограниченный rollout, health/smoke и критерии остановки. По итогам deployment проверен полезный результат в боте и успешный Data Cycle; закрыт серверный gate EPIC-026.

## Этапы

| Этап | Результат | Статус |
|---|---|---|
| Предпродовый аудит | Версия, diff, зависимости, миграции, конфигурация, стенд и реальные блокеры | in_progress; локальный TASK-032-1 done, server gate открыт |
| Кандидат | Исправления, тесты, документация, handoff `candidate`, независимое review | backlog |
| Артефакт | PR и terminal CI, exact tag, tag pipeline, immutable evidence | backlog |
| Rollout | Backup gate, deployment, health, Data Cycle и Telegram smoke; TASK-026-5 | backlog |

## Правило остановки

Отсутствие стенда, проверенного восстановления, серверных grants или credentials,
неуспешные миграции, красный gate, неясный rollback либо расхождение пользовательского
результата дают `NO-GO`. Исправление оформляется в этой инициативе и повторно проходит
затронутые проверки. Нельзя считать отсутствие обнаруженной проблемы доказательством
её отсутствия: в handoff фиксируются непроверенные области и остаточный риск.
