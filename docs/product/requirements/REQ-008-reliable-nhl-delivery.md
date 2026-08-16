# REQ-008 — Надёжная delivery-цепочка NHL

> **Статус:** confirmed
> **Владелец продукта:** пользователь
> **Создано:** 2026-08-16
> **Продолжает:** [REQ-007](REQ-007-production-data-runtime.md)

## Результат и ценность

VPS самостоятельно получает NHL facts и обязательные odds, безопасно обновляет
canonical прогнозы и гарантированно доставляет новые server data в локальный
контур для разработки и ручного обучения. Первый rollout работает только для
private Telegram without public domain; каждая production delivery имеет
versioned Git tag и immutable artifacts.

## Scope

- Atomic provider/odds source acquisition перед canonical refresh.
- Раздельные forecast odds и historical betting-reference odds.
- Отдельный verified VPS-to-Object-Storage sync и local read-only import.
- Private base Compose, optional public ingress и tag-only image release.

## Non-scope

- Deployment, migration, включение scheduler, автоматический training/DVC commit.
- Замена provider, автоматический promotion или public API rollout.

## Сценарии

1. Scheduler получает NHL facts и обязательные odds; только полный snapshot
   атомарно становится доступен Worker.
2. Утренний forecast сохраняет использованную quote. Reference quote для
   historical validation выбирается из `T-60…T-0` ближайшей к `T-15`; поздний
   provider backfill не переписывает forecast provenance. Existing legacy
   `*_close` остаётся неизменным: backfill заполняет отдельный набор `*_t15`
   вместе с provider/retrieval timing provenance.
3. Committed refresh создаёт immutable staging archive. Отдельный S3 sync
   проверяет remote manifest/files до cleanup; failure оставляет retryable state.
4. Локальный read-only sync верифицирует и дедуплицирует archive, создаёт
   descriptor; оператор вручную фиксирует выбранный input в DVC.
5. Private bot/API запускаются без Caddy и public DNS; public ingress — явный
   отдельный overlay. Только exact release tag производит runtime image digests.

## Критерии приёмки

- [ ] Ошибка NHL/Odds не заменяет valid source snapshot и не запускает refresh.
- [ ] Reference quote и forecast quote имеют distinct timestamps/provenance;
  quote after start не используется, backfill имеет provider/retrieval time.
- [ ] Historical `t15` backfill добавляет новые колонки, не перезаписывая
  существующие `*_close`; старая и новая betting validation воспроизводимы.
- [ ] Worker не имеет S3 credentials; sync remote-verifies upload и не удаляет
  staging до успеха; local corruption не меняет training input.
- [ ] Private Compose валиден без Caddy/domain/80/443; public ingress opt-in.
- [ ] PR/main получают CI/security, а image scans/provenance/digests создаются
  только exact versioned release tag.

## Ограничения и риски

- Odds обязательны и для historical business validation, и для текущего EV.
- При временном S3 failure canonical DB и persistent staging должны сохранить
  данные для retry; observability показывает safe sync status.
- Частота poll и S3 client выбираются реализацией, но не меняют временной
  selection contract и credential boundaries.

## Подтверждение

Требование подтверждено владельцем 2026-08-16 в ответ на feedback Operations
Agent; deployment остаётся отдельным разрешением.
