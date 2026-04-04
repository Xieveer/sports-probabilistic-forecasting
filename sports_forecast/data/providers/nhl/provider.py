""":class:`NhlWebApiSourceProvider` — сбор ``source.csv`` через NHL Web API."""

from __future__ import annotations

from pathlib import Path

from omegaconf import DictConfig, OmegaConf

from sports_forecast.config.loaders import PROJECT_ROOT as CONFIG_PROJECT_ROOT
from sports_forecast.data.providers.base import SourceFetchError, SourceProvider
from sports_forecast.data.providers.nhl.assembler import NhlDataAssembler, load_assembler_config
from sports_forecast.data.providers.nhl.client import NhlApiClient
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)


class NhlWebApiSourceProvider(SourceProvider):
    """Формирует ``data/source/<name>/source.csv`` из api-web.nhle.com."""

    def __init__(
        self,
        source_cfg: DictConfig,
        paths_cfg: DictConfig,
        project_root: Path | None = None,
    ) -> None:
        prov = source_cfg.get("provider") if source_cfg is not None else None
        if prov is None:
            raise SourceFetchError("nhl_web_api: нет секции provider")
        self._project_root = project_root if project_root is not None else CONFIG_PROJECT_ROOT
        self._source_dir = Path(paths_cfg.paths.source_dir)
        self._source_cfg = source_cfg
        self._client = NhlApiClient(prov)
        self._asm_cfg = load_assembler_config(prov)

    def fetch(self, source_name: str) -> Path:
        target_dir = self._project_root / self._source_dir / source_name
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / "source.csv"

        assembler = NhlDataAssembler(self._client, self._asm_cfg)
        df = assembler.build_dataframe(checkpoint_base=target_dir)

        try:
            df.to_csv(out_path, index=False)
        except OSError as e:
            raise SourceFetchError(f"Не удалось записать {out_path}: {e}") from e

        logger.info(
            "NhlWebApiSourceProvider: %d строк → %s",
            len(df),
            out_path,
        )
        return out_path

    def is_available(self) -> bool:
        merged = OmegaConf.to_container(self._source_cfg, resolve=True)
        if not isinstance(merged, dict):
            return False
        prov = merged.get("provider")
        return isinstance(prov, dict) and prov.get("type") == "nhl_web_api"
