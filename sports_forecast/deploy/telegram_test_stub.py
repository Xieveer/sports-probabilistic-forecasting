"""Минимальный controlled Telegram API stub только для first-rollout gate."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Handler(BaseHTTPRequestHandler):
    """Вернуть безопасные ответы getMe/getUpdates без журналирования URL token."""

    def do_GET(self) -> None:  # noqa: N802 - HTTP hook.
        self._reply()

    def do_POST(self) -> None:  # noqa: N802 - HTTP hook.
        self._reply()

    def log_message(self, _format: str, *_args: object) -> None:
        """Не допускать token-bearing request path в stdout."""

    def _reply(self) -> None:
        if self.path.endswith("getUpdates"):
            result: object = []
        elif self.path.endswith("getMe"):
            result = {"id": 1, "is_bot": True, "first_name": "fixture", "username": "fixture_bot"}
        else:
            result = True
        payload = json.dumps({"ok": True, "result": result}).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    """Запустить stub на internal Docker network port 8081."""
    HTTPServer(("0.0.0.0", 8081), _Handler).serve_forever()


if __name__ == "__main__":
    main()
