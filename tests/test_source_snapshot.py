"""Контракт атомарной публикации scheduler source snapshot."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from sports_forecast.orchestration.source_snapshot import (
    publish_source_snapshot,
    refresh_and_publish_source_snapshot,
)


def test_publish_source_snapshot_replaces_current_only_after_validation(tmp_path: Path) -> None:
    """Валидный новый CSV атомарно заменяет текущий snapshot."""
    source = tmp_path / "source.csv"
    source.write_text(
        "id,datetime,match_is_end,pinnacle_winner_withOT_home_close\n"
        "2,2026-09-29T21:00:00Z,0,1.91\n",
        encoding="utf-8",
    )
    current = tmp_path / "current.csv"
    current.write_text("id,datetime,match_is_end\n1,2026-09-28T21:00:00Z,0\n", encoding="utf-8")

    published = publish_source_snapshot(source, current)

    assert published == current
    assert current.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_invalid_source_snapshot_keeps_previous_current_file(tmp_path: Path) -> None:
    """Неполный source не повреждает последний валидный snapshot."""
    source = tmp_path / "source.csv"
    source.write_text("id,datetime\n2,2026-09-29T21:00:00Z\n", encoding="utf-8")
    current = tmp_path / "current.csv"
    previous = "id,datetime,match_is_end\n1,2026-09-28T21:00:00Z,0\n"
    current.write_text(previous, encoding="utf-8")

    with pytest.raises(ValueError, match="match_is_end"):
        publish_source_snapshot(source, current)

    assert current.read_text(encoding="utf-8") == previous


def test_refresh_and_publish_requires_complete_default_odds_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scheduler path не передаёт skip_odds и публикует результат только после refresh."""
    source = tmp_path / "source.csv"
    source.write_text(
        "id,datetime,match_is_end,pinnacle_winner_withOT_home_close\n"
        "2,2026-09-29T21:00:00Z,0,1.91\n",
        encoding="utf-8",
    )
    current = tmp_path / "current.csv"
    calls: list[str] = []

    def fake_refresh(tournament: str) -> tuple[Path, SimpleNamespace]:
        calls.append(tournament)
        return source, SimpleNamespace(quota_hit=False, merged_source=True)

    monkeypatch.setattr(
        "sports_forecast.orchestration.source_snapshot.refresh_source_with_odds_result",
        fake_refresh,
    )

    published = refresh_and_publish_source_snapshot("nhl", current)

    assert calls == ["nhl"]
    assert published == current


@pytest.mark.parametrize(
    ("odds_result", "message"),
    [
        (None, "odds refresh"),
        (SimpleNamespace(quota_hit=True, merged_source=True), "odds refresh"),
        (SimpleNamespace(quota_hit=False, merged_source=False), "odds refresh"),
    ],
)
def test_refresh_and_publish_keeps_current_when_mandatory_odds_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    odds_result: SimpleNamespace | None,
    message: str,
) -> None:
    """Partial/quota odds result не публикует facts-only snapshot."""
    source = tmp_path / "source.csv"
    source.write_text(
        "id,datetime,match_is_end,pinnacle_winner_withOT_home_close\n"
        "2,2026-09-29T21:00:00Z,0,1.91\n",
        encoding="utf-8",
    )
    current = tmp_path / "current.csv"
    previous = "id,datetime,match_is_end\n1,2026-09-28T21:00:00Z,0\n"
    current.write_text(previous, encoding="utf-8")
    monkeypatch.setattr(
        "sports_forecast.orchestration.source_snapshot.refresh_source_with_odds_result",
        lambda _tournament: (source, odds_result),
    )

    with pytest.raises(ValueError, match=message):
        refresh_and_publish_source_snapshot("nhl", current)

    assert current.read_text(encoding="utf-8") == previous


def test_refresh_and_publish_rejects_future_event_without_odds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Наличие merge не заменяет coverage gate для будущих матчей."""
    source = tmp_path / "source.csv"
    source.write_text(
        "id,datetime,match_is_end,pinnacle_winner_withOT_home_close\n2,2026-09-29T21:00:00Z,0,\n",
        encoding="utf-8",
    )
    current = tmp_path / "current.csv"
    current.write_text("id,datetime,match_is_end\n1,2026-09-28T21:00:00Z,0\n", encoding="utf-8")
    monkeypatch.setattr(
        "sports_forecast.orchestration.source_snapshot.refresh_source_with_odds_result",
        lambda _tournament: (source, SimpleNamespace(quota_hit=False, merged_source=True)),
    )

    with pytest.raises(ValueError, match="будущие события без обязательных odds"):
        refresh_and_publish_source_snapshot("nhl", current)
