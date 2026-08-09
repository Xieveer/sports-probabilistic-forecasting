# TASK-006-1 — Закрытие release gates для первого сообщения

> **Статус:** blocked
> **Владелец:** security-reviewer / devops-reviewer
> **Эпик:** [EPIC-006](../EPIC-006-first-telegram-delivery.md)
> **Требование:** [REQ-006](../../product/requirements/REQ-006-first-telegram-delivery.md)
> **ADR:** [ADR-006](../../architecture/adr/ADR-006-first-telegram-delivery-verification.md)

## Результат и границы

Есть доказуемо допустимый production-candidate: security finding обработан,
immutable runtime images и их evidence доступны, handoff заполнен фактами.
Задача не выполняет rollout и не отправляет Telegram-сообщения.

## Критерии приёмки

- [x] Зафиксировано устранение blocking security finding; `make security`
  на 2026-08-09 завершился с `No known vulnerabilities found` для production
  runtime dependencies.
- [ ] Для API, Worker и bot зафиксированы published immutable image digests и
  соответствующие CI/scan/provenance evidence.
- [x] `production-handoff.md` не содержит ложного утверждения о внешних
  проверках и содержит актуальный gate decision.

## План реализации

1. Воспроизвести security/release findings и классифицировать remediation.
2. Внести минимальные исправления зависимостей/конфигурации, выполнить проверки
   и подготовить immutable release evidence без секретов.
3. Передать оператору candidate и актуальный handoff; не запускать deployment.

## Затрагиваемые области и зависимости

- Lockfile и зависимости, CI/GHCR, `docs/operations/production-handoff.md`.
- Нужны внешние GitHub/GHCR и полномочия владельца для publish/принятия риска.
  На 2026-08-09 `gh auth status` не смог получить credential из keyring по
  timeout, поэтому publish и remote evidence не выполнялись.

## Проверка

- `make security`, `make production-check`, CI/GHCR evidence после разрешённой
  публикации; фактические результаты фиксируются только в done-отчёте.

## Handoff и отчёт

- Отчёт выполнения не создаётся до publication evidence: задача заблокирована,
  а не завершена.
- Follow-up / findings: передать TASK-006-2 и оператору ссылку на evidence.
