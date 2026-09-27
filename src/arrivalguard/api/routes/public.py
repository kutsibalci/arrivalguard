"""Bağlantı token'ıyla erişilen uçlar: hastanın rıza sayfası ve sürücünün cihaz doğrulama sayfası.

Token bilen kişi yalnızca KENDİ vakasındaki kendi kararını verebilir; vaka ayrıntısı (itinerary, diğer
kişiler, uyarılar) bu uçlardan dönmez. Geçersiz token → 404 (varlık sızdırılmaz).
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ... import PACKAGE_DIR
from ...agent.case_machine import CONSENT_SCOPES
from ...nac_client import SIM_DEVICE_PREFIX, NacError
from ..models import ConsentDecisionIn, DriverVerifyIn
from ..security import get_ctx

log = logging.getLogger("arrivalguard.public")
router = APIRouter(tags=["public"])
WEB = PACKAGE_DIR / "web"
MONITORED = {
    "tr": ["Telefonunuzun ülkeye giriş anı (dolaşım bildirimi)", "Hattınızın son saatlerde değişip değişmediği (SIM değişimi)",
           "Telefonunuza ulaşılabilirlik", "Havalimanı, güzergâh ve klinik bölgelerine giriş/çıkış (koordinat değil, yalnızca bölge)"],
    "en": ["The moment your phone joins a network in the destination country (roaming notification)",
           "Whether your line changed hands in the last hours (SIM swap)", "Whether your phone is reachable",
           "Entering/leaving the airport, route and clinic areas (areas only, never coordinates)"],
    "ar": ["لحظة اتصال هاتفك بشبكة في بلد الوصول (إشعار التجوال)", "ما إذا تغيّرت شريحتك في الساعات الأخيرة",
           "إمكانية الوصول إلى هاتفك", "الدخول إلى/الخروج من مناطق المطار والطريق والعيادة (مناطق فقط، دون إحداثيات)"],
}


def _not_found():
    return HTTPException(404, {"code": "NOT_FOUND", "message": "bağlantı geçersiz ya da süresi dolmuş"})


def _consent_case(ctx, token: str):
    case = ctx.store.find_case_by_secret("consent", token)
    if case is None or case.consent_token != token:
        raise _not_found()
    return case


@router.get("/consent/{token}", include_in_schema=False)
def consent_page(token: str):
    return FileResponse(WEB / "consent.html")


@router.get("/v1/consent/{token}")
def consent_info(token: str, ctx=Depends(get_ctx)):
    with ctx.lock:
        case = _consent_case(ctx, token)
        lang = case.language if case.language in MONITORED else "en"
        return {
            "clinic_name": case.clinic_name, "patient_first_name": case.patient_name.split()[0], "language": lang,
            "status": case.consent.get("status"), "state": case.state, "text_version": case.consent.get("text_version"),
            "monitored": MONITORED[lang], "operator_scopes": CONSENT_SCOPES,
            "retention_days": ctx.cfg.retention_days, "stored_locations": 0,
            "can_withdraw": case.monitoring,
        }


@router.post("/v1/consent/{token}")
def consent_decide(token: str, body: ConsentDecisionIn, ctx=Depends(get_ctx)):
    event = {"accept": "consent_granted", "decline": "consent_declined", "withdraw": "consent_withdrawn"}[body.decision]
    with ctx.lock:
        case = _consent_case(ctx, token)
        if body.decision in ("accept", "decline") and case.state != "pending_consent":
            raise HTTPException(409, {"code": "CONFLICT", "message": "karar zaten verilmiş"})
        if body.decision == "withdraw" and not case.monitoring:
            raise HTTPException(409, {"code": "CONFLICT", "message": "izleme zaten aktif değil"})
        ctx.handle(case, {"type": event, "method": "patient_link", "source": "patient", "actor": "patient"})
        return {"ok": True, "status": case.consent.get("status"), "state": case.state}


# ------------------------------------------------------------------ sürücü
def _driver_case(ctx, token: str):
    case = ctx.store.find_case_by_secret("driver", token)
    if case is None or case.driver_token != token or case.terminal:
        raise _not_found()
    return case


@router.get("/driver/{token}", include_in_schema=False)
def driver_page(token: str):
    return FileResponse(WEB / "driver.html")


@router.get("/v1/driver/{token}")
def driver_info(token: str, ctx=Depends(get_ctx)):
    with ctx.lock:
        case = _driver_case(ctx, token)
        return {"patient_first_name": case.patient_name.split()[0], "clinic_name": case.clinic_name,
                "meeting_point": case.meeting_point, "driver_name": case.driver.get("name"),
                "verified": bool(case.driver_verified_at), "nac_mode": ctx.nac.cfg.mode,
                "sim_device_prefix": SIM_DEVICE_PREFIX if ctx.nac.cfg.mode != "live" else None}


def _verify(ctx, case, device_token: str | None, method: str) -> dict:
    entry = ctx.handle(case, {"type": "driver_verify", "device_token": device_token, "method": method,
                              "source": "driver_link", "actor": "driver"})
    return entry


@router.post("/v1/driver/{token}/verify")
def driver_verify(token: str, body: DriverVerifyIn, ctx=Depends(get_ctx)):
    """Cihaz token'ı elde olan istemciler için (ör. operatör SDK'lı mobil uygulama). Tarayıcıdaki sürücü sayfası
    bunun yerine `GET /v1/driver/{token}/nv/start` ile operatörün OIDC akışını kullanır."""
    with ctx.lock:
        case = _driver_case(ctx, token)
        entry = _verify(ctx, case, body.device_token, "device_token")
        ok = entry.get("decision") == "driver_verified"
        return {"ok": ok, "decision": entry.get("decision"), "note": entry.get("note"),
                "meeting_code_sent": ok}


@router.get("/v1/driver/{token}/nv/start")
def driver_nv_start(token: str, sim_line: str | None = None, ctx=Depends(get_ctx)):
    """Number Verification OIDC akışını başlatır: sürücünün telefonunu operatörün yetkilendirme adresine yönlendirir.
    Telefon bu adresi MOBİL VERİ ile açmalıdır; operatör hattı ağ üzerinden tanır ve `/driver/nv/callback`'e döner.
    `sim_line` yalnızca fixture/simülatörde: cihazın hattını taklit eder (canlıda 400)."""
    with ctx.lock:
        case = _driver_case(ctx, token)
    if sim_line and ctx.nac.cfg.mode == "live":
        raise HTTPException(400, {"code": "INVALID_ARGUMENT", "message": "sim_line canlı modda kullanılamaz"})
    try:
        url = ctx.nv_begin(case, sim_line=sim_line or None)
    except ValueError as e:
        raise HTTPException(400, {"code": "INVALID_ARGUMENT", "message": str(e)}) from None
    except NacError as e:
        log.warning("nv start failed kind=%s", e.kind)
        return RedirectResponse(f"/driver/{quote(token)}?nv=error", status_code=303)
    return RedirectResponse(url, status_code=303)


@router.get("/driver/nv/callback", include_in_schema=False)
def driver_nv_callback(state: str = "", code: str = "", error: str = "", ctx=Depends(get_ctx)):
    """Operatör buraya `code` (ya da `error`) ile döner → token al → Number Verification → sürücü sayfasına geri."""
    token = ctx.nv_take_state(state)
    if token is None:
        return HTMLResponse("<!doctype html><meta charset=utf-8><title>ArrivalGuard</title>"
                            "<p>Doğrulama bağlantısının süresi dolmuş. Sürücü bağlantısını yeniden açın.</p>", status_code=400)
    page = f"/driver/{quote(token)}"
    if error or not code:
        log.info("nv callback operator error=%s", error[:40] or "no-code")
        return RedirectResponse(f"{page}?nv=network", status_code=303)
    try:
        device_token = ctx.nv.exchange_code(code, ctx.nv_redirect_uri)
    except NacError as e:
        log.warning("nv token exchange failed kind=%s", e.kind)
        return RedirectResponse(f"{page}?nv=error", status_code=303)
    with ctx.lock:
        try:
            case = _driver_case(ctx, token)
        except HTTPException:
            return RedirectResponse(page, status_code=303)
        entry = _verify(ctx, case, device_token, "oidc")
    return RedirectResponse(f"{page}?nv={'ok' if entry.get('decision') == 'driver_verified' else 'fail'}", status_code=303)
