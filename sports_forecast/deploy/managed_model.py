"""Разрешение и активация проверенного managed model bundle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from sports_forecast.deploy.model_bundle import (
    BundleVerificationError,
    VerifiedModelBundle,
    verify_model_bundle,
)
from sports_forecast.service.db.models import ModelDeployment
from sports_forecast.service.db.repository import ModelRegistryRepository


@dataclass(frozen=True)
class PinnedModelContract:
    """Один pinned deployment и bundle для единственного inference run."""

    deployment_id: int
    model_identity: str
    bundle_id: str
    bundle: VerifiedModelBundle
    model_file: Path


def _verified_deployment_bundle(
    deployment: ModelDeployment, bundle_root: Path, app_version: str
) -> PinnedModelContract:
    """Проверить DB binding и безопасно разрешить путь внутри managed root."""
    if not deployment.is_managed or not deployment.bundle_id:
        raise BundleVerificationError("Active deployment не привязан к managed bundle")
    location = deployment.managed_artifact_location
    if not location:
        raise BundleVerificationError("Managed artifact location отсутствует")
    root = bundle_root.resolve()
    artifact = (root / location).resolve()
    if not artifact.is_relative_to(root):
        raise BundleVerificationError("Managed artifact location выходит за bundle root")
    bundle_path = (root / deployment.bundle_id).resolve()
    if not bundle_path.is_relative_to(root) or bundle_path.name != deployment.bundle_id:
        raise BundleVerificationError("Managed bundle_id некорректен для bundle root")
    bundle = verify_model_bundle(bundle_path, app_version=app_version)
    if not isinstance(bundle, VerifiedModelBundle):
        raise BundleVerificationError("Legacy manifest нельзя использовать как managed bundle")
    if (
        bundle.bundle_id != deployment.bundle_id
        or bundle.model_identity != deployment.model_identity
        or bundle.model_pool != deployment.model_pool
        or bundle.market_spec != deployment.market_spec
        or artifact != (bundle_path / bundle.model_entrypoint).resolve()
    ):
        raise BundleVerificationError("DB deployment не совпадает с проверенным bundle")
    return PinnedModelContract(
        deployment_id=deployment.id,
        model_identity=deployment.model_identity,
        bundle_id=bundle.bundle_id,
        bundle=bundle,
        model_file=artifact,
    )


def resolve_active_model(
    session: Session,
    *,
    model_pool: str,
    market_spec: str,
    bundle_root: Path,
    app_version: str,
) -> PinnedModelContract:
    """Один раз закрепить active managed deployment для inference."""
    deployment = ModelRegistryRepository(session).get_active(model_pool, market_spec)
    if deployment is None:
        raise BundleVerificationError("Для managed model pool нет active deployment")
    return _verified_deployment_bundle(deployment, bundle_root, app_version)


def activate_managed_model(
    session: Session,
    *,
    bundle_path: Path,
    bundle_root: Path,
    app_version: str,
    model_pool: str,
    market_spec: str,
    candidate_report_ref: str,
    feature_contract_id: str,
    features: list[dict[str, str]],
    load_model: Callable[[Path, str], object],
) -> ModelDeployment:
    """Проверить и загрузить candidate до транзакционного переключения pointer."""
    root = bundle_root.resolve()
    path = bundle_path.resolve()
    if not path.is_relative_to(root):
        raise BundleVerificationError("Bundle candidate расположен вне разрешённого root")
    bundle = verify_model_bundle(path, app_version=app_version)
    if not isinstance(bundle, VerifiedModelBundle):
        raise BundleVerificationError("Для managed activation требуется manifest v2")
    if bundle.model_pool != model_pool or bundle.market_spec != market_spec:
        raise BundleVerificationError("Bundle предназначен для другой model pool / market spec")
    if bundle.feature_contract_id != feature_contract_id or list(bundle.features) != features:
        raise BundleVerificationError("Bundle feature contract не совпадает с runtime contract")
    model_file = (path / bundle.model_entrypoint).resolve()
    if not model_file.is_relative_to(path) or not model_file.is_file():
        raise BundleVerificationError("Model entrypoint отсутствует или выходит за bundle")
    loaded_model = load_model(model_file, bundle.algorithm)
    if loaded_model is None:
        raise BundleVerificationError("Model loader не вернул загруженную модель")
    return ModelRegistryRepository(session).promote_managed(
        model_pool=model_pool,
        market_spec=market_spec,
        model_identity=bundle.model_identity,
        candidate_report_ref=candidate_report_ref,
        artifact_ref=bundle.bundle_id,
        bundle_id=bundle.bundle_id,
        managed_artifact_location=f"{bundle.bundle_id}/{bundle.model_entrypoint}",
    )


def deployment_matches_pin(
    session: Session, model_pool: str, market_spec: str, pin: PinnedModelContract
) -> bool:
    """Блокировать active pointer и подтвердить pin перед DB publication."""
    active = ModelRegistryRepository(session).get_active(model_pool, market_spec, for_update=True)
    return bool(
        active is not None
        and active.id == pin.deployment_id
        and active.model_identity == pin.model_identity
        and active.bundle_id == pin.bundle_id
    )
