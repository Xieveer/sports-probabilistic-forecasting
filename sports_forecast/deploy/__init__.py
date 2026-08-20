"""Граница deploy между production runtime и local control plane.

``ModelPromoter`` требует MLflow и загружается только при явном обращении к
нему. Это позволяет Worker проверять immutable model bundle без MLflow в
production image.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from sports_forecast.deploy.promoter import ModelPromoter


__all__ = ["ModelPromoter"]


def __getattr__(name: str) -> Any:
    """Лениво загрузить MLflow-зависимый API local control plane."""
    if name == "ModelPromoter":
        from sports_forecast.deploy.promoter import ModelPromoter

        return ModelPromoter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
