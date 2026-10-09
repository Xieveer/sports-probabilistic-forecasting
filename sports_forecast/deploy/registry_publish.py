"""S3-compatible transport для публикации registry из отдельного локального процесса."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sports_forecast.identity.publication import (
    ConditionalWriteConflictError,
    StorageObject,
    UnsupportedConditionalWriteError,
)


class RegistryStorageError(RuntimeError):
    """Object Storage transport завершился ошибкой."""


_MAX_OBJECT_BYTES = 512 * 1024 * 1024


def _error_code(error: Exception) -> tuple[str, int | None]:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return "", None
    error_body = response.get("Error", {})
    metadata = response.get("ResponseMetadata", {})
    code = str(error_body.get("Code", "")) if isinstance(error_body, dict) else ""
    status = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None
    return code, status if isinstance(status, int) else None


def _is_missing(error: Exception) -> bool:
    code, status = _error_code(error)
    if code == "NoSuchBucket":
        return False
    return code in {"NoSuchKey", "NotFound", "404"} or status == 404


def _translate_put_error(error: Exception) -> Exception:
    code, status = _error_code(error)
    if code in {"PreconditionFailed", "ConditionalRequestConflict"} or status in {409, 412}:
        return ConditionalWriteConflictError("Условная запись Object Storage не прошла CAS")
    if code in {"NotImplemented", "XNotImplemented", "InvalidRequest"} or status == 501:
        return UnsupportedConditionalWriteError(
            "Endpoint не подтвердил поддержку условной записи; публикация остановлена"
        )
    return RegistryStorageError("Object Storage PUT завершился ошибкой")


def _credential_from_environment(name: str) -> str:
    direct = os.environ.get(name)
    file_path = os.environ.get(f"{name}_FILE")
    if not file_path:
        return direct or ""
    try:
        secret_bytes = Path(file_path).read_bytes()
    except OSError as exc:
        raise RegistryStorageError(f"Не удалось прочитать secret file для {name}") from exc
    if not secret_bytes or len(secret_bytes) > 16_384:
        raise RegistryStorageError(f"Secret file для {name} пуст или превышает 16 KiB")
    try:
        file_value = secret_bytes.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError as exc:
        raise RegistryStorageError(f"Secret file для {name} не является UTF-8") from exc
    if direct and direct != file_value:
        raise RegistryStorageError(f"Значения {name} и {name}_FILE не совпадают")
    return file_value


class Boto3RegistryStorage:
    """Transport для Amazon S3 и S3-compatible Yandex Object Storage."""

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "ru-central1",
        client: Any | None = None,
    ) -> None:
        if not endpoint.startswith(("https://", "http://")) or not bucket:
            raise ValueError("Требуются корректный S3 endpoint и bucket")
        self._bucket = bucket
        if client is None:
            try:
                import boto3  # type: ignore[import-untyped]
                from botocore.config import Config  # type: ignore[import-untyped]
            except ImportError as exc:  # pragma: no cover - отдельная install group
                raise RegistryStorageError(
                    "Для публикации registry требуется dependency group archive-sync"
                ) from exc
            client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                region_name=region,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                config=Config(
                    connect_timeout=5,
                    read_timeout=120,
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
        self._client = client

    @classmethod
    def from_environment(cls) -> Boto3RegistryStorage:
        """Создать transport из переменных отдельного local publisher process."""
        values = {
            "endpoint": os.environ.get("SF_OBJECT_STORAGE_ENDPOINT", ""),
            "bucket": os.environ.get("SF_OBJECT_STORAGE_BUCKET", ""),
            "access_key_id": _credential_from_environment("SF_OBJECT_STORAGE_ACCESS_KEY_ID"),
            "secret_access_key": _credential_from_environment(
                "SF_OBJECT_STORAGE_SECRET_ACCESS_KEY"
            ),
        }
        if any(not value for value in values.values()):
            raise RegistryStorageError(
                "Object Storage настройки publisher не заданы; credentials не записываются в файлы"
            )
        return cls(**values, region=os.environ.get("SF_OBJECT_STORAGE_REGION", "ru-central1"))

    def get(self, key: str, *, max_bytes: int | None = None) -> StorageObject:
        if max_bytes is not None and max_bytes < 0:
            raise ValueError("max_bytes не может быть отрицательным")
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            if _is_missing(exc):
                raise FileNotFoundError(key) from exc
            raise RegistryStorageError("Object Storage GET завершился ошибкой") from exc
        body_stream = response.get("Body")
        etag = response.get("ETag")
        content_length = response.get("ContentLength")
        if body_stream is None or not isinstance(etag, str) or not etag:
            raise RegistryStorageError("Object Storage GET не вернул bytes и ETag")
        try:
            if not isinstance(content_length, int) or content_length < 0:
                raise RegistryStorageError("Object Storage GET не вернул корректный Content-Length")
            if content_length > _MAX_OBJECT_BYTES:
                raise RegistryStorageError("Object Storage объект превышает лимит 512 MiB")
            if max_bytes is not None and content_length > max_bytes:
                raise RegistryStorageError(
                    "Object Storage Content-Length превышает download byte limit"
                )
            body = body_stream.read(content_length + 1)
            if len(body) != content_length:
                raise RegistryStorageError("Object Storage GET bytes не совпали с Content-Length")
            if max_bytes is not None and len(body) > max_bytes:
                raise RegistryStorageError("Object Storage stream превышает download byte limit")
            return StorageObject(body=body, etag=etag.strip('"'))
        finally:
            body_stream.close()

    def put(
        self,
        key: str,
        body: bytes,
        *,
        if_match: str | None = None,
        if_none_match: bool = False,
    ) -> str:
        if (if_match is None) == (not if_none_match):
            raise ValueError(
                "Каждый PUT должен иметь ровно одно условие If-Match или If-None-Match"
            )
        params: dict[str, object] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": body,
            "ContentType": "application/json" if key.endswith(".json") else "application/x-ndjson",
        }
        if if_match is not None:
            params["IfMatch"] = f'"{if_match.strip(chr(34))}"'
        else:
            params["IfNoneMatch"] = "*"
        try:
            response = self._client.put_object(**params)
        except Exception as exc:
            raise _translate_put_error(exc) from exc
        etag = response.get("ETag")
        if not isinstance(etag, str) or not etag:
            raise RegistryStorageError("Object Storage PUT не вернул ETag")
        return etag.strip('"')
