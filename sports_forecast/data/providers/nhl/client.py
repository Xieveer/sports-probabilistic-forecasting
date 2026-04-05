"""HTTP-клиент для NHL Web API: User-Agent, rate limit, retry."""

from __future__ import annotations

import json
import time
from typing import Any

import requests
from omegaconf import DictConfig, OmegaConf
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from sports_forecast.data.providers.base import SourceFetchError
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

_DEFAULT_BASE = "https://api-web.nhle.com/v1"
_DEFAULT_TIMEOUT = 45.0
_DEFAULT_RETRIES = 3
_DEFAULT_BACKOFF = 0.6
_DEFAULT_MIN_DELAY = 0.55
_DEFAULT_UA = "SportsProbabilisticForecasting/1.0 (+https://github.com/local)"
_STATUS_FORCELIST = (429, 500, 502, 503, 504)


class NhlApiClient:
    """HTTP-клиент к ``api-web.nhle.com`` с User-Agent, паузой между запросами и ретраями.

    Параметры сессии задаются веткой ``provider`` в ``conf/source/nhl.yaml``
    (``base_url``, ``timeout_sec``, ``min_delay_sec``, ``retries``, …).
    """

    def __init__(
        self,
        provider_cfg: DictConfig | dict[str, Any],
    ) -> None:
        """
        Args:
            provider_cfg: Секция ``provider`` из source-конфига или эквивалентный dict.
        """
        cfg = OmegaConf.to_container(provider_cfg, resolve=True)
        if not isinstance(cfg, dict):
            raise SourceFetchError("nhl_web_api: неверная секция provider")

        base = str(cfg.get("base_url", _DEFAULT_BASE)).rstrip("/")
        self._base_url = base
        self._timeout = float(cfg.get("timeout_sec", _DEFAULT_TIMEOUT))
        self._min_delay = float(cfg.get("min_delay_sec", _DEFAULT_MIN_DELAY))
        self._user_agent = str(cfg.get("user_agent", _DEFAULT_UA))
        retries = int(cfg.get("retries", _DEFAULT_RETRIES))
        backoff = float(cfg.get("backoff_factor", _DEFAULT_BACKOFF))

        retry = Retry(
            total=retries,
            backoff_factor=backoff,
            status_forcelist=_STATUS_FORCELIST,
            allowed_methods=frozenset({"GET"}),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session = requests.Session()
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._session.headers.update(
            {
                "User-Agent": self._user_agent,
                "Accept": "application/json",
            }
        )
        self._last_request_mono: float | None = None

    def _sleep_rate_limit(self) -> None:
        """Выдержать минимальный интервал между запросами (``min_delay_sec``)."""
        if self._last_request_mono is None:
            return
        elapsed = time.monotonic() - self._last_request_mono
        if elapsed < self._min_delay:
            time.sleep(self._min_delay - elapsed)

    def get_json(self, path: str) -> dict[str, Any]:
        """Выполнить GET к NHL Web API и распарсить JSON-объект.

        Args:
            path: Относительный путь без ведущего слэша, например ``schedule/2026-03-30``
                или ``gamecenter/2025021173/boxscore`` (к ``base_url`` из конфига).

        Returns:
            Словарь верхнего уровня ответа API.

        Raises:
            SourceFetchError: Ошибка HTTP после ретраев, сеть, ответ не JSON или не объект.

        Note:
            Успешный запрос логируется на уровне DEBUG с полем ``path``.
        """
        path = path.lstrip("/")
        url = f"{self._base_url}/{path}"
        self._sleep_rate_limit()
        try:
            resp = self._session.get(url, timeout=self._timeout)
            self._last_request_mono = time.monotonic()
            resp.raise_for_status()
        except requests.HTTPError as e:
            raise SourceFetchError(f"NHL API HTTP ошибка {url}: {e}") from e
        except requests.RequestException as e:
            raise SourceFetchError(f"NHL API сеть {url}: {e}") from e

        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise SourceFetchError(f"NHL API не JSON {url}: {e}") from e
        if not isinstance(data, dict):
            raise SourceFetchError(f"NHL API ожидался object, получено {type(data)}")
        logger.debug("NHL API GET ok: %s", path)
        return data
