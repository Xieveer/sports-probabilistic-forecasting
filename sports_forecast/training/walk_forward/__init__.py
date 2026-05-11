"""
Walk-forward simulation over a temporal holdout (calendar steps).

Modules:
    slicer: ``WalkForwardSlicer`` — month boundaries (UTC semantics on naive datetimes).
    runner: ``WalkForwardRunner`` — refit per step with fixed hyperparameters.
"""

from __future__ import annotations

from sports_forecast.training.walk_forward.runner import WalkForwardResult, WalkForwardRunner
from sports_forecast.training.walk_forward.schema import WalkForwardConfig
from sports_forecast.training.walk_forward.slicer import WalkForwardSlicer


__all__ = [
    "WalkForwardConfig",
    "WalkForwardResult",
    "WalkForwardRunner",
    "WalkForwardSlicer",
]
