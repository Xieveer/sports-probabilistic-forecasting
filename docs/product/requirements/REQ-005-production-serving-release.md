# REQ-005 — Безопасная поставка production serving-контура

> **Статус:** confirmed
> **Владелец продукта:** пользователь
> **Создано:** 2026-08-09

## Результат и ценность

До первого production-развёртывания приложение поставляется как минимальный,
проверяемый NHL serving-контур для рынка `winner_withOT`. VPS автоматически
получает свежие результаты и расписание NHL, строит признаки, материализует
прогнозы, записывает их в PostgreSQL и отправляет Telegram-digest. DevOps
Operations Agent получает точные immutable образы, model artifact, команды
миграции и materialization, сигналы готовности и безопасный acceptance test.
Deployment остаётся отдельным разрешаемым действием владельца.

## Scope

- Production Compose и CI/CD только для API, PostgreSQL, Telegram bot, Caddy и
  одноразового Worker; интеграция с существующим Grafana Alloy.
- NHL `winner_withOT`: ежедневный тяжёлый refresh данных → features → quality
  gate → materialization → Telegram-digest. VPS имеет исходящий HTTPS-доступ к
  NHL API и The Odds API; Worker не выполняет training.
- Локальный контур: DVC-реплицируемые исторические данные, MLflow experiments
  и Model Registry, обучение, оценка, ручное решение о promotion и создание
  model bundle.
- Наблюдение drift данных/прогнозов и сигнал владельцу о необходимости
  переобучения; автоматический retraining и automatic promotion запрещены.
- Immutable provenance image и модели, production migration, readiness,
  heartbeat, materialization state и acceptance test.
- Обновление production handoff и release evidence без секретов.

## Non-scope

- Deployment, публикация тега или image, управление VPS, секретами и Grafana
  Cloud до отдельного разрешения владельца.
- Training, DVC, Airflow, MLflow, Optuna, локальные Prometheus/Grafana и
  node-exporter на production-хосте.
- Fast path по подтверждённым составам до появления и валидации качественных
  lineup features. В первом выпуске допустим только ежедневный refresh; будущий
  предматчевый запуск является отдельной задачей после доказательства качества.

## Сценарии

1. Release manager создаёт `v1.0.0` после обязательных CI/security gates и
   передаёт DevOps точные `image@sha256` для всех runtime-сервисов.
2. Daily scheduler запускает Worker с immutable model artifact. Он читает
   только необходимые свежие NHL данные, строит features, проходит quality gate,
   идемпотентно материализует прогнозы и после успеха вызывает Telegram-digest.
3. Локальный ML-инженер запускает обучение на DVC-версии истории, сравнивает
   метрики в MLflow и вручную меняет версию/alias в MLflow Model Registry.
   Promotion создаёт immutable deployment manifest и bundle в Object Storage;
   Production загружает его по read-only доступу, сохраняя предыдущий для rollback.
4. API различает liveness процесса и readiness PostgreSQL; bot подтверждает
   event loop, Telegram API и внутренний API без публикации персональных данных.
5. Drift job фиксирует безопасный сигнал при выходе данных/предсказаний за
   согласованные пороги; он не запускает обучение, а уведомляет владельца.
6. После rollout безопасный acceptance test подтверждает сервис и не изменяет
   пользовательские данные, не отправляет сообщения и не запускает training.

## Критерии приёмки

- [ ] Для API, Worker и bot определены release provenance, digest, security
  scans и соответствие commit/tag; автоматический production deploy отсутствует.
- [ ] Production Compose не запускает training/MLflow/Airflow/Prometheus/Grafana/node-exporter;
  runtime data ограничены текущей и предыдущей моделью и inference-минимумом.
- [ ] Model artifact имеет immutable identity, checksum, совместимость с
  приложением, promotion/install/verify и rollback на предыдущий artifact.
- [ ] Worker имеет одну production-команду, bounded resources/time, атомарный
  идемпотентный write и last-success/last-failure contract; ежедневный NHL
  pipeline выполняется целиком без Airflow/DVC/MLflow на VPS.
- [ ] Локальная инструкция воспроизводит путь `DVC data revision → train →
  MLflow evaluation → manual promotion → immutable bundle`; drift создаёт
  только alert/задачу на retraining, не переобучает и не меняет production model.
- [ ] `/health` является liveness, `/ready` возвращает успех только при
  доступной PostgreSQL, а `/metrics` не публикуется через Caddy.
- [ ] Миграции PostgreSQL выполняются отдельной командой с backup, recovery и
  backward-compatible стратегией; API/Worker не изменяют schema при старте.
- [ ] Bot heartbeat и observability signals не содержат secrets или PII.
- [ ] Acceptance test, production handoff и измерение Worker содержат все
  доказательства, требуемые `docs/deploy/devops_message.md`.

## Ограничения, зависимости и риски

- Immutable model identity требует выполнения `TASK-003-1`, `TASK-003-2` и
  `TASK-003-3`; их нельзя заменить `deploy.yaml` с mutable `prod`-именем.
- Digest образов и фактические scan results появляются только в GitHub/GHCR;
  план не выдаёт их за уже существующие.
- Выбор migration framework, планировщика Worker и retention требует
  архитектурного решения до реализации.

## Предположения и открытые вопросы

- Предположение: Grafana Alloy на VPS может собирать внутренние HTTP-сигналы и
  container logs без открытия `/metrics` в public ingress.
- Source of truth и retention разделены: на VPS хранятся не более семи дней
  runtime raw/inference data, execution state и predictions; полная история
  датасетов и архив predictions/backup PostgreSQL не ограничивается по сроку в
  облачном хранилище. Политика должна предусматривать наблюдение стоимости и
  целостности archive, а не неявное удаление.
- MLflow Model Registry — control plane ручного promotion/provenance. Отдельный
  immutable `production-models/` prefix в том же Yandex Object Storage хранит
  bundles; VPS получает read-only доступ, а локальный promotion process — write.
  DVC remote не является механизмом активации модели на VPS.
- Daily refresh выполняется в `10:00` по Москве; scheduler на VPS должен быть
  выбран вместе с DevOps Operations Agent. Retention: семь дней на VPS,
  неограниченный срок в облачном archive при контроле стоимости и целостности.

## Подтверждение

Потребность и запрет на преждевременный deployment переданы владельцем через
`docs/deploy/devops_message.md` 2026-08-09. Жизненный цикл данных/моделей и
daily schedule согласованы владельцем в диалоге 2026-08-09.
