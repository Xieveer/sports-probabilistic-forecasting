"""Провайдер источника :class:`NhlWebApiSourceProvider` для ingest."""

from __future__ import annotations

from pathlib import Path

from omegaconf import DictConfig, OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT as CONFIG_PROJECT_ROOT
from sports_forecast.data.providers.base import SourceFetchError, SourceProvider
from sports_forecast.data.providers.nhl.assembler import (
    NhlDataAssembler,
    load_assembler_config,
    resolve_incremental_date_from,
)
from sports_forecast.data.providers.nhl.client import NhlApiClient
from sports_forecast.data.providers.nhl.schedule import clear_schedule_progress
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class NhlWebApiSourceProvider(SourceProvider):
    """Скачивание матчей NHL по Web API и запись ``source.csv`` для ``ingest``.

    Путь: ``{project_root}/{source_dir}/{source_name}/source.csv``.
    Детальные параметры — в ``conf/source/<name>.yaml``, секция ``provider``.
    """

    def __init__(
        self,
        source_cfg: DictConfig,
        paths_cfg: DictConfig,
        project_root: Path | None = None,
    ) -> None:
        """
        Args:
            source_cfg: Полный source-конфиг Hydra (нужна ветка ``provider`` с ``type: nhl_web_api``).
            paths_cfg: Конфиг путей с полем ``paths.source_dir``.
            project_root: Корень репозитория; по умолчанию как в :mod:`sports_forecast.config.loaders`.
        """
        prov = source_cfg.get("provider") if source_cfg is not None else None
        if prov is None:
            raise SourceFetchError("nhl_web_api: нет секции provider")
        self._project_root = project_root if project_root is not None else CONFIG_PROJECT_ROOT
        self._source_dir = Path(paths_cfg.paths.source_dir)
        self._source_cfg = source_cfg
        self._client = NhlApiClient(prov)
        self._asm_cfg = load_assembler_config(prov)

    def fetch(self, source_name: str) -> Path:
        """Выполнить загрузку из API и вернуть путь к готовому CSV.

        Args:
            source_name: Имя каталога под ``data/source`` (как у турнира при ingest).

        Returns:
            Путь к ``source.csv``.

        Raises:
            SourceFetchError: Ошибка записи файла или конфигурации на этапе инициализации.
        """
        target_dir = self._project_root / self._source_dir / source_name
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / "source.csv"

        asm_cfg = resolve_incremental_date_from(self._asm_cfg, out_path)
        logger.info(
            "NhlWebApiSourceProvider: старт загрузки source_name=%s, интервал %s … %s (incremental=%s)",
            source_name,
            asm_cfg.date_from.isoformat(),
            asm_cfg.date_to.isoformat(),
            asm_cfg.incremental,
        )
        assembler = NhlDataAssembler(self._client, asm_cfg)
        try:
            df = assembler.build_dataframe(
                checkpoint_base=target_dir,
                output_csv_path=out_path,
            )
        except OSError as e:
            raise SourceFetchError(f"Не удалось записать {out_path}: {e}") from e

        if self._asm_cfg.schedule_progress_file:
            sp = target_dir / self._asm_cfg.schedule_progress_file
            clear_schedule_progress(sp)
            logger.info(
                "NhlWebApiSourceProvider: удалён снимок расписания %s (успешное завершение)", sp
            )

        logger.info(
            "NhlWebApiSourceProvider: %d строк → %s",
            len(df),
            out_path,
        )
        return out_path

    def is_available(self) -> bool:
        """Доступен, если в конфиге явно указан ``provider.type == nhl_web_api``."""
        merged = OmegaConf.to_container(self._source_cfg, resolve=True)
        if not isinstance(merged, dict):
            return False
        prov = merged.get("provider")
        return isinstance(prov, dict) and prov.get("type") == "nhl_web_api"
