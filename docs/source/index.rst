.. Sports Probabilistic Forecasting documentation master file, created by
   sphinx-quickstart on Mon Dec  8 02:18:29 2025.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Sports Probabilistic Forecasting
=================================

Сервис вероятностного прогнозирования исходов спортивных событий.

.. toctree::
   :maxdepth: 2
   :caption: Содержание:

   installation
   quickstart
   api/index

Описание проекта
----------------

Sports Probabilistic Forecasting - это ML-система для предсказания результатов спортивных матчей
с использованием вероятностных моделей.

Основные возможности
~~~~~~~~~~~~~~~~~~~~

* Загрузка и обработка данных о спортивных матчах
* Очистка и создание признаков
* Обучение моделей машинного обучения
* Вероятностное прогнозирование результатов

Быстрый старт
-------------

Установка зависимостей::

    make install

Запуск обработки данных::

    make dvc-repro

Структура проекта
-----------------

.. code-block:: text

    sports_forecast/
    ├── data/           # Модуль загрузки данных
    ├── features/       # Модуль обработки признаков
    └── utils/          # Вспомогательные утилиты

Индексы и таблицы
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
