"""FastAPI application factory for RTL-SDR Analyzer Web Studio."""

import mimetypes
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers

from rtl_sdr_analyzer import __version__
from rtl_sdr_analyzer.config.models import Settings
from rtl_sdr_analyzer.engine.spectrum_engine import SpectrumEngine
from rtl_sdr_analyzer.storage.database import EventStore
from rtl_sdr_analyzer.web.routes import SweepCoordinator, create_api_router
from rtl_sdr_analyzer.web.ws import SpectrumBroadcaster, handle_spectrum_ws

STATIC_DIR = Path(__file__).resolve().parent / "static"

_MIME_OVERRIDES: dict[str, str] = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".json": "application/json",
}


def _register_web_mimetypes() -> None:
    """Override broken OS registry MIME mappings (e.g. Windows .js -> text/plain)."""
    mimetypes.init()
    for ext, mime in _MIME_OVERRIDES.items():
        mimetypes.add_type(mime, ext, strict=True)


_register_web_mimetypes()

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'"
)

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _hostname(netloc: str) -> str:
    return (urlsplit(f"//{netloc}").hostname or "").lower()


def is_request_trusted(headers: Headers, *, loopback_only: bool) -> bool:
    """Reject cross-site requests (CSRF) and DNS-rebinding attempts.

    * ``Origin`` (when sent) must match ``Host``: other websites cannot drive the radio.
    * When bound to loopback, ``Host`` must be a loopback name, which defeats DNS rebinding.
    """
    host = headers.get("host", "")
    if loopback_only and _hostname(host) not in _LOOPBACK_HOSTS:
        return False
    origin = headers.get("origin")
    if origin and origin != "null":
        return urlsplit(origin).netloc.lower() == host.lower()
    return origin != "null"


def create_app(
    engine: SpectrumEngine,
    store: EventStore | None = None,
    settings: Settings | None = None,
    *,
    manage_engine_lifecycle: bool = True,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    resolved_settings = settings or engine.settings
    loopback_only = _hostname(resolved_settings.web.host) in _LOOPBACK_HOSTS
    broadcaster = SpectrumBroadcaster(recording_provider=engine.recording_summary)
    sweeper = SweepCoordinator(engine=engine, store=store, broadcaster=broadcaster)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        import asyncio

        broadcaster.set_loop(asyncio.get_running_loop())
        engine.subscribe_frames(broadcaster.on_frame)
        engine.subscribe_status(broadcaster.on_status)
        if manage_engine_lifecycle:
            engine.start()
        try:
            yield
        finally:
            sweeper.cancel()
            engine.unsubscribe_frames(broadcaster.on_frame)
            engine.unsubscribe_status(broadcaster.on_status)
            if manage_engine_lifecycle:
                engine.stop()

    app = FastAPI(
        title="RTL-SDR Analyzer · AMSTech",
        version=__version__,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        needs_check = request.method not in _SAFE_METHODS or loopback_only
        if needs_check and not is_request_trusted(request.headers, loopback_only=loopback_only):
            response: Response = JSONResponse({"detail": "Cross-origin request blocked"}, 403)
        else:
            response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    router = create_api_router(
        engine=engine,
        store=store,
        settings=resolved_settings,
        broadcaster=broadcaster,
        sweeper=sweeper,
    )
    app.include_router(router)

    @app.websocket("/ws/spectrum")
    async def ws_spectrum(websocket: WebSocket) -> None:
        if not is_request_trusted(websocket.headers, loopback_only=loopback_only):
            await websocket.close(code=1008)
            return
        await handle_spectrum_ws(
            websocket=websocket,
            broadcaster=broadcaster,
            initial_status_fn=engine.get_status,
            latest_frame_fn=engine.get_latest_frame,
            recording_fn=engine.recording_summary,
        )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app
