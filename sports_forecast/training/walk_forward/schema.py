"""Structured defaults for walk-forward Hydra config (``walk_forward`` group)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WalkForwardConfig:
    """Walk-forward training / evaluation settings (mirrors ``conf/walk_forward.yaml``).

    The running pipeline reads the Hydra node ``cfg.walk_forward``; this dataclass
    documents the contract for tooling and optional static checks.
    """

    enabled: bool = False
    frequency: str = "month"
    init_train_end: str | None = None
    reuse_optuna_params: bool = True
