"""Локальный S3-compatible transport для server candidate batches и ack."""

from __future__ import annotations

from typing import Any

from sports_forecast.deploy.registry_publish import Boto3RegistryStorage, RegistryStorageError
from sports_forecast.identity.feedback import CandidateFeedbackError


class Boto3CandidateFeedbackStorage(Boto3RegistryStorage):
    """List/Get candidates и Put ack с отдельными локальными credentials."""

    @classmethod
    def from_environment(cls) -> Boto3CandidateFeedbackStorage:
        """Создать transport из отдельной local importer IAM identity."""
        import os

        from sports_forecast.deploy.registry_publish import _credential_from_environment

        endpoint = os.environ.get("SF_OBJECT_STORAGE_ENDPOINT", "")
        bucket = os.environ.get("SF_OBJECT_STORAGE_BUCKET", "")
        access_key_id = _credential_from_environment("SF_REGISTRY_FEEDBACK_ACCESS_KEY_ID")
        secret_access_key = _credential_from_environment("SF_REGISTRY_FEEDBACK_SECRET_ACCESS_KEY")
        if not all((endpoint, bucket, access_key_id, secret_access_key)):
            raise RegistryStorageError(
                "Не заданы Object Storage settings или credentials local feedback importer"
            )
        return cls(
            endpoint=endpoint,
            bucket=bucket,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region=os.environ.get("SF_OBJECT_STORAGE_REGION", "ru-central1"),
        )

    def list_keys(
        self,
        prefix: str,
        *,
        continuation_token: str | None = None,
        start_after: str | None = None,
        max_keys: int = 1000,
    ) -> tuple[tuple[str, ...], str | None]:
        """Прочитать одну bounded S3 ListObjectsV2 страницу."""
        if not prefix or not 1 <= max_keys <= 1000:
            raise ValueError("Некорректные параметры candidate object listing")
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Prefix": prefix,
            "MaxKeys": max_keys,
        }
        if continuation_token is not None:
            params["ContinuationToken"] = continuation_token
        elif start_after is not None:
            params["StartAfter"] = start_after
        try:
            response = self._client.list_objects_v2(**params)
        except Exception as exc:
            raise RegistryStorageError(
                "Object Storage candidate listing завершился ошибкой"
            ) from exc
        contents = response.get("Contents", [])
        if not isinstance(contents, list):
            raise CandidateFeedbackError("Object Storage вернул неверный список candidate keys")
        keys: list[str] = []
        for item in contents:
            if not isinstance(item, dict) or not isinstance(item.get("Key"), str):
                raise CandidateFeedbackError("Object Storage вернул некорректный candidate key")
            keys.append(item["Key"])
        truncated = response.get("IsTruncated", False)
        next_token = response.get("NextContinuationToken")
        if truncated and (not isinstance(next_token, str) or not next_token):
            raise CandidateFeedbackError("Object Storage не вернул continuation token")
        if not truncated:
            next_token = None
        return tuple(keys), next_token
