"""Sistem uçları: sağlık, durum, yapılandırma, debug, sayfalar."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ... import PACKAGE_DIR, __version__
from ...agent import STEP_LABELS
from ...agent.messages import COUNTRY_NAMES
from ..context import mask_deep
from ..security import Principal, get_ctx, require_admin, require_debug, require_demo, require_principal

router = APIRouter(tags=["system"])
WEB = PACKAGE_DIR / "web"


@router.get("/health")
def health(ctx=Depends(get_ctx)):
    out = {"ok": True, "version": __version__, "app_env": ctx.settings.app_env}
    if not ctx.settings.is_prod:
        out.update({"nac": ctx.nac.health(), "store": ctx.store.backend, "notify": ctx.notifier.name,
                    "profiles": len(ctx.nac.fx.profiles) if ctx.nac.fx else 0,
                    "scheduler": ctx.scheduler.status() if getattr(ctx, "scheduler", None) else None})
    return out


@router.get("/v1/config")
def config(ctx=Depends(get_ctx), _: Principal = Depends(require_principal)):
    return {"rules": ctx.cfg.to_dict(), "app": ctx.settings.public_dict()}


@router.get("/v1/state")
def state(ctx=Depends(get_ctx), p: Principal = Depends(require_principal)):
    with ctx.lock:
        cases = ctx.store.list_cases(None if p.is_admin else p.clinic_id)
        ids = {c.id for c in cases}
        base = ctx.settings.public_base_url.rstrip("/")
        return {
            "now": ctx.now().isoformat().replace("+00:00", "Z"),
            "config": ctx.cfg.to_dict(),
            "steps": [{"key": k, "label": v} for k, v in STEP_LABELS],
            "cases": [c.to_dict() for c in cases],
            "subscriptions": [s for s in ctx.store.list_subs() if s["case_id"] in ids],
            "degraded": ctx.degraded[-10:] if p.is_admin else [],
            "webhooks": {name: f"{base}/webhooks/{name}" for name in ("roaming", "geofence", "reachability")}
            | {"token_required": bool(ctx.settings.webhook_token)},
            "stored_locations_count": 0,  # tasarım gereği: konum geçmişi tutulmaz
        }


@router.post("/v1/reset")
def reset(ctx=Depends(get_ctx), _d=Depends(require_demo), _a: Principal = Depends(require_admin)):
    with ctx.lock:
        ctx.store.reset()
        ctx.facade.degraded.clear()
    return {"ok": True}


@router.get("/v1/_debug/calls")
def debug_calls(limit: int = 30, ctx=Depends(get_ctx), _d=Depends(require_debug), _a: Principal = Depends(require_admin)):
    # İstek gövdesi zaten maskeli; YANIT gövdeleri de maskelenir (device-status yanıtları numarayı geri döndürür)
    return [mask_deep(c.to_dict()) for c in ctx.nac.calls[-limit:]]


@router.get("/v1/_debug/profiles")
def debug_profiles(ctx=Depends(get_ctx), _d=Depends(require_debug), _a: Principal = Depends(require_admin)):
    return mask_deep(ctx.nac.fx.profiles) if ctx.nac.fx else {}


@router.get("/", include_in_schema=False)
def root(ctx=Depends(get_ctx)):
    out = {"app": "arrivalguard", "version": __version__, "motto": "Aynı sinyal, zıt anlam.", "docs": "/docs",
           "console": "/console", "health": "/health"}
    if ctx.settings.enable_demo:
        out |= {"demo": "/demo", "scenarios": list(SCENARIOS), "countries": COUNTRY_NAMES}
    return out


@router.get("/demo", include_in_schema=False, dependencies=[Depends(require_demo)])
def demo_page():
    return FileResponse(WEB / "demo.html")


@router.get("/console", include_in_schema=False)
def console_page():
    return FileResponse(WEB / "console.html")


SCENARIOS = ("happy-path", "sim-swap", "local-sim", "trouble", "api-down", "no-signal", "consent")
