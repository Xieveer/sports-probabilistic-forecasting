"""Legacy data_refresh не конкурирует с catalog-driven расписанием Airflow."""

from pathlib import Path


def test_legacy_data_refresh_has_no_schedule() -> None:
    source = (Path(__file__).resolve().parents[2] / "airflow/dags/dag_data_refresh.py").read_text()
    assert "schedule=None" in source
