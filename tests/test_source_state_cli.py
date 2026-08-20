"""CLI контракт initial source-state."""

from pathlib import Path

import pandas as pd

from sports_forecast.deploy.source_state_cli import main


def test_source_state_cli_build_and_install(tmp_path: Path) -> None:
    source_root = tmp_path / "input"
    source_root.mkdir()
    (source_root / "source.csv").write_text(
        "id,datetime,match_is_end\n1,2026-08-20T00:00:00Z,0\n", encoding="utf-8"
    )
    odds = source_root / "odds" / "pinnacle_odds.parquet"
    odds.parent.mkdir()
    pd.DataFrame([{"game_date": "2026-08-20"}]).to_parquet(odds)
    (source_root / "odds/refresh_state.json").write_text("{}", encoding="utf-8")
    bundles = tmp_path / "bundles"

    assert (
        main(
            [
                "build",
                "--source-csv",
                str(source_root / "source.csv"),
                "--odds-store",
                str(odds),
                "--checkpoint",
                str(source_root / "odds/refresh_state.json"),
                "--bundle-root",
                str(bundles),
            ]
        )
        == 0
    )
    bundle = next((bundles / "operational-archive/nhl-source-state/v1").iterdir())
    assert (
        main(["install", "--bundle", str(bundle), "--source-root", str(tmp_path / "volume")]) == 0
    )
