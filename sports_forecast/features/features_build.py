"""
Модуль генерации базовых фичей и таргета (processed-слой).

Назначение:
    Преобразовать промежуточные данные (interim) в датасет для обучения моделей,
    добавив базовые фичи (разность и сумма очков), их лаги и колонку таргета.
    Финальный датасет содержит только необходимые для обучения колонки.

Слой данных:
    Вход:  data/interim/{tournament}/matches_interim.parquet
    Выход: data/processed/{tournament}/dataset.parquet

Логика фичей:
    - Базовые фичи:
        * points_diff = home_points - away_points (разность очков)
        * points_total = home_points + away_points (сумма очков)
    - Лаговые фичи:
        * points_diff_lag1 = points_diff.shift(1)
        * points_total_lag1 = points_total.shift(1)
    - Таргет: бинарный флаг победы хозяев (home_points > away_points)

    Финальный датасет содержит только: points_diff, points_total,
    points_diff_lag1, points_total_lag1, target

Конфигурация:
    Управляется через Hydra-конфиг ``conf/features_basic.yaml``.
"""

from __future__ import annotations

from pathlib import Path

import hydra
import pandas as pd
from omegaconf import DictConfig

from sports_forecast.utils.log_config import get_logger


PROJECT_ROOT = Path(__file__).resolve().parents[2]
logger = get_logger(__name__)


def _add_basic_features(df: pd.DataFrame, cfg: DictConfig, tournament_name: str) -> pd.DataFrame:
    """Добавить базовые фичи: разность и сумма очков.

    Args:
        df: Датафрейм с данными турнира.
        cfg: Hydra-конфиг с параметрами фичей.
        tournament_name: Название турнира (для логирования).

    Returns:
        Датафрейм с добавленными базовыми фичами.
    """
    if not hasattr(cfg.features, "basic"):
        logger.warning(
            "Турнир %s: секция 'basic' не найдена в конфиге, пропускаю базовые фичи",
            tournament_name,
        )
        return df

    basic_cfg = cfg.features.basic

    # Разность очков (diff)
    if hasattr(basic_cfg, "diff"):
        diff_cfg = basic_cfg.diff
        home_col = diff_cfg.home_column
        away_col = diff_cfg.away_column
        diff_name = diff_cfg.name

        if home_col not in df.columns or away_col not in df.columns:
            logger.warning(
                "Турнир %s: колонки '%s' или '%s' не найдены, пропускаю создание фичи разности",
                tournament_name,
                home_col,
                away_col,
            )
        else:
            df[diff_name] = df[home_col] - df[away_col]
            logger.info(
                "Турнир %s: создана фича разности '%s' = %s - %s",
                tournament_name,
                diff_name,
                home_col,
                away_col,
            )

    # Сумма очков (total)
    if hasattr(basic_cfg, "total"):
        total_cfg = basic_cfg.total
        home_col = total_cfg.home_column
        away_col = total_cfg.away_column
        total_name = total_cfg.name

        if home_col not in df.columns or away_col not in df.columns:
            logger.warning(
                "Турнир %s: колонки '%s' или '%s' не найдены, пропускаю создание фичи суммы",
                tournament_name,
                home_col,
                away_col,
            )
        else:
            df[total_name] = df[home_col] + df[away_col]
            logger.info(
                "Турнир %s: создана фича суммы '%s' = %s + %s",
                tournament_name,
                total_name,
                home_col,
                away_col,
            )

    return df


def _add_lag_features(df: pd.DataFrame, cfg: DictConfig, tournament_name: str) -> pd.DataFrame:
    """Добавить лаговые фичи по конфигу.

    Args:
        df: Датафрейм с данными турнира.
        cfg: Hydra-конфиг с параметрами лагов.
        tournament_name: Название турнира (для логирования).

    Returns:
        Датафрейм с добавленными лаговыми фичами.
    """
    if not hasattr(cfg.features, "lag"):
        logger.warning(
            "Турнир %s: секция 'lag' не найдена в конфиге, пропускаю лаговые фичи",
            tournament_name,
        )
        return df

    lag_cfg = cfg.features.lag

    # Лаг разности очков
    if hasattr(lag_cfg, "diff"):
        diff_lag_cfg = lag_cfg.diff
        src_col = diff_lag_cfg.source_column
        new_col = diff_lag_cfg.new_column
        periods = int(diff_lag_cfg.periods)

        if src_col not in df.columns:
            logger.warning(
                "Турнир %s: колонка для лаг-фичи '%s' не найдена, пропускаю",
                tournament_name,
                src_col,
            )
        else:
            df[new_col] = df[src_col].shift(periods)
            logger.info(
                "Турнир %s: создана лаг-фича '%s' = %s.shift(%d)",
                tournament_name,
                new_col,
                src_col,
                periods,
            )

    # Лаг суммы очков
    if hasattr(lag_cfg, "total"):
        total_lag_cfg = lag_cfg.total
        src_col = total_lag_cfg.source_column
        new_col = total_lag_cfg.new_column
        periods = int(total_lag_cfg.periods)

        if src_col not in df.columns:
            logger.warning(
                "Турнир %s: колонка для лаг-фичи '%s' не найдена, пропускаю",
                tournament_name,
                src_col,
            )
        else:
            df[new_col] = df[src_col].shift(periods)
            logger.info(
                "Турнир %s: создана лаг-фича '%s' = %s.shift(%d)",
                tournament_name,
                new_col,
                src_col,
                periods,
            )

    return df


