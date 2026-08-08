"""HTTP-клиент The Odds API v4: квота, retry, кэш ответов на диск."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from omegaconf import DictConfig, OmegaConf
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from sports_forecast.config.loaders import PROJECT_ROOT, load_bookmaker_config
from sports_forecast.utils.log_config import get_logger


logger = get_logger(__name__)

# Статус в логе: HTTP-код или метка для cache-hit.
_ApiLogStatus = int | str


class QuotaBudgetError(RuntimeError):
    """Достигнут лимит реальных HTTP-запросов к The Odds API за один run (см. ``max_real_http_requests``)."""


@dataclass(frozen=True)
class OddsApiQuotaSnapshot:
    """Снимок квоты из заголовков ответа The Odds API."""

    requests_remaining: int | None
    requests_used: int | None


@dataclass(frozen=True)
class OddsApiKey:
    """Ключ The Odds API без раскрытия значения в диагностике."""

    tier: str
    value: str


_KEY_ENV_TIERS: tuple[tuple[str, str], ...] = (
    ("free", "ODDS_API_KEY_FREE"),
    ("20k", "ODDS_API_KEY_20K"),
    ("100k", "ODDS_API_KEY_100K"),
)


def configured_odds_api_keys() -> tuple[OddsApiKey, ...]:
    """Прочитать уникальные ключи в порядке расходования квоты."""
    keys: list[OddsApiKey] = []
    seen: set[str] = set()
    for tier, env_name in _KEY_ENV_TIERS:
        value = os.environ.get(env_name, "").strip()
        if value and value not in seen:
            keys.append(OddsApiKey(tier=tier, value=value))
            seen.add(value)
    if not keys:
        legacy = os.environ.get("ODDS_API_KEY", "").strip()
        if legacy:
            keys.append(OddsApiKey(tier="legacy", value=legacy))
    return tuple(keys)


def has_configured_odds_api_key() -> bool:
    """Вернуть True, если задан хотя бы один поддерживаемый ключ Odds API."""
    return bool(configured_odds_api_keys())


class OddsApiClient:
    """Клиент REST The Odds API (актуальные и исторические коэффициенты).

    Ключи: ``ODDS_API_KEY_FREE`` → ``ODDS_API_KEY_20K`` →
    ``ODDS_API_KEY_100K``; ``ODDS_API_KEY`` остаётся fallback.
    Параметры запросов и пути — из ``conf/bookmaker/the_odds_api.yaml``.

    Args:
        bookmaker_cfg: Результат ``load_bookmaker_config("the_odds_api")``; при ``None`` загружается автоматически.
        cache_dir: Каталог JSON-кэша; по умолчанию ``data/cache/the_odds_api``.
        session: Внешняя ``requests.Session`` (для тестов).
        max_real_http_requests: Если задан, после стольки успешных сетевых GET (кэш не считается) следующий
            запрос вызовет :class:`QuotaBudgetError` до отправки; ``None`` — без лимита.
    """

    def __init__(
        self,
        bookmaker_cfg: DictConfig | None = None,
        *,
        cache_dir: Path | None = None,
        session: requests.Session | None = None,
        max_real_http_requests: int | None = None,
    ) -> None:
        cfg_in = (
            bookmaker_cfg if bookmaker_cfg is not None else load_bookmaker_config("the_odds_api")
        )
        if cfg_in is None:
            raise ValueError("Не найден conf/bookmaker/the_odds_api.yaml")
        self._cfg = cfg_in
        book_node = OmegaConf.select(cfg_in, "bookmaker")
        self._book = book_node if book_node is not None else cfg_in
        api = self._book.api
        base = str(api.base_url).rstrip("/")
        prefix = str(api.api_prefix).rstrip("/")
        if not prefix.startswith("/"):
            prefix = "/" + prefix
        self._base_url = f"{base}{prefix}"
        self._api_keys = configured_odds_api_keys()
        if not self._api_keys:
            raise ValueError("Требуется один из ключей Odds API в переменных окружения")
        self._api_key_index = 0
        self._api_key = self._api_keys[self._api_key_index].value

        rl = self._book.get("rate_limit") or {}
        self._min_interval_sec = float(rl.get("min_interval_sec", 0.5))
        self._last_request_ts: float = 0.0
        self._max_real_http_requests = max_real_http_requests
        self._real_http_requests = 0

        self._cache_dir = cache_dir or (PROJECT_ROOT / "data" / "cache" / "the_odds_api")

        self._session = session or self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        retry = Retry(
            total=5,
            connect=3,
            read=3,
            backoff_factor=0.8,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        s = requests.Session()
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        return s

    def last_quota(self) -> OddsApiQuotaSnapshot:
        """Последние известные значения заголовков квоты (после успешного запроса)."""
        return OddsApiQuotaSnapshot(
            requests_remaining=getattr(self, "_quota_remaining", None),
            requests_used=getattr(self, "_quota_used", None),
        )

    def _throttle(self) -> None:
        now = time.monotonic()
        delta = now - self._last_request_ts
        if delta < self._min_interval_sec:
            time.sleep(self._min_interval_sec - delta)

    def _cache_path(self, cache_key: str) -> Path:
        """Вернуть непрозрачный путь: ключ запроса не попадает в имя файла."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        return self._cache_dir / f"odds-{sha256(cache_key.encode()).hexdigest()}.json"

    @staticmethod
    def _log_network_response(
        full_path: str,
        *,
        status: _ApiLogStatus,
        x_requests_remaining: str | None,
        cached: bool,
    ) -> None:
        """Лог GET The Odds API: только path и заголовки, без query (секрет не в URL)."""
        rem = x_requests_remaining if x_requests_remaining is not None else "n/a"
        logger.info(
            "Odds API: path=%s status=%s x-requests-remaining=%s cached=%s",
            full_path,
            status,
            rem,
            cached,
        )

    def _parse_quota_headers(self, resp: requests.Response) -> None:
        rem = resp.headers.get("x-requests-remaining")
        used = resp.headers.get("x-requests-used")
        try:
            self._quota_remaining = int(rem) if rem is not None else None
        except ValueError:
            self._quota_remaining = None
        try:
            self._quota_used = int(used) if used is not None else None
        except ValueError:
            self._quota_used = None
        if self._quota_remaining is not None and self._quota_remaining < 50:
            logger.warning(
                "The Odds API: осталось запросов по заголовку x-requests-remaining=%s",
                self._quota_remaining,
            )

    def _advance_api_key(self) -> bool:
        """Перейти к следующему tier после доказанного исчерпания квоты."""
        if self._api_key_index + 1 >= len(self._api_keys):
            return False
        previous = self._api_keys[self._api_key_index].tier
        self._api_key_index += 1
        current = self._api_keys[self._api_key_index]
        self._api_key = current.value
        logger.warning(
            "Odds API: quota tier=%s исчерпан, переключение на tier=%s", previous, current.tier
        )
        return True

    def get_json(
        self,
        path: str,
        params: dict[str, Any],
        *,
        cache_key: str | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any] | list[Any]:
        """GET с кэшем на диск и учётом квоты.

        Args:
            path: Относительный путь, например ``/sports/icehockey_nhl/odds``.
            params: Query-параметры (``apiKey`` добавляется автоматически).
            cache_key: Имя файла кэша; по умолчанию из path+params.
            use_cache: При True и существующем кэше тело не запрашивается.

        Returns:
            Распарсенный JSON.

        Raises:
            QuotaBudgetError: Если исчерпан внутренний лимит сетевых запросов за run.
            requests.HTTPError: При фатальной HTTP-ошибке после retries.
        """
        q = dict(params)
        q["apiKey"] = self._api_key
        full_path = path if path.startswith("/") else f"/{path}"
        cache_params = {key: value for key, value in q.items() if key != "apiKey"}
        key = (
            cache_key
            or f"{full_path}?{urlencode(sorted((k, str(v)) for k, v in cache_params.items()))}"
        )
        cpath = self._cache_path(key) if use_cache else None
        if cpath is not None and cpath.is_file():
            snap = self.last_quota()
            self._log_network_response(
                full_path,
                status="cache",
                x_requests_remaining=str(snap.requests_remaining)
                if snap.requests_remaining is not None
                else None,
                cached=True,
            )
            with cpath.open(encoding="utf-8") as f:
                cached: dict[str, Any] | list[Any] = json.load(f)
            return cached

        if (
            self._max_real_http_requests is not None
            and self._real_http_requests >= self._max_real_http_requests
        ):
            raise QuotaBudgetError(
                f"Достигнут лимит сетевых запросов The Odds API за run: "
                f"{self._max_real_http_requests}"
            )

        url = f"{self._base_url.rstrip('/')}{full_path}"
        while True:
            if (
                self._max_real_http_requests is not None
                and self._real_http_requests >= self._max_real_http_requests
            ):
                raise QuotaBudgetError(
                    f"Достигнут лимит сетевых запросов The Odds API за run: "
                    f"{self._max_real_http_requests}"
                )
            q["apiKey"] = self._api_key
            self._throttle()
            resp = self._session.get(url, params=dict(q), timeout=120)
            self._last_request_ts = time.monotonic()
            self._real_http_requests += 1
            self._parse_quota_headers(resp)
            self._log_network_response(
                full_path,
                status=resp.status_code,
                x_requests_remaining=resp.headers.get("x-requests-remaining"),
                cached=False,
            )
            if resp.status_code == 429 and self._advance_api_key():
                continue
            break
        resp.raise_for_status()
        data: dict[str, Any] | list[Any] = resp.json()
        if self._quota_remaining == 0:
            self._advance_api_key()
        if cpath is not None:
            with cpath.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        return data

    def fetch_odds_for_sport(
        self,
        sport_key: str,
        *,
        regions: str = "us",
        markets: list[str] | None = None,
        odds_format: str = "decimal",
        date_iso: str | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any] | list[Any]:
        """``/sports/{sport}/odds`` или исторический вариант при заданной дате.

        Args:
            sport_key: Ключ спорта (например ``icehockey_nhl``).
            regions: Регион букмекеров.
            markets: Список рынков; по умолчанию h2h + totals из конфига.
            odds_format: Формат коэффициентов в ответе.
            date_iso: Если задан — запрос к ``/historical/sports/...`` (один момент времени ISO).
            use_cache: Использовать дисковый кэш.

        Returns:
            Тело JSON (структура зависит от endpoint).
        """
        api = self._book.api
        m_h2h = list(api.get("markets_h2h") or ["h2h"])
        m_tot = list(api.get("markets_totals") or ["totals"])
        if markets is None:
            markets = list(dict.fromkeys(m_h2h + m_tot))
        markets_param = ",".join(markets)
        base_params: dict[str, Any] = {
            "regions": regions,
            "markets": markets_param,
            "oddsFormat": odds_format,
        }
        if date_iso:
            path = f"/historical/sports/{sport_key}/odds"
            base_params["date"] = date_iso
        else:
            path = f"/sports/{sport_key}/odds"
        cache_key = f"{path}_{markets_param}_{regions}_{date_iso or 'current'}"
        return self.get_json(path, base_params, cache_key=cache_key, use_cache=use_cache)
