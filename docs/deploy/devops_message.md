# Передача release-candidate `1.1.0` в Operations Agent

> **Статус:** подготовка production-кандидата; deployment этим сообщением не
> разрешается.
>
> **Канонический контракт:**
> [production-handoff.md](../operations/production-handoff.md).
>
> **Связанная задача:**
> [TASK-007-6](../backlog/tasks/TASK-007-6-measurement-devops-handoff-and-release.md).

## Цель передачи

Нужно подготовить проверяемый production-кандидат Sports Probabilistic
Forecasting `1.1.0` для NHL. Application team передаёт runtime-контракт и
локальные evidence; Operations Agent проверяет реальное окружение и готовит
изменения инфраструктуры. Ни tag, ни публикация образов, ни rollout не должны
быть выполнены без последующей явной авторизации владельца.

## Уже подтверждено локально

- Полный NHL canonical bootstrap: 22 218 событий, 26.86 с, peak RSS около
  1.05 GiB.
- Full-history refresh: 20 597 completed matches, 489 features, 1:42.02,
  peak RSS около 2.31 GiB. Worker budget: `2.0` CPU, RAM не менее `3g`,
  scheduler timeout `45m`.
- Future-fixture refresh завершился успешно и атомарно опубликовал 1 621
  prediction. Это проверяет publication path, но не заменяет run на актуальном
  provider snapshot.
- Бесплатный NHL Web API доступен без ключа: проверка `GET
  https://api-web.nhle.com/v1/schedule/now` 2026-08-16 вернула будущие матчи
  регулярного сезона с 2026-09-29 (`gameState=FUT`). Для канонического
  snapshot используйте штатный provider, а не сохраняйте raw HTTP response.

Полные локальные цифры и provenance находятся в
[worker-measurement-evidence.md](../operations/worker-measurement-evidence.md).

## Что требуется от Operations Agent

### 1. Подготовить неизменяемый release artifact

После reviewed merge в `main` и отдельного разрешения владельца на release:

1. создать security tag `v1.1.2`, совпадающий с версией в `pyproject.toml`;
2. запустить release pipeline для этого exact commit;
3. передать для API, Worker и bot по одному полному `image@sha256:<digest>`;
4. приложить GitHub CI result, build provenance attestation и результаты
   dependency, filesystem, secret и image scans;
5. подтвердить связь каждого digest с tag и commit SHA.

Не использовать mutable tag (`latest` или SemVer tag) как runtime identifier и
не переносить digests более раннего commit в Compose candidate.

### 2. Подготовить production runtime без запуска rollout

Сверить Compose и secret store с разделом «Runtime и конфигурация» канонического
handoff. Значения секретов не возвращать в отчёте и не коммитить. До запуска
должны быть подготовлены:

- отдельные scoped DB URLs: API только `SELECT`, Worker имеет нужную запись,
  acceptance использует отдельную read-only роль;
- read-only mount provider snapshot для Worker;
- persistent `runtime_models` с current/previous bundle и staging для archive;
- least-privilege credentials Object Storage только у sync-процесса, не у
  application runtime;
- точные immutable image references в `SF_API_IMAGE`, `SF_WORKER_IMAGE`,
  `SF_BOT_IMAGE`, `SF_POSTGRES_IMAGE`, `SF_CADDY_IMAGE`;
- назначенный владелец scheduler и его `SF_WORKER_RUN_ID` policy.

Команда запуска, порядок миграций и допустимые mounts определены в
[production-handoff.md](../operations/production-handoff.md) и
[production-runtime-topology.md](../operations/production-runtime-topology.md).

### 3. Подтвердить backup, recovery и доступы

До migration Operations Agent должен письменно зафиксировать:

- целевые RPO и RTO, владельца решения и частоту backup PostgreSQL/volumes;
- место хранения backup и результат проверяемого restore;
- предыдущий исправный immutable image и owner rollback;
- доступность production PostgreSQL, S3/Object Storage, внешних NHL/Telegram
  endpoints и DNS без раскрытия endpoint credentials;
- критерии остановки rollout: non-200 `/ready`, DB unavailable, crash loop,
  failure/staleness refresh или resource pressure.

Миграции additive: после их применения применяется forward-fix либо verified
restore, destructive downgrade запрещён.

### 4. Подтвердить candidate acceptance после будущего запуска

После authorised rollout (не в рамках текущей передачи) оператор запускает
только non-mutating:

```bash
make acceptance-check
```

Ожидаются HTTP 200 от `/health`, `/ready` и `/docs`, known safe prediction,
matching app/model version, safe Worker outcome и bot heartbeat. Проверка не
запускает Worker/training, не выполняет DML и не отправляет Telegram-сообщения.

Первая контролируемая доставка в Telegram требует отдельного разрешения
владельца и описана в handoff; не включать её в CI, scheduler или acceptance.

## Нужный ответ Operations Agent

Верните ссылками или безопасными идентификаторами:

1. commit SHA, tag, три image digests, provenance и scan reports;
2. заполненные RPO/RTO, backup/restore evidence, scheduler owner и rollback
   owner;
3. evidence production DB/S3 permissions и readiness external dependencies;
4. перечень подготовленных secret names и mounts без значений;
5. список замечаний, которые препятствуют candidate или требуют решения
   владельца.

Если хотя бы один пункт отсутствует, статус остаётся `NO-GO`: нельзя
компенсировать недостающие evidence обещанием выполнить их после rollout.
