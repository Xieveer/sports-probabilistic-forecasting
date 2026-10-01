"""NUL-список только двух immutable архивов текущего Data Cycle run."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


_RUN_ID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_ARTIFACT_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


def main(argv: list[str] | None = None) -> int:
    """Проверить descriptor и вывести точные manifest paths текущего run."""
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2 or not _RUN_ID.fullmatch(args[1]):
        return 2
    archive_root = Path(args[0]).resolve()
    run_id = args[1]
    descriptor = archive_root / "run-inputs" / f"{run_id}.json"
    try:
        payload = json.loads(descriptor.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 1
    if not isinstance(payload, dict) or payload.get("run_id") != run_id:
        return 1
    ids = (payload.get("canonical_artifact_id"), payload.get("source_artifact_id"))
    if any(not isinstance(value, str) or not _ARTIFACT_ID.fullmatch(value) for value in ids):
        return 1
    manifests = (
        archive_root / "operational-archive" / ids[0] / "manifest.json",
        archive_root / "operational-archive/nhl-source-state/v1" / ids[1] / "manifest.json",
    )
    if any(not manifest.is_file() or manifest.is_symlink() for manifest in manifests):
        return 1
    sys.stdout.buffer.write(b"".join(str(manifest).encode() + b"\0" for manifest in manifests))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
