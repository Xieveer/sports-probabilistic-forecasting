"""
Prediction Materialization Pipeline.

Предвычисляет предсказания для предстоящих матчей и
записывает их в Prediction Store (SQLite/PostgreSQL).

Поток:
    1. Загрузка inference-датасета (processed/inference_long.parquet)
    2. Загрузка prod-модели (из models/ директории)
    3. Вычисление predict_proba
    4. Агрегация: long-format → per-match predictions
    5. Запись в БД (upsert)

Запуск::

    uv run python -m sports_forecast.materialize \\
        tournament=uel_kz_1 \\
        market=winner \\
        market_spec=winner \\
        algorithm=catboost \\
        features=basic

Примечание:
    Модель загружается из ``models/{tournament}/{market_spec}/{algorithm}_{features}/``.
    Используется **prod**-версия модели.
"""

from __future__ import annotations

import json
import os
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import hydra
import numpy as np
import pandas as pd
import yaml
from omegaconf import DictConfig, OmegaConf
from sqlalchemy.orm import Session

from sports_forecast.config.model_strategy import effective_market_spec, model_strategy_name
from sports_forecast.deploy.managed_model import (
    PinnedModelContract,
    deployment_matches_pin,
    resolve_active_model,
)
from sports_forecast.deploy.model_bundle import BundleVerificationError, verify_model_bundle
from sports_forecast.predict import (
    find_model_file,
    get_model_dir,
    load_feature_names,
    load_model_from_path,
)
from sports_forecast.service.db.engine import get_engine, get_session
from sports_forecast.service.db.repository import ModelRegistryRepository, PredictionRepository
from sports_forecast.training.probability_metrics import audit_long_1x2_probabilities
from sports_forecast.utils.log_config import configure_logging, get_logger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = get_logger(__name__)


@dataclass(frozen=True)
class PromotedModelContract:
    """Явный контракт promoted-модели для materialize.

    Attributes:
        model_dir: Директория артефакта promoted-модели.
        algorithm: Имя алгоритма, выбранного на этапе promote.
        featureset: Имя набора фичей, выбранного на этапе promote.
    """

    model_dir: Path
    algorithm: str
    featureset: str


