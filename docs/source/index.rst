Sports Probabilistic Forecasting
=================================

MLOps-система вероятностного прогнозирования исходов спортивных событий
для value-беттинга.

.. toctree::
   :maxdepth: 2
   :caption: Руководства:

   installation
   quickstart
   feature_selection_workflow

.. toctree::
   :maxdepth: 2
   :caption: API Reference:

   api/index

.. toctree::
   :maxdepth: 1
   :caption: Архитектура:

   architecture

Обзор
-----

Проект представляет собой конфиг-управляемый ML-движок:

* **Data Pipeline** (DVC): ``source → raw → interim → processed``
* **Training Pipeline** (Hydra + MLflow): модели, калибровка, метрики
* **Inference API** (FastAPI): предвычисленные предикты из БД
* **Orchestration** (Airflow): фоновые задачи по расписанию
* **Monitoring** (Prometheus + Grafana): drift, performance, alerts

Поддерживаемые спорты
~~~~~~~~~~~~~~~~~~~~~

* **Cyberhockey** — UEL (Kazakhstan, Czech Republic)
* **Table Tennis** — Liga Pro (Russia, Europe, Belarus)

Технологический стек
~~~~~~~~~~~~~~~~~~~~

* Python 3.10+, Hydra, DVC, MLflow
* CatBoost, LightGBM, Logistic Regression, Stacking Ensemble
* FastAPI, SQLAlchemy, PostgreSQL/SQLite
* Airflow, Docker Compose
* Prometheus, Grafana, Pandera

Индексы и таблицы
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
