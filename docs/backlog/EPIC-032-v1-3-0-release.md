# EPIC-032 — Подготовка и выпуск v1.3.1

> **Статус:** done — ограниченный выпуск v1.3.1 на production
> **Приоритет:** high
> **Владелец:** Product Owner

## Память Product Owner

- Инициатива: `EPIC-032`; ветка `initiative/epic-032-v1-3-0-release`, worktree `.worktrees/epic-032-v1-3-0-release`.
- Workflow / этап: release engineering, независимое review, CI, immutable release evidence и Operations rollout завершены.
- Исходная цель: выпустить v1.3.0 на `ops-prod-01`, выявив исправимые проблемы до переключения production.
- Решение владельца: выпуск v1.3.0 запрошен 2026-10-11; после неудачного тегового gate владелец утвердил v1.3.1. Разрешение на ограниченный rollout действует только после всех release gates. При блокирующей находке — `NO-GO`, исправление и повторная проверка до deployment.
- Состав: интегрированные EPIC-026–031; серверный gate [TASK-026-5](tasks/TASK-026-5-registry-publication.md) закрыт в этом выпуске. EPIC-026 остаётся `blocked` по полному циклу REQ-026 #10. Исследовательский STOP EPIC-030 не означает promotion модели. EPL/ENG1 из EPIC-029 не включены в регулярный production цикл.
- Критерии и DoD: приведены ниже; [release checklist](../../references/release-checklist.md), [Definition of Done](../../references/definition-of-done.md) и [handoff](../operations/production-handoff.md).
- Выполнено: ветка создана от `main` `1520b73`; EPIC-026 — `blocked`, EPIC-027–031 — `done`. Версия проекта и lock сначала обновлены до 1.3.0, затем для исправленного кандидата до 1.3.1. Полный pytest исходного кандидата: 1624 passed, 9 skipped; отдельные PostgreSQL роли, race tests, managed activation и revision tests прошли на disposable PostgreSQL (43 passed). Синтетическая схема `0017` сохранена, восстановлена и успешно обновлена до `0025`; свежий production снимок проверен позднее, см. server gate ниже. `make lint`, `make type-check`, `make docs` (155 предупреждений на первом полном build), `make ai-validate`, `make production-check`, `make pre-commit` прошли; rendered Compose со всеми профилями прошёл verifier. Локальный `make security` не завершился из-за недоступного PyPI; PR #73 и #74 получили зелёные CI/security checks, включая Python dependencies и filesystem/secrets.
- Предыдущая роль: Operations Agent — ограниченный rollout, ручной NHL Data Cycle, Telegram delivery владельцу и первые плановые ticks подтверждены; [отчёт и unit-файлы](https://github.com/Xieveer/operations-agent/pull/33).
- Следующая роль: Product Owner EPIC-026 — отдельное решение о строгом registry reader и проверке непустой обратной очереди; Operations Agent — наблюдение за диском и резервная копия локального master.
- Открытые вопросы: EPIC-026/REQ-026 #10 остаётся `blocked`: строгий server resolver выключен, настоящий кандидат → локальное решение → новая публикация не наблюдались. Feedback проверен с пустой очередью; локальный master требует защищённой копии. Старый API прочитал схему `0025` на копии БД, совместимость старого Worker после новых записей не доказана; при сбое dispatcher останавливается до forward-fix или восстановления. Эти риски не скрывают успешный ограниченный выпуск.
- Release gate: PR #73 слит в `main` `80ddd0a`; annotated tag `v1.3.0` указывает на этот commit. [Теговый CI](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38142671658) завершился `failure` на Compose gate. Исправление — [TASK-032-2](tasks/TASK-032-2-release-compose-profiles.md); [PR #74](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/74) прошёл terminal CI и слит в `main` `757d3af338bb2bb36304cb3e81c0f2c93a0834e5`. Annotated tag `v1.3.1` указывает на этот commit. Первый дублирующий tag run `38145180105` упал на `502 Bad Gateway` при запуске Docker Buildx до сборки двух artifacts; [второй run](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38145180090) завершился `success`: release gates, first-rollout, все четыре опубликованных immutable образа, scan и provenance. Evidence tag `v1.3.1-evidence.1` прошёл [отдельный CI](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/38146778838).
- Server gate: read-only preflight подтвердил исходный production v1.2.15/DB `0017`; root-only свежий dump прошёл off-host readback и isolated restore. Репетиция на копии с сохранением ownership прошла `0018`–`0025`, grants и runtime privilege tests; старый API на новой схеме ответил `/ready` 200. После адресной очистки четырёх согласованных неиспользуемых images свободно 14,38 ГБ. Production перешёл на exact source commit/tag, схему `0025`, четыре immutable image refs и проверенный CatBoost bundle; ручной NHL Data Cycle завершился `success` с 51 прогнозом, штатное уведомление владельцу доставлено. Registry snapshot sequence 1 опубликован и установлен; server sync/feedback credentials, роли и расписание проверены, первые ticks успешны. Подробности — в [ops rollout](https://github.com/Xieveer/operations-agent/pull/33).
- Release evidence review: Reviewer проверил итоговый diff коммита `f4ee7dcb6911571ad58b601a41e9791692e56f5d` по manifest, handoff и EPIC; P0–P2 findings нет. SHA-256 проверенного diff: `8c7761b3028cb3a0c0b7bf3be9b443c956c466b4dc8c965a91e578f797179eee`. `make verify-release-evidence`, `make production-check` и `git diff --check` прошли после review.
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
| Предпродовый аудит | Версия, diff, зависимости, миграции, конфигурация, стенд и реальные блокеры | done |
| Кандидат | Исправления, тесты, документация, handoff `candidate`, независимое review | done |
| Артефакт | PR и terminal CI, exact tag, tag pipeline, immutable evidence | done |
| Rollout | Backup gate, deployment, health, Data Cycle и Telegram smoke; TASK-026-5 | done |

## Правило остановки

Отсутствие стенда, проверенного восстановления, серверных grants или credentials,
неуспешные миграции, красный gate, неясный rollback либо расхождение пользовательского
результата дают `NO-GO`. Исправление оформляется в этой инициативе и повторно проходит
затронутые проверки. Нельзя считать отсутствие обнаруженной проблемы доказательством
её отсутствия: в handoff фиксируются непроверенные области и остаточный риск.
