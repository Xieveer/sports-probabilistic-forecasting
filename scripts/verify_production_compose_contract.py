"""Проверить rendered production Compose contract без запуска сервисов."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

import yaml


APPLICATION_SERVICES = {"api", "telegram-bot", "source-acquirer", "worker", "archive-sync"}
EXPECTED_SERVICES = APPLICATION_SERVICES | {"db"}
FORBIDDEN_SERVICES = {"caddy", "mlflow", "prometheus", "grafana", "airflow", "dvc", "node-exporter"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _memory_mib(value: object) -> int:
    """Нормализовать ограниченный Compose memory value в MiB."""
    if not isinstance(value, str):
        raise ValueError("mem_limit должен быть строкой")
    normalized = value.lower()
    if normalized.isdecimal():
        return int(normalized) // (1024 * 1024)
    if normalized.endswith("g"):
        return int(normalized[:-1]) * 1024
    if normalized.endswith("m"):
        return int(normalized[:-1])
    raise ValueError("mem_limit должен использовать m или g")


def _has_bind_mount(volumes: object, *, source: Path | None, target: str, read_only: bool) -> bool:
    """Проверить нормализованный Compose bind mount."""
    if not isinstance(volumes, list):
        return False
    return any(
        isinstance(volume, dict)
        and volume.get("type") == "bind"
        and volume.get("target") == target
        and volume.get("read_only", False) is read_only
        and (source is None or volume.get("source") == str(source))
        for volume in volumes
    )


def verify_contract(rendered_path: Path, *, model_runtime_root: Path) -> None:
    """Проверить mounts, ресурсы, images и private rollout boundary."""
    loaded = yaml.safe_load(rendered_path.read_text(encoding="utf-8"))
    _require(isinstance(loaded, dict), "rendered Compose должен быть mapping")
    services = loaded.get("services")
    _require(isinstance(services, dict), "services отсутствуют")
    names = set(services)
    _require(names == EXPECTED_SERVICES, f"недопустимый состав services: {sorted(names)}")
    _require(not names & FORBIDDEN_SERVICES, "обнаружен запрещённый service")
    _require(set(loaded.get("volumes", {})) == {"pg_data"}, "разрешён только volume pg_data")

    for name, service in services.items():
        _require(isinstance(service, dict), f"{name}: service должен быть mapping")
        _require("ports" not in service, f"{name}: host ports запрещены")
        _require(bool(service.get("cpus")), f"{name}: cpus обязателен")
        _require(bool(service.get("mem_limit")), f"{name}: mem_limit обязателен")
        image = service.get("image")
        _require(
            isinstance(image, str) and "@sha256:" in image,
            f"{name}: image должен быть immutable digest",
        )

    for name in ("db", "api", "telegram-bot"):
        _require(services[name].get("restart") == "unless-stopped", f"{name}: restart contract")
    _require(bool(services["db"].get("healthcheck")), "db: healthcheck обязателен")
    base_memory = sum(
        _memory_mib(services[name]["mem_limit"]) for name in ("db", "api", "telegram-bot")
    )
    job_memory = max(
        _memory_mib(services[name]["mem_limit"])
        for name in ("source-acquirer", "worker", "archive-sync")
    )
    _require(
        base_memory + job_memory <= 6720,
        "8 GiB VPS не оставляет минимум 1.4 GiB для host, Docker и Alloy",
    )

    worker_volumes = services["worker"].get("volumes", [])
    _require(isinstance(worker_volumes, list), "worker: volumes должны быть list")
    _require(
        _has_bind_mount(
            worker_volumes, source=model_runtime_root, target="/app/models", read_only=True
        ),
        "worker: model bind mount отсутствует или не read-only",
    )
    _require(
        _has_bind_mount(worker_volumes, source=None, target="/app/data/source/nhl", read_only=True),
        "worker: canonical source-state read-only bind mount отсутствует",
    )
    _require(
        _has_bind_mount(worker_volumes, source=None, target="/app/archive", read_only=False),
        "worker: archive mount отсутствует",
    )
    _require(
        _has_bind_mount(
            services["archive-sync"].get("volumes", []),
            source=None,
            target="/app/archive",
            read_only=True,
        ),
        "archive-sync: archive read-only bind mount отсутствует",
    )


def main() -> None:
    """Проверить rendered YAML по CLI arguments."""
    parser = ArgumentParser(description="Проверка rendered production Compose contract")
    parser.add_argument("--rendered", type=Path, required=True)
    parser.add_argument("--model-runtime-root", type=Path, required=True)
    args = parser.parse_args()
    verify_contract(args.rendered, model_runtime_root=args.model_runtime_root)


if __name__ == "__main__":
    main()
