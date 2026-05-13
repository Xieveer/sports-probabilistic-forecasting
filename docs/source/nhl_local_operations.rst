
Локальный операционный чеклист (NHL и общий стек)
=================================================

Этот раздел фиксирует минимальный воспроизводимый порядок действий для локального запуска сервисов:
БД, API, Docker Compose, при необходимости Airflow и Telegram-бота. Секреты в текст не
вносятся — указываются только **имена** переменных окружения из шаблона репозитория.

Граница ответственности API
----------------------------

**Сервис API в runtime не выполняет тяжёлую генерацию признаков и не запускает обучение.**
Он отдаёт предвычисленные материализованные предсказания из витрины (БД); конвейеры подготовки
данных и инференса выполняются вне HTTP-запроса (воркеры, Airflow, CLI).

Подробности контракта и разделения слоёв см. в репозитории:

* :download:`service_orchestration_architecture.md <../cursor/context/service_orchestration_architecture.md>` — архитектура сервисов и оркестрации (Markdown).

Перед первым запуском
---------------------

1. Склонируйте репозиторий и перейдите в корень проекта.

2. Установите зависимости и pre-commit (эквивалентно ``uv sync`` + установка хуков)::

    make init

   Компоненты шага:

   * ``make install`` внутри цели вызывает ``uv sync`` (фиксация окружения из ``pyproject.toml``).
   * ``uv run pre-commit install`` — локальные git-хуки качества.

   Если нужно только синхронизировать окружение без хуков::

    uv sync

3. Скопируйте шаблон переменных и заполните значения локально (файл ``.env`` не коммитится)::

    cp .env.example .env

   Имена переменных, которые чаще всего нужны для операционного контура и NHL-сценариев:

   * ``ODDS_API_KEY`` — доступ к The Odds API (ингест коэффициентов и связанные задачи).
   * При запуске **Telegram-бота** (локально или через Compose-профиль ``bot``): ``BOT_TOKEN``, ``BOT_ALLOWED_USER_IDS``, ``BOT_ADMIN_USER_IDS``, ``BOT_API_BASE_URL``.
   * Для Compose без бота также актуальны, например: ``POSTGRES_PASSWORD``, ``GRAFANA_PASSWORD``, ``MLFLOW_TRACKING_URI``, образы ``SF_*_IMAGE`` в прод-подобных настройках — см. полный перечень в ``.env.example``.

Инициализация витрины предсказаний (SQLite / dev)
------------------------------------------------

После установки зависимостей создайте таблицы prediction store (как в типичном dev-сценарии для ``make api-dev``)::

    make db-init

Локальный API (dev)
--------------------

::

    make api-dev

По умолчанию приложение слушает ``127.0.0.1:8000`` (см. ``Makefile``, цель ``api-dev``).

Docker Compose (полный локальный стек)
---------------------------------------

Поднимите сервисы::

    make docker-up

Цель вызывает ``docker compose up -d``. Состав основных сервисов из ``docker-compose.yml``
(имена сервисов Compose):

* ``db`` — PostgreSQL (хранилище предсказаний и связанных данных; порт хоста по умолчанию ``5432``).
* ``api`` — FastAPI read-only сервер предсказаний (порт ``8000``).
* ``mlflow`` — MLflow tracking UI и backend (порт ``5000``).
* ``worker`` — образ для пакетной материализации (профиль ``worker``, не стартует автоматически с базовым ``up``).
* ``prometheus`` — сбор метрик (порт ``9090``).
* ``grafana`` — дашборды (порт ``3000``).
* ``telegram-bot`` — опционально, профиль ``bot``; зависит от ``api`` и переменных ``BOT_*``.

Airflow
-------

Один раз инициализируйте метаданные Airflow (миграции БД, пользователь admin в образе по умолчанию)::

    make airflow-init

Затем запустите webserver и scheduler::

    make airflow-up

