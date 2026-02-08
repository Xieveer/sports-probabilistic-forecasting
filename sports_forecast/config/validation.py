"""
Config Validation Module для ML Training Pipeline.

Валидация Hydra конфигов перед запуском обучения.
Реализует принцип "fail fast" — ловим ошибки конфигурации рано.
"""

from pathlib import Path

from omegaconf import DictConfig, OmegaConf


class ConfigValidationError(Exception):
    """Ошибка валидации конфигурации."""


def validate_experiment_config(cfg: DictConfig, project_root: Path) -> None:
    """Валидация конфигурации одного эксперимента.

    Проверяет: tournament, market, market_spec, algorithm, features,
    data_format, допустимость линии, наличие файла данных.

    Args:
        cfg: Полный Hydra config.
        project_root: Корневая директория проекта.

    Raises:
        ConfigValidationError: Если конфигурация невалидна.

    Examples:
        >>> validate_experiment_config(cfg, Path("/project"))
    """
    errors: list[str] = []

    # 1. Tournament задан
    if not hasattr(cfg, "tournament") or not hasattr(cfg.tournament, "name"):
        errors.append("tournament.name обязателен! Укажите: tournament=uel_kz_1")
    elif OmegaConf.is_missing(cfg.tournament, "name"):
        errors.append("tournament.name не задан! Укажите: tournament=uel_kz_1")

    # 2. Market family задан
    if not hasattr(cfg, "market") or not hasattr(cfg.market, "family"):
        errors.append("market.family обязателен! Укажите: market=total")
    elif OmegaConf.is_missing(cfg.market, "family"):
        errors.append("market.family не задан! Укажите: market=total")
    else:
        allowed_families = ["winner", "total", "handicap"]
        if cfg.market.family not in allowed_families:
            errors.append(
                f"market.family должен быть одним из {allowed_families}, "
                f"получено: {cfg.market.family}"
            )

    # 3. MarketSpec задан и валиден
    if not hasattr(cfg, "market_spec") or not hasattr(cfg.market_spec, "name"):
        errors.append("market_spec.name обязателен! Укажите: market_spec=total_over")
    elif OmegaConf.is_missing(cfg.market_spec, "name"):
        errors.append("market_spec.name не задан! Укажите: market_spec=total_over")

    # 4. Для total/handicap: line обязателен
    if hasattr(cfg, "market") and cfg.market.get("family") in ["total", "handicap"]:
        if "line" not in cfg.market_spec or OmegaConf.is_missing(cfg.market_spec, "line"):
            errors.append(
                f"market_spec.line обязателен для {cfg.market.family} markets! "
                f"Укажите: market_spec.line=6.5"
            )
        else:
            if hasattr(cfg, "tournament") and hasattr(cfg.tournament, "allowed_market_specs"):
                allowed_lines = get_allowed_lines(cfg.tournament, cfg.market.family)
                if allowed_lines and cfg.market_spec.line not in allowed_lines:
                    errors.append(
                        f"Line {cfg.market_spec.line} не допустима для "
                        f"{cfg.tournament.name}. Допустимые: {allowed_lines}"
                    )

    # 5. data_format явно задан
    if not hasattr(cfg.market_spec, "data_format"):
        errors.append("market_spec.data_format обязателен! Должен быть 'long' или 'wide'")
    else:
        data_format = cfg.market_spec.data_format
        if data_format not in ["long", "wide"]:
            errors.append(
                f"market_spec.data_format должен быть 'long' или 'wide', получено: {data_format}"
            )

    # 6. Файл данных существует
    if (
        hasattr(cfg, "tournament")
        and hasattr(cfg, "market_spec")
        and hasattr(cfg.market_spec, "data_format")
    ):
        try:
            data_path = get_data_path(cfg.tournament, cfg.market_spec.data_format)
            full_path = project_root / data_path

            if not full_path.exists():
                errors.append(
                    f"Файл данных не найден: {full_path}\n"
                    f"  Tournament: {cfg.tournament.name}\n"
                    f"  Format: {cfg.market_spec.data_format}\n"
                    f"  Убедитесь что DVC pipeline запущен: make dvc-repro"
                )
        except Exception as e:
            errors.append(f"Ошибка проверки пути к данным: {e}")

    # 7. Algorithm задан
    if not hasattr(cfg, "algorithm"):
        errors.append("algorithm config обязателен! Укажите: algorithm=catboost")
    elif not hasattr(cfg.algorithm, "_target_") or OmegaConf.is_missing(cfg.algorithm, "_target_"):
        errors.append("algorithm._target_ не задан! Должен указывать на класс модели")

    # 8. Featureset задан
    if not hasattr(cfg, "features"):
        errors.append("features config обязателен! Укажите: features=basic")
    elif not hasattr(cfg.features, "name") or OmegaConf.is_missing(cfg.features, "name"):
        errors.append("features.name не задан! Укажите: features=basic")

    # 9. Hyper стратегия валидна
    if hasattr(cfg, "hyper") and hasattr(cfg.hyper, "strategy"):
        strategy = cfg.hyper.strategy
        allowed_strategies = ["none", "grid", "optuna"]
        if strategy not in allowed_strategies:
            errors.append(
                f"hyper.strategy должна быть одной из {allowed_strategies}, получено: {strategy}"
            )

    if errors:
        error_msg = "\n❌ ОШИБКА ВАЛИДАЦИИ CONFIG:\n\n" + "\n".join(f"  • {err}" for err in errors)
        raise ConfigValidationError(error_msg)


