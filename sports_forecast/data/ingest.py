"""Модуль загрузки и первичной обработки данных матчей.

Этот модуль отвечает за преобразование исходных данных из CSV формата
в оптимизированный Parquet формат для дальнейшей обработки.

Основные функции:
    - Чтение CSV файлов с данными матчей
    - Конвертация в Parquet формат
    - Валидация структуры данных
    - Логирование процесса обработки

Структура данных:
    - Входные данные: data/source/{tournament_name}/source.csv
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

from sports_forecast.utils.log_config import get_logger


#: Корневая директория проекта
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Директория с исходными CSV файлами
DATA_SOURCE_DIR = PROJECT_ROOT / "data" / "source"

#: Директория для сырых данных в Parquet формате
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"

#: Логгер модуля для отслеживания процесса загрузки
logger = get_logger(__name__)


def process_tournament(source_dir: Path, raw_root: Path) -> None:
    """Обработать один турнир: CSV → Parquet (ингест данных).

    Читает CSV файл с данными матчей турнира и конвертирует его
    в оптимизированный Parquet формат для дальнейшей обработки.

    Args:
        source_dir: Путь к директории турнира в data/source.
            Ожидается структура: source_dir/source.csv
        raw_root: Корневая директория для сохранения Parquet файлов.
            Обычно это data/raw

    Returns:
        None

    Raises:
        FileNotFoundError: Если файл source.csv не найден (логируется warning).
        pd.errors.ParserError: Если CSV файл имеет неверный формат.

    Examples:
        >>> from pathlib import Path
        >>> source_path = Path("data/source/premier_league_2023")
        >>> raw_path = Path("data/raw")
        >>> process_tournament(source_path, raw_path)

    Note:
        Функция автоматически создает необходимые директории для выходных данных.
        Если файл source.csv отсутствует, турнир пропускается с предупреждением.
        Все колонки сохраняются как строки для избежания проблем с типами.

    Todo:
        * Добавить валидацию схемы CSV
        * Реализовать обработку ошибок парсинга
        * Добавить поддержку сжатия Parquet файлов
        * Добавить автоопределение разделителя CSV
    """
    tournament_name = source_dir.name
    source_csv = source_dir / "source.csv"
    output_parquet = raw_root / tournament_name / "matches.parquet"

    logger.info("=" * 60)
    logger.info("НАЧАЛО ОБРАБОТКИ ТУРНИРА: %s", tournament_name)
    logger.info("Ищу файл: %s", source_csv)
    logger.info("Файл существует: %s", source_csv.exists())
    logger.info("=" * 60)

    if not source_csv.exists():
        logger.warning("Пропускаю турнир %s: файл %s отсутствует", tournament_name, source_csv)
        return

    logger.info("Турнир %s: читаю %s", tournament_name, source_csv)

    try:
        # Читаем CSV, сохраняя все колонки как строки для избежания проблем с типами
        # low_memory=False для корректного определения типов во всем файле
        df: pd.DataFrame = pd.read_csv(
            source_csv,
            dtype=str,  # Все колонки как строки
            low_memory=False,
        )

        logger.info("Турнир %s: прочитано строк: %d", tournament_name, len(df))
        logger.info("Турнир %s: колонок: %d", tournament_name, len(df.columns))

        if df.empty:
            logger.warning("Турнир %s: CSV файл пустой, пропускаю", tournament_name)
            return

        logger.info(
            "Турнир %s: загружено %d записей, %d колонок",
            tournament_name,
            len(df),
            len(df.columns),
        )

        # Создаем директорию для выходного файла
        logger.info("Турнир %s: создаю директорию %s", tournament_name, output_parquet.parent)
        output_parquet.parent.mkdir(parents=True, exist_ok=True)

        # Сохраняем в Parquet с дополнительными параметрами
        logger.info("Турнир %s: сохраняю в %s", tournament_name, output_parquet)
        df.to_parquet(
            output_parquet,
            index=False,
            engine="pyarrow",
            compression="snappy",  # Сжатие для экономии места
        )

        # Проверяем, что файл создан
        if output_parquet.exists():
            file_size = output_parquet.stat().st_size
            logger.info(
                "Турнир %s: ✓ parquet создан → %s (размер: %.2f MB)",
                tournament_name,
                output_parquet,
                file_size / (1024 * 1024),
            )
        else:
            logger.error("Турнир %s: ✗ parquet НЕ СОЗДАН → %s", tournament_name, output_parquet)

    except pd.errors.ParserError as e:
        logger.error("Турнир %s: ошибка парсинга CSV - %s", tournament_name, e)
    except pd.errors.EmptyDataError as e:
        logger.error("Турнир %s: CSV файл пустой или поврежден - %s", tournament_name, e)
    except PermissionError as e:
        logger.error("Турнир %s: нет прав на запись - %s", tournament_name, e)
    except Exception as e:
        logger.error("Турнир %s: неожиданная ошибка - %s", tournament_name, e)
        import traceback

        logger.error("Traceback:\n%s", traceback.format_exc())


def run() -> None:
    """Запустить полный процесс ингеста данных: data/source → data/raw.

    Сканирует директорию data/source на наличие поддиректорий с турнирами
    и последовательно обрабатывает каждый турнир через process_tournament().

    Для каждого турнира:
        1. Читает source.csv
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
            INFO: Турнир premier_league_2023: читаю data/source/premier_league_2023/source.csv
            INFO: Турнир premier_league_2023: загружено 380 записей, 25 колонок

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
