\# Подготовка Sports Probabilistic Forecasting к production



DevOps Operations Agent проверил ветку `dev`, production handoff, Dockerfile, Compose и переданные immutable-образы.



Production deployment пока выполнять нельзя. Перед передачей сервиса в эксплуатацию необходимо закрыть перечисленные ниже задачи.



\## 1. Release и provenance образов



Нужно подготовить однозначный release-путь:



```text

dev

→ reviewed merge в main

→ успешные CI и security checks

→ tag v1.0.0

→ публикация immutable images

→ передача digest DevOps Operations Agent

```



Для API, Worker и Telegram bot необходимо предоставить:



\- точный commit SHA;

\- Git tag;

\- полный `image@sha256:digest`;

\- результаты CI;

\- результаты dependency, filesystem, secret и image security scans;

\- подтверждение соответствия каждого digest указанному commit.



Текущие образы считаются кандидатами, но не окончательным production release.



\## 2. Разделение training и serving



Обучение моделей выполняется локально и не переносится на production-сервер.



\### Локальный training-контур



Здесь остаются:



\- полные обучающие датасеты;

\- DVC и DVC cache;

\- MLflow и история экспериментов;

\- Optuna studies;

\- обучение и оценка моделей;

\- промежуточные артефакты;

\- полный набор исторических данных.



\### Production serving-контур



На сервере запускаются только:



\- FastAPI API;

\- PostgreSQL;

\- Telegram bot;

\- Caddy;

\- кратковременный inference/materialization Worker;

\- существующий Grafana Alloy.



На production-сервере не запускаются:



\- обучение моделей;

\- MLflow;

\- Airflow;

\- локальные Prometheus и Grafana;

\- отдельный node-exporter из application Compose.



\## 3. Immutable model artifact



Нужно определить контракт поставки production-модели:



\- стабильный идентификатор версии;

\- checksum;

\- связь с Git commit и release;

\- формат model artifact;

\- совместимость с версией Worker/API;

\- команда установки или promotion;

\- процедура проверки после установки;

\- предыдущая совместимая модель для rollback.



На сервере должны храниться только:



\- текущая production-модель;

\- предыдущая модель для rollback;

\- минимальные runtime-данные, необходимые для inference.



\## 4. Production materialization Worker



Текущий API самостоятельно прогнозы не вычисляет — он читает materialized predictions из PostgreSQL.



Нужна отдельная однозначная production-команда Worker, которая:



1\. Загружает утверждённую production-модель.

2\. Получает только необходимые свежие входные данные.

3\. Не запускает обучение или подбор гиперпараметров.

4\. Вычисляет прогнозы.

5\. Проверяет качество и полноту результата.

6\. Атомарно записывает результат в PostgreSQL.

7\. Безопасно поддерживает повторный запуск.

8\. Завершается после выполнения.

9\. Публикует безопасные last-success/last-failure signals.



Необходимо документировать:



\- точную команду;

\- входные и выходные данные;

\- необходимые environment variables;

\- максимальную продолжительность;

\- ожидаемое потребление памяти;

\- критерий успешного выполнения;

\- timeout и обработку частичного сбоя;

\- расписание запуска.



\## 5. API readiness



Сейчас `/health` возвращает HTTP 200 даже при недоступной PostgreSQL, указывая `status=degraded`.



Нужно реализовать один из вариантов:



\- возвращать non-2xx при недоступности обязательной зависимости; или

\- добавить отдельный `/ready`, который возвращает success только при готовности API и PostgreSQL.



Рекомендуемый контракт:



\- `/health` — liveness процесса;

\- `/ready` — readiness API и PostgreSQL;

\- `/metrics` — внутренний endpoint для Alloy, без публичной экспозиции.



\## 6. Telegram bot health и heartbeat



Текущий healthcheck проверяет только наличие процесса и недостаточен для production.



Нужно добавить безопасный heartbeat/last-success, подтверждающий:



\- работу event loop;

\- доступность Telegram Bot API;

\- доступность внутреннего API;

\- время последнего успешного обращения.



Нельзя помещать в logs, metrics или alerts:



\- Telegram token;

