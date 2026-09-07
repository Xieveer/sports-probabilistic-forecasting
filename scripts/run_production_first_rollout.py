# ruff: noqa: I001
"""Запустить локальный first-rollout contract в изолированном Docker project.

Runner намеренно принимает только digest-pinned image references через env-file.
Он не читает production `.env`, не печатает его содержимое и сохраняет только
redacted evidence. External Telegram/Object Storage acceptance остаются
контролируемыми test endpoints, заданными отдельным env fixture.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_first_rollout_fixtures import build_fixtures  # noqa: E402
from scripts.verify_production_compose_contract import verify_contract  # noqa: E402


RUNTIME_UID_GID = "10001:10001"
MINIO_IMAGE = "minio/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e"
MINIO_MC_IMAGE = "minio/mc@sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727"
_MEMORY_BYTES_PER_UNIT = {
    "B": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
}


def _run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """Выполнить команду без echo secret-bearing arguments."""
    return subprocess.run(
        command, cwd=PROJECT_ROOT, text=True, capture_output=True, check=True, timeout=timeout
    )


def _wait_for(command: list[str], *, timeout: int = 90) -> str:
    """Дождаться bounded health command, не раскрывая его stdout при неуспехе."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            command, cwd=PROJECT_ROOT, text=True, capture_output=True, check=False
        )
        if result.returncode == 0:
            return result.stdout
        time.sleep(1)
    raise RuntimeError("healthcheck не стал успешным за допустимое время")


