"""Реестр и фабрика :class:`SourceProvider` по полю ``provider.type`` в source-конфиге."""

from __future__ import annotations

from omegaconf import DictConfig, OmegaConf

from sports_forecast.data.providers.base import SourceProvider, SourceProviderError
from sports_forecast.data.providers.file_provider import FileSourceProvider
from sports_forecast.data.providers.http_provider import HttpApiSourceProvider
from sports_forecast.data.providers.nhl.provider import NhlWebApiSourceProvider


class UnknownProviderTypeError(SourceProviderError, ValueError):
    """Неизвестное значение ``provider.type``."""


class ProviderRegistry:
    """Маппинг строковых типов на фабрики провайдеров."""

    _registry: dict[str, type[SourceProvider]] = {}

    @classmethod
    def register(cls, type_id: str, provider_cls: type[SourceProvider]) -> None:
        cls._registry[type_id] = provider_cls

    @classmethod
    def create(
        cls,
        type_id: str,
        source_cfg: DictConfig,
        paths_cfg: DictConfig,
    ) -> SourceProvider:
        if type_id == "file":
            return FileSourceProvider(paths_cfg=paths_cfg)
        if type_id == "http_api":
            provider_section = source_cfg.get("provider") or OmegaConf.create({})
            return HttpApiSourceProvider(
                provider_cfg=provider_section,
                paths_cfg=paths_cfg,
            )
        if type_id == "nhl_web_api":
            return NhlWebApiSourceProvider(
                source_cfg=source_cfg,
                paths_cfg=paths_cfg,
            )
        raise UnknownProviderTypeError(f"Неизвестный provider.type: {type_id!r}")


def _merge_provider_defaults(source_cfg: DictConfig | None) -> DictConfig:
    defaults = OmegaConf.create({"provider": {"type": "file"}})
    if source_cfg is None:
        return defaults
    return OmegaConf.merge(defaults, source_cfg)


def get_provider(source_cfg: DictConfig | None, paths_cfg: DictConfig) -> SourceProvider:
    """Собрать провайдер по объединённому source-конфигу и конфигу путей.

    Args:
        source_cfg: Результат ``load_source_config`` или ``None``, если yaml нет.
        paths_cfg: Результат ``load_paths_config``.

    Returns:
        Экземпляр :class:`SourceProvider`.

    Raises:
        UnknownProviderTypeError: Неизвестный ``provider.type``.
    """
    merged = _merge_provider_defaults(source_cfg)
    provider_section = merged.get("provider") or OmegaConf.create({})
    type_id = OmegaConf.select(provider_section, "type") or "file"
    if not isinstance(type_id, str):
        raise UnknownProviderTypeError(f"provider.type должен быть строкой, получено: {type_id!r}")
    return ProviderRegistry.create(type_id, merged, paths_cfg)
