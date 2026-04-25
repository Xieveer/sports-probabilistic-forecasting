"""Интеграция odds-refresh в ``source_refresh.refresh_source`` (R20.4)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from omegaconf import OmegaConf


@patch("sports_forecast.orchestration.source_refresh.run_odds_refresh")
@patch("sports_forecast.orchestration.source_refresh.get_provider")
@patch("sports_forecast.orchestration.source_refresh.load_source_config")
@patch("sports_forecast.orchestration.source_refresh.load_paths_config")
def test_odds_enabled_calls_run_odds_refresh(
    _mock_paths: MagicMock,
    mock_load_source: MagicMock,
    mock_get_provider: MagicMock,
    mock_run_odds: MagicMock,
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "nhl" / "source.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("x\n", encoding="utf-8")

    mock_load_source.return_value = OmegaConf.create(
        {
            "name": "nhl",
            "provider": {"type": "nhl_web_api"},
            "odds": {"enabled": True, "bookmaker": "the_odds_api", "sport_key": "icehockey_nhl"},
        }
    )
    mock_get_provider.return_value = MagicMock(fetch=MagicMock(return_value=csv_path))

    from sports_forecast.orchestration.source_refresh import refresh_source

    out = refresh_source("nhl", skip_odds=False)
    assert out == csv_path
    mock_run_odds.assert_called_once()
    kwargs = mock_run_odds.call_args.kwargs
    assert kwargs["tournament"] == "nhl"
    assert kwargs["source_csv_path"] == csv_path
    assert kwargs["bookmaker_key"] == "the_odds_api"
    assert kwargs["sport_key"] == "icehockey_nhl"


@patch("sports_forecast.orchestration.source_refresh.run_odds_refresh")
@patch("sports_forecast.orchestration.source_refresh.get_provider")
@patch("sports_forecast.orchestration.source_refresh.load_source_config")
@patch("sports_forecast.orchestration.source_refresh.load_paths_config")
def test_skip_odds_does_not_call_run_odds_refresh(
    _mock_paths: MagicMock,
    mock_load_source: MagicMock,
    mock_get_provider: MagicMock,
    mock_run_odds: MagicMock,
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "nhl" / "source.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.touch()

    mock_load_source.return_value = OmegaConf.create(
        {
            "name": "nhl",
            "provider": {"type": "file"},
            "odds": {"enabled": True},
        }
    )
    mock_get_provider.return_value = MagicMock(fetch=MagicMock(return_value=csv_path))

    from sports_forecast.orchestration.source_refresh import refresh_source

    refresh_source("nhl", skip_odds=True)
    mock_run_odds.assert_not_called()


@pytest.mark.parametrize(
    "odds_block",
    [
        None,
        {"enabled": False},
    ],
)
@patch("sports_forecast.orchestration.source_refresh.run_odds_refresh")
@patch("sports_forecast.orchestration.source_refresh.get_provider")
@patch("sports_forecast.orchestration.source_refresh.load_source_config")
@patch("sports_forecast.orchestration.source_refresh.load_paths_config")
def test_odds_disabled_or_missing_section_skips(
    _mock_paths: MagicMock,
    mock_load_source: MagicMock,
    mock_get_provider: MagicMock,
    mock_run_odds: MagicMock,
    tmp_path: Path,
    odds_block: dict[str, object] | None,
) -> None:
    csv_path = tmp_path / "nhl" / "source.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.touch()

    base: dict = {"name": "nhl", "provider": {"type": "file"}}
    if odds_block is not None:
        base["odds"] = odds_block
    mock_load_source.return_value = OmegaConf.create(base)
    mock_get_provider.return_value = MagicMock(fetch=MagicMock(return_value=csv_path))

    from sports_forecast.orchestration.source_refresh import refresh_source

    refresh_source("nhl", skip_odds=False)
    mock_run_odds.assert_not_called()


@patch("sports_forecast.orchestration.source_refresh.run_odds_refresh")
@patch("sports_forecast.orchestration.source_refresh.get_provider")
@patch("sports_forecast.orchestration.source_refresh.load_source_config")
@patch("sports_forecast.orchestration.source_refresh.load_paths_config")
def test_odds_refresh_error_propagates_fail_fast(
    _mock_paths: MagicMock,
    mock_load_source: MagicMock,
    mock_get_provider: MagicMock,
    mock_run_odds: MagicMock,
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "nhl" / "source.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.touch()

    mock_load_source.return_value = OmegaConf.create(
        {
            "name": "nhl",
            "provider": {"type": "file"},
            "odds": {"enabled": True},
        }
    )
    mock_get_provider.return_value = MagicMock(fetch=MagicMock(return_value=csv_path))
    mock_run_odds.side_effect = ValueError("odds API down")

    from sports_forecast.orchestration.source_refresh import refresh_source

    with pytest.raises(ValueError, match="odds API down"):
        refresh_source("nhl", skip_odds=False)


@patch("sports_forecast.orchestration.source_refresh.refresh_source")
def test_main_cli_passes_skip_odds(mock_refresh: MagicMock) -> None:
    mock_refresh.return_value = Path("/dev/null")
    from sports_forecast.orchestration.source_refresh import main

    assert main(["--tournament", "nhl", "--skip-odds"]) == 0
    mock_refresh.assert_called_once_with("nhl", skip_odds=True)
