# TASK-007-9 — отчёт о выполнении

> **Статус задачи:** done
> **Дата:** 2026-08-16

Base Compose стал private Telegram-only: Caddy, DNS и ports 80/443 вынесены в
явный `docker-compose.public.yml`. Docker workflow публикует runtime images,
image scan и provenance только exact versioned tag; CI/security по-прежнему
запускаются на PR/main. Handoff фиксирует image digests и model bundle
ID/checksum/compatibility/current-previous rollback.

Проверки: private/public `docker compose config`, 11 topology tests, ruff,
mypy, `make docs`, `git diff --check`. Реальные tag, GHCR digests/provenance и
deployment не выполнялись.
