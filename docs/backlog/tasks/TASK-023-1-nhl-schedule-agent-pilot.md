# TASK-023-1 — Расписание NHL в Telegram и агентский delivery pilot

> **Статус:** in_progress
> **Владелец:** implementer (код) / operations-agent (production)
> **Эпик:** [EPIC-023](../EPIC-023-nhl-schedule-agent-pilot.md)
> **Требование:** [REQ-023](../../product/requirements/REQ-023-nhl-schedule-agent-pilot.md)
> **ADR:** [ADR-023](../../architecture/adr/ADR-023-minimal-agent-pilot-with-operations-agent.md)

## Результат и границы

Пользователь тестового Telegram-бота выбирает NHL, вводит целое `N=0–30` и получает
будущие матчи до конца соответствующего дня МСК, сгруппированные по датам. В каждой
записи сохраняются существующие прогноз, коэффициенты и value; для отсутствующих
обогащающих значений выводится «нет данных». Пустой период и неверный ввод имеют
детерминированный ответ.

Не меняются модели, data/odds pipeline и формула value. Не добавляются новые турниры,
subscriptions, Research, session memory, workflow registry/lease/GPG packages или
обязательный CI gate. Coding agents не выполняют production-команды и не получают
production secrets.

## Критерии приёмки

- [x] Перед реализацией рабочее дерево очищено от всего непринятого EPIC-022 scope без
  изменения Git history; unrelated tracked changes сохранены и перечислены в отчёте.
- [x] Выбор NHL и ввод `N=0–30` реализуют правила периода МСК; неправильный ввод не
  вызывает data request и сообщает допустимый формат.
- [x] Выдача группируется по датам, содержит время и команды, а также существующие
  прогноз/коэффициенты/value или «нет данных» по отдельному отсутствующему полю.
- [x] Отсутствие будущих матчей возвращает понятное сообщение.
- [x] Новое поведение проходит сначала targeted failing tests, затем unit/integration
  tests; регрессии существующих bot/API contracts исключены.
- [x] Фактически успешны `make lint`, полный test suite и Git CI для проверенного
  implementation commit; результаты зафиксированы в done-report. Финальный release commit
  дополнительно проходит tag pipeline до rollout.
- [x] Browser e2e тестового бота подтверждает именно форматированную выдачу с fixture,
  без production token; evidence не содержит секретов, chat IDs или полных Telegram payload.
- [ ] `operations-agent` до deployment документирует read-only discovery и исправляет
  устаревшие service facts. Он развёртывает только принятый immutable release через свой
  allowlist, проверяет лишь утверждённые health/log checks и автоматически откатывается
  при техническом сбое. Фактический rollout остаётся следующим gate.
- [ ] Production-result либо successful health/log evidence, либо completed rollback
  and non-terminal TASK status; пользовательская production-проверка не выполняется
  агентом.

## План реализации

1. Главный агент документирует точный список EPIC-022 targets, сохраняет diff snapshot
   вне репозитория при необходимости и обратимо удаляет только этот непринятый scope;
   проверяет чистоту EPIC-022 boundary. Затем переводит эту TASK в `in_progress`.
2. Implementer изучает текущие bot handlers, callbacks, `/upcoming` API contract и
   существующий formatter прогнозов; test-designer фиксирует first failing tests для
   ввода, календарного окна МСК, missing data и empty result.
3. Implementer реализует минимальный handler/formatter и тесты red → green → refactor;
   обновляет русскую пользовательскую документацию только в затронутой части.
4. Независимый reviewer проверяет diff, docs и evidence; после отсутствия blocking findings
   создаёт/проверяет commit по существующей политике и фиксирует exact hash.
5. На exact commit выполняются `make lint`, полный test suite и обязательный Git CI;
   agent проходит browser e2e test bot. Любое несовпадение останавливает rollout.
6. `operations-agent` выполняет только read-only server discovery и сверяет принятый
   release, target, rollback target и allowlist. При подтверждении он развёртывает
   release, выполняет утверждённые technical health/log checks и записывает фактический
   operations record.
7. При failure operations-agent автоматически rollback; TASK остаётся non-terminal и
   содержит safe diagnostic. При успехе implementer создаёт done-report, reviewer
   проверяет evidence, после чего возможен terminal status и полное EPIC review.

### Manifest rollback EPIC-022

Rollback не переписывает Git history и не затрагивает принятый `HEAD` `a28af79`.
Перед удалением главный агент сверяет этот manifest с `git status --short` и прекращает
операцию при новом нераспознанном изменении.

