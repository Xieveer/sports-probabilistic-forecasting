
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
materialize для ``winner_withOT`` / ``nhl`` по умолчанию; затем ``validate``. Пул и ``flock``
совпадают с ``data_refresh`` (переменные ``SF_REFRESH_POOL``, ``SF_REFRESH_LOCK_FILE``, …).

Переопределения через Airflow Variables: ``SF_NHL_MORNING_TOURNAMENT``, ``SF_NHL_MORNING_FEATURES``,
``SF_NHL_MORNING_MARKET``, ``SF_NHL_MORNING_SPEC``, ``SF_NHL_MORNING_MAX_ACTIVE_RUNS`` (и др., см. DAG).

**Хостовый cron (без Airflow)** — тот же смысл, что у DAG, в локальном часовом поясе Москвы::

    CRON_TZ=Europe/Moscow
    0 12 * * * cd /path/to/repo && SF_PROJECT_DIR=/path/to/repo uv run python -m sports_forecast.orchestration.cron_refresh \
      --tournaments nhl --features advanced --market winner_withOT --market-spec winner_withOT \
      >> /var/log/sf_nhl_morning.log 2>&1

**Ручной запуск (эквивалент команды DAG / cron, только печать shell):** ``make nhl-morning-refresh-dry-run``.
Для реального выполнения уберите ``--dry-run`` из выведенной команды или вызовите ``cron_refresh`` с теми же аргументами.

**Полный пайплайн без Telegram:** ``make nhl-morning-refresh`` (``cron_refresh`` + ``run_validation``).

**Тест с паузой до ближайшей целой минуты по МСК + offset и уведомлением в Telegram:** ``make nhl-morning-test-notify``
(скрипт ``scripts/run_nhl_refresh_notify.py``; в ``.env`` — ``BOT_TOKEN``, ``BOT_ALLOWED_USER_IDS``; API должен отвечать на ``BOT_API_BASE_URL`` или ``http://127.0.0.1:8000``).

.. note::

   Сценарий ``make nhl-morning-test-notify`` / ``run_nhl_refresh_notify.py`` — **временный**
   операционный обходной путь (отдельный процесс вне DAG). **Целевой prod-like контракт**
   эпика **R39** — один триггер Airflow ``nhl_morning_refresh``, который после ``validate``
   завершается шагом **digest** в том же стеке (см. подраздел ниже). Описание Variables/окружения
   ниже рассчитано на этот контракт; детали реализации — в ``docs/cursor/refactor/backlog/R39.md``
   (задачи R39.4–R39.5).

Prod-like E2E (R39)
~~~~~~~~~~~~~~~~~~~

**Цель:** зафиксировать ту же **упорядоченную** цепочку, что ожидается в production: после
обновления данных и материализации (promoted-модель) оператор получает **одно** согласованное
Telegram-сообщение (сводка / edge vs live Pinnacle), не наращивая параллельный refresh и не
обходя **pool** и **flock** на контуре refresh.

Целевой порядок стадий (контракт)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Для DAG ``nhl_morning_refresh`` (и аналогично для обобщения на ``data_refresh``):

1. **Триггер** — расписание или ручной запуск в UI Airflow (DAG не ставится на паузу).
2. **refresh** (задача ``refresh_nhl_morning`` / ``refresh_per_tournament``) —
   ``source`` (при ``odds.enabled`` в ``conf/source/nhl.yaml`` — инкрементальный Odds post-step
   внутри ``source_refresh``) → ``ingest`` → ``clean`` → ``features`` → ``materialize`` для
   параметров турнира/рынка (в утреннем DAG по умолчанию NHL / ``winner_withOT``, фичи
   ``advanced``; promoted-модель — как в контуре ``build_refresh_per_tournament_command``).
3. **validate** — ``python -m sports_forecast.validation.run_validation`` в каталоге проекта.
4. **digest** *(R39.4 CLI; DAG ``nhl_morning_refresh`` — R39.5)* — после ``validate`` задача Airflow
   ``post_refresh_digest`` (тот же refresh-пул, последовательное ребро ``validate >> post_refresh_digest``):
   чтение из **той же** БД prediction store, при необходимости Odds API, одно Telegram-сообщение.
   Ручной эквивалент — модуль :mod:`sports_forecast.orchestration.post_refresh_digest` (см. подраздел ниже).
   Включение/skip и override команды — Airflow Variables ``SF_TELEGRAM_DIGEST_ENABLE``,
   ``SF_POST_REFRESH_DIGEST_CMD`` (см. блок «Планируемый контракт digest» ниже и docstring DAG).

Используется **LocalExecutor**: команды Bash выполняются в процессе **scheduler**, поэтому
переменные окружения для Odds и Telegram должны быть доступны **контейнеру Airflow** (см. блок
env ниже), а не только сервису ``api``.

Чеклист: от триггера DAG до сообщения (целевой)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Для DAG ``nhl_morning_refresh`` ориентируйтесь на последовательность:

#. Локально: ``make docker-up``, при необходимости ``make airflow-init`` (один раз), затем
   ``make airflow-up``; в ``.env`` заданы пароль БД, при необходимости — ``ODDS_API_KEY``,
   ``BOT_TOKEN``, ``BOT_ALLOWED_USER_IDS`` (и проброс в сервисы Airflow — см. ниже).
#. В Airflow UI создан пул слотов с именем по умолчанию ``sf_refresh_pool`` (или измените Variable
   ``SF_REFRESH_POOL`` и создайте пул с новым именем); иначе задачи зависнут в очереди.
