"""Unified config loaders for Hydra compose.

Centralizes all Hydra compose calls for loading tournament, source,
bookmaker, and paths configs. Replaces duplicated loading logic
scattered across ingest.py and clean.py.

Examples:
    >>> from sports_forecast.config.loaders import (
    ...     load_tournament_config,
    ...     load_paths_config,
    ...     load_source_config,
    ... )
    >>> tcfg = load_tournament_config("uel_kz_1")
    >>> pcfg = load_paths_config()
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydra import compose, initialize_config_dir
from omegaconf import DictConfig, OmegaConf

from sports_forecast.utils.log_config import get_logger


if TYPE_CHECKING:
    from sports_forecast.orchestration.notification_profiles import NotificationProfile
    from sports_forecast.validation.tournament_quality import (
        ResultFieldRule,
        TournamentQualityGateConfig,
    )


logger = get_logger(__name__)

#: Корневая директория проекта
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Путь к директории конфигов
CONF_DIR = str((PROJECT_ROOT / "conf").resolve())


def load_tournament_config(tournament_name: str) -> DictConfig:
    """Загрузить конфигурацию турнира через Hydra compose.

    Hydra ``compose()`` помещает конфиг в namespace config-группы
    (``tournament``), поэтому результат разворачивается до плоского
    DictConfig для совместимости с потребителями.

    Args:
        tournament_name: Название турнира (например: ``'uel_kz_1'``, ``'lp_ru'``).

    Returns:
        DictConfig с конфигурацией турнира (плоская, без обёртки ``tournament:``).

    Raises:
        FileNotFoundError: Если конфиг турнира не найден.

    Examples:
        >>> cfg = load_tournament_config('uel_kz_1')
        >>> cfg.name
        'uel_kz_1'
    """
    config_path = PROJECT_ROOT / "conf" / "tournament" / f"{tournament_name}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Конфиг турнира не найден: {config_path}")

    try:
        with initialize_config_dir(config_dir=CONF_DIR, version_base="1.3"):
            cfg = compose(
                config_name=f"tournament/{tournament_name}",
                return_hydra_config=False,
            )
        # Hydra compose оборачивает конфиг под ключ config-группы "tournament".
        # Разворачиваем для совместимости: cfg.tournament → cfg.
        if "tournament" in cfg:
            return cfg.tournament  # type: ignore[no-any-return]
        return cfg  # type: ignore[no-any-return]
    except Exception as e:
        logger.error("Ошибка загрузки конфига турнира %s: %s", tournament_name, e)
        raise


def load_source_config(source_name: str) -> DictConfig:
    """Загрузить конфигурацию источника данных через Hydra compose.

    Args:
        source_name: Название источника (например: ``'uel'``, ``'lp_eu'``).

    Returns:
        DictConfig с конфигурацией источника.

    Raises:
        FileNotFoundError: Если конфиг источника не найден.

    Examples:
        >>> cfg = load_source_config('uel')
        >>> cfg.split_strategy.enabled
        True
    """
    config_path = PROJECT_ROOT / "conf" / "source" / f"{source_name}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Конфиг источника не найден: {config_path}")

    try:
        with initialize_config_dir(config_dir=CONF_DIR, version_base="1.3"):
            cfg = compose(
                config_name=f"source/{source_name}",
                return_hydra_config=False,
            )
        if "source" in cfg:
            return cfg.source  # type: ignore[no-any-return]
        return cfg  # type: ignore[no-any-return]
    except Exception as e:
        logger.error("Ошибка загрузки конфига источника %s: %s", source_name, e)
        raise


def load_bookmaker_config(bookmaker: str) -> DictConfig | None:
    """Загрузить конфигурацию букмекера.

    Читает YAML напрямую через OmegaConf — без Hydra compose, чтобы не конфликтовать
    с уже инициализированным GlobalHydra (например, внутри @hydra.main).
    Возвращает DictConfig с обёрткой ``bookmaker:`` для совместимости с
    ``apply_tournament_default_bookmaker``.

    Args:
        bookmaker: Название букмекера (например: ``'fonbet'``, ``'the_odds_api'``).

    Returns:
        DictConfig вида ``{bookmaker: {name: ..., ...}}`` или None если не найден.
    """
    config_path = PROJECT_ROOT / "conf" / "bookmaker" / f"{bookmaker}.yaml"
    if not config_path.exists():
        logger.warning("Конфиг букмекера %s не найден: %s", bookmaker, config_path)
        return None

    try:
        raw = OmegaConf.load(config_path)
        return OmegaConf.create({"bookmaker": raw})  # type: ignore[no-any-return]
    except Exception as e:
        logger.error("Ошибка загрузки конфига букмекера %s: %s", bookmaker, e)
        return None


def load_paths_config() -> DictConfig:
    """Загрузить конфигурацию путей через Hydra compose.

    Returns:
        DictConfig с ключом ``paths`` содержащим все пути проекта.

    Examples:
        >>> cfg = load_paths_config()
        >>> cfg.paths.raw_dir
        'data/raw'
    """
    try:
        with initialize_config_dir(config_dir=CONF_DIR, version_base="1.3"):
            return compose(  # type: ignore[no-any-return]
                config_name="paths",
                return_hydra_config=False,
            )
    except Exception as e:
        logger.error("Ошибка загрузки paths config: %s", e)
        raise


def load_tournament_quality_gate_config(tournament_name: str) -> TournamentQualityGateConfig:
    """Загрузить профиль tournament quality gate.

    Args:
        tournament_name: Идентификатор турнира, совпадающий с именем YAML-профиля.

    Returns:
        Нормализованные правила проверки полноты source-данных.

    Raises:
        FileNotFoundError: Если профиль отсутствует.
        ValueError: Если профиль не содержит обязательных полей или имеет неверное окно.
    """
    from sports_forecast.validation.tournament_quality import (
        ResultFieldRule,
        TournamentQualityGateConfig,
    )

    config_path = PROJECT_ROOT / "conf" / "quality_gate" / f"{tournament_name}.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(f"Профиль quality gate не найден: {config_path}")
    raw = OmegaConf.to_container(OmegaConf.load(config_path), resolve=True)
    if not isinstance(raw, dict):
        raise ValueError(f"Профиль quality gate должен быть объектом: {config_path}")
    try:
        window_hours = int(raw["schedule_window_hours"])
        required_fields = tuple(str(field) for field in raw["required_result_fields"])
        raw_rules = raw["result_field_rules"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Некорректный профиль quality gate: {config_path}") from exc
    if window_hours <= 0 or not required_fields or not isinstance(raw_rules, dict):
        raise ValueError(f"Некорректный профиль quality gate: {config_path}")
    rules: dict[str, ResultFieldRule] = {}
    for field_name, raw_rule in raw_rules.items():
        if not isinstance(field_name, str) or not isinstance(raw_rule, dict):
            raise ValueError(f"Некорректный профиль quality gate: {config_path}")
        value_type = raw_rule.get("value_type")
        if value_type not in {"integer", "enum"}:
            raise ValueError(f"Некорректный профиль quality gate: {config_path}")
        try:
            rules[field_name] = ResultFieldRule(
                value_type=value_type,
                minimum=float(raw_rule["minimum"]) if "minimum" in raw_rule else None,
                maximum=float(raw_rule["maximum"]) if "maximum" in raw_rule else None,
                allowed_values=tuple(str(value) for value in raw_rule.get("allowed_values", [])),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Некорректный профиль quality gate: {config_path}") from exc
        if value_type == "enum" and not rules[field_name].allowed_values:
            raise ValueError(f"Некорректный профиль quality gate: {config_path}")
    return TournamentQualityGateConfig(
        tournament=str(raw.get("tournament", tournament_name)),
        schedule_window_hours=window_hours,
        required_result_fields=required_fields,
        result_field_rules=rules,
        id_column=str(raw.get("id_column", "id")),
        datetime_column=str(raw.get("datetime_column", "datetime")),
        schedule_state_column=str(raw.get("schedule_state_column", "game_state")),
        schedule_finished_values=tuple(
            str(value) for value in raw.get("schedule_finished_values", ["OFF"])
        ),
        schedule_snapshot_filename=str(
            raw.get("schedule_snapshot_filename", "quality_gate_schedule.csv")
        ),
        schedule_coverage_filename=str(
            raw.get("schedule_coverage_filename", "quality_gate_schedule.coverage.json")
        ),
        source_finished_column=str(raw.get("source_finished_column", "match_is_end")),
        source_finished_values=tuple(
            str(value) for value in raw.get("source_finished_values", ["1", "true"])
        ),
    )


def load_notification_profiles() -> tuple[NotificationProfile, ...]:
    """Загрузить включённые notification-профили из конфигурационной группы.

    Returns:
        Профили, каждый из которых полностью определяет heavy path одного турнира.

    Raises:
        FileNotFoundError: Если конфигурационная группа отсутствует или пуста.
        ValueError: Если YAML-профиль не является объектом или не содержит обязательных полей.
    """
    from sports_forecast.orchestration.notification_profiles import NotificationProfile

    profiles_dir = PROJECT_ROOT / "conf" / "notification"
    paths = sorted(profiles_dir.glob("*.yaml")) if profiles_dir.is_dir() else []
    if not paths:
        raise FileNotFoundError(f"Профили уведомлений не найдены: {profiles_dir}")

    profiles: list[NotificationProfile] = []
    for path in paths:
        raw = OmegaConf.to_container(OmegaConf.load(path), resolve=True)
        if not isinstance(raw, dict):
            raise ValueError(f"Профиль уведомлений должен быть объектом: {path}")
        try:
            profile = NotificationProfile(
                profile_id=str(raw["profile_id"]),
                tournament=str(raw["tournament"]),
                market=str(raw["market"]),
                market_spec=str(raw["market_spec"]),
                window_hours=int(raw["window_hours"]),
                timezone=str(raw["timezone"]),
                heavy_schedule=str(raw["heavy_schedule"]),
                max_active_runs=int(raw["max_active_runs"]),
                max_active_tasks=int(raw["max_active_tasks"]),
                refresh_pool=str(raw["refresh_pool"]),
                lock_file=str(raw["lock_file"]),
                lock_wait_seconds=int(raw["lock_wait_seconds"]),
                enabled=bool(raw["enabled"]),
                poll_schedule=str(raw["poll_schedule"]),
                poll_max_active_runs=int(raw["poll_max_active_runs"]),
                poll_max_active_tasks=int(raw["poll_max_active_tasks"]),
                poll_pool=str(raw["poll_pool"]),
                poll_retries=int(raw["poll_retries"]),
                poll_retry_delay_seconds=int(raw["poll_retry_delay_seconds"]),
                poll_execution_timeout_seconds=int(raw["poll_execution_timeout_seconds"]),
                live_odds_adapter=str(raw["live_odds_adapter"]),
                live_odds_bookmaker_config=str(raw["live_odds_bookmaker_config"]),
                live_odds_sport_key=str(raw["live_odds_sport_key"]),
                live_odds_bookmaker_key=str(raw["live_odds_bookmaker_key"]),
                live_odds_team_registry=str(raw.get("live_odds_team_registry", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Некорректный профиль уведомлений: {path}") from exc
        if profile.enabled:
            profiles.append(profile)
    return tuple(profiles)
