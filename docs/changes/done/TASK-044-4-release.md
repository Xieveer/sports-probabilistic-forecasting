# TASK-044-4 — Выпуск v1.4.0

## Результат

2026-10-31 immutable v1.4.0 установлена на `ops-prod-01` по source tag
`v1.4.0` (`1bfefabdf95d60f08810235caca4a22ad73f5ec2`) и exact image
digests из [release manifest](../../../deploy/release-manifest.json).
Evidence tag `v1.4.0-evidence.1` закрепляет эти digest. API, бот и БД healthy;
схема `0026_bet_summary_notification` и модель v1.4.0 проверены.

Controlled NHL Data Cycle `672444d9-3611-4793-8e97-81272ff75207`
завершился `success` за 410 с: 22 727 событий, 232 прогноза,
213 будущих ready, 0 ошибок публикации; terminal notification доставлено.
Три следующих минутных вызова dispatcher прошли без GHCR pull. Ежедневный
слот 2026-11-01 10:00 МСК активен. Сезонный endpoint вернул 99
рассчитанных и пять открытых ставок; бот построил PNG-график. Пять
открытых ставок относятся к будущим матчам, поэтому новая сводка их
расчёта в этом цикле не возникла. Стартовое сообщение с номером версии и
тремя изменениями отправлено владельцу из работающего bot-контейнера.

## Проверки

- Независимый review [EPIC-044](../../backlog/EPIC-044-bets-cycle-report.md)
  без блокирующих findings; `make test` — 1741 passed, 10 skipped;
  `make lint`, `make security`, `make docs`, `make pre-commit`,
  `make production-check` прошли.
- [Source PR #102](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/102),
  post-merge [CI](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/41196325122)
  и [Security](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/41196325055),
  [Docker/first-rollout](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/41196451336) — success.
- [Evidence PR #103](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/103),
  post-merge CI/Security и [Release evidence workflow](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/41197806424)
  — success. Exact Worker на сервере проверил пакет модели и порядок
  489 признаков под UID 10001/read-only/network-none.
- Pre-switch и post-switch backup прошли полный off-host GET/bytecmp;
  isolated restore после выпуска подтвердил схему 0026, ставки и outbox.
  Детали и SHA в [production handoff](../../operations/production-handoff.md)
  и [эксплуатационном журнале](https://github.com/Xieveer/operations-agent/blob/main/docs/changes/2026-10-31-v1.4.0-release-evidence.md).

## Остаточные риски

Первый scheduled run v1.4.0 состоится 2026-11-01; его результат нельзя
подтвердить заранее. Первая реальная сводка рассчитанных ставок ожидает
завершения одного из пяти будущих матчей. Telegram outbox имеет
at-least-once delivery, поэтому при сбое между отправкой и ack возможно
повторное сообщение. Для rollback сохранены v1.3.7 source, exact images,
профиль, модель и DB backups; удаление ставок и downgrade схемы не нужны.
