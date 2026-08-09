"""Безопасный heartbeat Telegram bot для container healthcheck."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def write_heartbeat(path: Path, *, telegram_ok: bool, internal_api_ok: bool) -> None:
    """Атомарно записать только безопасный статус доступности зависимостей."""
    payload = {
        "updated_at": time.time(),
        "telegram_ok": telegram_ok,
        "internal_api_ok": internal_api_ok,
    }
    temporary = path.with_name(f".{path.name}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def is_healthy(path: Path, *, max_age_seconds: int) -> bool:
    """Проверить свежесть heartbeat и успешность обеих обязательных зависимостей."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("telegram_ok") is True
        and payload.get("internal_api_ok") is True
        and isinstance(payload.get("updated_at"), (int, float))
        and time.time() - float(payload["updated_at"]) <= max_age_seconds
    )


def main() -> None:
    """Вернуть non-zero, если bot heartbeat устарел или зависимости недоступны."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--max-age-seconds", type=int, default=120)
    args = parser.parse_args()
    raise SystemExit(0 if is_healthy(args.path, max_age_seconds=args.max_age_seconds) else 1)


if __name__ == "__main__":
    main()