- Вернуть к `HEAD` только tracked changes: `.env.example`, `.github/workflows/ci.yml`,
  `agents/reviewer.md`, `docs/development/ai-agents-and-skills.md`, `docs/source/index.rst`,
  `scripts/validate_ai_layer.py`, `skills/code-review/SKILL.md`,
  `sports_forecast/research/contracts.py`, `sports_forecast/research/orchestrator.py`,
  `sports_forecast/research/storage.py`, `tests/test_ai_layer_validation.py`,
  `tests/test_research_orchestrator.py`.
- Удалить только untracked EPIC-022 scope: `.workflow/`,
  `docs/architecture/adr/ADR-022-file-backed-engineering-workflow.md`,
  `docs/backlog/EPIC-022-autonomous-agent-workflow.md`,
  `docs/backlog/tasks/TASK-022-*.md`, `docs/changes/done/TASK-022-*.md`,
  `docs/product/requirements/REQ-022-autonomous-agent-workflow.md`,
  `docs/source/agent_workflow.rst`, `scripts/agent_doctor.py`,
  `sports_forecast/workflow/`, `sports_forecast/research/engineering_gateway.py`,
  `tests/test_research_engineering_gateway.py`, `tests/test_research_ledger.py`,
  `tests/test_workflow_doctor.py`, `tests/test_workflow_packages.py`,
  `tests/test_workflow_registry.py`.
- Сохранить REQ-023, ADR-023, EPIC-023 и TASK-023-1, созданные этим планированием, а
  также заменить EPIC-022/TASK-022 строками EPIC-023/TASK-023-1 в
  `docs/backlog/index.md`. Любой файл вне manifest сохраняется.
- После rollback проверить `git status --short`, `git diff --check`, отсутствие ссылок
  на EPIC-022 в tracked документации и доступность ссылок REQ-023/ADR-023/EPIC-023/TASK-023-1.

## Затрагиваемые области и зависимости

- Вероятные application areas: `sports_forecast/bot/`, Telegram/API formatter,
  `sports_forecast/service/routers/predictions.py`, соответствующие `tests/`, README/docs.
  Exact paths определяются только после тестового исследования current contracts.
- Operations boundary: `/home/xieveer/Документы/codex_projects/operations-agent`, его
  service passport и deployment runbook. Изменения там выполняет только
  `operations-agent` после read-only discovery.
- Необходимы изолированный test bot/browser access и server-side separate tokens, без
  передачи их значений в этот repository.

## Проверка

- Targeted red/green tests для handler/formatter/timezone/missing data/empty result.
- `make lint`, полный test suite и `git diff --check` — фактические команды фиксируются
  в done-report.
- Git CI exact accepted commit: успешная ссылка/ID без секретных данных.
- Browser e2e test bot: NHL → `N` → formatted result; запись содержит только безопасный
  итог без chat IDs/payload.
- Operations Agent: read-only discovery, accepted immutable release, approved health/log
  checks и success/rollback evidence по его service record.

## Handoff и отчёт

- Отчёт выполнения: `docs/changes/done/TASK-023-1-nhl-schedule-agent-pilot.md`.
- Follow-up / findings: 2026-09-22 в авторизованной вкладке test bot пройден полный browser
  E2E на коде commit `93d0d0a`: `/upcoming` → NHL → `1` → будущий матч, сгруппированный по
  дате МСК, с прогнозом, home/away коэффициентами, home/away value и решениями. Ответ пришёл
  от краткоживущей локальной HTTP-fixture; production endpoint и production token не
  использовались. После проверки fixture и локальный polling остановлены. В evidence не
  записывались chat IDs, токены, payload или снимки интерфейса. Следующие gates: Git CI
  exact commit, затем read-only discovery operations-agent и ограниченный deployment.
- Review: независимый reviewer принял functional commit `93d0d0a`; merge commit
  `7bedfe8` прошёл CI и Security. Последующее formatting-уточнение `ef8ace6` также прошло
  CI и Security; final release commit проходит tag pipeline отдельно.
- Commit/push: deploy release получает immutable identity только из tag pipeline и
  операционной записи; SemVer tag сам по себе runtime identifier не является.
- Release remediation: tag `v1.1.15` остановлен до publication и deploy на isolated
  MinIO fixture (Docker exit 125). Follow-up `v1.1.16` изолированно исправляет этот
  release gate; production scope TASK не меняется.
