"""Планирование изолированного heavy refresh из каталога портфеля."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from sports_forecast.config.portfolio import PortfolioCatalog, load_portfolio_catalog
from sports_forecast.orchestration.refresh_command import build_refresh_per_tournament_command


@dataclass(frozen=True)
class HeavyRefreshTarget:
    """Одна независимая heavy-цепочка tournament/source/model pool."""

    tournament: str
    source: str
    model_pool: str
    market_spec: str
    lock_key: str


def build_heavy_refresh_targets(catalog: PortfolioCatalog) -> tuple[HeavyRefreshTarget, ...]:
    """Построить targets из deployment profiles, не используя статические списки."""
    targets: list[HeavyRefreshTarget] = []
    for profile in sorted(catalog.deployment_profiles.values(), key=lambda item: item.name):
        tournament = catalog.tournaments[profile.tournament]
        key_input = f"{tournament.name}:{tournament.source}".encode()
        lock_key = f"sf-refresh-{hashlib.sha256(key_input).hexdigest()[:16]}"
        targets.append(
            HeavyRefreshTarget(
                tournament=tournament.name,
                source=tournament.source,
                model_pool=profile.model_pool,
                market_spec=profile.market_spec,
                lock_key=lock_key,
            )
        )
    return tuple(targets)


def load_heavy_refresh_targets(catalog_path: Path) -> tuple[HeavyRefreshTarget, ...]:
    """Загрузить канонический каталог и построить targets для scheduler-а."""
    return build_heavy_refresh_targets(load_portfolio_catalog(catalog_path))


def build_heavy_refresh_command(
    target: HeavyRefreshTarget, *, project_dir: str, uv_run: str
) -> str:
    """Собрать heavy-команду строго для одного target с его per-key lock."""
    source_cmd = f"{uv_run} python -m sports_forecast.orchestration.source_refresh --tournament {{tournament}}"
    return build_refresh_per_tournament_command(
        project_dir=project_dir,
        uv_run=uv_run,
        tournaments_expr=target.tournament,
        features_config="basic",
        market="winner",
        market_spec=target.market_spec,
        source_cmd=source_cmd,
        lock_file=f"/tmp/{target.lock_key}.lock",
        lock_wait_seconds=300,
    )
