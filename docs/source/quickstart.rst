
Быстрый старт
==============

Data Pipeline (DVC)
-------------------

Пайплайн данных управляется через DVC и состоит из трёх стадий:

1. **Ingest** — ``source → raw`` (CSV → Parquet, split по турнирам)
2. **Clean** — ``raw → interim`` (типизация, маппинг, валидация)
3. **Features** — ``interim → processed`` (генерация фичей, long/wide)

Запуск полного пайплайна::

    make dvc-repro

Поэтапно::

    uv run python -m sports_forecast.data.ingest
    uv run python -m sports_forecast.data.clean
    uv run python -m sports_forecast.features.features_build --multirun \
        tournament=uel_kz_1,uel_kz_2,uel_cz,lp_ru,lp_eu,lp_eu_a18,lp_by \
        features=advanced

Наборы фичей
~~~~~~~~~~~~~

* ``features=basic`` — минимальный набор (~19–25 фичей), для быстрых тестов
* ``features=advanced`` — полный набор (~52–75 фичей), для экспериментов

Переключение через ``params.yaml``:

.. code-block:: yaml

    features:
      config: advanced   # или basic

Обучение моделей
-----------------

Обучение запускается через Hydra CLI, результаты логируются в MLflow::

    # Одиночный эксперимент
    uv run python -m sports_forecast.train \
        tournament=uel_kz_1 \
        market=winner \
        market_spec=winner \
        algorithm=catboost \
        features=advanced

    # Multirun по всем турнирам
    uv run python -m sports_forecast.train --multirun \
        tournament=uel_kz_1,uel_kz_2,uel_cz,lp_ru,lp_eu,lp_eu_a18,lp_by \
        market=winner market_spec=winner algorithm=catboost features=advanced

Или через Makefile::

    make train TOURNAMENT=uel_kz_1 MARKET=winner SPEC=winner ALG=catboost FEAT=advanced

Просмотр результатов
---------------------

MLflow UI::

    make mlflow-ui
    # Открыть http://127.0.0.1:5000

FastAPI (prediction API)::

    make api-dev
    # Swagger: http://127.0.0.1:8000/docs

Валидация данных
-----------------

Проверка качества данных через Pandera::

    make validate-data

Сборка документации
--------------------

::

    cd docs && make html
    # Результат: docs/build/index.html