#. Заданы **Airflow Variables** (или эквивалент через префикс ``AIRFLOW_VAR_`` в Compose), как
   минимум ``SF_PROJECT_DIR`` / ``SF_UV_RUN``; при отличии от дефолтов — lock/pool (таблица ниже).
#. DAG ``nhl_morning_refresh`` включён (unpaused); при тесте — **Trigger DAG**.
#. Дождаться успешных ``refresh_nhl_morning``, ``validate`` и ``post_refresh_digest`` — успех и одно
   сообщение в Telegram / или осмысленный текст при отсутствии ключа Odds (или runtime-skip digest
   через Variable ``SF_TELEGRAM_DIGEST_ENABLE``).

Для проверки уведомления **вне** Airflow по-прежнему можно ``make nhl-morning-test-notify`` — это
обходной путь, а не замена задачи ``post_refresh_digest`` в DAG.

Post-refresh digest CLI (R39.4)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Модуль ``sports_forecast.orchestration.post_refresh_digest`` читает предстоящие матчи из той же витрины,
что и ``GET /predict/upcoming/{tournament}`` (через ``PredictionRepository.get_upcoming_predictions``),
обогащает batch'ем live Pinnacle (как HTTP-слой при ``live_pinnacle=true``), собирает **одно** сообщение
и либо печатает его (``--dry-run``), либо отправляет в Telegram через ``sendMessage`` (без aiogram).

**Проверка текста без Telegram** (нужны доступ к БД и файл ``models/<tournament>/<market_spec>/best/deploy.yaml``)::

   uv run python -m sports_forecast.orchestration.post_refresh_digest --dry-run

С явным корнем репозитория и окном 72 ч::

   uv run python -m sports_forecast.orchestration.post_refresh_digest --dry-run \
     --project-root /path/to/SportsProbabilisticForecasting --hours 72

**Отправка в Telegram** (в ``.env`` или окружении: ``BOT_TOKEN``, ``BOT_ALLOWED_USER_IDS`` — берётся **первый**
id из списка через запятую; для live Pinnacle — ``ODDS_API_KEY``)::

   uv run python -m sports_forecast.orchestration.post_refresh_digest \
     --project-root /path/to/SportsProbabilisticForecasting

Переменная ``SF_TELEGRAM_DIGEST_ENABLE`` со значениями ``0``, ``false``, ``no`` (без учёта регистра) отключает
запуск **без** ``--dry-run`` (выход ``0``, БД не трогается). C ``--dry-run`` отключение **не** действует:
можно отладить текст и витрину, не отправляя сообщение. Если ``deploy.yaml`` отсутствует, при **отправке**
команда завершится с кодом ``1``; при ``--dry-run`` в теле будет предупреждение, код ``0``.

Airflow Variables: ``nhl_morning_refresh`` и ``data_refresh``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Значения задаются в **Admin → Variables** или через окружение вида ``AIRFLOW_VAR_<KEY>`` (см.
``airflow/docker-compose.airflow.yml``). Дефолты в коде — в скобках.

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Variable
     - Назначение
   * - ``SF_PROJECT_DIR``
     - Корень репозитория внутри контейнера (``/app``).
   * - ``SF_UV_RUN``
     - Префикс запуска Python (``uv run``).
   * - ``SF_SOURCE_REFRESH_CMD``
     - Шаблон команды source-stage; ``{tournament}`` подставляется в команду refresh.
   * - ``SF_REFRESH_POOL``
     - Имя **pool** для тяжёлых Bash-задач (по умолчанию ``sf_refresh_pool``).
   * - ``SF_REFRESH_LOCK_FILE``
     - Путь к lock ``flock`` (по умолчанию ``/tmp/sf_refresh_pipeline.lock``).
   * - ``SF_REFRESH_LOCK_WAIT_SECONDS``
     - Таймаут ожидания lock, секунды (целое; по умолчанию ``300``).

**Только ``data_refresh``**

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Variable
     - Назначение
   * - ``SF_REFRESH_TOURNAMENTS``
     - Список турниров через запятую.
   * - ``SF_FEATURES_CONFIG``
     - Конфиг фич (по умолчанию ``basic``).
   * - ``SF_MATERIALIZE_MARKET`` / ``SF_MATERIALIZE_SPEC``
     - Рынок и спека материализации.

