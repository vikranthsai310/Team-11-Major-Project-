"""A deliberately small HTTP server for the dashboard: standard library only.

Localhost only (``docs/17-UI-SPEC.md`` §A1): the dashboard has no authentication
and reads a signing-key directory's deployment, so binding anything but the
loopback interface is refused rather than configurable.
"""

from __future__ import annotations

import json
import mimetypes
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlparse

from batcher.dashboard.data import NotReady

STATIC = Path(__file__).resolve().parent / "static"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class Provider(Protocol):
    def catalogue(self) -> dict: ...
    def replay(self, policy: str, rate: str, index: int) -> dict: ...
    def compare(self) -> dict: ...
    def live(self) -> dict: ...


class DashboardProvider:
    """Wires the data sources together; compare results are computed once."""

    def __init__(self, library, live, compare):
        self.library = library
        self._live = live
        self._compare = lru_cache(maxsize=1)(compare)

    def catalogue(self) -> dict:
        return self.library.catalogue()

    def replay(self, policy: str, rate: str, index: int) -> dict:
        return self.library.replay(policy, rate, index)

    def compare(self) -> dict:
        return self._compare()

    def live(self) -> dict:
        return self._live()


def make_handler(provider: Provider, static_dir: Path = STATIC):
    allowed = {p.name for p in static_dir.iterdir() if p.is_file()}

    class Handler(BaseHTTPRequestHandler):
        server_version = "BatcherDashboard/1.0"

        def do_GET(self):  # noqa: N802 - the stdlib's name
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path == "/api/catalogue":
                    return self._json(provider.catalogue())
                if url.path == "/api/replay":
                    return self._json(
                        provider.replay(
                            query.get("policy", "p2"),
                            query.get("rate", "matched"),
                            int(query.get("episode", "0")),
                        )
                    )
                if url.path == "/api/compare":
                    return self._json(provider.compare())
                if url.path == "/api/live":
                    return self._json(provider.live())
                if url.path in ("/", "/index.html"):
                    return self._file("index.html")
                if url.path.startswith("/static/"):
                    name = url.path.removeprefix("/static/")
                    if name in allowed:
                        return self._file(name)
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except NotReady as error:
                return self._json({"error": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE)
            except (KeyError, ValueError) as error:
                return self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            except Exception as error:  # the UI shows it; the server keeps serving
                return self._json(
                    {"error": f"{type(error).__name__}: {error}"},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def _json(self, payload, status=HTTPStatus.OK):
            body = json.dumps(payload, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _file(self, name: str):
            body = (static_dir / name).read_bytes()
            kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return None

    return Handler


def serve(provider: Provider, host: str = "127.0.0.1", port: int = 8050) -> ThreadingHTTPServer:
    if host not in LOCAL_HOSTS:
        raise ValueError(f"refusing to bind {host!r}: the dashboard is localhost-only")
    return ThreadingHTTPServer((host, port), make_handler(provider))
