"""
Config Validation Module для ML Training Pipeline.

Валидация Hydra конфигов перед запуском parent и nested runs.
Реализует принцип "fail fast" - ловим ошибки конфигурации рано.
"""

from pathlib import Path

from omegaconf import DictConfig


class ConfigValidationError(Exception):
    """Ошибка валидации конфигурации."""

    pass


def validate_parent_config(cfg: DictConfig, project_root: Path) -> None:
    """
    Валидация конфигурации перед запуском parent MLflow run.

    Args:
        cfg: Полный Hydra config
        project_root: Корневая директория проекта

    Raises:
        ConfigValidationError: Если конфигурация невалидна

    Examples:
        >>> validate_parent_config(cfg, Path("/project"))
    """
    errors: list[str] = []

    # 1. Tournament задан
    if not hasattr(cfg, "tournament") or not hasattr(cfg.tournament, "name"):
        errors.append("tournament.name обязателен!")
    else:
        tournament_name = cfg.tournament.name
        if tournament_name == "???":
            errors.append("tournament.name не задан! Укажите: tournament=uel_kz_1")

    # 2. Market family задан
    if not hasattr(cfg, "market") or not hasattr(cfg.market, "family"):
        errors.append("market.family обязателен!")
    else:
        market_family = cfg.market.family
        if market_family == "???":
            errors.append("market.family не задан! Укажите: market=total")

        # Валидация допустимых family
        allowed_families = ["winner", "total", "handicap"]
        if market_family not in allowed_families:
            errors.append(
                f"market.family должен быть одним из {allowed_families}, получено: {market_family}"
            )

    # 3. MarketSpec задан и валиден
    if not hasattr(cfg, "market_spec") or not hasattr(cfg.market_spec, "name"):
        errors.append("market_spec.name обязателен!")
    else:
        market_spec_name = cfg.market_spec.name
        if market_spec_name == "???":
            errors.append("market_spec.name не задан! Укажите: market_spec=total_over")

    # 4. Для total: line обязателен
    if hasattr(cfg, "market") and cfg.market.get("family") == "total":
        if not hasattr(cfg.market_spec, "line") or cfg.market_spec.line == "???":
            errors.append(
                "market_spec.line обязателен для total markets! Укажите: market_spec.line=6.5"
            )
        else:
            # Проверяем что line допустима для турнира
            if hasattr(cfg, "tournament") and hasattr(cfg.tournament, "allowed_market_specs"):
                allowed_lines = cfg.tournament.allowed_market_specs.total.get("lines", [])
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

    # 7. Recipe задан (если используется)
    if hasattr(cfg, "recipe") and (not hasattr(cfg.recipe, "name") or cfg.recipe.name == "???"):
        errors.append("recipe.name не задан! Укажите: recipe=total_baseline")

    # Если есть ошибки - падаем с подробным сообщением
    if errors:
        error_msg = "\n❌ ОШИБКА ВАЛИДАЦИИ PARENT CONFIG:\n\n" + "\n".join(
            f"  • {err}" for err in errors
        )
        raise ConfigValidationError(error_msg)


def validate_experiment_config(cfg_experiment: DictConfig) -> None:
    """
    Валидация конфигурации перед запуском experiment (nested run).

    Args:
        cfg_experiment: Config для конкретного эксперимента

    Raises:
        ConfigValidationError: Если конфигурация невалидна

    Examples:
        >>> validate_experiment_config(cfg_exp)
    """
    errors: list[str] = []

    # 1. Algorithm задан
    if not hasattr(cfg_experiment, "algorithm"):
        errors.append("algorithm config обязателен!")
    else:
        if not hasattr(cfg_experiment.algorithm, "_target_"):
            errors.append("algorithm._target_ обязателен! Должен указывать на класс модели")
        elif cfg_experiment.algorithm._target_ == "???":
            errors.append("algorithm._target_ не задан!")

    # 2. Featureset задан
    if not hasattr(cfg_experiment, "features"):
        errors.append("features config обязателен!")
    else:
        if not hasattr(cfg_experiment.features, "name"):
            errors.append("features.name обязателен!")
        elif cfg_experiment.features.name == "???":
            errors.append("features.name не задан! Укажите: features=advanced")

    # 3. Hyper стратегия валидна
    if hasattr(cfg_experiment, "hyper") and hasattr(cfg_experiment.hyper, "strategy"):
        strategy = cfg_experiment.hyper.strategy
        allowed_strategies = ["none", "grid", "optuna"]
        if strategy not in allowed_strategies:
            errors.append(
                f"hyper.strategy должна быть одной из {allowed_strategies}, получено: {strategy}"
            )

    # Если есть ошибки - падаем
    if errors:
        error_msg = "\n❌ ОШИБКА ВАЛИДАЦИИ EXPERIMENT CONFIG:\n\n" + "\n".join(
            f"  • {err}" for err in errors
        )
        raise ConfigValidationError(error_msg)


