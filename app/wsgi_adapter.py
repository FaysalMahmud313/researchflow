"""Run the ASGI app under a plain WSGI server, using one thread only.

Some free hosts (PythonAnywhere) run WSGI apps with Python threads switched off. FastAPI
normally sends ordinary `def` endpoints and file reads to a thread pool, and the usual
ASGI-to-WSGI bridges need a background thread, so both hang there. This adapter instead:

* runs each request to completion on an event loop owned by the calling (only) thread, and
* makes "run in a thread" mean "call it right here" (run_blocking_calls_inline).

A WSGI worker handles one request at a time anyway, so nothing is lost. The app is built on
the first request, after the server has forked its worker. Responses are buffered in memory,
which suits the small upload limits such hosts need. Under uvicorn none of this is used.
"""
import asyncio
import logging
from http import HTTPStatus
from typing import Any, Awaitable, Callable, Iterable, MutableMapping

logger = logging.getLogger("researchflow.wsgi")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
AsgiApp = Callable[[Scope, Callable[[], Awaitable[Message]], Callable[[Message], Awaitable[None]]], Awaitable[None]]
StartResponse = Callable[[str, list[tuple[str, str]]], Any]


def run_blocking_calls_inline() -> None:
    """Make anyio's thread pool (used by FastAPI and Starlette) call functions in place."""
    import anyio.to_thread

    async def run_sync(func: Callable[..., Any], *args: Any, **_options: Any) -> Any:
        return func(*args)

    anyio.to_thread.run_sync = run_sync  # type: ignore[assignment]


class SingleThreadedWSGI:
    def __init__(self, app_factory: Callable[[], Any], trust_proxy_headers: bool = False) -> None:
        self._factory = app_factory
        self._trust_proxy = trust_proxy_headers
        self._loop: asyncio.AbstractEventLoop | None = None
        self._app: AsgiApp | None = None

    def _start(self) -> tuple[asyncio.AbstractEventLoop, AsgiApp]:
        if self._loop is None or self._app is None:
            loop = asyncio.new_event_loop()
            app = self._factory()
            # Startup work (FastAPI's lifespan) runs once; a WSGI worker has no shutdown signal.
            loop.run_until_complete(app.router.lifespan_context(app).__aenter__())
            self._loop, self._app = loop, app
        return self._loop, self._app

    def _scope(self, environ: dict[str, Any]) -> Scope:
        headers: list[tuple[bytes, bytes]] = []
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                name = key[5:].replace("_", "-").lower()
            elif key in ("CONTENT_TYPE", "CONTENT_LENGTH") and value:
                name = key.replace("_", "-").lower()
            else:
                continue
            headers.append((name.encode("latin-1"), str(value).encode("latin-1")))

        client = (str(environ.get("REMOTE_ADDR") or "127.0.0.1"), int(environ.get("REMOTE_PORT") or 0))
        scheme = str(environ.get("wsgi.url_scheme") or "http")
        if self._trust_proxy:
            # Set by the host's own front proxy. X-Forwarded-For can start with values the
            # visitor made up, so only its last entry (added by that proxy) is used.
            real_ip = str(environ.get("HTTP_X_REAL_IP") or "").strip()
            forwarded = str(environ.get("HTTP_X_FORWARDED_FOR") or "").split(",")[-1].strip()
            if real_ip or forwarded:
                client = (real_ip or forwarded, 0)
            proto = str(environ.get("HTTP_X_FORWARDED_PROTO") or "").split(",")[0].strip().lower()
            if proto in ("http", "https"):
                scheme = proto

        raw_path = (str(environ.get("SCRIPT_NAME") or "") + str(environ.get("PATH_INFO") or "/")).encode("latin-1")
        return {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": str(environ.get("SERVER_PROTOCOL") or "HTTP/1.1").rpartition("/")[2],
            "method": str(environ.get("REQUEST_METHOD") or "GET").upper(),
            "scheme": scheme,
            "path": raw_path.decode("utf-8", "replace"),
            "raw_path": raw_path,
            "query_string": str(environ.get("QUERY_STRING") or "").encode("latin-1"),
            "root_path": "",
            "headers": headers,
            "client": client,
            "server": (str(environ.get("SERVER_NAME") or "localhost"), int(environ.get("SERVER_PORT") or 80)),
        }

    def __call__(self, environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        loop, app = self._start()
        body_in = environ["wsgi.input"]
        try:
            remaining = max(0, int(environ.get("CONTENT_LENGTH") or 0))
        except ValueError:
            remaining = 0
        status = 0
        out_headers: list[tuple[str, str]] = []
        chunks: list[bytes] = []

        async def receive() -> Message:
            nonlocal remaining
            if remaining > 0:
                data = body_in.read(min(remaining, 65536))
                remaining = remaining - len(data) if data else 0
                return {"type": "http.request", "body": data, "more_body": remaining > 0}
            if remaining == 0:
                remaining = -1
                return {"type": "http.request", "body": b"", "more_body": False}
            # Body fully delivered: wait as an open connection would (cancelled when the response is done).
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                out_headers.extend((k.decode("latin-1"), v.decode("latin-1")) for k, v in message.get("headers", []))
            elif message["type"] == "http.response.body":
                chunks.append(bytes(message.get("body", b"")))

        try:
            loop.run_until_complete(app(self._scope(environ), receive, send))
        except Exception:
            logger.exception("Unhandled error on %s %s", environ.get("REQUEST_METHOD"), environ.get("PATH_INFO"))
            status = 0
        if not status:
            start_response("500 Internal Server Error", [("Content-Type", "application/json")])
            return [b'{"detail": "An internal server error occurred."}']
        try:
            phrase = HTTPStatus(status).phrase
        except ValueError:
            phrase = "Status"
        start_response(f"{status} {phrase}", out_headers)
        return chunks