\- chat/user IDs;

\- usernames;

\- тексты сообщений;

\- ответы Telegram API;

\- другие персональные данные.



\## 7. PostgreSQL и migrations



Необходимо определить production migration procedure.



Требуется:



\- точная команда migration;

\- порядок выполнения относительно запуска API и Worker;

\- backward compatibility;

\- поведение при частично выполненной migration;

\- backup перед изменением схемы;

\- rollback или recovery procedure.



Одного вызова SQLAlchemy `create\\\_all()` недостаточно как документированной production migration strategy.



\## 8. Runtime-данные



На production-сервер не нужно переносить весь ML-проект и все исторические данные.



На сервере остаются:



\- PostgreSQL с актуальными predictions;

\- минимальная необходимая служебная история;

\- текущая и предыдущая production-модели;

\- ограниченные входные данные для ближайшего materialization;

\- last-success/last-failure state;

\- PostgreSQL backups.



На сервер не переносятся:



\- полные training datasets;

\- DVC cache;

\- MLflow artifacts и история экспериментов;

\- Optuna studies;

\- промежуточные результаты обучения;

\- все исторические версии моделей;

\- локальные monitoring databases.



Следует определить retention policy для predictions, входных данных, логов и резервных копий.



\## 9. Observability



Локальные Grafana и Prometheus можно оставить в репозитории для разработки, но они должны быть исключены из production Compose.



Production observability будет построена через уже существующие:



\- Grafana Cloud;

\- Grafana Alloy;

\- Timeweb monitoring.



Необходимо сохранить или адаптировать полезные application dashboards и alerts для Grafana Cloud.



Обязательные сигналы:



\- API availability и readiness;

\- PostgreSQL availability;

\- Telegram bot heartbeat;

\- container restart loop;

\- последний успешный materialization;

\- failed или stale materialization;

\- prediction freshness;

\- deployment success/failure/rollback;

\- CPU, memory, disk и container resource pressure.



\## 10. Безопасный acceptance test



Нужно предоставить smoke/acceptance test, который после rollout проверяет:



\- API liveness;

\- API readiness и PostgreSQL;

\- получение тестового prediction;

\- корректную версию API и модели;

\- Telegram bot connectivity;

\- отсутствие ошибок в logs;

\- обновление materialization last-success.



Проверка не должна:



\- изменять реальные пользовательские данные;

\- отправлять незапланированные сообщения;

\- раскрывать secrets или персональные данные;

\- запускать обучение.



\## 11. Ожидаемый production-контур



Предварительный ресурсный бюджет:



| Компонент | CPU ceiling | Memory ceiling | Режим |

|---|---:|---:|---|

| API | 1.5 CPU | 1536 MiB | постоянно |

| PostgreSQL | 1 CPU | 1536 MiB | постоянно |

| Telegram bot | 0.5 CPU | 384 MiB | постоянно |

| Caddy | 0.25 CPU | 128 MiB | постоянно |

| Worker | 2 CPU | 2048 MiB | только materialization |



Постоянный application ceiling — около 3.5 GiB.



Во время materialization общий application ceiling — около 5.5 GiB. Фактическое потребление Worker необходимо измерить prod-like запуском.



\## 12. Что передать DevOps после доработки



После выполнения задач необходимо передать:



1\. Reviewed commit в `main`.

2\. Git tag `v1.0.0`.

3\. Immutable digests API, Worker и Telegram bot.

4\. Результаты CI и security/image scans.

5\. Контракт immutable model artifact.

6\. Точную production-команду materialization.

7\. Migration и recovery procedure.

8\. Обновлённые health/readiness endpoints.

9\. Telegram heartbeat contract.

10\. Безопасный acceptance test.

11\. Результат prod-like измерения Worker.

12\. Список environment variables и имён secrets без значений.



После этого DevOps Operations Agent:



\- проверит production host;

\- завершит Compose;

\- настроит Grafana Cloud observability;

\- подготовит backup и restore;

\- зафиксирует rollout и rollback plan;

\- запросит отдельное явное разрешение владельца на production deployment.



До получения такого разрешения production deployment не выполняется.
