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
- Выполнено: ветка создана от `main` `1520b73`; EPIC-026 — `blocked`, EPIC-027–031 — `done`. Версия проекта и lock сначала обновлены до 1.3.0, затем для исправленного кандидата до 1.3.1. Полный pytest исходного кандидата: 1624 passed, 9 skipped; отдельные PostgreSQL роли, race tests, managed activation и revision tests прошли на disposable PostgreSQL (43 passed). Синтетическая схема `0017` сохранена, восстановлена и успешно обновлена до `0025`; свежий production снимок проверен позднее, см. server gate ниже. `make lint`, `make type-check`, `make docs` (155 предупреждений на первом полном build), `make ai-validate`, `make production-check`, `make pre-commit` прошли; rendered Compose со всеми профилями прошёл verifier. Локальный `make security` не завершился из-за недоступного PyPI; PR #73 и #74 получили зелёные CI/security checks, включая Python dependencies и filesystem/secrets.
- Предыдущая роль: Reviewer — полное review кандидата `v1.3.1` на `b074e89` не нашло P0–P2; в review release evidence замечания P2 к порядку bootstrap/migrator и устаревшей памяти исправлены до evidence commit.
- Следующая роль: Reviewer — подтвердить итоговый release evidence diff; затем Product Owner — evidence tag/CI; Operations Agent — серверные registry, rollback и acceptance gates до deployment.
- Открытые вопросы: release evidence tag/CI, доставка server credentials и sync/feedback EPIC-026, совместимость отката или проверенный forward-fix, сквозной API/бот smoke и ограниченный production rollout. Первый P1 по отдельным DB ролям исправлен в [TASK-032-1](tasks/TASK-032-1-registry-production-roles.md); серверные SQL probes ещё нужны. Production revision, свежий backup/off-host readback/restore, upgrade его копии и wrapper 1.3.1 в exact Worker подтверждены в server gate ниже. Root SSH доступен; 14 ГБ свободного места требует повторной проверки перед image pull и rollout. До закрытия открытых пунктов — `NO-GO`.
- Release gate: PR #73 слит в `main` `80ddd0a`; annotated tag `v1.3.0` указывает на этот commit. [Теговый CI](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38142671658) завершился `failure` на Compose gate. Исправление — [TASK-032-2](tasks/TASK-032-2-release-compose-profiles.md); [PR #74](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/74) прошёл terminal CI и слит в `main` `757d3af338bb2bb36304cb3e81c0f2c93a0834e5`. Annotated tag `v1.3.1` указывает на этот commit. Первый дублирующий tag run `38145180105` упал на `502 Bad Gateway` при запуске Docker Buildx до сборки двух artifacts; [второй run](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38145180090) завершился `success`: release gates, first-rollout, все четыре опубликованных immutable образа, scan и provenance. До release evidence и серверных gates — `NO-GO`.
- Server gate: read-only preflight подтвердил production v1.2.15, DB `0017`, healthy API/bot/DB и dispatcher timer enabled; root-only свежий dump `v1.3.1` прошёл полную off-host SHA-256/readback проверку и изолированный restore за 12 секунд. Отчёт Operations Agent: `operations-agent/docs/changes/2026-10-11-v1.3.1-backup-gate.md`. Локальная репетиция на копии с сохранением ownership прошла `0018`–`0025`, grants и три runtime privilege tests без изменения исходных агрегатов (`operations-agent/docs/changes/2026-10-11-v1.3.1-db-rehearsal.md`). Первый тест с `--no-owner` дал ложный отказ; правильная копия совпала с production по владельцам 25 таблиц и 24 sequence. Bundle legacy CatBoost `sha256:956edb47e9737516ce8a29ed42a6cea08af6522fed1b9510a614201c20daad09` проверен в exact опубликованном Worker image (UID 10001, сеть выключена, 489 признаков); серверный pointer не менялся. Registry и acceptance остаются открытыми.
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
