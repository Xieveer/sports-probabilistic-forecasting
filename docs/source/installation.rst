
Установка
=========

Требования
----------

* Python >= 3.10
* uv (менеджер пакетов)

Установка через uv
------------------

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

    make lint
