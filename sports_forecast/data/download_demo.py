"""
Скрипт загрузки демо-данных с Яндекс.Диска.

Назначение:
    - скачать небольшой публичный файл с Я.Диска
    - сохранить его в data/source/{tournament}/source.json (или .csv)
    - чтобы можно было запустить весь пайплайн на демо-данных:

        make download-demo-data
        make dvc-repro
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlencode

import requests

from sports_forecast.utils.log_config import configure_logging, get_logger


PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = get_logger(__name__)


def get_yandex_disk_download_url(public_url: str) -> str:
    """
    Преобразовать публичную ссылку Яндекс.Диска в прямую ссылку для скачивания.

    Args:
        public_url: Публичная ссылка на файл (например, https://disk.yandex.ru/d/...)

    Returns:
        Прямая ссылка для скачивания файла

    Raises:
        requests.HTTPError: Если не удалось получить ссылку для скачивания
        ValueError: Если в ответе API отсутствует ссылка для скачивания
    """
    api_url = "https://cloud-api.yandex.net/v1/disk/public/resources/download?"
    params = {"public_key": public_url}

    logger.info("Получаю прямую ссылку для скачивания с Яндекс.Диска...")
    response = requests.get(api_url + urlencode(params), timeout=30)
    response.raise_for_status()

    response_data: dict[str, str] = response.json()
    download_url = response_data.get("href")

    if not download_url:
        raise ValueError("Не удалось получить ссылку для скачивания из ответа API")

    logger.info("Прямая ссылка получена")
    return download_url


def download_file(url: str, dst: Path, is_yandex_disk: bool = False) -> None:
    """
    Скачать файл по HTTP и сохранить на диск.

    Args:
        url: URL для скачивания (публичная ссылка или прямая)
        dst: Путь для сохранения файла
        is_yandex_disk: Если True, преобразует публичную ссылку Я.Диска в прямую
    """
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Если это Яндекс.Диск, получаем прямую ссылку
    if is_yandex_disk or "disk.yandex" in url:
        url = get_yandex_disk_download_url(url)

    logger.info("Скачиваю файл:\n  url=%s\n  → %s", url, dst)

    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with dst.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    size_kb = dst.stat().st_size / 1024
    logger.info("Файл загружен: %s (%.1f KB)", dst, size_kb)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Загрузка демо-данных с Yandex.Disk в data/source/{tournament}/source.csv",
    )
    parser.add_argument(
        "--url",
        required=True,
        help=(
            "Публичная ссылка на файл с Яндекс.Диска (например, https://disk.yandex.ru/d/...) "
            "или прямая ссылка на скачивание с другого источника."
        ),
    )
    parser.add_argument(
        "--tournament",
        default="uel",
        help="Имя турнира/подпапки в data/source (по умолчанию: uel).",
    )
    parser.add_argument(
        "--filename",
        default="source.csv",
        help="Имя файла в data/source/{tournament}/ (по умолчанию: source.csv).",
    )
    return parser.parse_args()


def main() -> None:
    configure_logging()
    args = parse_args()

    source_root = PROJECT_ROOT / "data" / "source"
    dst = source_root / args.tournament / args.filename

    download_file(args.url, dst, is_yandex_disk=True)

    logger.info(
        "Готово. Демо-данные лежат в: %s\nТеперь можно запустить пайплайн: `make dvc-repro`",
        dst,
    )


if __name__ == "__main__":
    main()
