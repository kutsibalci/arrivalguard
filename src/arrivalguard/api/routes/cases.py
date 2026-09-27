"""Vaka uçları (X-API-Key, klinik bazlı erişim)."""
from __future__ import annotations

import logging
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from ...agent import CaseMachine
from ...agent.case_machine import consent_link
from ..context import clinic_public
from ..models import ActionIn, CaseIn, ClinicIn, EventIn
from ..security import Principal, check_case_access, get_ctx, require_admin, require_principal

log = logging.getLogger("arrivalguard.cases")
router = APIRouter(prefix="/v1", tags=["cases"])


def _bad(message: str, code: str = "INVALID_ARGUMENT") -> HTTPException:
    return HTTPException(400, {"code": code, "message": message})


@router.post("/cases", status_code=201)
def create_case(body: CaseIn, ctx=Depends(get_ctx), p: Principal = Depends(require_principal)):
    clinic_id = body.clinic_id or (None if p.is_admin else p.clinic_id)
    if clinic_id is None:
        raise _bad("yönetici anahtarıyla clinic_id zorunlu")
    if not p.can_access(clinic_id):
        raise HTTPException(403, {"code": "PERMISSION_DENIED", "message": "bu klinik için yetkiniz yok"})
    with ctx.lock:
        clinic = ctx.store.get_clinic(clinic_id)
        if clinic is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": f"klinik yok: {clinic_id}"})
        try:
            case = ctx.create_case(body.model_dump(mode="json") | {"_actor": p.actor}, clinic)
        except ValueError as e:
            raise _bad(str(e)) from e
        out = case.to_dict()
        if case.state == "pending_consent":
            out["consent_link"] = consent_link(case)  # klinik, SMS ulaşmazsa bağlantıyı elden iletebilir
        return out


@router.get("/cases")
def list_cases(state: str | None = None, limit: int = Query(100, ge=1, le=500), ctx=Depends(get_ctx),
               p: Principal = Depends(require_principal)):
    with ctx.lock:
        cases = ctx.store.list_cases(None if p.is_admin else p.clinic_id, [state] if state else None)
    return [c.to_dict() for c in cases[-limit:]]


@router.get("/cases/{case_id}")
def get_case(case_id: str, ctx=Depends(get_ctx), p: Principal = Depends(require_principal)):
    with ctx.lock:
        return check_case_access(p, ctx.store.get_case(case_id)).to_dict()


@router.delete("/cases/{case_id}", status_code=204)
def delete_case(case_id: str, ctx=Depends(get_ctx), p: Principal = Depends(require_principal)):
    """Silme talebi (KVKK m.7 / GDPR m.17): izleme sürüyorsa önce abonelikler silinir, sonra kayıt tümüyle kaldırılır."""
    with ctx.lock:
        case = check_case_access(p, ctx.store.get_case(case_id))
        if not case.subscriptions_deleted:
            ctx.unsubscribe(case)
        ctx.store.delete_case(case.id)
        log.info("case deleted on request id=%s actor=%s", case.id, p.actor)


@router.get("/cases/{case_id}/audit")
def case_audit(case_id: str, ctx=Depends(get_ctx), p: Principal = Depends(require_principal)):
    """Kapanış raporu — kliniğin hizmet kanıtı (ham numara, kod ve token yok)."""
    with ctx.lock:
        return CaseMachine.audit(check_case_access(p, ctx.store.get_case(case_id)))


@router.post("/cases/{case_id}/events")
def post_event(case_id: str, body: EventIn, ctx=Depends(get_ctx), p: Principal = Depends(require_principal)):
    """Şebeke olayını elle besler (webhook'un manuel eşdeğeri). Yalnızca ENABLE_MANUAL_EVENTS açıkken."""
    if not ctx.settings.enable_manual_events:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "manuel olay beslemesi kapalı (ENABLE_MANUAL_EVENTS=0)"})
    if body.type.startswith("consent_"):
        raise _bad("rıza kararı yalnızca hastanın rıza bağlantısından verilir")
    with ctx.lock:
        case = check_case_access(p, ctx.store.get_case(case_id))
        at = body.now.astimezone(timezone.utc) if body.now and body.now.tzinfo else (
            body.now.replace(tzinfo=timezone.utc) if body.now else ctx.now())
        entry = ctx.handle(case, {"type": body.type, "source": "manual", "actor": p.actor, **body.data}, at)
        return {"entry": entry, "case": case.to_dict()}


@router.post("/cases/{case_id}/actions")
def post_action(case_id: str, body: ActionIn, ctx=Depends(get_ctx), p: Principal = Depends(require_principal)):
    """Koordinatör aksiyonları: ack_alert, manual_release, confirm_arrival, reassign_driver, report/clear_disruption, close_case, note."""
    with ctx.lock:
        case = check_case_access(p, ctx.store.get_case(case_id))
        data = body.model_dump(mode="json", exclude_none=True)
        if body.action == "reassign_driver" and body.driver_id:
            clinic = ctx.store.get_clinic(case.clinic_id) or {}
            drv = next((d for d in clinic.get("drivers") or [] if d["id"] == body.driver_id), None)
            if drv is None:
                raise _bad(f"klinikte sürücü yok: {body.driver_id}")
            data["driver"] = drv
        try:
            entry = ctx.handle(case, {"type": "coordinator_action", "actor": p.actor, "source": "coordinator", **data})
        except ValueError as e:
            raise _bad(str(e), "FAILED_PRECONDITION") from e
        return {"entry": entry, "case": case.to_dict()}


# ------------------------------------------------------------------ klinik sicili
@router.get("/clinics")
def list_clinics(ctx=Depends(get_ctx), p: Principal = Depends(require_principal)):
    return [clinic_public(c) for c in ctx.store.list_clinics() if p.can_access(c["id"])]


@router.get("/clinics/{clinic_id}")
def get_clinic(clinic_id: str, ctx=Depends(get_ctx), p: Principal = Depends(require_principal)):
    c = ctx.store.get_clinic(clinic_id)
    if c is None or not p.can_access(clinic_id):
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "klinik yok"})
    return clinic_public(c)


@router.put("/clinics/{clinic_id}")
def put_clinic(clinic_id: str, body: ClinicIn, ctx=Depends(get_ctx), p: Principal = Depends(require_principal)):
    if body.id != clinic_id:
        raise _bad("gövdedeki id yol ile aynı olmalı")
    existing = ctx.store.get_clinic(clinic_id)
    if existing is None and not p.is_admin:
        raise HTTPException(403, {"code": "PERMISSION_DENIED", "message": "yeni klinik yalnızca yönetici anahtarıyla oluşturulur"})
    if not p.can_access(clinic_id):
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "klinik yok"})
    try:
        with ctx.lock:
            return clinic_public(ctx.save_clinic(body.model_dump(mode="json")))
    except ValueError as e:
        raise _bad(str(e)) from e


@router.post("/scheduler/run")
def scheduler_run(ctx=Depends(get_ctx), _: Principal = Depends(require_admin)):
    """Zamanlayıcı turunu hemen çalıştırır (işletim/test)."""
    return ctx.run_scheduler_once()
