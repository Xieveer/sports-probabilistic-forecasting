"""Проверяемый отчёт кандидата на основе MLflow run и его betting trace."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Set
from typing import Any

import pandas as pd

from sports_forecast.betting.bootstrap import BlockBootstrap
from sports_forecast.config.portfolio import PortfolioCatalog


def build_tournament_candidate_report(
    catalog: PortfolioCatalog,
    profile_name: str,
    *,
    run_id: str,
    run_status: str,
    tags: Mapping[str, str],
    metrics: Mapping[str, float],
    bet_trace: pd.DataFrame,
    competition_codes: Set[str],
    data_sha256: str,
    data_rows: int,
) -> dict[str, Any]:
    """Построить отчёт только для завершённого кандидата с данными и ставками."""
    profile = catalog.deployment_profiles.get(profile_name)
    if profile is None:
        raise ValueError(f"Профиль {profile_name} отсутствует в каталоге")
    if profile.state != "candidate":
        raise ValueError(f"Профиль {profile_name} не является кандидатом")
    tournament = catalog.tournaments[profile.tournament]
    if run_status != "FINISHED" or not run_id.strip():
        raise ValueError("Обучение кандидата не завершено успешно")
    if (
        tags.get("tournament") != profile.tournament
        or tags.get("market_spec") != profile.market_spec
    ):
        raise ValueError("MLflow run не соответствует профилю кандидата")
    if data_rows <= 0 or len(data_sha256) != 64:
        raise ValueError("Данные кандидата отсутствуют или не имеют контрольной суммы")
    if tournament.competition_code and competition_codes != {tournament.competition_code}:
        raise ValueError("Данные кандидата содержат неверный состав соревнований")

    names = {
        "logloss": "test_logloss",
        "auc": "test_auc",
        "brier": "test_brier",
        "roi": "betting_roi",
        "coverage": "betting_coverage",
        "n_bets": "betting_n_bets",
    }
    values: dict[str, float] = {}
    for name, metric_key in names.items():
        raw = metrics.get(metric_key)
        if raw is None or not math.isfinite(float(raw)):
            raise ValueError(f"У кандидата отсутствует метрика {metric_key}")
        values[name] = float(raw)
    if values["n_bets"] <= 0 or not 0 < values["coverage"] <= 1:
        raise ValueError("У кандидата нет проверяемого покрытия ставок")
    if "bet_placed" in bet_trace:
        placed = bet_trace["bet_placed"].astype(bool)
    elif "stake" in bet_trace:
        placed = pd.to_numeric(bet_trace["stake"], errors="coerce").fillna(0) > 0
    else:
        raise ValueError("Betting trace не содержит признак размещённой ставки")
    if int(placed.sum()) != int(values["n_bets"]):
        raise ValueError("Число ставок в MLflow и betting trace различается")
    if "id" not in bet_trace or "datetime" not in bet_trace:
        raise ValueError("Betting trace не содержит ID и дату тестовых матчей")
    ids = bet_trace["id"].astype("string")
    dates = pd.to_datetime(bet_trace["datetime"], errors="coerce", utc=True)
    if ids.isna().any() or dates.isna().any():
        raise ValueError("Betting trace содержит пустой ID или дату тестового матча")
    event_ids = sorted(set(ids.astype(str)))
    n_events = len(event_ids)
    if n_events == 0 or len(bet_trace) != 2 * n_events:
        raise ValueError("Winner long-format требует две строки на тестовый матч")
    normalized_coverage = min(1.0, values["n_bets"] / n_events)
    if not math.isclose(values["coverage"], normalized_coverage, abs_tol=1e-8):
        raise ValueError("Покрытие MLflow не соответствует betting trace")
    n_bet_events = len(set(ids.loc[placed].astype(str)))
    first_event = dates.min().isoformat()
    last_event = dates.max().isoformat()
    event_ids_sha256 = hashlib.sha256("\n".join(event_ids).encode("utf-8")).hexdigest()

    boot = BlockBootstrap(bet_trace, n_resamples=500, seed=42).run()
    roi_stats = boot.metrics.get("roi")
    if roi_stats is None or not math.isfinite(roi_stats.se):
        raise ValueError("У кандидата нет пригодного betting trace для оценки разброса ROI")

    return {
        "state": "candidate",
        "tournament": profile.tournament,
        "display_name": tournament.display_name or profile.tournament,
        "model_pool": profile.model_pool,
        "market_spec": profile.market_spec,
        "run_id": run_id,
        "data_sha256": data_sha256,
        "data_rows": data_rows,
        "competition_codes": sorted(competition_codes),
        "test_window": {
            "first_event": first_event,
            "last_event": last_event,
            "n_events": n_events,
            "n_rows": len(bet_trace),
            "event_ids_sha256": event_ids_sha256,
        },
        "ml_metrics": {key: values[key] for key in ("logloss", "auc", "brier")},
        "betting_metrics": {
            **{key: values[key] for key in ("roi", "coverage", "n_bets")},
            "event_coverage": n_bet_events / n_events,
            "n_bet_events": n_bet_events,
        },
        "coverage_unit": (
            "betting_coverage = min(1, число ставок / число тестовых матчей); "
            "event_coverage = доля уникальных матчей хотя бы с одной ставкой"
        ),
        "simulation_metrics": {
            "roi_std": roi_stats.se,
            "roi_ci_lower": roi_stats.ci_lower,
            "roi_ci_upper": roi_stats.ci_upper,
            "bootstrap_resamples": boot.n_resamples,
        },
        "odds_limitation": (
            "Источник, время получения и прематч статус исторических коэффициентов "
            "Smart Tables не подтверждены; betting-метрики исследовательские."
            if profile.candidate_bookmaker == "smart_tables"
            else "Проверьте источник и время получения odds до решения о публикации."
        ),
    }
