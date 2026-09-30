# TASK-025-32 — Сетевой путь archive-sync

> **Статус:** реализация, локальные проверки и независимый review завершены;
> source-tag CI завершён; release evidence CI и production runtime gate открыты.

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
- Штатный sync обоих сохранённых production artifacts, recovery run и новый
  цикл на VPS ещё не выполнялись.
- Независимый Reviewer не нашёл блокирующих P0/P1/P2; дополнительно
  подтвердил Docker loopback fixture → host-network client и 65 адресных тестов.
- PR #54 выявил в dependency audit три CVE для зафиксированного `urllib3`
  2.7.0. `uv lock --upgrade-package urllib3` обновил только его до 2.8.0;
  повторный локальный `pip-audit` полного runtime export не нашёл известных
  уязвимостей. Повторное независимое review не нашло блокирующих findings:
  `uv lock --check --offline`, `uv tree --locked --package urllib3`, импорт
  версии в проектной venv и commit hooks прошли; PR/merge CI зелёные.
- Source tag `v1.2.12` на merge commit `2d247f2c42a65145881662e544f87023b85002a0`:
  [Docker pipeline](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36767386816)
  завершился успешно. First-rollout проверил оба archive artifacts через
  штатный host-network sync к loopback S3 fixture; опубликованы exact digests,
  scan/provenance. Это локальный release gate, не production sync.
- Независимое release evidence review не нашло блокирующих findings:
  source tag, CI/Docker jobs, четыре опубликованных digest, handoff и model
  wrapper сверены. Проверенный evidence content commit:
  `24ceef5e677b190fe61093a19aeaebfe7556d3c9`. Evidence CI и
  production runtime gate остаются открытыми.
- Проверенный security correction commit:
  `fa2ac931cde0135f48c14d4aad87e54f7fe05bb3`.
- Проверенный content commit: `b509c1f169c135f3e5a8604894593f516e5046bb`;
  commit gate прошёл Ruff, форматирование, mypy и остальные применимые hooks.

## Передача

Следующая роль — Product Owner для release evidence gate и Operations Agent
для ограниченного production rollout. До успешного
ручного цикла оба NHL timer остаются выключенными. При новой production
ошибке остановиться и сообщить факты владельцу.
