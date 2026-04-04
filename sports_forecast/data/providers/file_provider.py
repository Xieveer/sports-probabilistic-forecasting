"""Локальный провайдер: существующий CSV в ``data/source/<name>/source.csv``."""

from __future__ import annotations

from pathlib import Path

from omegaconf import DictConfig

from sports_forecast.config.loaders import PROJECT_ROOT as CONFIG_PROJECT_ROOT
from sports_forecast.data.providers.base import SourceDataNotFoundError, SourceProvider
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class FileSourceProvider(SourceProvider):
    """Обёртка над прежней файловой схемой ingest.

    Возвращает путь к ``{source_dir}/{source_name}/source.csv`` без чтения файла;
    чтение с прежними параметрами ``pandas.read_csv`` остаётся в :mod:`ingest`.
    """

    def __init__(self, paths_cfg: DictConfig, project_root: Path | None = None) -> None:
        """
        Args:
            paths_cfg: Конфиг путей (поле ``paths.source_dir`` относительно корня проекта).
            project_root: Корень репозитория; по умолчанию совпадает с ``config.loaders``.
        """
        self._project_root = project_root if project_root is not None else CONFIG_PROJECT_ROOT
        self._source_dir = Path(paths_cfg.paths.source_dir)

    def fetch(self, source_name: str) -> Path:
        source_csv = self._project_root / self._source_dir / source_name / "source.csv"
        if not source_csv.exists():
            logger.debug("FileSourceProvider: файл не найден: %s", source_csv)
            raise SourceDataNotFoundError(f"Исходный файл не найден: {source_csv}")
        return source_csv

    def is_available(self) -> bool:
        root = self._project_root / self._source_dir
        return root.is_dir()
