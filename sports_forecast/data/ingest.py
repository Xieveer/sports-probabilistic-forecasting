"""Модуль загрузки и первичной обработки данных матчей.

Этот модуль отвечает за преобразование исходных данных из JSON формата
в оптимизированный Parquet формат для дальнейшей обработки.

Основные функции:
    - Чтение JSON файлов с данными матчей
    - Конвертация в Parquet формат
    - Валидация структуры данных
    - Логирование процесса обработки

Структура данных:
    - Входные данные: data/source/{tournament_name}/source.json
    - Выходные данные: data/raw/{tournament_name}/matches.parquet

Attributes:
    PROJECT_ROOT (Path): Корневая директория проекта
    DATA_SOURCE_DIR (Path): Директория с исходными данными
    DATA_RAW_DIR (Path): Директория для сырых данных в Parquet формате
    logger (Logger): Логгер модуля

Example:
    Запуск обработки всех турниров::

        $ python -m sports_forecast.data.ingest

    Или через DVC::

        $ dvc repro ingest

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from sports_forecast.utils.logging import get_logger


#: Корневая директория проекта
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Директория с исходными JSON файлами
DATA_SOURCE_DIR = PROJECT_ROOT / "data" / "source"

#: Директория для сырых данных в Parquet формате
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"

#: Логгер модуля для отслеживания процесса загрузки
logger = get_logger(__name__)


def process_tournament(source_dir: Path, raw_root: Path) -> None:
    """Обработать один турнир: JSON → Parquet (ингест данных).

    Читает JSON файл с данными матчей турнира и конвертирует его
    в оптимизированный Parquet формат для дальнейшей обработки.

    Args:
        source_dir: Путь к директории турнира в data/source.
            Ожидается структура: source_dir/source.json
        raw_root: Корневая директория для сохранения Parquet файлов.
            Обычно это data/raw

    Returns:
        None

    Raises:
        FileNotFoundError: Если файл source.json не найден (логируется warning).
        pd.errors.ParserError: Если JSON файл имеет неверный формат.

    Examples:
        >>> from pathlib import Path
        >>> source_path = Path("data/source/premier_league_2023")
        >>> raw_path = Path("data/raw")
        >>> process_tournament(source_path, raw_path)

    Note:
        Функция автоматически создает необходимые директории для выходных данных.
        Если файл source.json отсутствует, турнир пропускается с предупреждением.

    Todo:
        * Добавить валидацию схемы JSON
        * Реализовать обработку ошибок парсинга
        * Добавить поддержку сжатия Parquet файлов
    """
    tournament_name = source_dir.name
    source_json = source_dir / "source.json"
    output_parquet = raw_root / tournament_name / "matches.parquet"

    if not source_json.exists():
        logger.warning("Пропускаю турнир %s: файл %s отсутствует", tournament_name, source_json)
        return

    logger.info("Турнир %s: читаю %s", tournament_name, source_json)
    df: pd.DataFrame = pd.read_json(source_json, lines=False)

    logger.info("Турнир %s: загружено %d записей", tournament_name, len(df))

    output_parquet.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_parquet, index=False)

    logger.info("Турнир %s: parquet → %s", tournament_name, output_parquet)


def run() -> None:
    """Запустить полный процесс ингеста данных: data/source → data/raw.

    Сканирует директорию data/source на наличие поддиректорий с турнирами
    и последовательно обрабатывает каждый турнир через process_tournament().

    Для каждого турнира:
        1. Читает source.json
        2. Конвертирует в DataFrame
        3. Сохраняет как matches.parquet

    Returns:
        None

    Raises:
        FileNotFoundError: Если директория data/source не существует.

    Examples:
        Запуск из командной строки::

            >>> run()
            INFO: Найдено турниров: 5
            INFO: Турнир premier_league_2023: читаю data/source/premier_league_2023/source.json
            INFO: Турнир premier_league_2023: загружено 380 записей

        Или через Python API::

            >>> from sports_forecast.data.ingest import run
            >>> run()

    See Also:
        process_tournament: Обработка отдельного турнира

    Note:
        Функция использует pathlib.Path для кросс-платформенной совместимости.
        Все пути разрешаются относительно корня проекта.
    """
    if not DATA_SOURCE_DIR.exists():
        raise FileNotFoundError(f"Каталог с источниками не найден: {DATA_SOURCE_DIR}")

    tournaments = sorted(p for p in DATA_SOURCE_DIR.iterdir() if p.is_dir())
    if not tournaments:
        logger.warning("В %s не найдено ни одного турнира", DATA_SOURCE_DIR)
        return

    logger.info("Найдено турниров: %d", len(tournaments))

    for tournament_dir in tournaments:
        process_tournament(tournament_dir, DATA_RAW_DIR)


if __name__ == "__main__":
    run()
