
API Reference
=============

Полная документация API проекта Sports Probabilistic Forecasting.

.. toctree::
   :maxdepth: 2
   :caption: Модули:

   data
   features
   training
   betting
   service
   monitoring
   validation
   utils

Обзор модулей
-------------

* :doc:`data` — Загрузка (ingest) и очистка (clean) данных
* :doc:`features` — Генерация признаков, pipeline, feature selection
* :doc:`training` — Модели, trainer, калибровка, оптимизация, ансамбли
* :doc:`betting` — Симулятор ставок, работа с коэффициентами
* :doc:`service` — FastAPI приложение, БД, роутеры
* :doc:`monitoring` — Drift detection, performance, A/B testing
* :doc:`validation` — Pandera-схемы, quality gates
* :doc:`utils` — Метрики, таргеты, логирование
