# EPIC-032 — Подготовка и выпуск v1.3.1

> **Статус:** in_progress — предпродовая проверка
> **Приоритет:** high
> **Владелец:** Product Owner

## Память Product Owner

- Инициатива: `EPIC-032`; ветка `initiative/epic-032-v1-3-0-release`, worktree `.worktrees/epic-032-v1-3-0-release`.
- Workflow / этап: release engineering → независимое review → CI → immutable release evidence → Operations rollout.
- Исходная цель: выпустить v1.3.0 на `ops-prod-01`, выявив исправимые проблемы до переключения production.
- Решение владельца: выпуск v1.3.0 запрошен 2026-10-11; после неудачного тегового gate владелец утвердил v1.3.1. Разрешение на ограниченный rollout действует только после всех release gates. При блокирующей находке — `NO-GO`, исправление и повторная проверка до deployment.
- Состав: интегрированные EPIC-026–031; EPIC-026 сохраняет открытый серверный gate [TASK-026-5](tasks/TASK-026-5-registry-publication.md). Исследовательский STOP EPIC-030 не означает promotion модели. EPL/ENG1 из EPIC-029 не включать в регулярный production цикл автоматически.
- Критерии и DoD: приведены ниже; [release checklist](../../references/release-checklist.md), [Definition of Done](../../references/definition-of-done.md) и [handoff](../operations/production-handoff.md).
- Выполнено: ветка создана от `main` `1520b73`; EPIC-026 — `blocked`, EPIC-027–031 — `done`. Версия проекта и lock обновлены `uv version` до 1.3.0. `uv sync --offline --frozen --group dev` восстановил локальное окружение после первоначального DNS-сбоя. Полный pytest после исправления: 1624 passed, 9 skipped; отдельные PostgreSQL роли, race tests, managed activation и revision tests прошли на disposable PostgreSQL (43 passed). Синтетическая схема `0017` сохранена, восстановлена и успешно обновлена до `0025`; свежая production копия не использовалась. `make lint`, `make type-check`, `make docs` (155 предупреждений на первом полном build), `make ai-validate`, `make production-check`, `make pre-commit` прошли; rendered Compose со всеми профилями прошёл verifier. Локальный `make security` не завершился из-за недоступного PyPI; [PR #73](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/73) на commit `dcf8ee9` получил три зелёных CI checks, включая Python dependencies и filesystem/secrets.
- Предыдущая роль: Reviewer — полное независимое review кандидата `v1.3.1` на `b074e89` не нашло открытых P0–P2; исправление TASK-032-2, version bump, release workflows, runbook и handoff согласованы.
- Следующая роль: Product Owner — terminal CI после записи этого gate, merge [PR #74](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/74), exact tag `v1.3.1` и tag pipeline; Operations Agent — read-only server preflight до deployment.
- Открытые вопросы: точный текущий production revision, свежий backup/restore, server credentials и sync/feedback EPIC-026, полный production-подобный цикл и release evidence. Первичный P1 об отдельных ролях sync/feedback исправлен локально в [TASK-032-1](tasks/TASK-032-1-registry-production-roles.md), серверное подтверждение остаётся открытым. Локальный wrapper legacy CatBoost с `app_version=1.3.0` и exact source commit собран для неудавшегося тега; wrapper `1.3.1` и проверка в exact Worker image ещё нужны. Read-only SSH 2026-10-11 показал 14 ГБ свободного места и 8,9 млн свободных inode. Ключ временного `sf_epic025` отклонён, `xieveer` входит по SSH, но `sudo -n` требует пароль. Отдельный root SSH ключ из server inventory успешно прошёл read-only `id -un`; Operations Agent проводит server preflight через него. Running digests, Alembic revision и backup ещё не подтверждены. Все пункты требуют evidence до GO.
- Release gate: PR #73 слит в `main` `80ddd0a`; annotated tag `v1.3.0` указывает на этот commit. [Теговый CI](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38142671658) завершился `failure` на Compose gate до публикации образов: в workflow не включены новые opt-in registry профили. Исправление и red/green проверка — [TASK-032-2](tasks/TASK-032-2-release-compose-profiles.md); [PR #74](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/74) получил три зелёных CI checks на version bump commit `b074e89`. Тег `v1.3.0` не перемещать; владелец утвердил `v1.3.1`. До terminal CI итогового evidence commit и tag pipeline — `NO-GO`.
- Обновлено: 2026-10-11.

## Проверяемый результат

1. Версия `1.3.1` однозначно связана с exact commit, annotated tag, immutable image digests, model bundle и release evidence. В runtime, manifest, handoff и package version нет расхождений.
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
