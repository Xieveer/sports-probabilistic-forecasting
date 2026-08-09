"""
Database engine management.

Поддерживает:
- SQLite для разработки (по умолчанию)
- PostgreSQL для продакшена (через ``DATABASE_URL``)

Конфигурация через переменные окружения:
    ``DATABASE_URL`` — полная строка подключения (e.g.
    ``postgresql://user:pass@host:5432/sports_forecast``)
    Если не задана — используется ``sqlite:///predictions.db``.

Примеры::

    from sports_forecast.service.db.engine import get_engine, get_session

    engine = get_engine()
    with get_session() as session:
        session.query(Prediction).filter_by(match_id="123").all()
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from sports_forecast.service.db.models import Base


_DEFAULT_DB_URL = "sqlite:///predictions.db"

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def get_database_url() -> str:
    """Получить URL базы данных из окружения или дефолт.

    Returns:
        Database URL string.
    """
    return os.environ.get("DATABASE_URL", _DEFAULT_DB_URL)


def get_engine(database_url: str | None = None) -> Engine:
    """Получить или создать SQLAlchemy Engine (singleton).

    Args:
        database_url: URL базы данных (опционально, приоритет над env).

    Returns:
        SQLAlchemy Engine.
    """
    global _engine  # noqa: PLW0603

    if _engine is None:
        url = database_url or get_database_url()
        connect_args = {}

        # SQLite: allow multi-thread access
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        _engine = create_engine(
            url,
            connect_args=connect_args,
            pool_pre_ping=True,
            echo=False,
        )

    return _engine


def get_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """Получить фабрику сессий (singleton).

    Args:
        engine: SQLAlchemy Engine (опционально).

    Returns:
        sessionmaker instance.
    """
    global _SessionFactory  # noqa: PLW0603

    if _SessionFactory is None:
        eng = engine or get_engine()
        _SessionFactory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)

    return _SessionFactory


@contextmanager
def get_session(engine: Engine | None = None) -> Generator[Session, None, None]:
    """Context manager для сессии БД.

    Args:
        engine: SQLAlchemy Engine (опционально).

    Yields:
        SQLAlchemy Session.

    Examples:
        >>> with get_session() as session:
        ...     preds = session.query(Prediction).all()
    """
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _ensure_sqlite_predictions_schema(eng: Engine) -> None:
    """Для существующих SQLite-БД: добавить колонки, появившиеся в ORM после create_all.

    ``create_all`` не изменяет уже созданные таблицы. При добавлении полей в
    ``Prediction`` старые файлы ``predictions.db`` остаются без новых колонок;
    здесь выполняется минимальный ALTER только для известных расхождений.

    Args:
        eng: SQLAlchemy Engine (ожидается SQLite).
    """
    if not str(eng.url).startswith("sqlite"):
        return
    insp = inspect(eng)
    if not insp.has_table("predictions"):
        return
    column_names = {c["name"] for c in insp.get_columns("predictions")}
    with eng.begin() as conn:
        if "model_tag" not in column_names:
            conn.execute(
                text(
                    "ALTER TABLE predictions ADD COLUMN model_tag VARCHAR(16) NOT NULL DEFAULT 'prod'"
                )
            )
        if "model_pool" not in column_names:
            conn.execute(text("ALTER TABLE predictions ADD COLUMN model_pool VARCHAR(128)"))
        if "immutable_model_version" not in column_names:
            conn.execute(
                text("ALTER TABLE predictions ADD COLUMN immutable_model_version VARCHAR(192)")
            )


def init_db(engine: Engine | None = None) -> None:
    """Создать все таблицы (если не существуют).

    Args:
        engine: SQLAlchemy Engine (опционально).
    """
    eng = engine or get_engine()
    Base.metadata.create_all(eng)
    _ensure_sqlite_predictions_schema(eng)


def reset_engine() -> None:
    """Сбросить singleton engine (для тестов)."""
    global _engine, _SessionFactory  # noqa: PLW0603
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
