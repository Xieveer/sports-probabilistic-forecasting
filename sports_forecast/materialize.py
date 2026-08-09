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
from dataclasses import dataclass
from pathlib import Path

import hydra
import numpy as np
import pandas as pd
import yaml
from omegaconf import DictConfig, OmegaConf

from sports_forecast.predict import (
    find_model_file,
    get_model_dir,
    load_feature_names,
    load_model_from_path,
)
from sports_forecast.service.db.engine import get_engine, get_session
from sports_forecast.service.db.repository import ModelRegistryRepository, PredictionRepository
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
    project_root: Path, algorithm_name: str, fallback: DictConfig
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
        logger.warning("Конфиг алгоритма %s не найден, использую cfg.algorithm", algorithm_cfg_path)
        return fallback

    loaded = OmegaConf.load(algorithm_cfg_path)
    if isinstance(loaded, DictConfig):
        return loaded

    logger.warning("Некорректный конфиг алгоритма %s, использую cfg.algorithm", algorithm_cfg_path)
    return fallback


def _resolve_model_provenance(
    cfg: DictConfig, registry: ModelRegistryRepository
) -> tuple[str | None, str | None]:
    """Вернуть provenance active pointer для pool-run либо legacy ``None``."""
    model_pool = cfg.get("model_pool")
    if model_pool is None:
        return None, None
    pool_name = model_pool.get("name")
    if not isinstance(pool_name, str) or not pool_name:
        raise ValueError("model_pool.name обязателен для materialize")
    market_spec = str(cfg.market_spec.name)
    active = registry.get_active(pool_name, market_spec)
    if active is None:
        raise ValueError("Materialize model pool требует active production pointer")
    return pool_name, active.model_identity


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
    # P(win) = proba[:, 1] для бинарной классификации
    proba_win = proba[:, 1] if proba.ndim == 2 and proba.shape[1] == 2 else proba

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

        # Нормализуем (сумма = 1.0)
        total = p_home + p_away
        if total > 0:
            p_home_norm = p_home / total
            p_away_norm = p_away / total
        else:
            p_home_norm = 0.5
            p_away_norm = 0.5

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
            }
        )

    return pd.DataFrame(records)


def materialize_predictions(cfg: DictConfig, version: str = "prod") -> bool:
    """Предвычислить предсказания и записать в БД.

    Args:
        cfg: Полный Hydra конфиг.
        version: Версия модели (``"prod"`` по умолчанию).

    Returns:
        True если материализация успешна.
    """
    tournament_name = str(cfg.tournament.name)
    market_name = str(cfg.market.get("name", cfg.market.get("family", "winner")))
    market_spec_name = str(cfg.market_spec.name)
    algorithm_name = str(cfg.algorithm.name)
    featureset_name = str(cfg.features.name)
    data_format = str(cfg.market_spec.data_format)
    model_dir = get_model_dir(cfg, PROJECT_ROOT)
    algorithm_cfg = cfg.algorithm

    if version == "prod":
        promoted = _load_promoted_contract(cfg, PROJECT_ROOT)
        if promoted is None:
            logger.error("Materialize(prod) требует валидный promoted contract")
            return False
        model_dir = promoted.model_dir
        algorithm_name = promoted.algorithm
        featureset_name = promoted.featureset
        algorithm_cfg = _load_algorithm_config(PROJECT_ROOT, algorithm_name, cfg.algorithm)

    model_version = f"{algorithm_name}_{featureset_name}_{version}"

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
        model_file = find_model_file(model_dir, version=version)

        if model_file is None:
            logger.error("Модель не найдена в %s (version=%s)", model_dir, version)
            return False

        model = load_model_from_path(algorithm_cfg, model_file)

        # 2. Загружаем feature list
        feature_names = load_feature_names(model_dir)

        # 3. Загружаем inference data
        processed_root = PROJECT_ROOT / cfg.paths.processed_dir
        inference_path = processed_root / tournament_name / f"inference_{data_format}.parquet"

        if not inference_path.exists():
            logger.warning("Inference data не найден: %s", inference_path)
            return False

        df = pd.read_parquet(inference_path)
        logger.info("Inference data loaded: %d строк", len(df))

        if df.empty:
            logger.warning("Inference data пуст — нет предстоящих матчей")
            return True  # Не ошибка

        # 4. Извлекаем фичи
        if feature_names:
            available = [f for f in feature_names if f in df.columns]
            if len(available) < len(feature_names):
                missing = set(feature_names) - set(available)
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
        preds_df = _aggregate_long_predictions(df, proba)
        logger.info("Агрегировано %d предсказаний (матчей)", len(preds_df))

        if preds_df.empty:
            logger.warning("Нет агрегированных предсказаний")
            return True

        # 7. Файловый результат готовится до смены DB-витрины. Если этот шаг
        # не удался, прежние API predictions остаются нетронутыми.
        predictions_root = PROJECT_ROOT / cfg.paths.predictions_dir
        out_dir = predictions_root / tournament_name / market_spec_name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"predictions_{version}.parquet"
        preds_df.to_parquet(out_path, index=False)
        logger.info("Parquet сохранён: %s", out_path)

        # 8. Запись в БД. Schema применяет отдельная migration command.
        with get_session() as session:
            repo = PredictionRepository(session)
            model_pool, immutable_model_version = _resolve_model_provenance(
                cfg, ModelRegistryRepository(session)
            )

            records: list[dict[str, object]] = []
            for _, row in preds_df.iterrows():
                records.append(
                    {
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
                        "home_player": row.get("home_player"),
                        "away_player": row.get("away_player"),
                        "match_datetime": row.get("match_datetime"),
                        "proba_home": row.get("proba_home"),
                        "proba_away": row.get("proba_away"),
                        "odds_raw": row.get("odds_raw"),
                        "status": "ok",
                    }
                )
            count = repo.publish_showcase(
                records,
                tournament=tournament_name,
                market=market_name,
                market_spec=market_spec_name,
            )

            logger.info("Записано %d предсказаний в Prediction Store", count)

        logger.info("Материализация для %s завершена успешно", tournament_name)
        return True

    except Exception:
        logger.exception("Ошибка материализации для %s", tournament_name)
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
