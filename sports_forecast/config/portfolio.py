"""Загрузка и валидация конфигурационного каталога портфеля.

Каталог не заменяет Hydra-конфиги турниров: он связывает уже существующие
турниры с модельными пулами и профилями жизненного цикла. Это позволяет
планировщику и обучению получить один проверяемый источник состава портфеля.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class PortfolioConfigError(ValueError):
    """Конфигурация портфеля нарушает доменные инварианты."""


@dataclass(frozen=True)
class ModelPool:
    """Обучающий пул совместимых турниров для набора market/spec."""

    name: str
    sport: str
    market_specs: tuple[str, ...]


@dataclass(frozen=True)
class PoolMembership:
    """Принадлежность турнира к model pool для конкретных спецификаций."""

    model_pool: str
    market_specs: tuple[str, ...]


@dataclass(frozen=True)
class PortfolioTournament:
    """Турнир и его источник в конфигурационном портфеле."""

    name: str
    sport: str
    source: str
    memberships: tuple[PoolMembership, ...]


@dataclass(frozen=True)
class DeploymentProfile:
    """Жизненный цикл одной модели для турнира и market/spec."""

    name: str
    tournament: str
    model_pool: str
    market_spec: str
    state: str
    immutable_model_ref: str | None
    candidate_report_ref: str | None


@dataclass(frozen=True)
class PortfolioCatalog:
    """Проверенный снимок каталога портфеля."""

    model_pools: dict[str, ModelPool]
    tournaments: dict[str, PortfolioTournament]
    deployment_profiles: dict[str, DeploymentProfile]


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PortfolioConfigError(f"{field} должен быть YAML-объектом")
    return value


def _required_text(raw: dict[str, Any], field: str, context: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PortfolioConfigError(f"{context}: {field} обязателен")
    return value.strip()


def _text_list(raw: dict[str, Any], field: str, context: str) -> tuple[str, ...]:
    value = raw.get(field)
    if not isinstance(value, list) or not value:
        raise PortfolioConfigError(f"{context}: {field} должен быть непустым списком")
    items = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    if len(items) != len(value) or len(set(items)) != len(items):
        raise PortfolioConfigError(f"{context}: {field} содержит пустое или повторяющееся значение")
    return items


def _load_model_pools(raw: dict[str, Any]) -> dict[str, ModelPool]:
    pools: dict[str, ModelPool] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise PortfolioConfigError("model_pools содержит некорректное имя")
        context = f"model_pool {name}"
        config = _mapping(value, context)
        pools[name] = ModelPool(
            name=name,
            sport=_required_text(config, "sport", context),
            market_specs=_text_list(config, "market_specs", context),
        )
    return pools


def _load_tournaments(raw: dict[str, Any]) -> dict[str, PortfolioTournament]:
    tournaments: dict[str, PortfolioTournament] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise PortfolioConfigError("tournaments содержит некорректное имя")
        context = f"tournament {name}"
        config = _mapping(value, context)
        memberships_raw = config.get("memberships")
        if not isinstance(memberships_raw, list) or not memberships_raw:
            raise PortfolioConfigError(f"{context}: memberships должен быть непустым списком")
        memberships: list[PoolMembership] = []
        for membership_raw in memberships_raw:
            membership = _mapping(membership_raw, f"{context}.memberships")
            memberships.append(
                PoolMembership(
                    model_pool=_required_text(membership, "model_pool", context),
                    market_specs=_text_list(membership, "market_specs", context),
                )
            )
        tournaments[name] = PortfolioTournament(
            name=name,
            sport=_required_text(config, "sport", context),
            source=_required_text(config, "source", context),
            memberships=tuple(memberships),
        )
    return tournaments


def _load_deployment_profiles(raw: dict[str, Any]) -> dict[str, DeploymentProfile]:
    profiles: dict[str, DeploymentProfile] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise PortfolioConfigError("deployment_profiles содержит некорректное имя")
        context = f"deployment_profile {name}"
        config = _mapping(value, context)
        state = _required_text(config, "state", context)
        if state not in {"candidate", "production"}:
            raise PortfolioConfigError(f"{context}: state должен быть candidate или production")
        model_ref = config.get("immutable_model_ref")
        report_ref = config.get("candidate_report_ref")
        if model_ref is not None and (not isinstance(model_ref, str) or not model_ref.strip()):
            raise PortfolioConfigError(
                f"{context}: immutable_model_ref должен быть непустой строкой"
            )
        if report_ref is not None and (not isinstance(report_ref, str) or not report_ref.strip()):
            raise PortfolioConfigError(
                f"{context}: candidate_report_ref должен быть непустой строкой"
            )
        if state == "production" and not model_ref:
            raise PortfolioConfigError(f"{context}: immutable_model_ref обязателен для production")
        if state == "production" and not report_ref:
            raise PortfolioConfigError(f"{context}: candidate_report_ref обязателен для production")
        profiles[name] = DeploymentProfile(
            name=name,
            tournament=_required_text(config, "tournament", context),
            model_pool=_required_text(config, "model_pool", context),
            market_spec=_required_text(config, "market_spec", context),
            state=state,
            immutable_model_ref=model_ref.strip() if isinstance(model_ref, str) else None,
            candidate_report_ref=report_ref.strip() if isinstance(report_ref, str) else None,
        )
    return profiles


def _validate_catalog(catalog: PortfolioCatalog) -> None:
    assigned_specs: set[tuple[str, str]] = set()
    for tournament in catalog.tournaments.values():
        for membership in tournament.memberships:
            pool = catalog.model_pools.get(membership.model_pool)
            if pool is None:
                raise PortfolioConfigError(
                    f"tournament {tournament.name}: model_pool {membership.model_pool} не найден"
                )
            if pool.sport != tournament.sport:
                raise PortfolioConfigError(
                    f"tournament {tournament.name}: model_pool {pool.name} несовместим со sport "
                    f"{tournament.sport}"
                )
            for market_spec in membership.market_specs:
                if market_spec not in pool.market_specs:
                    raise PortfolioConfigError(
                        f"tournament {tournament.name}: market_spec {market_spec} не входит "
                        f"в model_pool {pool.name}"
                    )
                key = (tournament.name, market_spec)
                if key in assigned_specs:
                    raise PortfolioConfigError(
                        f"tournament {tournament.name}: market_spec {market_spec} назначен "
                        "в несколько model_pool"
                    )
                assigned_specs.add(key)

    deployed_targets: set[tuple[str, str]] = set()
    for profile in catalog.deployment_profiles.values():
        tournament = catalog.tournaments.get(profile.tournament)
        if tournament is None:
            raise PortfolioConfigError(
                f"deployment_profile {profile.name}: tournament {profile.tournament} не найден"
            )
        pool = catalog.model_pools.get(profile.model_pool)
        if pool is None:
            raise PortfolioConfigError(
                f"deployment_profile {profile.name}: model_pool {profile.model_pool} не найден"
            )
        membership_exists = any(
            membership.model_pool == profile.model_pool
            and profile.market_spec in membership.market_specs
            for membership in tournament.memberships
        )
        if not membership_exists:
            raise PortfolioConfigError(
                f"deployment_profile {profile.name}: model_pool {profile.model_pool} "
                f"для market_spec {profile.market_spec} не назначен турниру {profile.tournament}"
            )
        target = (profile.tournament, profile.market_spec)
        if target in deployed_targets:
            raise PortfolioConfigError(
                f"deployment_profile {profile.name}: для tournament/market_spec уже есть профиль"
            )
        deployed_targets.add(target)


def load_portfolio_catalog(path: Path) -> PortfolioCatalog:
    """Загрузить и проверить YAML-каталог портфеля.

    Args:
        path: Путь к YAML-файлу каталога.

    Returns:
        Типизированный, проверенный снимок конфигурации.

    Raises:
        FileNotFoundError: Если файл каталога отсутствует.
        PortfolioConfigError: Если структура или ссылки нарушают контракт.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Каталог портфеля не найден: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PortfolioConfigError(f"Не удалось прочитать каталог портфеля: {path}") from exc
    config = _mapping(raw, "Каталог портфеля")
    catalog = PortfolioCatalog(
        model_pools=_load_model_pools(_mapping(config.get("model_pools"), "model_pools")),
        tournaments=_load_tournaments(_mapping(config.get("tournaments"), "tournaments")),
        deployment_profiles=_load_deployment_profiles(
            _mapping(config.get("deployment_profiles", {}), "deployment_profiles")
        ),
    )
    _validate_catalog(catalog)
    return catalog
