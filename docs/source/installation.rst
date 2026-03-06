
Установка
=========

Требования
----------

* Python >= 3.10
* uv (менеджер пакетов)
* Docker + Docker Compose (для сервисов)

Установка через uv
-------------------

1. Клонируйте репозиторий::

    git clone <repository-url>
    cd SportsProbabilisticForecasting

2. Установите зависимости::

    make install

   Или напрямую через uv::

    uv sync

3. Инициализируйте pre-commit хуки::

    make init

Проверка установки
------------------

Запустите тесты::

    make test

Проверьте качество кода::

    make pre-commit

Docker-окружение
----------------

Для запуска полного стека сервисов::

    # Сборка образов
    make docker-build

    # Запуск (PostgreSQL, MLflow, FastAPI, Worker)
    make docker-up

    # Остановка
    make docker-down

Airflow
-------

::

    make airflow-init   # Инициализация БД
    make airflow-up     # Запуск
    make airflow-down   # Остановка

Мониторинг
----------

::

    make monitor-up     # Prometheus + Grafana
    make monitor-down   # Остановка
