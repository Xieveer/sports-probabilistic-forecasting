"""График накопленного денежного результата фактических ставок."""

from sports_forecast.bot.bet_chart import render_season_pnl_chart


def test_empty_and_nonempty_seasons_render_png() -> None:
    """Даже без рассчитанных ставок владелец получает читаемый график."""
    for points in (
        [],
        [{"date": "2026-09-02", "cumulative_cash_pnl": "120.00"}],
    ):
        image = render_season_pnl_chart(
            start="2026-09-01", end="2026-10-31", tournament="nhl", points=points
        )
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(image) > 500