def get_data_path(tournament_cfg: DictConfig, data_format: str) -> Path:
    """Получить путь к данным на основе tournament и data_format.

    Args:
        tournament_cfg: ``cfg.tournament``.
        data_format: ``"long"`` или ``"wide"``.

    Returns:
        Путь к parquet файлу (относительный).

    Raises:
        ValueError: Если формат не поддерживается.

    Examples:
        >>> path = get_data_path(cfg.tournament, "long")
        >>> # data/processed/uel_kz_1/train_long.parquet
    """
    if data_format not in ["long", "wide"]:
        raise ValueError(f"data_format должен быть 'long' или 'wide', получено: {data_format}")

    processed_dir = Path(tournament_cfg.data.processed_dir)

    filename = tournament_cfg.data.formats.get(data_format)
    if not filename:
        raise ValueError(
            f"Формат '{data_format}' не определён для турнира "
            f"{tournament_cfg.name}. "
            f"Доступные: {list(tournament_cfg.data.formats.keys())}"
        )

    return processed_dir / filename  # type: ignore[no-any-return]


def check_line_allowed(tournament_cfg: DictConfig, market_family: str, line: float) -> bool:
    """Проверить допустимость линии для турнира.

    Args:
        tournament_cfg: ``cfg.tournament``.
        market_family: ``"total"`` / ``"handicap"``.
        line: Значение линии (например, 6.5).

    Returns:
        True если линия допустима, иначе False.
    """
    if not hasattr(tournament_cfg, "allowed_market_specs"):
        return True

    market_specs = tournament_cfg.allowed_market_specs.get(market_family)
    if not market_specs:
        return True

    allowed_lines = market_specs.get("lines", [])
    if not allowed_lines:
        return True

    return line in allowed_lines


def get_allowed_lines(tournament_cfg: DictConfig, market_family: str) -> list[float]:
    """Получить список допустимых линий для турнира и market family.

    Args:
        tournament_cfg: ``cfg.tournament``.
        market_family: ``"total"`` / ``"handicap"``.

    Returns:
        Список допустимых линий.

    Examples:
        >>> lines = get_allowed_lines(cfg.tournament, "total")
        >>> # [3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5]
    """
    if not hasattr(tournament_cfg, "allowed_market_specs"):
        return []

    market_specs = tournament_cfg.allowed_market_specs.get(market_family)
    if not market_specs:
        return []

    return market_specs.get("lines", [])  # type: ignore[no-any-return]


def print_config_summary(cfg: DictConfig) -> None:
    """Вывести краткую сводку по конфигурации (для отладки).

    Args:
        cfg: Hydra config.
    """
    print("━" * 80)
    print("CONFIGURATION SUMMARY")
    print("━" * 80)

    if hasattr(cfg, "tournament"):
        print(f"  Tournament: {cfg.tournament.name}")
        print(f"  Sport: {cfg.tournament.get('sport', 'N/A')}")

    if hasattr(cfg, "market"):
        print(f"  Market: {cfg.market.family}")

    if hasattr(cfg, "market_spec"):
        print(f"  MarketSpec: {cfg.market_spec.name}")
        print(f"  Side: {cfg.market_spec.get('side', 'N/A')}")
        if hasattr(cfg.market_spec, "line"):
            print(f"  Line: {cfg.market_spec.line}")
        print(f"  Data Format: {cfg.market_spec.data_format}")

    if hasattr(cfg, "algorithm"):
        print(f"  Algorithm: {cfg.algorithm.name}")

    if hasattr(cfg, "features"):
        print(f"  Features: {cfg.features.name}")

    print("━" * 80)
