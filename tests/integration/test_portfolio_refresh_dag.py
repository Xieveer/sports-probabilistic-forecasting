"""Контракт DAG, который раскрывает heavy targets из portfolio catalog."""

from __future__ import annotations

from pathlib import Path


def test_portfolio_refresh_dag_uses_catalog_and_not_static_tournament_variable() -> None:
    """DAG получает targets из каталога и ограничивает fan-out Airflow pool-ом."""
    source = (
        Path(__file__).resolve().parents[2] / "airflow" / "dags" / "dag_portfolio_refresh.py"
    ).read_text(encoding="utf-8")

    assert "load_heavy_refresh_targets" in source
    assert "SF_PORTFOLIO_CATALOG" in source
    assert "SF_REFRESH_TOURNAMENTS" not in source
    assert "pool_slots=1" in source