**Только ``nhl_morning_refresh``**

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Variable
     - Назначение
   * - ``SF_NHL_MORNING_TOURNAMENT``, ``SF_NHL_MORNING_FEATURES``, ``SF_NHL_MORNING_MARKET``, ``SF_NHL_MORNING_SPEC``
     - Параметры утреннего NHL-контура (дефолты: ``nhl``, ``advanced``, ``winner_withOT``).
   * - ``SF_NHL_MORNING_MAX_ACTIVE_RUNS`` / ``SF_NHL_MORNING_MAX_ACTIVE_TASKS``
     - Лимиты параллелизма самого DAG (по умолчанию ``1`` / ``1``).

**Примечание:** у ``data_refresh`` свои имена для лимитов DAG — ``SF_REFRESH_MAX_ACTIVE_RUNS`` /
``SF_REFRESH_MAX_ACTIVE_TASKS`` (дефолт ``1``); при тюнинге не путать с ``SF_NHL_MORNING_*``.

Переменные окружения (Compose, API, бот, воркеры Airflow)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Имена без значений — см. ``.env.example`` и ``docs/deploy/secrets.md``.

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Переменная
     - Где нужна
   * - ``DATABASE_URL``
     - **Prediction store:** в ``docker-compose.yml`` задана для ``api``, ``worker``; в
       ``airflow/docker-compose.airflow.yml`` — для сервисов Airflow (та же БД, что у API).
       Для хостового CLI можно задать в ``.env`` (см. комментарий в шаблоне).
   * - ``POSTGRES_PASSWORD`` (и косвенно строка подключения)
     - Сборка URL БД в Compose.
   * - ``ODDS_API_KEY``
     - The Odds API: **ingest/source_refresh** на соответствующих турнирах; обогащение live Pinnacle
       в **API** (``GET /predict/...`` с ``live_pinnacle``). Для **digest** (R39) тот же ключ должен
       быть доступен процессу, выполняющему шаг digest (контейнер Airflow при LocalExecutor).
   * - ``BOT_TOKEN``, ``BOT_ALLOWED_USER_IDS``, ``BOT_ADMIN_USER_IDS``, ``BOT_API_BASE_URL``
     - Сервис ``telegram-bot`` (профиль ``bot``); **digest** (R39) будет использовать те же секреты
       для отправки операционного сообщения (получатели — как минимум из ``BOT_ALLOWED_USER_IDS``,
       точный контракт — R39.3).
   * - ``MLFLOW_TRACKING_URI``
     - Worker / Airflow-контур (в compose — ``http://mlflow:5000``).

В шаблоне ``airflow/docker-compose.airflow.yml`` сейчас **не** пробрасываются ``ODDS_API_KEY`` и
``BOT_*`` из хостового ``.env``. После внедрения digest (R39.5/R39.6) для полного parity добавьте
их в ``environment`` блока ``x-airflow-common`` (или подключите ``env_file``), не логируя значения.

Контракт digest в Airflow (R39.4–R39.5)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* **Airflow Variable** ``SF_TELEGRAM_DIGEST_ENABLE`` — runtime-skip шага ``post_refresh_digest`` в
  ``dag_nhl_morning_refresh`` (значения ``0``, ``false``, ``no``, ``off`` без учёта регистра; по
  умолчанию включено). Отдельно от этого CLI при ручном запуске учитывает **env**
  ``SF_TELEGRAM_DIGEST_ENABLE`` (см. модуль :mod:`sports_forecast.orchestration.post_refresh_digest`).
* **Airflow Variable** ``SF_POST_REFRESH_DIGEST_CMD`` — непустая строка задаёт полную shell-команду
  после ``cd`` в ``SF_PROJECT_DIR`` (в шаблоне — ``bash -lc``); иначе вызывается
  ``SF_UV_RUN python -m sports_forecast.orchestration.post_refresh_digest`` с аргументами из
  ``dag_run.conf`` / ``params``.
* Переменные окружения уровня **бота** (``BOT_TOKEN``, ``BOT_ALLOWED_USER_IDS``, …) — для отправки
  сообщения из задачи digest.

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
   * - ``make nhl-morning-refresh``
     - Выполнить полный утренний ``cron_refresh`` для ``nhl`` / ``winner_withOT`` + ``run_validation`` (без Telegram).
   * - ``make nhl-morning-test-notify``
     - Пауза до ближайшей минуты МСК + offset, затем тот же refresh + validate и сводка ``/predict/upcoming/nhl`` в Telegram.

Дополнительные замечания
~~~~~~~~~~~~~~~~~~~~~~~~

* Полная сборка HTML-документации проекта: ``make docs`` из корня репозитория.
* Остановка Compose-стека: ``make docker-down``; Airflow: ``make airflow-down``.