def _add_target_column(df: pd.DataFrame, cfg: DictConfig, tournament_name: str) -> pd.DataFrame:
    """Добавить таргет-колонку: победа хозяев.

    Args:
        df: Датафрейм с данными турнира.
        cfg: Hydra-конфиг с параметрами таргета.
        tournament_name: Название турнира (для логирования).

    Returns:
        Датафрейм с добавленной таргет-колонкой.
    """
    if not hasattr(cfg.features, "target"):
        logger.warning(
            "Турнир %s: секция 'target' не найдена в конфиге, пропускаю создание таргета",
            tournament_name,
        )
        return df

    target_cfg = cfg.features.target
    target_name = target_cfg.name
    home_col = target_cfg.home_column
    away_col = target_cfg.away_column

    if home_col not in df.columns or away_col not in df.columns:
        logger.warning(
            "Турнир %s: колонки '%s' или '%s' не найдены, пропускаю создание таргета",
            tournament_name,
            home_col,
            away_col,
        )
        return df

    # Таргет: 1 если хозяева выиграли, 0 иначе
    df[target_name] = (df[home_col] > df[away_col]).astype(int)

    wins = df[target_name].sum()
    total = len(df)
    win_rate = (wins / total * 100) if total > 0 else 0

    logger.info(
        "Турнир %s: создан таргет '%s' (победа хозяев: %s > %s). Побед хозяев: %d/%d (%.1f%%)",
        tournament_name,
        target_name,
        home_col,
        away_col,
        wins,
        total,
        win_rate,
    )

    return df


def _select_final_columns(
    df: pd.DataFrame,
    cfg: DictConfig,
    tournament_name: str,
    *,
    include_target: bool,
) -> pd.DataFrame:
    """Выбрать колонки для финального датасета (meta + features [+ target]).

    Args:
        df: Датафрейм с подготовленными фичами.
        cfg: Hydra-конфиг с параметрами финальных колонок.
        tournament_name: Название турнира (для логирования).
        include_target: Добавлять ли таргет в итоговый набор (True для train, False для inference).

    Returns:
        Датафрейм с только необходимыми колонками.
    """
    features_cfg = getattr(cfg, "features", {})

    meta_cols = list(getattr(features_cfg, "meta_columns", []) or [])
    feature_cols = list(getattr(features_cfg, "final_columns", []) or [])

    cols: list[str] = []
    cols.extend(meta_cols)
    cols.extend(feature_cols)

    target_name: str | None = None
    if include_target and hasattr(features_cfg, "target"):
        target_name = features_cfg.target.name
        cols.append(target_name)

    available_cols = [c for c in cols if c in df.columns]

    if len(available_cols) != len(cols):
        missing = set(cols) - set(df.columns)
        logger.warning(
            "Турнир %s: не все финальные колонки найдены, отсутствуют %s",
            tournament_name,
            missing,
        )

    if not available_cols:
        logger.warning(
            "Турнир %s: не найдено ни одной финальной колонки, возвращаю исходный датафрейм",
            tournament_name,
        )
        return df

    df_final = df[available_cols].copy()
    logger.info(
        "Турнир %s: выбраны финальные колонки (%d): %s",
        tournament_name,
        len(available_cols),
        ", ".join(available_cols),
    )

    return df_final


