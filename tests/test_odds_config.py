"""
Контракт YAML для The Odds API: bookmaker_profiles, snapshot_discovery, source odds.bookmakers.

Проверяет наличие ключей и допустимые значения семантики (R21.2), без runtime-логики snapshot discovery.
"""

from __future__ import annotations

from numbers import Real
from typing import Any, Final

import pytest
from omegaconf import DictConfig, OmegaConf

from sports_forecast.config.loaders import load_bookmaker_config, load_source_config
from sports_forecast.data.providers.odds.enrichment import (
    BookmakerExtractionProfile,
    _v3_row_keys_for_profile,
)
from sports_forecast.data.providers.odds.store import ODDS_STORE_COLUMNS_V3


_WINNER_SEMANTICS: Final[frozenset[str]] = frozenset({"winner", "winner_withOT"})
_TOTAL_SEMANTICS: Final[frozenset[str]] = frozenset({"total", "total_withOT"})

_EXPECTED_PROFILE_IDS: Final[tuple[str, ...]] = ("pinnacle", "onexbet")


def _as_plain(node: Any) -> Any:
    """OmegaConf / dict → json-safe структура для isinstance-проверок."""
    if node is None:
        return None
    return OmegaConf.to_container(node, resolve=True)


@pytest.fixture
def the_odds_book_root() -> DictConfig:
    """Узел ``bookmaker`` из ``conf/bookmaker/the_odds_api.yaml``."""
    cfg = load_bookmaker_config("the_odds_api")
    assert cfg is not None, "the_odds_api.yaml должен загружаться"
    br = OmegaConf.select(cfg, "bookmaker")
    assert br is not None
    return br  # type: ignore[return-value]


class TestTheOddsApiBookmakerProfiles:
    """Секция bookmaker_profiles: ключи, enum семантики, has_draw."""

    def test_profiles_keys_and_schema(self, the_odds_book_root: DictConfig) -> None:
        raw = _as_plain(OmegaConf.select(the_odds_book_root, "bookmaker_profiles"))
        assert isinstance(raw, dict), "bookmaker_profiles должен быть mapping"
        for pid in _EXPECTED_PROFILE_IDS:
            assert pid in raw, f"ожидается bookmaker_profiles.{pid}"
            prof = raw[pid]
            assert isinstance(prof, dict)
            key = prof.get("key")
            assert key == pid, f"bookmaker_profiles.{pid}.key должен совпадать с именем профиля"
            ws = prof.get("winner_semantics")
            ts = prof.get("total_semantics")
            assert ws in _WINNER_SEMANTICS, f"некорректный winner_semantics: {ws!r}"
            assert ts in _TOTAL_SEMANTICS, f"некорректный total_semantics: {ts!r}"
            hd = prof.get("has_draw")
            assert isinstance(hd, bool), "has_draw должен быть bool"

    def test_pinnacle_onexbet_semantics_contract(self, the_odds_book_root: DictConfig) -> None:
        """Pinnacle = full game (with OT); 1xBet = regulation (с ничьей)."""
        raw = _as_plain(OmegaConf.select(the_odds_book_root, "bookmaker_profiles"))
        assert isinstance(raw, dict)
        pin = raw.get("pinnacle")
        one = raw.get("onexbet")
        assert isinstance(pin, dict) and isinstance(one, dict)
        assert pin.get("winner_semantics") == "winner_withOT"
        assert pin.get("total_semantics") == "total_withOT"
        assert pin.get("has_draw") is False
        assert one.get("winner_semantics") == "winner"
        assert one.get("total_semantics") == "total"
        assert one.get("has_draw") is True

    def test_profile_expected_columns_subset_of_store_v3(
        self, the_odds_book_root: DictConfig
    ) -> None:
        """Префиксы/семантика профилей (close) согласованы с ``ODDS_STORE_COLUMNS_V3``."""
        raw = _as_plain(OmegaConf.select(the_odds_book_root, "bookmaker_profiles"))
        assert isinstance(raw, dict)
        v3 = set(ODDS_STORE_COLUMNS_V3)
        for name, node in raw.items():
            if not isinstance(node, dict):
                continue
            p = BookmakerExtractionProfile.from_mapping(str(name), node)
            for c in _v3_row_keys_for_profile(p):
                assert c in v3, f"профиль {name}: {c!r} отсутствует в OddsStore V3"


class TestTheOddsApiSnapshotDiscovery:
    """Типы и наличие snapshot_discovery (параметры для R21.4+)."""

    def test_snapshot_discovery_types(self, the_odds_book_root: DictConfig) -> None:
        raw = _as_plain(OmegaConf.select(the_odds_book_root, "snapshot_discovery"))
        assert isinstance(raw, dict), "snapshot_discovery должен быть mapping"
        offsets = raw.get("open_probe_offsets_hours")
        margin = raw.get("close_margin_hours")
        assert isinstance(offsets, list), "open_probe_offsets_hours должен быть списком"
        assert all(isinstance(x, int) and not isinstance(x, bool) for x in offsets), (
            "open_probe_offsets_hours: ожидаются целые часы (int)"
        )
        assert margin is not None, "close_margin_hours обязателен"
        assert isinstance(margin, Real) and not isinstance(margin, bool), (
            "close_margin_hours должен быть числом (int или float)"
        )

    def test_snapshot_discovery_non_empty_offsets(self, the_odds_book_root: DictConfig) -> None:
        raw = _as_plain(OmegaConf.select(the_odds_book_root, "snapshot_discovery"))
        assert isinstance(raw, dict)
        offsets = raw.get("open_probe_offsets_hours")
        assert isinstance(offsets, list) and len(offsets) >= 1


class TestNhlSourceOddsBookmakers:
    """source/nhl odds.bookmakers согласован с multi-bookmaker конфигом."""

    def test_nhl_odds_includes_configured_bookmakers(self) -> None:
        sc = load_source_config("nhl")
        odds = sc.get("odds") or {}
        bms = _as_plain(odds.get("bookmakers") if hasattr(odds, "get") else None)
        assert isinstance(bms, list), "odds.bookmakers должен быть списком"
        assert bms == ["pinnacle", "onexbet"]
        # R20-поля на месте
        assert odds.get("enabled") is True
        assert str(odds.get("bookmaker") or "") == "the_odds_api"
        assert str(odds.get("sport_key") or "") == "icehockey_nhl"
        assert odds.get("store_path") is not None
        assert odds.get("state_path") is not None
