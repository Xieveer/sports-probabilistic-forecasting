"""HTTP proof-of-concept: скачивание CSV по URL в ``data/source/<name>/source.csv``.

.. note::
    Proof-of-concept: достаточно для демонстрации расширения ingest через конфиг.
    Продакшен-использование (аутентификация, пагинация, лимиты) вынесено за рамки.
"""

from __future__ import annotations

from pathlib import Path

import requests
from omegaconf import DictConfig, OmegaConf
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from sports_forecast.config.loaders import PROJECT_ROOT as CONFIG_PROJECT_ROOT
from sports_forecast.data.providers.base import SourceFetchError, SourceProvider
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

_DEFAULT_TIMEOUT_SEC = 30.0
_DEFAULT_TOTAL_RETRIES = 3
_DEFAULT_BACKOFF = 0.5
_DEFAULT_STATUS_FORCELIST = (500, 502, 503, 504)


class HttpApiSourceProvider(SourceProvider):
    """Скачивает тело ответа GET и сохраняет как ``source.csv`` для дальнейшего ingest."""

    def __init__(
        self,
        provider_cfg: DictConfig,
        paths_cfg: DictConfig,
        project_root: Path | None = None,
    ) -> None:
        """
        Args:
            provider_cfg: Ветка ``provider`` из source-конфига (``url``, ``timeout_sec``, …).
            paths_cfg: Конфиг путей (``paths.source_dir``).
            project_root: Корень репозитория.
        """
        self._project_root = project_root if project_root is not None else CONFIG_PROJECT_ROOT
        self._source_dir = Path(paths_cfg.paths.source_dir)
        self._cfg = provider_cfg
        cfg_dict = OmegaConf.to_container(provider_cfg, resolve=True)
        if not isinstance(cfg_dict, dict):
            raise SourceFetchError("provider/http_api: неверная секция provider")
        url = cfg_dict.get("url")
        if not url or not isinstance(url, str):
            raise SourceFetchError(
                "provider/http_api: поле 'url' обязательно и должно быть строкой"
            )
        self._url: str = url
        self._timeout_sec = float(cfg_dict.get("timeout_sec", _DEFAULT_TIMEOUT_SEC))
        self._total_retries = int(cfg_dict.get("retries", _DEFAULT_TOTAL_RETRIES))

    def _build_session(self) -> requests.Session:
        retry = Retry(
            total=self._total_retries,
            backoff_factor=_DEFAULT_BACKOFF,
            status_forcelist=_DEFAULT_STATUS_FORCELIST,
            allowed_methods=frozenset({"GET"}),
        )
        adapter = HTTPAdapter(max_retries=retry)
        session = requests.Session()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def fetch(self, source_name: str) -> Path:
        target_dir = self._project_root / self._source_dir / source_name
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / "source.csv"
        session = self._build_session()
        try:
            response = session.get(self._url, timeout=self._timeout_sec)
            response.raise_for_status()
        except requests.HTTPError as e:
            raise SourceFetchError(f"HTTP ошибка при загрузке {self._url}: {e}") from e
        except requests.RequestException as e:
            raise SourceFetchError(f"Сетевая ошибка при загрузке {self._url}: {e}") from e
        try:
            out_path.write_bytes(response.content)
        except OSError as e:
            raise SourceFetchError(f"Не удалось записать {out_path}: {e}") from e
        logger.info(
            "HttpApiSourceProvider (PoC): сохранено %d байт → %s",
            len(response.content),
            out_path,
        )
        return out_path

    def is_available(self) -> bool:
        cfg_dict = OmegaConf.to_container(self._cfg, resolve=True)
        if isinstance(cfg_dict, dict):
            url = cfg_dict.get("url")
            return isinstance(url, str) and bool(url.strip())
        return False
