"""CAMARA CloudEvents sink'leri. Kimlik: `Authorization: Bearer <WEBHOOK_TOKEN>` (sinkCredential).

Her olay: token doğrulama → abonelik/vaka eşleme → CloudEvent id tekilleştirme (kalıcı, 2 gün) → durum makinesi.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from ...nac_client.privacy import mask_phone
from ..security import check_webhook_token, get_ctx

log = logging.getLogger("arrivalguard.webhooks")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])
SUB_ENDS = "subscription-ends"


def _parse_time(v, fallback: datetime) -> datetime:
    if not v:
        return fallback
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return fallback
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _prepare(ctx, ev, authorization: str | None, sink: str):
    check_webhook_token(ctx, authorization)
    if not isinstance(ev, dict) or not ev.get("type"):
        raise HTTPException(400, {"code": "INVALID_ARGUMENT", "message": "CloudEvent bekleniyor (type zorunlu)"})
    data = ev.get("data") or {}
    case, target = ctx.resolve_webhook_case(data)
    at = _parse_time(ev.get("time"), ctx.now())
    if case is None:
        if str(ev["type"]).endswith(SUB_ENDS):
            # Vaka kapanıp abonelikler silinince Nokia `subscription-ends` gönderir: yapılacak iş yok, 200 → tekrar denemesin
            log.info("webhook %s: kapanmış aboneliğin subscription-ends olayı sub=%s", sink, data.get("subscriptionId"))
            return None, "", data, at, False
        phone = (data.get("device") or {}).get("phoneNumber")
        log.warning("webhook %s: eşleşmeyen abonelik type=%s sub=%s phone=%s", sink, ev["type"], data.get("subscriptionId"),
                    mask_phone(phone) if phone else "-")
        raise HTTPException(404, {"code": "UNKNOWN_SUBSCRIPTION", "message": "abonelik/vaka eşleşmedi"})
    ce_id = ev.get("id")
    duplicate = bool(ce_id) and ctx.store.seen_event(f"{sink}:{ce_id}", ctx.now())
    return case, target, data, at, duplicate


def _brief(data: dict) -> str:
    """Olayın karar veren alanları — kişisel veri içermez (ülke kodu, ulaşılabilirlik, bölge)."""
    keys = ("countryCode", "countryName", "roaming", "reachable", "connectivity", "reachabilityStatus", "area")
    parts = [f"{k}={data[k]}" for k in keys if k in data and k != "area"]
    if "area" in data:
        parts.append("area=" + str((data.get("area") or {}).get("areaType")))
    return (" " + " ".join(parts)) if parts else ""


def _subscription_ended(ctx, case, target: str, at: datetime) -> dict:
    entry = ctx.handle(case, {"type": "subscription_ended", "target": target or "?", "source": "webhook"}, at)
    return {"ok": True, "handled": SUB_ENDS, "case_id": case.id, "entry": entry}


@router.post("/roaming")
def webhook_roaming(ev: dict = Body(...), authorization: str | None = Header(default=None), ctx=Depends(get_ctx)):
    """Device Roaming Status sink'i (roaming-on / roaming-change-country / roaming-off)."""
    with ctx.lock:
        case, target, data, at, dup = _prepare(ctx, ev, authorization, "roaming")
        if case is None:
            return {"ok": True, "handled": SUB_ENDS, "case_id": None}
        if dup:
            return {"ok": True, "duplicate": True}
        etype = ev["type"]
        log.info("webhook roaming: case=%s type=%s%s", case.id, etype.rsplit(".", 1)[-1], _brief(data))
        if etype.endswith(SUB_ENDS):
            return _subscription_ended(ctx, case, "roaming", at)
        if etype.endswith("roaming-off"):
            return {"ok": True, "handled": "roaming-off", "case_id": case.id,
                    "note": "Cihaz ev şebekesine döndü — vaka akışını değiştirmez."}
        if not (etype.endswith("roaming-on") or etype.endswith("roaming-change-country") or etype.endswith("roaming-status")):
            raise HTTPException(400, {"code": "UNSUPPORTED_TYPE", "message": f"desteklenmeyen CloudEvent tipi: {etype}"})
        country = data.get("countryCode") or data.get("country")
        source = "webhook"
        if country is None and case.patient_phone:
            # roaming-on olayı ülke taşımayabilir → anlık roaming sorgusuyla tamamla
            r = ctx.facade.call("roaming", case.patient_phone)
            country = (r.data or {}).get("countryCode") if isinstance(r.data, dict) else None
            source = f"webhook+poll({r.source})"
        entry = ctx.handle(case, {"type": "roaming_on", "country": country, "source": source}, at)
        return {"ok": True, "case_id": case.id, "entry": entry, "case": case.to_dict()}


@router.post("/geofence")
def webhook_geofence(ev: dict = Body(...), authorization: str | None = Header(default=None), ctx=Depends(get_ctx)):
    """Geofencing sink'i (area-entered / area-left). Bölge adı abonelik indeksinden çözülür."""
    with ctx.lock:
        case, zone, data, at, dup = _prepare(ctx, ev, authorization, "geofence")
        if case is None:
            return {"ok": True, "handled": SUB_ENDS, "case_id": None}
        if dup:
            return {"ok": True, "duplicate": True}
        etype = ev["type"]
        log.info("webhook geofence: case=%s type=%s%s", case.id, etype.rsplit(".", 1)[-1], _brief(data))
        if etype.endswith(SUB_ENDS):
            return _subscription_ended(ctx, case, f"geofence:{zone}", at)
        if etype.endswith("area-entered"):
            kind = "geofence_enter"
        elif etype.endswith("area-left"):
            kind = "geofence_left"
        else:
            raise HTTPException(400, {"code": "UNSUPPORTED_TYPE", "message": f"desteklenmeyen CloudEvent tipi: {etype}"})
        payload = {"zone": zone or data.get("zone") or "?", "source": "webhook"}
        if data.get("stationary_min") is not None:
            payload["stationary_min"] = data["stationary_min"]
        entry = ctx.handle(case, {"type": kind, **payload}, at)
        return {"ok": True, "case_id": case.id, "entry": entry, "case": case.to_dict()}


@router.post("/reachability")
def webhook_reachability(ev: dict = Body(...), authorization: str | None = Header(default=None), ctx=Depends(get_ctx)):
    """Device Reachability Status sink'i: reachability-disconnected → ulaşılamıyor; reachability-data/sms → ulaşılabilir."""
    with ctx.lock:
        case, _, data, at, dup = _prepare(ctx, ev, authorization, "reachability")
        if case is None:
            return {"ok": True, "handled": SUB_ENDS, "case_id": None}
        if dup:
            return {"ok": True, "duplicate": True}
        etype = ev["type"]
        log.info("webhook reachability: case=%s type=%s%s", case.id, etype.rsplit(".", 1)[-1], _brief(data))
        if etype.endswith(SUB_ENDS):
            return _subscription_ended(ctx, case, "reachability", at)
        if etype.endswith("reachability-disconnected"):
            reachable = False
        elif etype.endswith("reachability-data") or etype.endswith("reachability-sms"):
            reachable = True
        else:
            raise HTTPException(400, {"code": "UNSUPPORTED_TYPE", "message": f"desteklenmeyen CloudEvent tipi: {etype}"})
        entry = ctx.handle(case, {"type": "reachability_change", "reachable": reachable, "source": "webhook"}, at)
        return {"ok": True, "case_id": case.id, "entry": entry, "case": case.to_dict()}
