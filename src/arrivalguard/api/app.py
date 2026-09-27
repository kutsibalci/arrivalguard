"""ArrivalGuard API — medikal turist varış koruması. "Aynı sinyal, zıt anlam."

Olay güdümlü: Nokia Device Roaming Status aboneliği → CloudEvents webhook → vaka durum makinesi →
hastaya/sürücüye/aileye/koordinatöre mesaj. Geofencing ve Device Reachability abonelikleri aynı makineye akar;
zamanlayıcı süreye bağlı kuralları çalıştırır.

Çalıştırma:  uvicorn arrivalguard.api.app:create_app --factory
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .. import PACKAGE_DIR, REPO_ROOT, __version__
from ..nac_client.privacy import MaskingFilter
from .context import AppContext
from .routes import cases, demo, public, system, webhooks
from .scheduler import Scheduler
from .security import SecurityHeadersMiddleware
from .settings import Settings

log = logging.getLogger("arrivalguard.api")


def _load_dotenv() -> None:
    try:  # .env varsa yükle (opsiyonel bağımlılık)
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
        load_dotenv()
    except ImportError:
        pass


def _setup_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for h in root.handlers:
        if not any(isinstance(f, MaskingFilter) for f in h.filters):
            h.addFilter(MaskingFilter())


def create_app(settings: Settings | None = None, ctx: AppContext | None = None) -> FastAPI:
    _load_dotenv()
    _setup_logging()
    settings = settings or Settings.from_env()
    settings.validate()
    ctx = ctx or AppContext(settings)
    ctx.seed_clinics()
    ctx.scheduler = Scheduler(ctx, settings.scheduler_interval_s)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ctx.scheduler.start()
        try:
            yield
        finally:
            ctx.scheduler.stop()

    app = FastAPI(title="ArrivalGuard", version=__version__, lifespan=lifespan,
                  description="Medikal turist varış koruması — Nokia Network as Code (CAMARA) sinyalleriyle olay güdümlü vaka ajanı.",
                  docs_url="/docs", redoc_url=None, openapi_url="/openapi.json")
    app.state.ctx = ctx
    app.add_middleware(SecurityHeadersMiddleware)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST", "PUT", "DELETE"],
                           allow_headers=["content-type", "x-api-key"])
    for r in (system.router, cases.router, webhooks.router, public.router, demo.router):
        app.include_router(r)
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "web"), name="static")
    log.info("ArrivalGuard %s env=%s nac=%s store=%s notify=%s auth=%s", __version__, settings.app_env, ctx.nac.cfg.mode,
             ctx.store.backend, ctx.notifier.name, "on" if settings.auth_enabled else "OFF")
    return app