Используются два файла Compose: ``docker-compose.yml`` и ``airflow/docker-compose.airflow.yml``.
Сервисы Airflow: ``airflow-init`` (профиль ``init``, одноразовый запуск), ``airflow-webserver``
(UI на порту ``8080``), ``airflow-scheduler``.

Утренний NHL (12:00 MSK / 09:00 UTC, R37.6)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Airflow:** DAG ``nhl_morning_refresh`` (``airflow/dags/dag_nhl_morning_refresh.py``) — расписание
``0 9 * * *`` в часовом поясе планировщика Airflow по умолчанию (**UTC**), то есть **09:00 UTC**
= **12:00 по Москве** (MSK, UTC+3). Пайплайн: ``source`` (при ``odds.enabled`` в ``conf/source/nhl.yaml``
— инкрементальный odds post-step внутри ``source_refresh``) → ingest → clean → features →
materialize для ``winner_withOT`` / ``nhl_train`` по умолчанию; затем ``validate``. Пул и ``flock``
совпадают с ``data_refresh`` (переменные ``SF_REFRESH_POOL``, ``SF_REFRESH_LOCK_FILE``, …).

Переопределения через Airflow Variables: ``SF_NHL_MORNING_TOURNAMENT``, ``SF_NHL_MORNING_FEATURES``,
``SF_NHL_MORNING_MARKET``, ``SF_NHL_MORNING_SPEC``, ``SF_NHL_MORNING_MAX_ACTIVE_RUNS`` (и др., см. DAG).

**Хостовый cron (без Airflow)** — тот же смысл, что у DAG, в локальном часовом поясе Москвы::

    CRON_TZ=Europe/Moscow
    0 12 * * * cd /path/to/repo && SF_PROJECT_DIR=/path/to/repo uv run python -m sports_forecast.orchestration.cron_refresh \
      --tournaments nhl_train --features advanced --market winner_withOT --market-spec winner_withOT \
      >> /var/log/sf_nhl_morning.log 2>&1

**Ручной запуск (эквивалент команды DAG / cron, только печать shell):** ``make nhl-morning-refresh-dry-run``.
Для реального выполнения уберите ``--dry-run`` из выведенной команды или вызовите ``cron_refresh`` с теми же аргументами.

Smoke-проверки API
------------------

При работающем API на хосте по умолчанию::

    curl -sf http://127.0.0.1:8000/health

Интерактивная документация OpenAPI::

    xdg-open http://127.0.0.1:8000/docs

(или откройте URL в браузере вручную).

Сводка: цели Makefile и эффект
------------------------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Цель
     - Эффект (кратко)
   * - ``make init``
     - ``uv sync`` + установка pre-commit хуков (полная первичная настройка окружения разработчика).
   * - ``uv sync`` / ``make install``
     - Установка и синхронизация зависимостей Python через uv из ``pyproject.toml``.
   * - ``make db-init``
     - Создание таблиц prediction store через ``init_db()`` (типичный dev-путь к SQLite).
   * - ``make api-dev``
     - Локальный FastAPI с hot-reload на ``127.0.0.1:8000`` (dev, SQLite по конфигу сервиса).
   * - ``make docker-up``
     - Запуск стека из ``docker-compose.yml``: PostgreSQL, API, MLflow, Prometheus, Grafana (и др. по файлу).
   * - ``make airflow-init``
     - Одноразовая инициализация БД Airflow и создание admin-пользователя (Compose-профиль ``init``).
   * - ``make airflow-up``
     - Фоновый запуск Airflow webserver и scheduler поверх общего ``docker-compose.yml``.
   * - ``make nhl-morning-refresh-dry-run``
     - Печать shell-команды утреннего NHL-refresh (как DAG ``nhl_morning_refresh``), без выполнения.

Дополнительные замечания
~~~~~~~~~~~~~~~~~~~~~~~~

* Полная сборка HTML-документации проекта: ``make docs`` из корня репозитория.
* Остановка Compose-стека: ``make docker-down``; Airflow: ``make airflow-down``.
