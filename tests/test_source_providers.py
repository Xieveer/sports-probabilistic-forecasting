"""Тесты source-адаптеров (R14)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from omegaconf import OmegaConf

from sports_forecast.data.providers import (
    FileSourceProvider,
    HttpApiSourceProvider,
    SourceDataNotFoundError,
    SourceProvider,
    SourceProviderError,
    UnknownProviderTypeError,
    get_provider,
)
from sports_forecast.data.providers.base import SourceFetchError


def test_source_provider_cannot_instantiate_abc() -> None:
    with pytest.raises(TypeError, match="abstract"):
        SourceProvider()  # type: ignore[abstract,misc]


def test_file_source_provider_is_concrete_subclass() -> None:
    assert issubclass(FileSourceProvider, SourceProvider)
    paths_cfg = OmegaConf.create({"paths": {"source_dir": "data/source"}})
    instance = FileSourceProvider(
        paths_cfg=paths_cfg,
        project_root=Path(__file__).resolve().parents[1],
    )
    assert isinstance(instance, SourceProvider)


def test_file_provider_fetch_on_demo_uel(tmp_path: Path) -> None:
    source_csv = tmp_path / "data" / "source" / "uel" / "source.csv"
    source_csv.parent.mkdir(parents=True)
    source_csv.write_text("id,date\n1,2026-08-09\n", encoding="utf-8")

    paths_cfg = OmegaConf.create({"paths": {"source_dir": "data/source"}})
    provider = FileSourceProvider(paths_cfg=paths_cfg, project_root=tmp_path)

    path = provider.fetch("uel")

    assert path == source_csv


def test_file_provider_missing_file_raises() -> None:
    paths_cfg = OmegaConf.create({"paths": {"source_dir": "data/source"}})
    provider = FileSourceProvider(
        paths_cfg=paths_cfg,
        project_root=Path(__file__).resolve().parents[1],
    )
    with pytest.raises(SourceDataNotFoundError):
        provider.fetch("nonexistent_tournament_xyz")


def test_get_provider_defaults_to_file() -> None:
    paths_cfg = OmegaConf.create({"paths": {"source_dir": "data/source"}})
    provider = get_provider(None, paths_cfg)
    assert isinstance(provider, FileSourceProvider)


def test_get_provider_unknown_type() -> None:
    paths_cfg = OmegaConf.create({"paths": {"source_dir": "data/source"}})
    cfg = OmegaConf.create({"provider": {"type": "alien_db"}})
    with pytest.raises(UnknownProviderTypeError):
        get_provider(cfg, paths_cfg)


@patch.object(HttpApiSourceProvider, "_build_session")
def test_http_api_provider_fetch_writes_csv(mock_build_session: MagicMock, tmp_path: Path) -> None:
    mock_response = MagicMock()
    mock_response.content = b"id,status\n1,ok\n"
    mock_response.raise_for_status = MagicMock()
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response
    mock_build_session.return_value = mock_session

    paths_cfg = OmegaConf.create({"paths": {"source_dir": "data/source"}})
    prov_cfg = OmegaConf.create(
        {"type": "http_api", "url": "https://example.invalid/export.csv", "retries": 1}
    )
    provider = HttpApiSourceProvider(
        provider_cfg=prov_cfg,
        paths_cfg=paths_cfg,
        project_root=tmp_path,
    )
    out = provider.fetch("t_api")
    assert out == tmp_path / "data" / "source" / "t_api" / "source.csv"
    assert out.read_bytes() == b"id,status\n1,ok\n"
    mock_session.get.assert_called_once()


def test_http_api_provider_requires_url() -> None:
    paths_cfg = OmegaConf.create({"paths": {"source_dir": "data/source"}})
    prov_cfg = OmegaConf.create({"type": "http_api"})
    with pytest.raises(SourceFetchError, match="url"):
        HttpApiSourceProvider(provider_cfg=prov_cfg, paths_cfg=paths_cfg)


def test_source_errors_inherit_base() -> None:
    assert issubclass(SourceDataNotFoundError, SourceProviderError)
    assert issubclass(SourceFetchError, SourceProviderError)
    assert issubclass(UnknownProviderTypeError, SourceProviderError)
