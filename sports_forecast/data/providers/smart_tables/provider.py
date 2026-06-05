"""Провайдер источника Smart Tables API для ingest."""

from __future__ import annotations

from pathlib import Path

from omegaconf import DictConfig, OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT as CONFIG_PROJECT_ROOT
from sports_forecast.data.providers.base import SourceFetchError, SourceProvider
from sports_forecast.data.providers.smart_tables.assembler import (
    SmartTablesDataAssembler,
    load_assembler_config,
)
from sports_forecast.data.providers.smart_tables.client import SmartTablesApiClient
from sports_forecast.data.providers.smart_tables.incremental import run_incremental
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class SmartTablesSourceProvider(SourceProvider):
    """Скачивание матчей сборных Smart Tables и запись ``source.csv``.

    Путь: ``{project_root}/{source_dir}/{source_name}/source.csv`` (как у NHL).
    Ingest-slug: ``football_nationals`` → ``data/source/football_nationals/``.
    """

    def __init__(
        self,
        source_cfg: DictConfig,
        paths_cfg: DictConfig,
        project_root: Path | None = None,
    ) -> None:
        prov = source_cfg.get("provider") if source_cfg is not None else None
        if prov is None:
            raise SourceFetchError("smart_tables_api: нет секции provider")
        self._project_root = project_root if project_root is not None else CONFIG_PROJECT_ROOT
        self._source_dir = Path(paths_cfg.paths.source_dir)
        self._source_cfg = source_cfg
        self._client = SmartTablesApiClient(prov)
        self._asm_cfg = load_assembler_config(prov)

    def fetch(self, source_name: str) -> Path:
        """Выполнить backfill или incremental и вернуть путь к ``source.csv``.

        Args:
            source_name: Имя каталога под ``data/source`` (как у турнира при ingest).

        Returns:
            Путь к ``source.csv``.
        """
        target_dir = self._project_root / self._source_dir / source_name
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / "source.csv"

        logger.info(
            "SmartTablesSourceProvider: старт mode=%s storage=%s",
            self._asm_cfg.mode,
            target_dir,
        )

        if self._asm_cfg.mode == "incremental":
            prov = OmegaConf.to_container(self._source_cfg.provider, resolve=True)
            inc = prov.get("incremental", {}) if isinstance(prov, dict) else {}
            df = run_incremental(
                self._client,
                catalog_path=self._asm_cfg.catalog_path,
                national_teams_only=self._asm_cfg.national_teams_only,
                competition_codes=self._asm_cfg.competition_codes,
                storage_dir=target_dir,
                output_csv_path=out_path,
                raw_root=target_dir / self._asm_cfg.raw_cache_dir,
                nearest_limit=int(inc.get("nearest_matches_limit", 50)),
                stat_odds_sidecar_name=str(inc.get("stat_odds_sidecar", "match_stat_odds.parquet")),
            )
        else:
            assembler = SmartTablesDataAssembler(self._client, self._asm_cfg)
            try:
                df = assembler.build_dataframe(
                    storage_dir=target_dir,
                    output_csv_path=out_path,
                )
            except OSError as e:
                raise SourceFetchError(f"Не удалось записать {out_path}: {e}") from e

        logger.info(
            "SmartTablesSourceProvider: %d строк → %s",
            len(df),
            out_path,
        )
        return out_path

    def is_available(self) -> bool:
        """Доступен при ``provider.type == smart_tables_api``."""
        merged = OmegaConf.to_container(self._source_cfg, resolve=True)
        if not isinstance(merged, dict):
            return False
        prov = merged.get("provider")
        return isinstance(prov, dict) and prov.get("type") == "smart_tables_api"
