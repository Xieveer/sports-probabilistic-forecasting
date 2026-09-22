# ADR-023 — Минимальный агентский цикл с Operations Agent

> **Статус:** accepted
> **Дата:** 2026-09-16
> **Связанное требование:** [REQ-023](../../product/requirements/REQ-023-nhl-schedule-agent-pilot.md)

## Контекст и критерии выбора

После аудита EPIC-022 владелец отменяет непринятый workflow: registry, lease,
GPG/evidence, Research integration, session memory и обязательный CI gate не доказали
пользу на принятом Git-инкременте. Пилоту требуется один реальный пользовательский
результат — расписание NHL в Telegram — и один полный, но короткий путь до production.

Владелец делегировал `operations-agent` ограниченный production-deploy и rollback после
полного набора локальных проверок, Git CI, независимого review и браузерного e2e тестового
бота. Production-бот не получает агентских пользовательских сообщений: после deploy
разрешены только health-checks и безопасные логи. Отдельный проект `operations-agent`
уже описывает ограниченный immutable deploy entrypoint и rollback, но его паспорт Sports
Forecasting содержит устаревшее утверждение об отсутствии production rollout; это требует
read-only discovery и синхронизации до первого deploy по этому решению.

Критерии выбора:

- один наблюдаемый пользовательский результат и принятый commit;
- новый агент продолжает работу без чата по обычным каноническим документам;
- минимальные новые механизмы и отсутствие self-referential process gate;
- least privilege, immutable release, известный rollback target и отсутствие секретов в Git;
- независимая проверяемость каждой границы: код, тестовый бот, release и production health.

## Рассмотренные варианты

1. **Status quo:** сохранить текущий до-EPIC-022 цикл `REQ → ADR → EPIC/TASK →
   implementer → reviewer → commit` и выполнять deploy вручную. Он прост и уже
   документирован, но не проверяет делегированное владельцем безопасное доведение
   ограниченного release до production.
2. **Восстановить EPIC-022 и устранить findings:** добавить registry, lease, signed
   packages, doctor, Research gateway и CI gate. Он покрывает много гипотетических
   рисков, но уже создал непринятый сложный scope, bootstrap/recovery-исключения и не
   доказал реальный lifecycle. Не отвечает критерию минимального вертикального среза.
3. **Минимальный пилот поверх существующих артефактов:** использовать обычные REQ/ADR,
   один EPIC и одну TASK, независимый review/commit и отдельный `operations-agent` для
   ограниченного release. Перед deploy обязательны полные tests/lint/Git CI и browser
   e2e на тестовом боте. Release идентифицируется exact commit и существующим immutable
   механизмом; после deploy — только technical health/log checks и автоматический
   rollback при неуспехе.

## Решение

Владелец подтвердил решение 2026-09-16. EPIC-023 содержит одну пользовательскую TASK
вертикального среза (TASK-023-1) и отдельный завершённый baseline prerequisite TASK-023-2;
он не добавляет workflow runtime, реестр, lease, persistent agent memory или новый CI gate.

Минимальный граф:

```text
REQ-023 + ADR-023
  → TASK-023-1 (один пользовательский сценарий)
  → implementer: tests + docs
  → независимый reviewer: review + accepted Git commit
  → полный test/lint + Git CI на exact commit
  → browser e2e тестового Telegram-бота
  → operations-agent: limited deploy → health/logs
  → done
                    └→ failure: automatic rollback → TASK in_progress/blocked
```

`operations-agent` является единственной production-границей. Его разрешённая операция
принимает лишь допустимый сервис и проверенный immutable release через allowlist; coding
agents не получают общий SSH, shell, Docker, sudo или secret access. До deploy он выполняет
read-only discovery фактического host/runtime и обновляет свой service passport на
наблюдаемых фактах. Если target, права, downtime, persistent data или rollback target
отличаются от задокументированных, deployment останавливается и решение возвращается
владельцу.

## Последствия

- Положительные: пилот проверяет именно пользовательскую ценность и полный delivery
  path; следующий агент читает стандартные REQ/ADR/TASK/done-report вместо нового
  orchestration protocol; production-права изолированы у профильного агента.
- Отрицательные и стоимость: один агент не получает «магическую» автономию вне этого
  маршрута; browser e2e и production discovery требуют поддерживаемого тестового
  контура; ошибочный server passport сначала должен быть выправлен evidence, а не
  предположением.
- Безопасность и эксплуатация: отдельные test/prod tokens не покидают сервер; release
  связана с exact commit и immutable artifact; production acceptance пользователя остаётся
  ручной; health failure приводит к rollback, но не заменяет pre-deploy gates.
- Отменённый scope: непринятый EPIC-022 и его REQ/ADR/TASK/docs/code удаляются из
  рабочего дерева при отдельном обратимом шаге. Его идеи не переносятся в EPIC-023 без
  нового подтверждённого требования.

## Проверка и пересмотр

Решение подтверждено, если один реальный сценарий REQ-023 проходит без нового
bootstrap/recovery-исключения, независимый агент продолжает по артефактам без чата,
создан accepted Git commit, а ограниченный deploy/health path либо успешно завершён,
либо безопасно откатился. Стоимость ручных операций фиксируется в done-report.

Решение пересматривается и дальнейшая автономизация не расширяется, если требуются новые
виды bootstrap/recovery, нельзя совместить clean worktree, commit и release evidence,
нет принятой TASK после пилота либо стоимость ручных действий несоразмерна пользе.

## Источники и неизвестное

- [REQ-023](../../product/requirements/REQ-023-nhl-schedule-agent-pilot.md) —
  подтверждённая продуктовая граница и делегирование владельца.
- `operations-agent/docs/runbooks/github-actions-deployment.md` — локальный
  runbook limited immutable deployment; факт применимости к текущему runtime ещё
  требует read-only discovery.
- [OpenAI: A practical guide to building agents](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/) — рекомендуется инкрементальное
  усложнение orchestration.
- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) — простые композиционные workflow предпочтительны до доказанной
  необходимости большей автономии.
