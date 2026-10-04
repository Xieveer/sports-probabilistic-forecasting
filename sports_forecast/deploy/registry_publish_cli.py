"""Команды локальной публикации registry и opt-in проверки S3 endpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from uuid import uuid4

from sports_forecast.deploy.registry_publish import Boto3RegistryStorage
from sports_forecast.identity.publication import (
    ConditionalWriteConflictError,
    RegistryPublisher,
    Storage,
    UnsupportedConditionalWriteError,
)


def probe_conditional_writes(storage: Storage, *, prefix: str) -> dict[str, str]:
    """Проверить create-if-absent, conflict и compare-and-swap на временном prefix."""
    normalized_prefix = prefix.strip("/")
    if not normalized_prefix or any(
        part in {"", ".", ".."} for part in normalized_prefix.split("/")
    ):
        raise ValueError("Некорректный Object Storage prefix")
    probe_id = str(uuid4())
    key = f"{normalized_prefix}/probes/{probe_id}/condition.json"
    initial = json.dumps({"probe_id": probe_id, "version": 1}, sort_keys=True).encode()
    updated = json.dumps({"probe_id": probe_id, "version": 2}, sort_keys=True).encode()
    etag = storage.put(key, initial, if_none_match=True)
    if storage.get(key).body != initial:
        raise RuntimeError("Contract probe: GET bytes не совпали с первым PUT")
    try:
        storage.put(key, b'{"unexpected":true}', if_none_match=True)
    except ConditionalWriteConflictError:
        pass
    else:
        raise UnsupportedConditionalWriteError(
            "Contract probe: endpoint принял повторный create-if-absent PUT"
        )
    if storage.get(key).body != initial:
        raise RuntimeError("Contract probe: конфликтующая запись изменила исходный объект")
    storage.put(key, updated, if_match=etag)
    if storage.get(key).body != updated:
        raise RuntimeError("Contract probe: GET bytes не совпали с CAS PUT")
    try:
        storage.put(key, b'{"unexpected":true}', if_match=etag)
    except ConditionalWriteConflictError:
        pass
    else:
        raise UnsupportedConditionalWriteError(
            "Contract probe: endpoint принял PUT с устаревшим ETag"
        )
    if storage.get(key).body != updated:
        raise RuntimeError("Contract probe: устаревший ETag изменил объект")
    return {"status": "supported", "probe_key_sha256": hashlib.sha256(key.encode()).hexdigest()}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sf-registry-publish")
    subcommands = parser.add_subparsers(dest="command", required=True)
    publish = subcommands.add_parser("publish", help="Опубликовать проверенный snapshot")
    publish.add_argument("snapshot", type=Path)
    publish.add_argument("--prefix", default="entity-registry/v1")
    publish.add_argument("--actor", default=None)
    probe = subcommands.add_parser("probe", help="Проверить conditional writes endpoint")
    probe.add_argument("--prefix", default="entity-registry/v1")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        storage = Boto3RegistryStorage.from_environment()
        if args.command == "probe":
            probe_result = probe_conditional_writes(storage, prefix=args.prefix)
            print(json.dumps(probe_result, sort_keys=True))
            return 0
        actor = args.actor
        if actor is None:
            import os

            actor = os.environ.get("SF_ENTITY_REGISTRY_ACTOR", "")
        publisher = RegistryPublisher(
            storage,
            prefix=args.prefix,
            lock_path=args.snapshot.resolve().parent.parent / "publisher.lock",
            actor=actor,
        )
        publication_result = publisher.publish(args.snapshot)
        print(
            json.dumps(
                {
                    "publication_id": publication_result.publication_id,
                    "sequence": publication_result.sequence,
                    "snapshot_id": publication_result.snapshot_id,
                    "status": "published",
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        ConditionalWriteConflictError,
        UnsupportedConditionalWriteError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"registry publication failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
