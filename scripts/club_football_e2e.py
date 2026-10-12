"""Локальный E2E клубного 1X2 на реальном upcoming Smart Tables."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import httpx
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hydra import compose, initialize
from omegaconf import OmegaConf
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sports_forecast.bot.handlers import predict as bot_predict
from sports_forecast.bot.handlers.predict import _upcoming_query_params
from sports_forecast.config.loaders import load_source_config, load_tournament_config
from sports_forecast.data.clean import process_tournament as clean_tournament
from sports_forecast.data.club_upcoming import fetch_club_upcoming, write_upcoming_snapshot
from sports_forecast.data.ingest import process_tournament as ingest_tournament
from sports_forecast.data.providers.smart_tables.catalog import (
    filter_national_competitions,
    load_competition_catalog,
)
from sports_forecast.data.providers.smart_tables.client import SmartTablesApiClient
from sports_forecast.features.features_build import process_tournament_new
from sports_forecast.materialize import materialize_predictions
from sports_forecast.service.db.models import Base, Prediction
from sports_forecast.service.routers import predictions as predictions_router


ROOT = Path(__file__).resolve().parents[1]
HISTORY_SHA256 = "799cd61405e8d9ffb7aee8ac078fcbce9abefda3c2c3450c26a2c22b21407975"
STRATEGIES = ("football_long_binary", "football_wide_multiclass")


def _fetch_snapshot(local_root: Path, *, base_url: str, limit: int) -> tuple[Path, dict]:
    source_cfg = load_source_config("football_top_leagues")
    provider_cfg = OmegaConf.merge(
        source_cfg.provider,
        OmegaConf.create(
            {"base_url": base_url, "timeout_sec": 20, "retries": 2, "timeout_attempts": 2}
        ),
    )
    competitions = filter_national_competitions(
        load_competition_catalog(str(source_cfg.provider.catalog_path)),
        national_teams_only=False,
        competition_codes=list(source_cfg.provider.competition_codes),
    )
    observed_at = datetime.now(UTC)
    frame, coverage = fetch_club_upcoming(
        SmartTablesApiClient(provider_cfg), competitions, limit=limit, observed_at=observed_at
    )
    expected = set(source_cfg.provider.competition_codes)
    if set(coverage) != expected or not all(coverage.values()):
        raise ValueError(f"Неполное покрытие клубного пула: {coverage}")
    source_dir = local_root / "source" / "football_top_leagues"
    upcoming_path = source_dir / "upcoming.csv"
    write_upcoming_snapshot(frame, coverage, upcoming_path, observed_at=observed_at)
    return upcoming_path, coverage


def _build_inference(local_root: Path, upcoming_path: Path) -> dict:
    history_path = ROOT / "data/source/football_top_leagues/source.csv"
    history_hash = sha256(history_path.read_bytes()).hexdigest()
    if history_hash != HISTORY_SHA256:
        raise ValueError("Исторический source.csv отличается от обучающего snapshot")
    source_manifest = json.loads(upcoming_path.with_suffix(".snapshot.json").read_text())
    if sha256(upcoming_path.read_bytes()).hexdigest() != source_manifest["sha256"]:
        raise ValueError("Upcoming source snapshot изменился после получения")
    history = pd.read_csv(history_path, dtype=str, low_memory=False)
    upcoming = pd.read_csv(upcoming_path, dtype=str, low_memory=False)
    combined = pd.concat([history, upcoming], ignore_index=True)
    if not combined["match_id"].is_unique:
        raise ValueError("Исторические и match-center ID пересеклись")
    source_dir = upcoming_path.parent
    combined.to_csv(source_dir / "source.csv", index=False)
    paths = OmegaConf.create(
        {
            "paths": {
                "source_dir": "data/local_test/source",
                "raw_dir": "data/local_test/raw",
                "interim_dir": "data/local_test/interim",
                "processed_dir": "data/local_test/processed",
                "predictions_dir": "data/local_test/predictions",
                "models_dir": "models",
            }
        }
    )
    raw_root = local_root / "raw"
    interim_root = local_root / "interim"
    processed_root = local_root / "processed"
    tournament_cfg = load_tournament_config("football_top_leagues")
    ingest_tournament(source_dir, raw_root, paths)
    clean_tournament(raw_root / "football_top_leagues", tournament_cfg, paths)
    with initialize(version_base="1.3", config_path="../conf"):
        feature_cfg = compose(
            config_name="features_pipeline",
            overrides=["tournament=football_top_leagues", "features=basic"],
        )
    process_tournament_new(
        "football_top_leagues",
        interim_root,
        processed_root,
        feature_cfg.features,
        tournament_cfg=tournament_cfg,
        inference_only=True,
    )
    counts: dict[str, int] = {}
    for data_format, multiplier in (("long", 2), ("wide", 1)):
        path = processed_root / "football_top_leagues" / f"inference_{data_format}.parquet"
        frame = pd.read_parquet(path)
        if len(frame) != len(upcoming) * multiplier or not frame["status"].eq("upcoming").all():
            raise ValueError(f"Inference {data_format} потерял upcoming-события")
        path.with_suffix(".snapshot.json").write_text(
            json.dumps(
                {
                    "source": "smart_tables",
                    "observed_at": source_manifest["observed_at"],
                    "sha256": sha256(path.read_bytes()).hexdigest(),
                    "source_sha256": source_manifest["sha256"],
                    "history_sha256": history_hash,
                    "coverage": source_manifest["coverage"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        counts[data_format] = len(frame)
    return {"history_sha256": history_hash, "inference": counts}


def _materialize_and_preview(local_root: Path) -> dict:
    db_path = local_root / "predictions.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for strategy in STRATEGIES:
            with initialize(version_base="1.3", config_path="../conf"):
                cfg = compose(
                    config_name="config",
                    overrides=[
                        "tournament=football_top_leagues",
                        "market=winner",
                        "market_spec=winner_1x2",
                        "algorithm=catboost",
                        "features=basic",
                        f"model_strategy={strategy}",
                    ],
                )
            cfg.paths.processed_dir = "data/local_test/processed"
            cfg.paths.predictions_dir = "data/local_test/predictions"
            if not materialize_predictions(cfg, version="shadow", session=session):
                raise ValueError(f"Materialize failed: {strategy}")
        session.commit()
        counts = {
            strategy: session.query(Prediction)
            .filter_by(
                tournament="football_top_leagues",
                source_namespace=f"local_test/{strategy}",
                status="ok",
            )
            .count()
            for strategy in STRATEGIES
        }

    @contextmanager
    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(predictions_router.public_router)
    bot_cfg = OmegaConf.create(
        {
            "bot": {
                "api_base_url": "http://testserver",
                "club_test_enabled": True,
                "club_test_hours": 168,
                "live_pinnacle": False,
            }
        }
    )
    params = _upcoming_query_params("football_top_leagues", bot_cfg)
    with patch.object(predictions_router, "get_session", test_session):
        response = TestClient(app).get("/predict/upcoming/football_top_leagues", params=params)
    response.raise_for_status()
    items = response.json()["predictions"]
    if not items:
        raise ValueError("API не выдал ни одного upcoming-прогноза")

    class PreviewMessage:
        def __init__(self) -> None:
            self.text = ""

        async def answer(self, text: str) -> None:
            self.text = text

    message = PreviewMessage()

    async def render_bot() -> None:
        async_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )
        with (
            patch.object(predictions_router, "get_session", test_session),
            patch.object(bot_predict.httpx, "AsyncClient", return_value=async_client),
        ):
            await bot_predict.cmd_club_test(message, bot_cfg)  # type: ignore[arg-type]

    asyncio.run(render_bot())
    preview = message.text
    if "1X2 (бинарная)" not in preview or "1X2 (многоклассовая)" not in preview:
        raise ValueError("Бот не показал обе модельные стратегии")
    (local_root / "bot_preview.txt").write_text(preview, encoding="utf-8")
    return {
        "materialized": counts,
        "api_count": len(items),
        "bot_preview": "data/local_test/bot_preview.txt",
    }


def main() -> None:
    """Получить реальный snapshot и проверить локальную выдачу."""
    parser = argparse.ArgumentParser(description="Локальный E2E клубного 1X2")
    parser.add_argument("--base-url", default="https://smart-tables.ru/api/v1")
    parser.add_argument("--nearest-limit", type=int, default=10)
    parser.add_argument("--use-snapshot", action="store_true")
    args = parser.parse_args()
    local_root = ROOT / "data/local_test"
    if args.use_snapshot:
        upcoming_path = local_root / "source/football_top_leagues/upcoming.csv"
        coverage = json.loads(upcoming_path.with_suffix(".snapshot.json").read_text())["coverage"]
    else:
        upcoming_path, coverage = _fetch_snapshot(
            local_root, base_url=args.base_url, limit=args.nearest_limit
        )
    build = _build_inference(local_root, upcoming_path)
    publication = _materialize_and_preview(local_root)
    print(json.dumps({"coverage": coverage, **build, **publication}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