def _split_by_status(
    df: pd.DataFrame, cfg: DictConfig, tournament_name: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Разделить данные на train (finished) и inference (upcoming) по статусу."""
    if not hasattr(cfg, "split"):
        logger.warning(
            "Турнир %s: секция 'split' не найдена в конфиге, всё пойдет в train", tournament_name
        )
        return df.copy(), df.iloc[0:0].copy()

    status_col = cfg.split.status_column
    if status_col not in df.columns:
        logger.error(
            "Турнир %s: колонка статуса '%s' не найдена. Колонки: %s",
            tournament_name,
            status_col,
            list(df.columns),
        )
        return df.iloc[0:0].copy(), df.iloc[0:0].copy()

    drop_statuses = set(cfg.split.get("drop_statuses", []) or [])
    if drop_statuses:
        before = len(df)
        df = df[~df[status_col].isin(drop_statuses)].copy()
        logger.info(
            "Турнир %s: отброшено по статусам %s: %d строк",
            tournament_name,
            sorted(drop_statuses),
            before - len(df),
        )

    train_status = cfg.split.train_status
    inference_status = cfg.split.inference_status

    train_df = df[df[status_col] == train_status].copy()
    inference_df = df[df[status_col] == inference_status].copy()

    logger.info(
        "Турнир %s: split по '%s': train=%d (%s), inference=%d (%s)",
        tournament_name,
        status_col,
        len(train_df),
        train_status,
        len(inference_df),
        inference_status,
    )

    return train_df, inference_df


def _drop_target_for_inference(
    df: pd.DataFrame, cfg: DictConfig, tournament_name: str
) -> pd.DataFrame:
    """Удалить таргет из inference-датасета."""
    if hasattr(cfg.features, "target"):
        target_name = cfg.features.target.name
        if target_name in df.columns:
            df = df.drop(columns=[target_name])
            logger.info("Турнир %s: удалён таргет '%s' из inference", tournament_name, target_name)
    return df


def process_tournament(tournament_dir: Path, cfg: DictConfig) -> None:
    """Обработать один турнир: interim → processed.

    Args:
        tournament_dir: Путь к директории турнира в interim-слое.
        cfg: Hydra-конфиг с параметрами генерации фичей.
    """
    tournament_name = tournament_dir.name
    interim_path = tournament_dir / "matches_interim.parquet"

    if not interim_path.exists():
        logger.warning("Турнир %s: файл %s не найден, пропускаю", tournament_name, interim_path)
        return

    logger.info("Турнир %s: читаю interim %s", tournament_name, interim_path)
    df: pd.DataFrame = pd.read_parquet(interim_path)

    if df is None or df.empty:
        logger.warning("Турнир %s: пустой датафрейм interim, пропускаю", tournament_name)
        return

    logger.info(
        "Турнир %s: загружено %d записей, %d колонок",
        tournament_name,
        len(df),
        df.shape[1],
    )

    # Добавляем базовые фичи (разность и сумма)
    df = _add_basic_features(df, cfg, tournament_name)

    # Добавляем лаговые фичи
    df = _add_lag_features(df, cfg, tournament_name)

    # Делим на train/inference до финальной селекции
    train_df, inference_df = _split_by_status(df, cfg, tournament_name)

    # Таргет нужен только для train (finished)
    train_df = _add_target_column(train_df, cfg, tournament_name)

    # На всякий случай гарантируем, что в inference таргета нет
    inference_df = _drop_target_for_inference(inference_df, cfg, tournament_name)

    # Финальная селекция колонок:
    # - train: meta + features + target
    # - inference: meta + features (без таргета)
    train_df = _select_final_columns(train_df, cfg, tournament_name, include_target=True)
    inference_df = _select_final_columns(
        inference_df,
        cfg,
        tournament_name,
        include_target=False,
    )

    # Сохраняем результат
    processed_root = PROJECT_ROOT / cfg.paths.processed_dir
    out_dir = processed_root / tournament_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Имена файлов берём из конфига (если есть), иначе дефолты
    train_name = getattr(getattr(cfg, "outputs", {}), "train_filename", "train.parquet")
    inf_name = getattr(getattr(cfg, "outputs", {}), "inference_filename", "inference.parquet")
    save_all = bool(getattr(getattr(cfg, "outputs", {}), "save_all", False))
    all_name = getattr(getattr(cfg, "outputs", {}), "all_filename", "dataset.parquet")

    train_path = out_dir / train_name
    inf_path = out_dir / inf_name

    if not train_df.empty:
        logger.info(
            "Турнир %s: записываю train (%d записей, %d колонок) → %s",
            tournament_name,
            len(train_df),
            train_df.shape[1],
            train_path,
        )
        train_df.to_parquet(train_path, index=False)
    else:
        logger.warning("Турнир %s: train пустой, файл не записан", tournament_name)

    if not inference_df.empty:
        logger.info(
            "Турнир %s: записываю inference (%d записей, %d колонок) → %s",
            tournament_name,
            len(inference_df),
            inference_df.shape[1],
            inf_path,
        )
        inference_df.to_parquet(inf_path, index=False)
    else:
        logger.warning("Турнир %s: inference пустой, файл не записан", tournament_name)

    if save_all:
        all_path = out_dir / all_name
        logger.info(
            "Турнир %s: записываю dataset (all) (%d записей, %d колонок) → %s",
            tournament_name,
            len(df),
            df.shape[1],
            all_path,
        )
        df.to_parquet(all_path, index=False)


@hydra.main(config_path="../../conf", config_name="features_basic", version_base="1.3")
def run(cfg: DictConfig) -> None:
    """Запустить генерацию фичей и таргета для всех турниров из interim-слоя."""
    interim_root = PROJECT_ROOT / cfg.paths.interim_dir
    processed_root = PROJECT_ROOT / cfg.paths.processed_dir

    if not interim_root.exists():
        raise RuntimeError(f"Папка с interim-данными не найдена: {interim_root}")

    processed_root.mkdir(parents=True, exist_ok=True)

    tournaments = sorted(p for p in interim_root.iterdir() if p.is_dir())
    if not tournaments:
        logger.warning("В %s нет ни одного турнира, ничего обрабатывать", interim_root)
        return

    logger.info("Найдено турниров в interim: %d", len(tournaments))
    for tournament_dir in tournaments:
        process_tournament(tournament_dir, cfg)


if __name__ == "__main__":
    run()
