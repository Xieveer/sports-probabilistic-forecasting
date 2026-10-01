# TASK-025-36 — Отчёт Developer: жизненный цикл first-rollout

> **Статус:** исправление, review, PR CI и tag pipeline пройдены; production gate ожидается.
> **Дата:** 2026-10-02
> **Задача:** [TASK-025-36](../../backlog/tasks/TASK-025-36-first-rollout-source-first-lifecycle.md)

## Причина и изменение

Точное локальное воспроизведение tag pipeline v1.2.14 из опубликованных OCI
artifacts показало: Worker вызвал `run_full_refresh` без Data Cycle run и
завершился с сообщением «Подготовленный snapshot требует Data Cycle run».
First-rollout использовал старую последовательность, в которой Worker запускался
до формирования и проверки нового immutable входа. Дополнительно gate удалял
контейнер Worker, оставляя в CI только общее сообщение об ошибке.

Тестовый сценарий теперь создаёт и захватывает durable Data Cycle run, запускает
calendar stage, готовит canonical/source архивы, проверяет Object Storage sync,
завершает `archive_sync` и лишь после этого запускает Worker с тем же run ID и
executor generation. Повторный запуск Worker проверяет идемпотентность. При
ненулевом коде Worker gate проверяет секреты и сохраняет ограниченный хвост
его логов до удаления контейнера.

## Проверки

- Red: новый тест жизненного цикла first-rollout не импортировал ещё
  отсутствовавший helper. Green: 53 адресных теста прошли после исправления.
- `make lint`: passed.
- `make test-unit`: 1 263 passed, 13 deselected, 40 warnings после последней
  правки теста.
- `make production-check`: passed.
- Полный локальный first-rollout на пяти OCI artifacts tag v1.2.14:
  passed; проверены bootstrap, source state, два remote-verified archive,
  Worker, повторный идемпотентный запуск, API/calendar и Telegram.
  Для проверки незакоммиченного кода временный wrapper обошёл только
  требование clean worktree; исходный release gate его сохраняет.
- Независимый Reviewer: P0–P2 findings нет; отдельно проверены source-first
  порядок, executor fencing, Docker mounts, redaction, идемпотентность,
  release docs и full EPIC границы. Адресные 46 тестов Reviewer прошли.
- PR [#57](https://github.com/Xieveer/sports-probabilistic-forecasting/pull/57)
  прошёл три проверки CI и слит на
  `774602cb3d2db8ce65b4411637ff86e057fc76ec`.
- Tag [v1.2.15 Docker pipeline](https://github.com/Xieveer/sports-probabilistic-forecasting/actions/runs/36931948706)
  завершился успешно: clean first-rollout подтвердил два архива до Worker,
  API/бота и idempotency; опубликованные digests совпали с tested, scan и
  provenance прошли. Production gate остаётся открытым.

Проверенный код и документация: commit
`f6c4af0f27851c554fb148ba219a27191f207bcc`. Этот отдельный evidence
commit содержит только ссылки на проверенный hash.

Production остаётся v1.2.12; оба NHL timer выключены. Теги v1.2.13 и
v1.2.14 не меняются и не используются для deployment.
