# TASK-025-9 — Production выпуск 1.2.0 и проверка NHL

> **Статус:** backlog
> **Владелец:** Product Owner и Operations Agent
> **Эпик:** [EPIC-025](../EPIC-025-bot-schedule-readiness.md)
> **Требование:** [REQ-025](../../product/requirements/REQ-025-bot-schedule-readiness.md)
> **ADR:** [ADR-026](../../architecture/adr/ADR-026-calendar-and-data-cycle-control.md)

## Результат

Выпустить проверенный exact commit как `v1.2.0`, запустить новый NHL Data Cycle
по расписанию и подтвердить работу бота, API и ежедневного scheduler на
production. Футбольный production pipeline не включается.

## Критерии приёмки

- [ ] Все функциональные TASK инициативы прошли независимое review, full EPIC
  review, локальные проверки и terminal PR CI. `pyproject.toml` и handoff
  указывают `1.2.0`; `make production-check` прошёл для `candidate`.
- [ ] Operations имеет привилегированное read-only evidence текущих image
  digests, Docker/DB состояния, последнего NHL run, календарного покрытия,
  прав/секретов по metadata и проверенного PostgreSQL backup. До этого
  rollback target не считается установленным.
- [ ] Измерены длительность полного NHL цикла и quota future odds; выбранные
  cadence/allowlist не создают overlap. Старый timer и новый dispatcher
  переключаются взаимоисключающе, с проверкой disabled/enabled и следующего
  trigger. На preflight 2026-09-26 старый NHL timer был disabled/inactive.
- [ ] Reviewer создаёт tag только на проверенном commit в `main`. Tag pipeline
  завершён успешно, immutable image digests/provenance/security evidence
  проверены перед изменением VPS.
- [ ] Operations применяет additive migrations с backup, ограниченный rollout
  и smoke: `/health`, `/ready`, календарь 0/7/30, event readiness, admin
  status/history/schedule/manual run, terminal stages, timer next trigger,
  допустимый журнал и отсутствие дубля цикла. Проверка не публикует секреты
  или полный внешний ответ.
- [ ] После первого scheduled запуска подтверждены run_id, дата/время,
  стадии, фактическое 30-дневное coverage и сообщение администратору.
  Неуспех запускает документированный rollback/forward fix, не ложный DoD.

## Текущее evidence и блокеры

Read-only preflight Operations Agent 2026-09-26: unit/drop-in NHL timer
установлен, конфигурация 10:00 Europe/Moscow проверена, но timer
`disabled/inactive`, last/next trigger отсутствуют. Текущий SSH-пользователь
не имеет доступа к Docker, DB, protected deploy record и журналу systemd;
эти gates требуют привилегированной операционной проверки. Сервер не менялся.
Каноническое evidence хранится в отдельном operations repo:
`docs/changes/2026-09.md` и `docs/services/sports-probabilistic-forecasting.md`.

## Handoff и отчёт

- Зависит от всех функциональных TASK инициативы, включая TASK-025-10,
  и полного EPIC review.
- Перед rollout обновить `docs/operations/production-handoff.md` до
  `v1.2.0 candidate`, выполнить `make production-check`.
- Deployment evidence и итоговый done report ожидаются после production smoke.
