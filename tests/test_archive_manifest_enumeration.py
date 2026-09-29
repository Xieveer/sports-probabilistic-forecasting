"""Archive manifest enumeration fails closed if filesystem traversal fails."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HELPER = PROJECT_ROOT / "deploy/systemd/list-canonical-archive-manifests.sh"


def test_nonzero_find_result_is_returned_to_scheduler(tmp_path: Path) -> None:
    """A real traversal followed by nonzero exit must fail archive enumeration."""
    archive = tmp_path / "operational-archive"
    archive.mkdir()
    (archive / "artifact" / "manifest.json").parent.mkdir()
    manifest = archive / "artifact" / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_find = fake_bin / "find"
    fake_find.write_text('#!/bin/sh\n/usr/bin/find "$@"\nexit 23\n', encoding="utf-8")
    fake_find.chmod(0o755)

    result = subprocess.run(
        ["bash", str(HELPER), str(tmp_path)],
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
        capture_output=True,
        check=False,
    )

    assert result.returncode == 23
    assert result.stdout == f"{manifest}\0".encode()


def test_missing_archive_directory_is_an_empty_archive(tmp_path: Path) -> None:
    """No prior archive content is a valid empty enumeration."""
    result = subprocess.run(
        ["bash", str(HELPER), str(tmp_path)],
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == b""


def test_inaccessible_archive_root_is_not_treated_as_an_empty_archive(tmp_path: Path) -> None:
    """An unreadable parent must fail closed instead of reporting zero manifests."""
    archive_root = tmp_path / "archive-root"
    archive_root.mkdir()
    archive = archive_root / "operational-archive"
    archive.mkdir()
    (archive / "manifest.json").write_text("{}", encoding="utf-8")
    archive_root.chmod(0)
    try:
        result = subprocess.run(
            ["bash", str(HELPER), str(archive_root)],
            capture_output=True,
            check=False,
        )
    finally:
        archive_root.chmod(0o700)

    assert result.returncode != 0
