# TASK-025-32 — Сетевой путь archive-sync

> **Статус:** реализация, локальные проверки и независимый review завершены;
> CI и production runtime gate открыты.

## Причина

На production v1.2.11 одноразовый `archive-sync` через Docker bridge повторяемо
не завершает TLS handshake с Object Storage. Тот же immutable image через
host network устанавливает TLS, а host S3 client записал и обратно проверил
первый artifact. Конкретная причина сбоя bridge пока не установлена.
Run `47ebfeb2-5113-465d-9a8e-92f709370639` остаётся `running/archive_sync`;
второй artifact и durable `verified` ещё не подтверждены. Диагностика:
`operations-agent/docs/changes/2026-09-30-v1.2.11-archive-network-diagnosis.md`.

## Изменение

- Только production `archive-sync` запускается с `network_mode: host`.
  Сохранены UID/GID, read-only rootfs и staging, writable sync-state,
  tmpfs, ресурсы и два существующих Object Storage secret mounts. Добавлены
  сброс capabilities и запрет повышения привилегий.
- Rendered Compose gate отвергает возврат этого сервиса в bridge и host
  network у остальных runtime services.
- First-rollout S3 fixture получает случайный порт только на `127.0.0.1`;
  штатный sync из host network получает этот endpoint. Это сохраняет проверку
  двух archives через тот же Compose CLI.
- Версия кандидата и примеры handoff обновлены до v1.2.12. Обоснование границы
  и отката — [ADR-027](../../architecture/adr/ADR-027-archive-sync-host-network.md).

## Проверки

- Red: новый Compose contract test упал без `network_mode: host`; mutation
  test отверг отсутствие gate; fixture test упал без loopback port binding.
- Green: 73 адресных теста прошли в собственной venv рабочей ветки.
- `make lint`, `make type-check`, `make production-check`,
  `uv lock --check --offline` и `git diff --check` прошли.
- Полный first-rollout с release images, terminal CI, штатный sync обоих
  сохранённых artifacts, recovery run и новый цикл на VPS ещё не выполнялись.
- Независимый Reviewer не нашёл блокирующих P0/P1/P2; дополнительно
  подтвердил Docker loopback fixture → host-network client и 65 адресных тестов.
- Проверенный content commit: `b509c1f169c135f3e5a8604894593f516e5046bb`;
  commit gate прошёл Ruff, форматирование, mypy и остальные применимые hooks.

## Передача

Следующая роль — Product Owner для PR/CI/release gates и Operations Agent
для ограниченного production rollout. До успешного
ручного цикла оба NHL timer остаются выключенными. При новой production
ошибке остановиться и сообщить факты владельцу.
