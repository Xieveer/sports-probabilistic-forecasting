#!/usr/bin/env bash
# NUL-delimited archive manifest list; propagate filesystem traversal failures.
set -euo pipefail

archive_root="${1:?нужен archive root}"
archive_dir="${archive_root%/}/operational-archive"
if [[ ! -d "${archive_root}" || ! -r "${archive_root}" || ! -x "${archive_root}" ]]; then
  echo "Archive root недоступен: ${archive_root}" >&2
  exit 1
fi
if [[ ! -e "${archive_dir}" ]]; then
  exit 0
fi

find "${archive_dir}" -type f -name manifest.json -print0