def _wait_for_docker_health(container_id: str, *, timeout: int = 120) -> None:
    """Дождаться Docker health=healthy, а не только успешного inspect."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_id],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if status.returncode == 0 and status.stdout.strip() == "healthy":
            return
        time.sleep(1)
    raise RuntimeError("Docker health не стал healthy за допустимое время")


def _pull_image(image: str) -> None:
    """Pull immutable digest с bounded retry для transient registry failures."""
    for attempt in range(3):
        result = subprocess.run(
            ["docker", "pull", image], cwd=PROJECT_ROOT, capture_output=True, text=True
        )
        if result.returncode == 0:
            return
        if attempt < 2:
            time.sleep(2)
    raise RuntimeError("не удалось pull immutable image после трёх попыток")


def _image_refs(env_file: Path) -> dict[str, str]:
    """Вернуть only image@digest references из env-file без вывода values."""
    values = dict(
        line.split("=", 1)
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    refs = {key: value for key, value in values.items() if key.endswith("_IMAGE")}
    if not refs or any("@sha256:" not in value for value in refs.values()):
        raise ValueError("first-rollout принимает только image@sha256:digest")
    return refs


def _env_values(env_file: Path) -> dict[str, str]:
    """Прочитать fixture env без передачи значений в stdout/logs."""
    return dict(
        line.split("=", 1)
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


def _clean_worktree_issues(status: str) -> list[str]:
    """Вернуть все изменения кроме OCI download, разрешённого только CI gate."""
    return [
        line
        for line in status.splitlines()
        if not (line.startswith("?? artifacts/release-oci/") and line.endswith(".oci.tar"))
    ]


def _service_status(compose: list[str]) -> list[dict[str, Any]]:
    """Сохранить redacted health/restart status без логов и environment."""
    output = _run([*compose, "ps", "--format", "json"]).stdout.strip()
    if not output:
        return []
    decoded = (
        json.loads(output)
        if output.startswith("[")
        else [json.loads(line) for line in output.splitlines()]
    )
    return decoded if isinstance(decoded, list) else [decoded]


def _service_resources(service_ids: dict[str, str]) -> dict[str, str]:
    """Снять bounded RSS/CPU evidence без environment или payload приложения."""
    resources: dict[str, str] = {}
    for service, container_id in service_ids.items():
        resources[service] = _run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.CPUPerc}} {{.MemUsage}}",
                container_id,
            ]
        ).stdout.strip()
    return resources


def _parse_memory_usage_bytes(docker_stats_value: str) -> int:
    """Разобрать current-memory часть ``docker stats`` в bytes."""
    current, separator, limit = docker_stats_value.partition("/")
    if not separator or not limit.strip():
        raise ValueError("не удалось разобрать RSS из docker stats")
    current = current.strip()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?I?B)", current, re.IGNORECASE)
    if match is None:
        raise ValueError("не удалось разобрать RSS из docker stats")
    amount = float(match.group(1))
    unit = match.group(2).upper()
    if amount < 0 or unit not in _MEMORY_BYTES_PER_UNIT:
        raise ValueError("некорректное RSS measurement")
    return int(amount * _MEMORY_BYTES_PER_UNIT[unit])


def _disk_usage(path: Path) -> dict[str, int]:
    """Снять и валидировать host free-space evidence для существующего mount."""
    if not path.exists():
        raise ValueError(f"disk target не существует: {path}")
    usage = shutil.disk_usage(path)
    measurement = {
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
    }
    if (
        measurement["total_bytes"] <= 0
        or measurement["used_bytes"] < 0
        or measurement["free_bytes"] < 0
        or measurement["used_bytes"] > measurement["total_bytes"]
        or measurement["free_bytes"] > measurement["total_bytes"]
    ):
        raise ValueError(f"некорректное disk measurement для {path}")
    return measurement


def _parse_df_disk_usage(output: str) -> dict[str, int]:
    """Разобрать portable ``df -kP`` внутри container в bytes."""
    rows = output.splitlines()
    if len(rows) != 2:
        raise ValueError("некорректный disk measurement из df")
    fields = rows[1].split()
    if len(fields) < 5:
        raise ValueError("некорректный disk measurement из df")
    try:
        total_kib, used_kib, free_kib = (int(fields[index]) for index in (1, 2, 3))
    except ValueError as exc:
        raise ValueError("некорректный disk measurement из df") from exc
    measurement = {
        "total_bytes": total_kib * 1024,
        "used_bytes": used_kib * 1024,
        "free_bytes": free_kib * 1024,
    }
    if (
        measurement["total_bytes"] <= 0
        or measurement["used_bytes"] < 0
        or measurement["free_bytes"] < 0
        or measurement["used_bytes"] + measurement["free_bytes"] > measurement["total_bytes"]
    ):
        raise ValueError("некорректный disk measurement из df")
    return measurement


def _container_disk_usage(container_id: str, path: str) -> dict[str, int]:
    """Снять disk evidence named volume внутри владеющего им Docker container."""
    output = _run(["docker", "exec", container_id, "df", "-kP", path]).stdout
    return _parse_df_disk_usage(output)


def _disk_usage_delta(
    before: dict[str, dict[str, int]], after: dict[str, dict[str, int]]
) -> dict[str, int]:
    """Вернуть disk growth only для полного одинакового набора evidence targets."""
    if not before or set(before) != set(after):
        raise ValueError("disk targets до и после rollout не совпадают")
    return {target: after[target]["used_bytes"] - before[target]["used_bytes"] for target in before}


def _database_disk_path(container_id: str) -> Path:
    """Найти host source DB volume, иначе остановить rollout без неполного evidence."""
    sources = _run(
        [
            "docker",
            "inspect",
            "--format",
            '{{range .Mounts}}{{.Source}}{{"\\n"}}{{end}}',
            container_id,
        ]
    ).stdout.splitlines()
    if not sources:
        raise RuntimeError("не найден DB volume для disk evidence")
    return Path(sources[0])


def _run_worker_with_peak_rss(
    compose: list[str], *, project_name: str, values: dict[str, str], timeout: int = 300
) -> dict[str, int]:
    """Выполнить Worker один раз, сохранив максимум RSS до удаления container."""
    container_name = f"{project_name}-worker-resource-evidence"
    container_id = _run(
        [*compose, "run", "--detach", "--name", container_name, "worker"], timeout=60
    ).stdout.strip()
    if not container_id:
        raise RuntimeError("Worker container не вернул ID для RSS evidence")
    samples: list[int] = []
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            stats = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container_id],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if stats.returncode == 0 and stats.stdout.strip():
                samples.append(_parse_memory_usage_bytes(stats.stdout.strip()))
            state = (
                _run(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        "{{.State.Running}} {{.State.ExitCode}}",
                        container_id,
                    ]
                )
                .stdout.strip()
                .split()
            )
            if state and state[0] == "false":
                if len(state) != 2 or state[1] != "0":
                    raise RuntimeError("Worker one-shot завершился с ошибкой")
                if not samples or max(samples) <= 0:
                    raise RuntimeError("Worker peak RSS не удалось измерить")
                logs = _run(["docker", "logs", container_id])
                _assert_logs_are_redacted(logs.stdout + logs.stderr, values)
                return {"peak_rss_bytes": max(samples), "sample_count": len(samples)}
            time.sleep(0.2)
        raise RuntimeError("Worker one-shot не завершился за допустимое время")
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_id], cwd=PROJECT_ROOT, capture_output=True, check=False
        )


def _assert_logs_are_redacted(logs: str, values: dict[str, str]) -> None:
    """Отклонить stdout/stderr services, содержащие любой test-secret value."""
    secrets = [
        Path(value).read_text(encoding="utf-8").strip()
        for key, value in values.items()
        if key.endswith("_FILE") and Path(value).is_file()
    ]
    if any(secret and secret in logs for secret in secrets):
        raise RuntimeError("service logs содержат secret value")


def _run_one_shot_checked(
    command: list[str], *, values: dict[str, str], timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    """Проверить stdout/stderr удаляемого one-shot container до его discard."""
    result = _run(command, timeout=timeout)
    _assert_logs_are_redacted(result.stdout + result.stderr, values)
    return result


def _probe_runtime_identities(
    *, project_name: str, values: dict[str, str], postgres_image: str
) -> None:
    """Подтвердить реальными runtime roles API read и Worker read/write whitelist."""
    network = f"{project_name}_default"
    api_probe = (
        'export PGPASSWORD="$(cat /run/secrets/database_url | '
        "sed -E 's#.*://[^:]+:([^@]+)@.*#\\1#')\"; "
        "psql -h db -U sf_api_reader -d sports_forecast -v ON_ERROR_STOP=1 -tAc "
        '"SELECT count(*) FROM predictions p WHERE NOT EXISTS (SELECT 1 FROM '
        'tournament_publication_states s WHERE s.tournament = p.tournament)"'
    )
    worker_probe = (
        'export PGPASSWORD="$(cat /run/secrets/database_url | '
        "sed -E 's#.*://[^:]+:([^@]+)@.*#\\1#')\"; "
        "psql -h db -U sf_refresh_writer -d sports_forecast -v ON_ERROR_STOP=1 -c "
        '"BEGIN; SELECT count(*) FROM predictions; SELECT count(*) FROM '
        "tournament_publication_states; SELECT count(*) FROM worker_executions; "
        "SELECT count(*) FROM model_deployments; SELECT count(*) FROM refresh_locks; "
        "SELECT count(*) FROM canonical_events; SELECT count(*) FROM canonical_event_revisions; "
        "SELECT count(*) FROM refresh_watermarks; SELECT count(*) FROM bootstrap_imports; "
        "INSERT INTO worker_executions (run_id, status) VALUES ('grant-probe', 'running'); "
        "INSERT INTO refresh_locks (tournament, run_id) VALUES ('grant-probe', 'grant-probe'); ROLLBACK;\""
    )
    for secret_key, command in (
        ("SF_API_DATABASE_URL_FILE", api_probe),
        ("SF_WORKER_DATABASE_URL_FILE", worker_probe),
    ):
        _run_one_shot_checked(
            [
                "docker",
                "run",
                "--rm",
                "--read-only",
                "--network",
                network,
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=16m",
                "--mount",
                f"type=bind,src={values[secret_key]},dst=/run/secrets/database_url,readonly",
                "--entrypoint",
                "/bin/sh",
                postgres_image,
                "-ec",
                command,
            ],
            values=values,
            timeout=120,
        )


def run_first_rollout(*, env_file: Path, evidence_path: Path, app_version: str) -> dict[str, Any]:
    """Проверить clean Compose contract и default runtime identity.

    Полный stateful путь выполняется CI после подстановки реально pullable test
    digest. Локальная функция завершает только шаги, не требующие сети или
    внешнего fixture endpoint; несостоявшийся Docker command остаётся failure.
    """
    started = time.monotonic()
    worktree_issues = _clean_worktree_issues(_run(["git", "status", "--porcelain"]).stdout)
    if worktree_issues:
        raise RuntimeError("release evidence требует clean Git worktree")
    head_commit = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    tag = os.environ.get("GITHUB_REF_NAME", "local")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        if tag != f"v{app_version}":
            raise RuntimeError("release tag не совпадает с application version")
        tag_commit = _run(["git", "rev-list", "-n", "1", tag]).stdout.strip()
        if tag_commit != head_commit:
            raise RuntimeError("release tag должен указывать на проверяемый commit")
    refs = _image_refs(env_file)
    values = _env_values(env_file)
    project_name = f"sf-rollout-{os.getpid()}-{int(started)}"
    evidence: dict[str, Any] = {
        "commit": head_commit,
        "tag": tag,
        "images": refs,
        "runtime_uid_gid": RUNTIME_UID_GID,
        "application_version": app_version,
        "health": {},
        "migration_revision": None,
        "model_bundle_id": None,
        "bootstrap_id": None,
        "source_state_id": None,
        "resources": {"runtime_services": {}, "worker_one_shot": {}, "disk": {}},
        "ports": {},
        "model_pointer": {"status": "not-run"},
        "rollback": {"status": "not-run"},
    }
    with tempfile.TemporaryDirectory(prefix="sf-first-rollout-") as temporary:
        runtime_root = Path(temporary)
        fixture_root = Path(values["SF_CANONICAL_SOURCE_ROOT"]).parents[1]
        fixtures = build_fixtures(fixture_root, app_version=app_version)
        if fixtures["runtime_models"] != Path(values["SF_MODEL_RUNTIME_ROOT"]):
            raise ValueError("fixture runtime_models не совпадает с Compose bind mount")
        rendered = runtime_root / "rendered.yml"
        rendered.write_text(
            _run(
                [
                    "docker",
                    "compose",
                    "--project-name",
                    project_name,
                    "--env-file",
                    str(env_file),
                    "-f",
                    "docker-compose.prod.yml",
                    "--profile",
                    "migration",
                    "--profile",
                    "worker",
                    "--profile",
                    "operational-sync",
                    "--profile",
                    "source-acquisition",
                    "config",
                ]
            ).stdout,
            encoding="utf-8",
        )
        verify_contract(rendered, model_runtime_root=Path(values["SF_MODEL_RUNTIME_ROOT"]))
        evidence["model_bundle_id"] = (fixtures["runtime_models"] / "current").resolve().name
        evidence["bootstrap_id"] = fixtures["bootstrap"].name
        evidence["source_state_id"] = fixtures["source_state"].name
        for image in refs.values():
            _pull_image(image)
        _run(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "0:0",
                "--mount",
                f"type=bind,src={fixtures['runtime_models']},dst=/fixtures/runtime-models",
                "--mount",
                f"type=bind,src={values['SF_CANONICAL_SOURCE_ROOT']},dst=/fixtures/source",
                "--mount",
                f"type=bind,src={values['SF_OPERATIONAL_ARCHIVE_ROOT']},dst=/fixtures/archive",
                "--mount",
                f"type=bind,src={values['SF_ARCHIVE_SYNC_STATE_ROOT']},dst=/fixtures/sync-state",
                "--entrypoint",
                "/bin/chown",
                refs["SF_WORKER_IMAGE"],
                "-R",
                RUNTIME_UID_GID,
                "/fixtures/runtime-models",
                "/fixtures/source",
                "/fixtures/archive",
                "/fixtures/sync-state",
            ]
        )
        current_before_rollback = (fixtures["runtime_models"] / "current").resolve().name
        previous_before_rollback = (fixtures["runtime_models"] / "previous").resolve().name
        for expected_current in (previous_before_rollback, current_before_rollback):
            _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--read-only",
                    "--user",
                    RUNTIME_UID_GID,
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=64m",
                    "--mount",
                    f"type=bind,src={fixtures['runtime_models']},dst=/app/models",
                    refs["SF_WORKER_IMAGE"],
                    "/app/.venv/bin/python",
                    "-m",
                    "sports_forecast.deploy.model_bundle",
                    "rollback",
                    "--runtime-root",
                    "/app/models",
                    "--app-version",
                    app_version,
                ],
                timeout=180,
            )
            if (fixtures["runtime_models"] / "current").resolve().name != expected_current:
                raise RuntimeError(
                    "rollback model pointer не переключился на verified previous bundle"
                )
        evidence["model_pointer"] = {
            "current_before": current_before_rollback,
            "previous_before": previous_before_rollback,
            "current_after": (fixtures["runtime_models"] / "current").resolve().name,
            "status": "current-previous-current-ok",
        }
        # Проверка default entrypoint теми же immutable images: root filesystem
        # закрыта, identity задаётся численно, `/tmp` получает единственный tmpfs.
        for image in (
            refs["SF_API_IMAGE"],
            refs["SF_WORKER_IMAGE"],
            refs["SF_BOT_IMAGE"],
            refs["SF_ARCHIVE_SYNC_IMAGE"],
        ):
            result = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--read-only",
                    "--user",
                    RUNTIME_UID_GID,
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=64m",
                    "--entrypoint",
                    "id",
                    image,
                    "-u",
                ]
            )
            if result.stdout.strip() != "10001":
                raise RuntimeError("runtime image не запускается как UID 10001")
        evidence["health"]["image_identity"] = "ok"
        compose = [
            "docker",
            "compose",
            "--project-name",
            project_name,
            "--env-file",
            str(env_file),
            "-f",
            "docker-compose.prod.yml",
            "--profile",
            "migration",
        ]
        try:
            _run([*compose, "up", "-d", "db"], timeout=180)
            db_container = _run([*compose, "ps", "-q", "db"]).stdout.strip()
            disk_paths = {
                "runtime_models": fixtures["runtime_models"],
                "canonical_source": Path(values["SF_CANONICAL_SOURCE_ROOT"]),
                "operational_archive": Path(values["SF_OPERATIONAL_ARCHIVE_ROOT"]),
                "archive_sync_state": Path(values["SF_ARCHIVE_SYNC_STATE_ROOT"]),
            }
            evidence["resources"]["disk"]["before"] = {
                name: _disk_usage(path) for name, path in disk_paths.items()
            }
            evidence["resources"]["disk"]["before"]["database"] = _container_disk_usage(
                db_container, "/var/lib/postgresql/data"
            )
            _run_one_shot_checked(
                [*compose, "run", "--rm", "role-bootstrap"], values=values, timeout=180
            )
            _run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "db",
                    "psql",
                    "-U",
                    "sf_user",
                    "-d",
                    "sports_forecast",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    "CREATE TABLE rollout_restore_sentinel (payload text NOT NULL); "
                    "INSERT INTO rollout_restore_sentinel VALUES ('first-rollout-pre-migration')",
                ],
                timeout=180,
            )
            backup = runtime_root / "pre-migration.sql"
            backup.write_text(
                _run(
                    [*compose, "exec", "-T", "db", "pg_dump", "-U", "sf_user", "sports_forecast"],
                    timeout=180,
                ).stdout,
                encoding="utf-8",
            )
            _run_one_shot_checked([*compose, "run", "--rm", "migrator"], values=values, timeout=300)
            role_contract = _run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "db",
                    "psql",
                    "-U",
                    "sf_user",
                    "-d",
                    "sports_forecast",
                    "-tA",
                    "-F",
                    "|",
                    "-c",
                    "SELECT has_table_privilege('sf_api_reader', 'public.predictions', 'SELECT'), "
                    "has_table_privilege('sf_api_reader', 'public.alembic_version', 'SELECT'), "
                    "has_table_privilege('sf_refresh_writer', 'public.alembic_version', 'SELECT')",
                ],
                timeout=180,
            ).stdout.strip()
            if role_contract != "t|f|f":
                raise RuntimeError("DB catalog grants не соответствуют reader/writer deny contract")
            evidence["health"]["database_role_catalog"] = "ok"
            _probe_runtime_identities(
                project_name=project_name,
                values=values,
                postgres_image=refs["SF_POSTGRES_IMAGE"],
            )
            evidence["health"]["runtime_identity_probes"] = "ok"
            _run_one_shot_checked(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--read-only",
                    "--user",
                    RUNTIME_UID_GID,
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=64m",
                    "--network",
                    f"{project_name}_default",
                    "--mount",
                    f"type=bind,src={values['SF_WORKER_DATABASE_URL_FILE']},dst=/run/secrets/worker_database_url,readonly",
                    "--mount",
                    f"type=bind,src={fixtures['bootstrap']},dst=/fixtures/bootstrap/{fixtures['bootstrap'].name},readonly",
                    "--env",
                    "DATABASE_URL_FILE=/run/secrets/worker_database_url",
                    refs["SF_WORKER_IMAGE"],
                    "/app/.venv/bin/python",
                    "-m",
                    "sports_forecast.deploy.canonical_bootstrap",
                    "import-nhl",
                    "--bundle",
                    f"/fixtures/bootstrap/{fixtures['bootstrap'].name}",
                ],
                values=values,
                timeout=180,
            )
            evidence["health"]["canonical_bootstrap"] = "ok"
            _run_one_shot_checked(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--read-only",
                    "--user",
                    RUNTIME_UID_GID,
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=64m",
                    "--mount",
                    f"type=bind,src={fixtures['source_state']},dst=/fixtures/source-state/{fixtures['source_state'].name},readonly",
                    "--mount",
                    f"type=bind,src={values['SF_CANONICAL_SOURCE_ROOT']},dst=/app/data/source/nhl",
                    refs["SF_WORKER_IMAGE"],
                    "/app/.venv/bin/python",
                    "-m",
                    "sports_forecast.deploy.source_state_cli",
                    "install",
                    "--bundle",
                    f"/fixtures/source-state/{fixtures['source_state'].name}",
                    "--source-root",
                    "/app/data/source/nhl",
                ],
                values=values,
                timeout=180,
            )
            evidence["health"]["source_state_install"] = "ok"
            worker_compose = [*compose, "--profile", "worker"]
            evidence["resources"]["worker_one_shot"] = _run_worker_with_peak_rss(
                worker_compose, project_name=project_name, values=values, timeout=300
            )
            _run_one_shot_checked(
                [*worker_compose, "run", "--rm", "worker"], values=values, timeout=180
            )
            execution_count = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--read-only",
                    "--user",
                    RUNTIME_UID_GID,
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=64m",
                    "--network",
                    f"{project_name}_default",
                    "--mount",
                    f"type=bind,src={values['SF_MIGRATOR_DATABASE_URL_FILE']},dst=/run/secrets/migrator_database_url,readonly",
                    "--env",
                    "DATABASE_URL_FILE=/run/secrets/migrator_database_url",
                    refs["SF_API_IMAGE"],
                    "/app/.venv/bin/python",
                    "-c",
                    "from sqlalchemy import create_engine, text; import os; "
                    "print(create_engine(os.environ['DATABASE_URL']).connect().execute("
                    "text(\"select count(*) from worker_executions where run_id = '"
                    + values["SF_WORKER_RUN_ID"]
                    + "'\")).scalar())",
                ],
                timeout=180,
            ).stdout.strip()
            if execution_count != "1":
                raise RuntimeError("повтор Worker run_id создал duplicate execution")
            evidence["health"]["worker_refresh"] = "ok"
            evidence["health"]["worker_run_id_idempotency"] = "ok"
            minio_name = f"{project_name}-minio"
            _run_one_shot_checked(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    minio_name,
                    "--network",
                    f"{project_name}_default",
                    "--network-alias",
                    "minio",
                    "--env",
                    "MINIO_ROOT_USER=fixture-access-key",
                    "--env",
                    "MINIO_ROOT_PASSWORD=fixture-secret-key",
                    MINIO_IMAGE,
                    "server",
                    "/data",
                ],
                values=values,
            )
            _wait_for(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    f"{project_name}_default",
                    MINIO_MC_IMAGE,
                    "alias",
                    "set",
                    "fixture",
                    "http://minio:9000",
                    "fixture-access-key",
                    "fixture-secret-key",
                ],
                timeout=90,
            )
            _run_one_shot_checked(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    f"{project_name}_default",
                    "--entrypoint",
                    "/bin/sh",
                    MINIO_MC_IMAGE,
                    "-c",
                    "mc alias set fixture http://minio:9000 fixture-access-key fixture-secret-key >/dev/null && "
                    "mc mb --ignore-existing fixture/fixture-bucket >/dev/null",
                ],
                values=values,
            )
            _run_one_shot_checked(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--read-only",
                    "--user",
                    RUNTIME_UID_GID,
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=64m",
                    "--network",
                    f"{project_name}_default",
                    "--mount",
                    f"type=bind,src={values['SF_OBJECT_STORAGE_ACCESS_KEY_ID_FILE']},dst=/run/secrets/object_storage_access_key,readonly",
                    "--mount",
                    f"type=bind,src={values['SF_OBJECT_STORAGE_SECRET_ACCESS_KEY_FILE']},dst=/run/secrets/object_storage_secret_key,readonly",
                    "--mount",
                    f"type=bind,src={values['SF_OPERATIONAL_ARCHIVE_ROOT']},dst=/app/archive,readonly",
                    "--mount",
                    f"type=bind,src={values['SF_ARCHIVE_SYNC_STATE_ROOT']},dst=/app/sync-state",
                    "--env",
                    "SF_OBJECT_STORAGE_ENDPOINT=http://minio:9000",
                    "--env",
                    "SF_OBJECT_STORAGE_BUCKET=fixture-bucket",
                    "--env",
                    "SF_OBJECT_STORAGE_ACCESS_KEY_ID_FILE=/run/secrets/object_storage_access_key",
                    "--env",
                    "SF_OBJECT_STORAGE_SECRET_ACCESS_KEY_FILE=/run/secrets/object_storage_secret_key",
                    refs["SF_ARCHIVE_SYNC_IMAGE"],
                ],
                values=values,
                timeout=180,
            )
            evidence["health"]["archive_sync"] = "ok"
            current = _run(
                [
                    *compose,
                    "run",
                    "--rm",
                    "migrator",
                    "/app/.venv/bin/alembic",
                    "-c",
                    "/app/alembic.ini",
                    "current",
                ],
                timeout=180,
            )
            evidence["migration_revision"] = current.stdout.strip().split()[0]
            _run([*compose, "up", "-d", "api"], timeout=180)
            _wait_for(
                [*compose, "exec", "-T", "api", "curl", "-fsS", "http://localhost:8000/ready"]
            )
            evidence["health"]["api_ready"] = "ok"
            telegram_stub = f"{project_name}-telegram-test"
            _run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    telegram_stub,
                    "--network",
                    f"{project_name}_default",
                    "--network-alias",
                    "telegram-test",
                    refs["SF_BOT_IMAGE"],
                    "/app/.venv/bin/python",
                    "-m",
                    "sports_forecast.deploy.telegram_test_stub",
                ]
            )
            _run([*compose, "up", "-d", "telegram-bot"], timeout=180)
            _wait_for(
                [
                    *compose,
                    "exec",
                    "-T",
                    "telegram-bot",
                    "curl",
                    "-fsS",
                    "http://api:8000/health",
                ],
                timeout=30,
            )
            evidence["health"]["bot_internal_api"] = "ok"
            _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--read-only",
                    "--user",
                    RUNTIME_UID_GID,
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=64m",
                    "--network",
                    f"{project_name}_default",
                    "--env",
                    "BOT_TELEGRAM_API_BASE_URL=http://telegram-test:8081",
                    refs["SF_BOT_IMAGE"],
                    "/app/.venv/bin/python",
                    "-c",
                    "import asyncio; from aiogram import Bot; from aiogram.client.session.aiohttp import AiohttpSession; "
                    "from aiogram.client.telegram import TelegramAPIServer; "
                    "bot=Bot('123456:fixture_test_token_for_local_contract', session=AiohttpSession(api=TelegramAPIServer.from_base('http://telegram-test:8081'))); "
                    "asyncio.run(bot.get_me())",
                ],
                timeout=30,
            )
            evidence["health"]["bot_telegram_get_me"] = "ok"
            try:
                _wait_for(
                    [
                        *compose,
                        "exec",
                        "-T",
                        "telegram-bot",
                        "/app/.venv/bin/python",
                        "-m",
                        "sports_forecast.bot.heartbeat",
                        "--path",
                        "/tmp/sf-bot-heartbeat.json",
                        "--max-age-seconds",
                        "60",
                    ],
                    timeout=90,
                )
            except RuntimeError as exc:
                _assert_logs_are_redacted(
                    _run([*compose, "logs", "--no-color", "telegram-bot"]).stdout, values
                )
                state = _service_status(compose)
                bot_state = next(
                    (item for item in state if item.get("Service") == "telegram-bot"), {}
                )
                raise RuntimeError(
                    "Telegram heartbeat не стал healthy; container state="
                    f"{bot_state.get('State', 'unknown')}"
                ) from exc
            evidence["health"]["telegram_heartbeat"] = "ok"
            _wait_for_docker_health(
                _run([*compose, "ps", "-q", "telegram-bot"]).stdout.strip(), timeout=120
            )
            rollback_database = "sf_rollout_restore_check"
            _run([*compose, "exec", "-T", "db", "createdb", "-U", "sf_user", rollback_database])
            _run(["docker", "cp", str(backup), f"{db_container}:/tmp/pre-migration.sql"])
            _run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "db",
                    "psql",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-U",
                    "sf_user",
                    "-d",
                    rollback_database,
                    "-f",
                    "/tmp/pre-migration.sql",
                ]
            )
            restored_payload = _run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "db",
                    "psql",
                    "-U",
                    "sf_user",
                    "-d",
                    rollback_database,
                    "-tA",
                    "-c",
                    "SELECT payload FROM rollout_restore_sentinel",
                ]
            ).stdout.strip()
            restored_has_alembic = _run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "db",
                    "psql",
                    "-U",
                    "sf_user",
                    "-d",
                    rollback_database,
                    "-tA",
                    "-c",
                    "SELECT to_regclass('public.alembic_version') IS NOT NULL",
                ]
            ).stdout.strip()
            if restored_payload != "first-rollout-pre-migration" or restored_has_alembic != "f":
                raise RuntimeError("isolated DB restore не сохранил pre-migration schema/content")
            evidence["rollback"] = {
                "pre_migration_backup": "created",
                "isolated_restore": "schema-and-content-ok",
                "status": "ok",
            }
            evidence["health"]["database_bootstrap"] = "ok"
            evidence["services"] = _service_status(compose)
            expected_services = {"db", "api", "telegram-bot"}
            observed = {str(item.get("Service")): item for item in evidence["services"]}
            if set(observed) != expected_services or any(
                item.get("State") != "running" or int(item.get("ExitCode", 1)) != 0
                for item in observed.values()
            ):
                raise RuntimeError("runtime services не достигли healthy running state")
            restart_counts = {
                service: int(
                    _run(
                        ["docker", "inspect", "--format", "{{.RestartCount}}", str(item["ID"])]
                    ).stdout
                )
                for service, item in observed.items()
            }
            if any(restart_counts.values()):
                raise RuntimeError("runtime service имеет restart count больше нуля")
            evidence["restart_counts"] = restart_counts
            ports = {service: item.get("Publishers", []) for service, item in observed.items()}
            evidence["ports"] = ports
            if any(
                publisher.get("PublishedPort", 0)
                for publishers in ports.values()
                for publisher in publishers
            ):
                raise RuntimeError("runtime service имеет published host port")
            if any(item.get("Health") != "healthy" for item in observed.values()):
                raise RuntimeError("runtime services не достигли Docker healthy status")
            service_logs = _run([*compose, "logs", "--no-color", *expected_services])
            _assert_logs_are_redacted(service_logs.stdout + service_logs.stderr, values)
            evidence["health"]["all_service_logs_redacted"] = "ok"
            evidence["resources"]["runtime_services"] = _service_resources(
                {service: str(item["ID"]) for service, item in observed.items()}
            )
            evidence["resources"]["disk"]["after"] = {
                name: _disk_usage(path) for name, path in disk_paths.items()
            }
            evidence["resources"]["disk"]["after"]["database"] = _container_disk_usage(
                db_container, "/var/lib/postgresql/data"
            )
            evidence["resources"]["disk"]["used_growth_bytes"] = _disk_usage_delta(
                evidence["resources"]["disk"]["before"], evidence["resources"]["disk"]["after"]
            )
        finally:
            subprocess.run(
                ["docker", "rm", "-f", f"{project_name}-telegram-test"],
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["docker", "rm", "-f", f"{project_name}-minio"], capture_output=True, check=False
            )
            _run([*compose, "down", "--volumes", "--remove-orphans"], timeout=180)
    evidence["elapsed_seconds"] = round(time.monotonic() - started, 3)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return evidence


def main() -> None:
    """CLI локального contract gate."""
    parser = argparse.ArgumentParser(description="Production first-rollout contract")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--app-version", required=True)
    args = parser.parse_args()
    run_first_rollout(
        env_file=args.env_file, evidence_path=args.evidence, app_version=args.app_version
    )


if __name__ == "__main__":
    main()