def get_data_path(tournament_cfg: DictConfig, data_format: str) -> Path:
    """
    Получить путь к данным на основе tournament и data_format.

    Args:
        tournament_cfg: cfg.tournament
        data_format: "long" или "wide"

    Returns:
        Путь к parquet файлу (относительный)

    Raises:
        ValueError: Если формат не поддерживается

    Examples:
        >>> path = get_data_path(cfg.tournament, "long")
        >>> # data/processed/uel_kz_1/train_long.parquet
    """
    if data_format not in ["long", "wide"]:
        raise ValueError(f"data_format должен быть 'long' или 'wide', получено: {data_format}")

    # Получаем базовую директорию
    processed_dir = Path(tournament_cfg.data.processed_dir)

    # Получаем имя файла для формата
    filename = tournament_cfg.data.formats.get(data_format)
    if not filename:
        raise ValueError(
            f"Формат '{data_format}' не определён для турнира "
            f"{tournament_cfg.name}. Доступные: {list(tournament_cfg.data.formats.keys())}"
        )

    return processed_dir / filename  # type: ignore[no-any-return]


def check_line_allowed(tournament_cfg: DictConfig, market_family: str, line: float) -> bool:
    """
    Проверить допустимость линии для турнира.

    Args:
        tournament_cfg: cfg.tournament
        market_family: "total" / "handicap"
        line: Значение линии (например, 6.5)

    Returns:
        True если линия допустима, иначе False

    Examples:
        >>> is_allowed = check_line_allowed(cfg.tournament, "total", 6.5)
    """
    if not hasattr(tournament_cfg, "allowed_market_specs"):
        return True  # Если реестра нет - разрешаем всё

    market_specs = tournament_cfg.allowed_market_specs.get(market_family)
    if not market_specs:
        return True

    allowed_lines = market_specs.get("lines", [])
    if not allowed_lines:
        return True  # Если линии не указаны - разрешаем всё

    return line in allowed_lines


def get_allowed_lines(tournament_cfg: DictConfig, market_family: str) -> list[float]:
    """
    Получить список допустимых линий для турнира и market family.

    Args:
        tournament_cfg: cfg.tournament
        market_family: "total" / "handicap"

    Returns:
        Список допустимых линий

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
    """
    Вывести краткую сводку по конфигурации (для отладки).

    Args:
        cfg: Hydra config

    Examples:
        >>> print_config_summary(cfg)
    """
    print("━" * 80)
    print("📋 CONFIGURATION SUMMARY")
    print("━" * 80)

    # Tournament
    if hasattr(cfg, "tournament"):
        print(f"🏆 Tournament: {cfg.tournament.name}")
        print(f"   Sport: {cfg.tournament.get('sport', 'N/A')}")

    # Market
    if hasattr(cfg, "market"):
        print(f"📊 Market: {cfg.market.family}")

    # MarketSpec
    if hasattr(cfg, "market_spec"):
        print(f"🎯 MarketSpec: {cfg.market_spec.name}")
        print(f"   Side: {cfg.market_spec.get('side', 'N/A')}")
        if hasattr(cfg.market_spec, "line"):
            print(f"   Line: {cfg.market_spec.line}")
        print(f"   Data Format: {cfg.market_spec.data_format}")

    # Recipe
    if hasattr(cfg, "recipe"):
        print(f"📝 Recipe: {cfg.recipe.name}")
        if hasattr(cfg.recipe, "algorithms"):
            print(f"   Algorithms: {', '.join(cfg.recipe.algorithms)}")
        if hasattr(cfg.recipe, "featuresets"):
            print(f"   Features: {', '.join(cfg.recipe.featuresets)}")

    print("━" * 80)
