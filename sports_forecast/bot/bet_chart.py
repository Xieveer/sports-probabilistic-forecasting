"""PNG-график накопленного денежного результата фактических ставок."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from io import BytesIO

import matplotlib


matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def render_season_pnl_chart(
    *,
    start: str,
    end: str,
    tournament: str,
    points: Sequence[Mapping[str, str]],
) -> bytes:
    """Построить сезонную линию общего денежного PnL в памяти."""
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    dates = [start_date]
    values = [0.0]
    for point in points:
        dates.append(date.fromisoformat(point["date"]))
        values.append(float(Decimal(point["cumulative_cash_pnl"])))
    if dates[-1] < end_date:
        dates.append(end_date)
        values.append(values[-1])
    figure, axis = plt.subplots(figsize=(9, 4.5), layout="constrained")
    try:
        axis.step(
            dates,
            values,
            where="post",
            color="#1565c0",
            linewidth=2.5,
            marker="o",
            markersize=3,
        )
        axis.axhline(0, color="#777777", linewidth=0.8)
        axis.set_title(f"{tournament.upper()} · денежный PnL с начала сезона")
        axis.set_ylabel("Рубли")
        axis.grid(True, alpha=0.25)
        figure.autofmt_xdate()
        output = BytesIO()
        figure.savefig(output, format="png", dpi=120)
        return output.getvalue()
    finally:
        plt.close(figure)
