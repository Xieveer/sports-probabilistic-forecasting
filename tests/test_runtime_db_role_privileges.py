"""Integration checks for least-privilege runtime Postgres identities."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


@pytest.mark.integration
@pytest.mark.skipif(
    not (
        os.environ.get("SF_TEST_CONTROL_DATABASE_URL")
        and os.environ.get("SF_TEST_API_READER_DATABASE_URL")
    ),
    reason="Задайте runtime DB URLs на disposable PostgreSQL для grants tests",
)
def test_control_and_reader_roles_cannot_cross_their_database_boundaries() -> None:
    """Control читает только цикл и не завершает его; API reader не видит control state."""
    control_engine = create_engine(os.environ["SF_TEST_CONTROL_DATABASE_URL"])
    reader_engine = create_engine(os.environ["SF_TEST_API_READER_DATABASE_URL"])
    try:
        with control_engine.connect() as connection:
            assert (
                connection.execute(text("SELECT count(*) FROM data_cycle_runs")).scalar_one() >= 0
            )
            with pytest.raises(SQLAlchemyError):
                connection.execute(text("SELECT count(*) FROM predictions")).scalar_one()
            connection.rollback()
            with pytest.raises(SQLAlchemyError):
                connection.execute(text("UPDATE data_cycle_runs SET status='success' WHERE false"))

        with reader_engine.connect() as connection, pytest.raises(SQLAlchemyError):
            connection.execute(
                text("SELECT count(*) FROM data_cycle_control_requests")
            ).scalar_one()
    finally:
        control_engine.dispose()
        reader_engine.dispose()
