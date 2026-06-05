"""HTTP-клиент Smart Tables backend: Origin/Referer, rate limit, retry."""

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

_DEFAULT_BASE = "https://backend.smart-tables.ru/api/v1"
_DEFAULT_ORIGIN = "https://smart-tables.ru"
_DEFAULT_REFERER = "https://smart-tables.ru/"
_DEFAULT_TIMEOUT = 60.0
_DEFAULT_RETRIES = 3
_DEFAULT_BACKOFF = 0.8
_DEFAULT_MIN_DELAY = 1.0
_DEFAULT_TIMEOUT_ATTEMPTS = 4
_DEFAULT_TIMEOUT_RETRY_BACKOFF = 1.5
_STATUS_FORCELIST = (429, 500, 502, 503, 504)


class SmartTablesApiClient:
    """HTTP-клиент к ``backend.smart-tables.ru`` с паузой между запросами и ретраями.

    Параметры задаются веткой ``provider`` в ``conf/source/smart_tables.yaml``.
    """

    def __init__(self, provider_cfg: DictConfig | dict[str, Any]) -> None:
        """
        Args:
            provider_cfg: Секция ``provider`` из source-конфига.
        """
        cfg = OmegaConf.to_container(provider_cfg, resolve=True)
        if not isinstance(cfg, dict):
            raise SourceFetchError("smart_tables_api: неверная секция provider")

        self._base_url = str(cfg.get("base_url", _DEFAULT_BASE)).rstrip("/")
        self._timeout = float(cfg.get("timeout_sec", _DEFAULT_TIMEOUT))
        self._min_delay = float(cfg.get("min_delay_sec", _DEFAULT_MIN_DELAY))
        retries = int(cfg.get("retries", _DEFAULT_RETRIES))
        backoff = float(cfg.get("backoff_factor", _DEFAULT_BACKOFF))
        self._timeout_attempts = max(1, int(cfg.get("timeout_attempts", _DEFAULT_TIMEOUT_ATTEMPTS)))
        self._timeout_retry_backoff = float(
            cfg.get("timeout_retry_backoff_sec", _DEFAULT_TIMEOUT_RETRY_BACKOFF)
        )
        origin = str(cfg.get("origin", _DEFAULT_ORIGIN))
        referer = str(cfg.get("referer", _DEFAULT_REFERER))

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
                "Accept": "application/json",
                "Origin": origin,
                "Referer": referer,
            }
        )
        self._last_request_mono: float | None = None

    def _sleep_rate_limit(self) -> None:
        if self._last_request_mono is None:
            return
        elapsed = time.monotonic() - self._last_request_mono
        if elapsed < self._min_delay:
            time.sleep(self._min_delay - elapsed)

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Выполнить GET и вернуть JSON-объект верхнего уровня.

        Args:
            path: Относительный путь без ведущего слэша.
            params: Query-параметры.

        Returns:
            Словарь ответа API.

        Raises:
            SourceFetchError: HTTP/сеть/JSON/``success: false``.
        """
        path = path.lstrip("/")
        url = f"{self._base_url}/{path}"
        resp: requests.Response | None = None

        for attempt in range(self._timeout_attempts):
            self._sleep_rate_limit()
            try:
                resp = self._session.get(url, params=params, timeout=self._timeout)
                self._last_request_mono = time.monotonic()
                resp.raise_for_status()
                break
            except requests.HTTPError as e:
                raise SourceFetchError(f"Smart Tables HTTP ошибка {url}: {e}") from e
            except (requests.ConnectTimeout, requests.ReadTimeout) as e:
                if attempt + 1 >= self._timeout_attempts:
                    raise SourceFetchError(
                        f"Smart Tables таймаут {url} после {self._timeout_attempts} попыток: {e}"
                    ) from e
                wait = self._timeout_retry_backoff * (2**attempt)
                logger.warning(
                    "Smart Tables таймаут %s (попытка %d/%d), пауза %.1f с",
                    path,
                    attempt + 1,
                    self._timeout_attempts,
                    wait,
                )
                time.sleep(wait)
            except requests.RequestException as e:
                raise SourceFetchError(f"Smart Tables сеть {url}: {e}") from e

        if resp is None:
            raise SourceFetchError(f"Smart Tables: нет ответа для {url}")

        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise SourceFetchError(f"Smart Tables не JSON {url}: {e}") from e
        if not isinstance(data, dict):
            raise SourceFetchError(f"Smart Tables ожидался object, получено {type(data)}")
        if data.get("success") is False:
            raise SourceFetchError(f"Smart Tables API success=false {url}: {data.get('errors')}")
        logger.debug("Smart Tables GET ok: %s", path)
        return data