def _load_promoted_contract(cfg: DictConfig, project_root: Path) -> PromotedModelContract | None:
    """Загрузить контракт promoted-модели из deploy.yaml.

    Args:
        cfg: Полный Hydra-конфиг.
        project_root: Корневая директория проекта.

    Returns:
        Контракт promoted-модели или None, если контракт отсутствует/некорректен.
    """
    tournament_name = str(cfg.tournament.name)
    market_spec_name = str(cfg.market_spec.name)
    runtime_bundle = cfg.get("runtime_model_bundle")
    if isinstance(runtime_bundle, str) and runtime_bundle:
        promoted_dir = Path(runtime_bundle)
    else:
        models_dir = Path(str(cfg.paths.models_dir))
        promoted_dir = project_root / models_dir / tournament_name / market_spec_name / "best"
    deploy_path = promoted_dir / "deploy.yaml"

    if not deploy_path.exists():
        logger.error("Promoted contract не найден: %s", deploy_path)
        return None

    try:
        raw = yaml.safe_load(deploy_path.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.exception("Не удалось прочитать promoted contract: %s", deploy_path)
        return None

    model_meta = raw.get("model", {})
    algorithm_name = model_meta.get("algorithm")
    featureset_name = model_meta.get("featureset")
    if not algorithm_name or not featureset_name:
        logger.error(
            "Promoted contract некорректен: отсутствуют model.algorithm/featureset в %s",
            deploy_path,
        )
        return None

    return PromotedModelContract(
        model_dir=promoted_dir,
        algorithm=str(algorithm_name),
        featureset=str(featureset_name),
    )


def _load_algorithm_config(
    project_root: Path, algorithm_name: str, fallback: DictConfig, *, strict: bool = False
) -> DictConfig:
    """Загрузить конфиг алгоритма по имени из conf/algorithm.

    Args:
        project_root: Корневая директория проекта.
        algorithm_name: Имя алгоритма.
        fallback: Fallback-конфиг, если файл не найден.

    Returns:
        Конфиг алгоритма для загрузки модели.
    """
    algorithm_cfg_path = project_root / "conf" / "algorithm" / f"{algorithm_name}.yaml"
    if not algorithm_cfg_path.exists():
        if strict:
            raise BundleVerificationError(
                f"Algorithm config отсутствует для managed bundle: {algorithm_name}"
            )
        logger.warning("Конфиг алгоритма %s не найден, использую cfg.algorithm", algorithm_cfg_path)
        return fallback

    loaded = OmegaConf.load(algorithm_cfg_path)
    if isinstance(loaded, DictConfig):
        return loaded

    if strict:
        raise BundleVerificationError(
            f"Algorithm config некорректен для managed bundle: {algorithm_name}"
        )

    logger.warning("Некорректный конфиг алгоритма %s, использую cfg.algorithm", algorithm_cfg_path)
    return fallback


def _resolve_verified_model_provenance(
    cfg: DictConfig, registry: ModelRegistryRepository
) -> tuple[str | None, str | None, PinnedModelContract | None]:
    """Сверить managed registry identity с проверенным runtime bundle."""
    model_pool = cfg.get("model_pool")
    if model_pool is None:
        return None, None, None
    pool_name = model_pool.get("name")
    if not isinstance(pool_name, str) or not pool_name:
        raise ValueError("model_pool.name обязателен для materialize")
    active = registry.get_active(pool_name, str(cfg.market_spec.name))
    if active is None:
        raise ValueError("Materialize model pool требует active production pointer")
    if active.is_managed:
        app_version = cfg.get("runtime_model_bundle_app_version") or os.environ.get(
            "SF_APP_VERSION"
        )
        bundle_root_value = cfg.get("runtime_model_bundle_root") or os.environ.get(
            "SF_MODEL_RUNTIME_ROOT"
        )
        if not isinstance(app_version, str) or not app_version:
            raise ValueError("Managed materialize требует app version для проверки bundle")
        if not isinstance(bundle_root_value, str) or not bundle_root_value:
            raise ValueError("Managed materialize требует managed bundle root")
        pin = resolve_active_model(
            registry.session,
            model_pool=pool_name,
            market_spec=str(cfg.market_spec.name),
            bundle_root=Path(bundle_root_value),
            app_version=app_version,
        )
        return pool_name, pin.model_identity, pin
    runtime_bundle = cfg.get("runtime_model_bundle")
    app_version = cfg.get("runtime_model_bundle_app_version")
    if not isinstance(runtime_bundle, str) or not runtime_bundle:
        raise ValueError("Legacy materialize требует явно заданный verified bundle")
    if not isinstance(app_version, str) or not app_version:
        raise ValueError("Legacy materialize требует app version для проверки bundle")
    bundle = verify_model_bundle(Path(runtime_bundle), app_version=app_version)
    if bundle.model_identity != active.model_identity:
        raise BundleVerificationError("bundle identity не совпадает с active registry")
    return pool_name, bundle.model_identity, None


def _assert_pin_current(
    session: Session,
    model_pool: str | None,
    market_spec: str,
    pin: PinnedModelContract | None,
) -> None:
    """Отказать публикации, если managed pointer сменился после inference."""
    if (
        pin is not None
        and model_pool is not None
        and not deployment_matches_pin(session, model_pool, market_spec, pin)
    ):
        raise BundleVerificationError("Managed model pointer изменился во время inference")


def _long_row_participant_display_name(row: pd.Series) -> str:
    """Отображаемое имя участника из одной строки long-format inference.

    ``wide_to_long`` кладёт идентификатор в ``pl`` (команда NHL и т.п.); для
    индивидуальных рынков может быть ``pl_short_name_en``. Материализация
    должна поддерживать оба варианта.

    Args:
        row: Строка inference DataFrame (long).

    Returns:
        Непустая строка или ``""``, если подходящего поля нет.
    """
    for col in ("pl_short_name_en", "pl"):
        if col not in row.index:
            continue
        val = row[col]
        if pd.isna(val):
            continue
        text = str(val).strip()
        if text and text.lower() != "nan":
            return text
    return ""


def _aggregate_long_predictions(
    df: pd.DataFrame,
    proba: np.ndarray,
) -> pd.DataFrame:
    """Агрегировать long-format предсказания в per-match записи.

    Для winner market: каждый матч имеет 2 строки (home, away).
    Вероятность класса 1 для home row = P(home wins),
    для away row = P(away wins).

    Имена для БД/digest: ``pl_short_name_en`` или fallback на ``pl`` (см.
    :func:`_long_row_participant_display_name`).

    Args:
        df: Inference DataFrame (long format).
        proba: Матрица вероятностей (N x 2 для бинарной).

    Returns:
        DataFrame с одной строкой на матч и колонками:
        match_id, match_datetime, home_player, away_player,
        proba_home, proba_away, predictions_json, odds_raw.
    """
    model_probabilities = np.asarray(proba, dtype=float)
    if model_probabilities.shape[0] != len(df):
        raise ValueError("Model probability row count does not match inference input")
    if model_probabilities.ndim == 2:
        if model_probabilities.shape[1] != 2:
            raise ValueError("winner market requires exactly two model probability outcomes")
        if not np.isfinite(model_probabilities).all():
            raise ValueError("Model probabilities must be finite")
        if ((model_probabilities < 0) | (model_probabilities > 1)).any():
            raise ValueError("Model probabilities must be in the range [0, 1]")
        if not np.allclose(model_probabilities.sum(axis=1), 1.0, rtol=0, atol=1e-6):
            raise ValueError("Model probability outcomes must sum to one per input row")
        proba_win = model_probabilities[:, 1]
    elif model_probabilities.ndim == 1:
        if not np.isfinite(model_probabilities).all():
            raise ValueError("Model probabilities must be finite")
        if ((model_probabilities < 0) | (model_probabilities > 1)).any():
            raise ValueError("Model probabilities must be in the range [0, 1]")
        proba_win = model_probabilities
    else:
        raise ValueError("Model probabilities must be a vector or two-outcome matrix")

    df = df.copy()
    df["proba_win"] = proba_win

    records: list[dict] = []

    # Группируем по match_id
    for match_id, group in df.groupby("id"):
        home_row = group[group["side"] == "h"]
        away_row = group[group["side"] == "a"]

        if home_row.empty or away_row.empty:
            logger.warning("Матч %s: отсутствует home или away строка, пропускаю", match_id)
            continue

        home = home_row.iloc[0]
        away = away_row.iloc[0]

        p_home = float(home["proba_win"])
        p_away = float(away["proba_win"])
        if not np.isfinite([p_home, p_away]).all() or not (0 <= p_home <= 1 and 0 <= p_away <= 1):
            raise ValueError(
                "Aggregated model probabilities must be finite and in the range [0, 1]"
            )

        # Нормализуем (сумма = 1.0)
        total = p_home + p_away
        if not np.isfinite(total) or total <= 0:
            raise ValueError("Aggregated model probabilities must have a positive finite sum")
        p_home_norm = p_home / total
        p_away_norm = p_away / total
        if (
            not np.isfinite([p_home_norm, p_away_norm]).all()
            or not (0 <= p_home_norm <= 1 and 0 <= p_away_norm <= 1)
            or not np.isclose(p_home_norm + p_away_norm, 1.0, rtol=0, atol=1e-12)
        ):
            raise ValueError("Aggregated outcome probabilities must be finite and sum to one")

        predictions = {
            "home_win": round(p_home_norm, 4),
            "away_win": round(p_away_norm, 4),
        }

        # Odds из raw
        odds_raw_val = home.get("odds_raw")
        if pd.isna(odds_raw_val):
            odds_raw_val = None

        records.append(
            {
                "match_id": str(match_id),
                "match_datetime": pd.to_datetime(home["datetime"]),
                "home_player": _long_row_participant_display_name(home),
                "away_player": _long_row_participant_display_name(away),
                "proba_home": round(p_home_norm, 6),
                "proba_away": round(p_away_norm, 6),
                "predictions_json": json.dumps(predictions, ensure_ascii=False),
                "odds_raw": str(odds_raw_val) if odds_raw_val is not None else None,
                "canonical_event_id": (
                    int(home["canonical_event_id"])
                    if "canonical_event_id" in group.columns
                    and pd.notna(home["canonical_event_id"])
                    else None
                ),
            }
        )

    return pd.DataFrame(records)


def _aggregate_football_1x2_predictions(
    df: pd.DataFrame,
    proba: np.ndarray,
    classes: np.ndarray,
    *,
    strategy: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Собрать 1X2 и отдельно вернуть события с невалидным остатком."""
    probabilities = np.asarray(proba, dtype=float)
    class_list = list(np.asarray(classes))
    if strategy == "football_long_binary":
        if probabilities.shape != (len(df), 2) or set(class_list) != {0, 1}:
            raise ValueError("Long 1X2 требует бинарные вероятности классов 0/1")
        valid, rejected = audit_long_1x2_probabilities(df, probabilities[:, class_list.index(1)])
        home_rows = df.loc[df["is_home"].astype(int).eq(1)].set_index("id")
        away_rows = df.loc[df["is_home"].astype(int).eq(0)].set_index("id")
    elif strategy == "football_wide_multiclass":
        if probabilities.shape != (len(df), 3) or set(class_list) != {0, 1, 2}:
            raise ValueError("Wide 1X2 требует классы 0/1/2")
        if (
            not np.isfinite(probabilities).all()
            or (probabilities < 0).any()
            or (probabilities > 1).any()
            or not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-6)
        ):
            raise ValueError("Wide 1X2 содержит невалидное распределение")
        if df["id"].isna().any() or df["id"].duplicated().any():
            raise ValueError("Wide 1X2 содержит пустой или повторный ID")
        valid = pd.DataFrame(
            {
                "home_win": probabilities[:, class_list.index(0)],
                "draw": probabilities[:, class_list.index(1)],
                "away_win": probabilities[:, class_list.index(2)],
            },
            index=df["id"],
        )
        rejected = pd.DataFrame(columns=["reason"])
        home_rows = df.set_index("id")
        away_rows = home_rows
    else:
        raise ValueError(f"Неизвестная модельная стратегия 1X2: {strategy}")

    records: list[dict[str, object]] = []
    for match_id, probabilities_row in valid.iterrows():
        event_key = cast(Any, match_id)
        home = home_rows.loc[event_key]
        away = away_rows.loc[event_key]
        p_home = round(float(probabilities_row["home_win"]), 6)
        p_draw = round(float(probabilities_row["draw"]), 6)
        p_away = round(1.0 - p_home - p_draw, 6)
        if min(p_home, p_draw, p_away) < 0:
            raise ValueError(f"1X2 стал невалидным после округления: {match_id}")
        predictions = {"home_win": p_home, "draw": p_draw, "away_win": p_away}
        odds_raw = home.get("odds_raw")
        if pd.isna(odds_raw):
            odds_raw = None
        canonical_id = home.get("canonical_event_id")
        away_canonical_id = away.get("canonical_event_id")
        if (
            pd.notna(canonical_id)
            and pd.notna(away_canonical_id)
            and int(canonical_id) != int(away_canonical_id)
        ):
            raise ValueError(f"Разные canonical_event_id для матча {match_id}")
        if pd.isna(canonical_id):
            canonical_id = away_canonical_id
        records.append(
            {
                "match_id": str(match_id),
                "match_datetime": pd.to_datetime(home["datetime"]),
                "home_player": str(home["pl"]),
                "away_player": str(
                    away["pl"] if strategy == "football_long_binary" else home["opp"]
                ),
                "proba_home": p_home,
                "proba_away": p_away,
                "predictions_json": json.dumps(predictions, ensure_ascii=False),
                "odds_raw": str(odds_raw) if odds_raw is not None else None,
                "canonical_event_id": int(canonical_id) if pd.notna(canonical_id) else None,
            }
        )
    rejected_report = rejected.reset_index().rename(columns={"id": "match_id"})
    if "match_id" not in rejected_report:
        rejected_report["match_id"] = pd.Series(dtype=str)
    return pd.DataFrame(records), rejected_report[["match_id", "reason"]]


def _publish_empty_showcase(
    session: Session | None,
    *,
    tournament: str,
    market: str,
    market_spec: str,
    source_namespace: str | None = None,
    model_pool: str | None = None,
    pin: PinnedModelContract | None = None,
) -> None:
    """Атомарно закрыть прежнюю активную витрину при пустом model input."""
    session_context = get_session() if session is None else nullcontext(session)
    with session_context as db_session:
        _assert_pin_current(db_session, model_pool, market_spec, pin)
        if pin is not None and not source_namespace:
            raise ValueError("Managed empty publication requires source_namespace")
        PredictionRepository(db_session).publish_showcase(
            [],
            tournament=tournament,
            market=market,
            market_spec=market_spec,
            source_namespace=source_namespace,
        )


def _remove_staged_predictions(path: Path) -> None:
    """Best-effort cleanup артефакта, не влияющий на результат DB publication."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Не удалось удалить временный parquet: %s", path, exc_info=True)


def _assert_local_test_session(session: Session, project_root: Path) -> None:
    """Допустить 1X2 только в изолированную локальную SQLite test DB."""
    bind = session.get_bind()
    url = bind.engine.url
    if url.get_backend_name() != "sqlite":
        raise ValueError("Локальный 1X2 требует SQLite test DB")
    database = url.database
    if database is None or database in ("", ":memory:"):
        return
    test_root = (project_root / "data" / "local_test").resolve()
    if not Path(database).resolve().is_relative_to(test_root):
        raise ValueError("Локальный 1X2 требует DB внутри data/local_test")


def _assert_smart_tables_upcoming_snapshot(inference_path: Path, df: pd.DataFrame) -> None:
    """Проверить источник, байты и будущую дату каждого upcoming-события."""
    manifest_path = inference_path.with_suffix(".snapshot.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("source") != "smart_tables":
        raise ValueError("Локальный 1X2 требует snapshot Smart Tables")
    actual_hash = sha256(inference_path.read_bytes()).hexdigest()
    if manifest.get("sha256") != actual_hash:
        raise ValueError("Hash inference не совпадает со Smart Tables snapshot")
    observed_at = pd.to_datetime(manifest.get("observed_at"), utc=True, errors="coerce")
    if pd.isna(observed_at):
        raise ValueError("Smart Tables snapshot не содержит observed_at")
    now = datetime.now(UTC)
    if (
        observed_at.to_pydatetime() > now
        or (now - observed_at.to_pydatetime()).total_seconds() > 3600
    ):
        raise ValueError("Smart Tables upcoming snapshot устарел или датирован будущим")
    scheduled = pd.to_datetime(df.get("datetime"), utc=True, errors="coerce")
    if (
        scheduled is None
        or scheduled.isna().any()
        or (scheduled <= observed_at).any()
        or (scheduled <= now).any()
    ):
        raise ValueError("Upcoming содержит матч без будущей даты")


def materialize_predictions(
    cfg: DictConfig, version: str = "prod", *, session: Session | None = None
) -> bool:
    """Предвычислить предсказания и записать в БД.

    Args:
        cfg: Полный Hydra конфиг.
        version: Версия модели (``"prod"`` по умолчанию).
        session: Внешняя DB-транзакция для atomic publication (опционально).

    Returns:
        True если материализация успешна.
    """
    tournament_name = str(cfg.tournament.name)
    market_name = str(cfg.market.get("name", cfg.market.get("family", "winner")))
    market_spec_name = str(cfg.market_spec.name)
    algorithm_name = str(cfg.algorithm.name)
    featureset_name = str(cfg.features.name)
    data_format = str(effective_market_spec(cfg).data_format)
    strategy = model_strategy_name(cfg)
    club_local = market_spec_name == "winner_1x2"
    if club_local and (
        session is None or version != "shadow" or strategy == "standard" or cfg.get("model_pool")
    ):
        logger.error("Локальный 1X2 требует явную strategy, shadow и внешнюю test DB-сессию")
        return False
    if club_local:
        try:
            assert session is not None
            _assert_local_test_session(session, PROJECT_ROOT)
        except ValueError as exc:
            logger.error("Локальная DB не прошла проверку: %s", exc)
            return False
    model_dir = get_model_dir(cfg, PROJECT_ROOT)
    algorithm_cfg = cfg.algorithm

    # Фиксируем registry identity и проверяем байты до загрузки модели и input.
    # Эта же identity переносится в публикацию без повторного чтения pointer.
    pinned_model: PinnedModelContract | None = None
    staged_predictions_path: Path | None = None
    try:
        session_context = get_session() if session is None else nullcontext(session)
        with session_context as db_session:
            model_pool, immutable_model_version, pinned_model = _resolve_verified_model_provenance(
                cfg, ModelRegistryRepository(db_session)
            )
    except (BundleVerificationError, ValueError) as exc:
        logger.error("Managed model contract не прошёл проверку: %s", exc)
        return False
    runtime_feature_contract = cfg.get("feature_contract_id")
    if (
        pinned_model is not None
        and runtime_feature_contract is not None
        and runtime_feature_contract != pinned_model.bundle.feature_contract_id
    ):
        logger.error("Runtime feature contract не совпадает с managed bundle")
        return False

    if pinned_model is not None:
        model_dir = pinned_model.bundle.path
        algorithm_name = pinned_model.bundle.algorithm
        algorithm_cfg = _load_algorithm_config(
            PROJECT_ROOT, algorithm_name, cfg.algorithm, strict=True
        )
    elif version == "prod":
        promoted = _load_promoted_contract(cfg, PROJECT_ROOT)
        if promoted is None:
            logger.error("Materialize(prod) требует валидный promoted contract")
            return False
        model_dir = promoted.model_dir
        algorithm_name = promoted.algorithm
        featureset_name = promoted.featureset
        algorithm_cfg = _load_algorithm_config(PROJECT_ROOT, algorithm_name, cfg.algorithm)

    model_version = f"{algorithm_name}_{featureset_name}_{version}"
    if club_local:
        model_version = f"{model_version}__{strategy}"

    logger.info("=" * 60)
    logger.info("MATERIALIZE PREDICTIONS")
    logger.info("  Tournament: %s", tournament_name)
    logger.info("  Market: %s / %s", market_name, market_spec_name)
    logger.info("  Algorithm: %s", algorithm_name)
    logger.info("  Features: %s", featureset_name)
    logger.info("  Model version: %s", model_version)
    logger.info("=" * 60)

    try:
        # 1. Загружаем модель
        model_file = (
            pinned_model.model_file
            if pinned_model is not None
            else find_model_file(model_dir, version=version)
        )
        if club_local and model_file != model_dir / f"{strategy}_shadow.cbm":
            raise ValueError("Локальный 1X2 требует точный shadow-артефакт стратегии")

        if model_file is None:
            logger.error("Модель не найдена в %s (version=%s)", model_dir, version)
            return False

        model = load_model_from_path(algorithm_cfg, model_file)

        # 2. Загружаем feature list
        feature_names = (
            [str(feature["name"]) for feature in pinned_model.bundle.features]
            if pinned_model is not None
            else load_feature_names(model_dir)
        )

        # 3. Загружаем inference data
        processed_root = PROJECT_ROOT / cfg.paths.processed_dir
        inference_path = processed_root / tournament_name / f"inference_{data_format}.parquet"

        if not inference_path.exists():
            logger.warning("Inference data не найден: %s", inference_path)
            return False

        df = pd.read_parquet(inference_path)
        logger.info("Inference data loaded: %d строк", len(df))
        if club_local and not df.empty:
            _assert_smart_tables_upcoming_snapshot(inference_path, df)
            if "status" not in df or not df["status"].eq("upcoming").all():
                raise ValueError("Локальный 1X2 принимает только upcoming-события")
            score_columns = (
                ("pl_points", "opp_points")
                if data_format == "long"
                else ("home_points", "away_points")
            )
            if any(column in df and df[column].notna().any() for column in score_columns):
                raise ValueError("Upcoming 1X2 содержит известный итоговый счёт")

        if df.empty:
            logger.warning("Inference data пуст — нет предстоящих матчей")
            _publish_empty_showcase(
                session,
                tournament=tournament_name,
                market=market_name,
                market_spec=market_spec_name,
                source_namespace=(
                    f"local_test/{strategy}" if club_local else cfg.get("source_namespace")
                ),
                model_pool=model_pool,
                pin=pinned_model,
            )
            return True

        # 4. Извлекаем фичи
        if feature_names:
            available = [f for f in feature_names if f in df.columns]
            if len(available) < len(feature_names):
                missing = set(feature_names) - set(available)
                if pinned_model is not None or club_local:
                    raise BundleVerificationError(
                        f"Managed bundle features отсутствуют во входе: {sorted(missing)}"
                    )
                logger.warning("Отсутствуют фичи: %s", missing)
            features = df[available]
        else:
            features = df.select_dtypes(include="number")
            logger.warning(
                "Feature list не найден, используются все числовые: %d", features.shape[1]
            )

        # 5. Predict
        logger.info("Считаю predict_proba на %d строках, %d фичей...", *features.shape)
        proba = model.predict_proba(features)

        # 6. Агрегация
        if club_local:
            preds_df, rejected = _aggregate_football_1x2_predictions(
                df, proba, np.asarray(getattr(model, "classes_", None)), strategy=strategy
            )
            logger.info(
                "1X2: отклонено %d из %d матчей (%.2f%%)",
                len(rejected),
                len(preds_df) + len(rejected),
                100 * len(rejected) / max(1, len(preds_df) + len(rejected)),
            )
            if not rejected.empty:
                logger.warning("1X2 карантин прогноза: %s", rejected.to_dict(orient="records"))
        else:
            preds_df = _aggregate_long_predictions(df, proba)
        logger.info("Агрегировано %d предсказаний (матчей)", len(preds_df))

        if preds_df.empty:
            raise ValueError("Непустой inference не дал агрегированных предсказаний")

        # 7. Подготовить файл во временном пути. Production parquet меняется
        # только после успешной проверки pin и записи DB-витрины.
        predictions_root = PROJECT_ROOT / cfg.paths.predictions_dir
        out_dir = predictions_root / tournament_name / market_spec_name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / (
            f"predictions_{version}_{strategy}.parquet"
            if club_local
            else f"predictions_{version}.parquet"
        )
        staged_predictions_path = out_dir / f".{out_path.name}.{uuid4().hex}.tmp"
        preds_df.to_parquet(staged_predictions_path, index=False)

        # 8. Запись в БД. Schema применяет отдельная migration command.
        session_context = get_session() if session is None else nullcontext(session)
        with session_context as db_session:
            _assert_pin_current(db_session, model_pool, market_spec_name, pinned_model)
            repo = PredictionRepository(db_session)
            records: list[dict[str, object]] = []
            publication_run_id = (
                cfg.get("refresh_run_id")
                or os.environ.get("SF_WORKER_RUN_ID")
                or f"materialize-{uuid4().hex}"
            )
            for _, row in preds_df.iterrows():
                publication_record: dict[str, object] = {
                    "match_id": row["match_id"],
                    "tournament": tournament_name,
                    "market": market_name,
                    "market_spec": market_spec_name,
                    "predictions": json.loads(row["predictions_json"]),
                    "model_version": model_version,
                    "algorithm": algorithm_name,
                    "featureset": featureset_name,
                    "model_pool": model_pool,
                    "immutable_model_version": immutable_model_version,
                    "refresh_run_id": publication_run_id,
                    "canonical_snapshot_id": cfg.get("canonical_snapshot_id"),
                    "feature_contract_id": (
                        pinned_model.bundle.feature_contract_id
                        if pinned_model is not None
                        else cfg.get("feature_contract_id")
                    ),
                    "home_player": row.get("home_player"),
                    "away_player": row.get("away_player"),
                    "match_datetime": row.get("match_datetime"),
                    "proba_home": row.get("proba_home"),
                    "proba_away": row.get("proba_away"),
                    "odds_raw": row.get("odds_raw"),
                    "status": "ok",
                }
                if club_local:
                    publication_record["source_namespace"] = f"local_test/{strategy}"
                if pinned_model is not None:
                    publication_record.update(
                        {
                            "refresh_run_id": publication_run_id,
                            "bundle_id": pinned_model.bundle_id,
                            "model_identity": pinned_model.model_identity,
                            "source_namespace": cfg.get("source_namespace"),
                            "canonical_event_id": row.get("canonical_event_id"),
                            "input_snapshot_ref": cfg.get("canonical_snapshot_id"),
                        }
                    )
                records.append(publication_record)
            count = repo.publish_showcase(
                records,
                tournament=tournament_name,
                market=market_name,
                market_spec=market_spec_name,
                source_namespace=f"local_test/{strategy}" if club_local else None,
            )

            logger.info("Записано %d предсказаний в Prediction Store", count)

        if session is None:
            try:
                staged_predictions_path.replace(out_path)
                logger.info("Parquet сохранён: %s", out_path)
            except OSError:
                logger.warning(
                    "DB-витрина обновлена, но локальный parquet не обновлён: %s",
                    out_path,
                    exc_info=True,
                )
            finally:
                _remove_staged_predictions(staged_predictions_path)
            staged_predictions_path = None
        else:
            # Внешний владелец транзакции может откатить DB после возврата.
            # Parquet в таком сценарии не является подтверждённой публикацией.
            _remove_staged_predictions(staged_predictions_path)
            staged_predictions_path = None

        logger.info("Материализация для %s завершена успешно", tournament_name)
        return True

    except Exception:
        if staged_predictions_path is not None:
            _remove_staged_predictions(staged_predictions_path)
        logger.exception("Ошибка материализации для %s", tournament_name)
        if session is not None:
            # Внешний владелец транзакции обязан получить ошибку, чтобы отозвать
            # stale-метки и любые частичные изменения публикации.
            raise
        return False


@hydra.main(config_path="../conf", config_name="config", version_base="1.3")
def run(cfg: DictConfig) -> None:
    """Запустить Prediction Materialization Pipeline.

    Args:
        cfg: Hydra-конфиг.
    """
    configure_logging(level=cfg.logging.level)

    logger.info("=" * 80)
    logger.info("PREDICTION MATERIALIZATION PIPELINE v2.0")
    logger.info("=" * 80)

    # DB setup
    db_url = cfg.get("database", {}).get("url", None)
    if db_url:
        import os

        os.environ["DATABASE_URL"] = str(db_url)

    get_engine()

    version = cfg.get("model_version", "prod")

    success = materialize_predictions(cfg, version=version)
    if success:
        logger.info("Материализация завершена успешно")
    else:
        logger.error("Материализация завершена с ошибками")


if __name__ == "__main__":
    run()
