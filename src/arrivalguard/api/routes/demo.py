"""Tek tuşla demo senaryoları (ENABLE_DEMO=1). Jüri önünde elle veri girilmez; olaylar göreli zamanla akar.

Her senaryo gerçek yoldan geçer: ctx.create_case → ctx.handle (durum makinesi + Nokia facade + bildirim +
abonelik yaşam döngüsü). Fixture profilleri çalışma anında göreli tarihe çekilir (`_prime`), böylece
"SIM 3 saat önce değişti" makinenin takvim tarihinden bağımsızdır.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from ...agent import Case, CaseMachine
from ...nac_client import SIM_DEVICE_PREFIX, normalize_phone
from ..context import iso
from ..models import DemoIn
from ..security import Principal, get_ctx, require_admin, require_demo

router = APIRouter(prefix="/v1/demo", tags=["demo"], dependencies=[Depends(require_demo)])

CLINIC_ID = "clinic-1"
DRIVER_PHONE = "+447700900101"
IMPOSTOR_PHONE = "+447700900109"
FAMILY = {"name": "Ahmed (kardeş)", "phone": "+447700900099", "language": "en"}


def _itinerary(t0: datetime, transit: int = 974, dest: int = 90, arrival_min: int = 180) -> dict:
    return {"destination_country": dest, "legs": [
        {"country": transit, "eta": iso(t0), "label": "Doha aktarma"},
        {"country": dest, "eta": iso(t0 + timedelta(minutes=arrival_min)), "label": "İstanbul varış"}]}


class Runner:
    """Senaryo koşucusu: olayı gerçek yoldan işler, UI için adım kaydı üretir."""

    def __init__(self, ctx, case: Case, t0: datetime):
        self.ctx, self.case, self.t0, self.steps = ctx, case, t0, []

    def run(self, minutes: float, etype: str, node: str, title: str, **data) -> dict:
        entry = self.ctx.handle(self.case, {"type": etype, "source": "demo", **data}, self.t0 + timedelta(minutes=minutes))
        self.steps.append({
            "seq": entry.get("seq"), "t": entry["t"], "minute": minutes, "event": etype, "node": node, "title": title,
            "decision": entry.get("decision"), "rule": entry.get("rule"), "note": entry.get("note"),
            "confidence": entry.get("confidence"), "state": self.case.state, "step_index": self.case.step_index,
            "alerts": len(self.case.alerts), "messages": len(self.case.messages),
        })
        return entry


def _start(ctx, body: DemoIn | None) -> datetime:
    body = body or DemoIn()
    if body.reset:
        ctx.store.reset()
        ctx.facade.degraded.clear()
        ctx.nac.breaker.reset()
    start = body.start or datetime.now(timezone.utc)
    return start if start.tzinfo else start.replace(tzinfo=timezone.utc)


def _prime(ctx, phone: str, patch: dict) -> None:
    if ctx.nac.fx is not None:
        ctx.nac.fx.update_profile(normalize_phone(phone), patch)


def _new_case(ctx, name: str, phone: str, lang: str, t0: datetime, *, consent: bool = True, arrival_min: int = 180) -> Case:
    clinic = ctx.store.get_clinic(CLINIC_ID)
    if clinic is None:
        raise HTTPException(500, {"code": "INTERNAL", "message": "demo kliniği yok (fixtures/clinics.json)"})
    return ctx.create_case({"patient_name": name, "patient_phone": phone, "language": lang,
                            "itinerary": _itinerary(t0, arrival_min=arrival_min), "driver_id": "drv-1",
                            "family_contact": dict(FAMILY), "consent": {"method": "clinic_form"} if consent else None,
                            "_actor": "demo"}, clinic, at=t0)


def _out(ctx, scenario: str, runners: list[Runner], extra: dict | None = None) -> dict:
    out = {
        "scenario": scenario, "cases": [r.case.to_dict() for r in runners], "steps": [r.steps for r in runners],
        "audits": [CaseMachine.audit(r.case) for r in runners], "degraded": ctx.degraded[-10:],
        "config": ctx.cfg.to_dict(), "stored_locations_count": 0,
    }
    if len(runners) == 1:
        out["case"], out["timeline_steps"] = out["cases"][0], out["steps"][0]
    return out | (extra or {})


def _clean_sim(ctx, phone: str, t0: datetime, **extra) -> None:
    _prime(ctx, phone, {"sim_swap_at": iso(t0 - timedelta(days=90)), "roaming": True, "country_code": 90, "reachable": True,
                        "fail": None, **extra})


DRIVER_TOKEN = SIM_DEVICE_PREFIX + DRIVER_PHONE        # sürücünün KENDİ cihazı
IMPOSTOR_TOKEN = SIM_DEVICE_PREFIX + IMPOSTOR_PHONE    # sürücü numarasını iddia eden başka cihaz


@router.post("/happy-path")
def demo_happy_path(body: DemoIn | None = None, ctx=Depends(get_ctx), _: Principal = Depends(require_admin)):
    """Tam zincir: aktarma → varış → SIM temiz → taklit numara uyarısı → sahte cihaz reddi → sürücü cihazı doğrulandı
    (buluşma kodu) → sahte arama reddi → gerçek sürücü → klinik → aile mesajı, abonelikler silinir."""
    with ctx.lock:
        t0 = _start(ctx, body)
        phone = "+447700900001"
        _clean_sim(ctx, phone, t0)
        r = Runner(ctx, _new_case(ctx, "Layla A.", phone, "en", t0), t0)
        r.run(0, "roaming_on", "transit", "Doha aktarması görüldü — kısa selam, sürücü GÖNDERİLMEZ", country=974)
        r.run(180, "roaming_on", "airport", "İstanbul'a varış (hedef ülke + ETA penceresi) → bütünlük kapısı", country=90)
        r.run(184, "driver_call", "airport", "Sürücünün numarasından arama — ama cihaz doğrulaması YOK (numara taklidi?)", caller_phone=DRIVER_PHONE)
        r.run(186, "driver_verify", "airport", "Başka bir cihaz sürücü numarasıyla doğrulamaya çalıştı — şebeke REDDETTİ", device_token=IMPOSTOR_TOKEN)
        r.run(188, "driver_verify", "airport", "Sürücü kendi cihazını doğruladı (Number Verification) → buluşma kodu", device_token=DRIVER_TOKEN)
        r.run(190, "driver_call", "airport", "Sahte 'sürücü' araması — kayıtlı sürücü değil", caller_phone=IMPOSTOR_PHONE)
        r.run(195, "driver_call", "airport", "Gerçek sürücü arıyor — kayıtlı + taze doğrulama → ilk temas", caller_phone=DRIVER_PHONE)
        r.run(200, "geofence_left", "corridor", "Havalimanından ayrıldı — transfer başladı", zone="airport")
        r.run(210, "geofence_enter", "corridor", "Koridora giriş — rota beklenen hatta", zone="corridor")
        r.run(245, "geofence_enter", "clinic", "Klinik kapısı — vaka kapandı, aileye bilgi, abonelikler silindi", zone="clinic")
        return _out(ctx, "happy-path", [r], {"headline": "Sürücü, hastanın telefonunda değil KENDİ cihazında doğrulanır; "
                                                         "hasta, kodu söyleyen araca biner."})


@router.post("/sim-swap")
def demo_sim_swap(body: DemoIn | None = None, ctx=Depends(get_ctx), _: Principal = Depends(require_admin)):
    """Varışta SIM 3 saat önce değişmiş → pickup detayları BEKLETİLİR; koordinatör hattı teyit edip manuel serbest bırakır."""
    with ctx.lock:
        t0 = _start(ctx, body)
        phone = "+447700900003"
        swap_at = iso(t0 + timedelta(minutes=180) - timedelta(hours=3))
        _prime(ctx, phone, {"sim_swap_at": swap_at, "roaming": True, "country_code": 90, "reachable": True, "fail": None})
        r = Runner(ctx, _new_case(ctx, "Omar K.", phone, "ar", t0), t0)
        r.run(0, "roaming_on", "transit", "Doha aktarması — kısa selam", country=974)
        r.run(180, "roaming_on", "airport", "Varış → SIM Swap kontrolü: son 3 saatte değişmiş → DONDURULDU", country=90)
        r.run(188, "driver_verify", "airport", "Sürücü cihazı doğrulandı — ama kod hastaya GÖNDERİLMEZ (hat şüpheli)", device_token=DRIVER_TOKEN)
        r.run(192, "driver_call", "airport", "Sürücü aradı — vaka dondurulmuş, ilk temas SAYILMAZ", caller_phone=DRIVER_PHONE)
        r.run(200, "sim_swap_result", "airport", "Koordinatör manuel yeniden kontrol istedi — hâlâ taze", swapped=True, sim_swap_at=swap_at)
        return _out(ctx, "sim-swap", [r], {"headline": "Numara ele geçirilmiş olabilir → sürücü adı, plaka ve buluşma kodu gönderilmedi."})


@router.post("/local-sim")
def demo_local_sim(body: DemoIn | None = None, ctx=Depends(get_ctx), _: Principal = Depends(require_admin)):
    """ANA GÖSTERİ — aynı sinyal, zıt anlam.

    A: ilk temastan ÖNCE ulaşılamıyor → 7 dk sonra ALARM. B: ilk temastan SONRA ulaşılamıyor → tolerans içinde alarm DÜŞER.
    """
    with ctx.lock:
        t0 = _start(ctx, body)
        pa, pb = "+447700900004", "+447700900001"
        for p in (pa, pb):
            _clean_sim(ctx, p, t0)
        a = Runner(ctx, _new_case(ctx, "Fatima N.", pa, "en", t0), t0)
        a.run(0, "roaming_on", "transit", "Doha aktarması", country=974)
        a.run(180, "roaming_on", "airport", "Varış → SIM temiz, karşılama mesajı gönderildi", country=90)
        a.run(185, "reachability_change", "airport", "Cihaz ulaşılamıyor — İLK TEMAS YOK", reachable=False)
        a.run(192, "tick", "airport", f"7 dk sessizlik ≥ {ctx.cfg.unreachable_before_contact_alert_min} dk eşiği → ALARM")

        b = Runner(ctx, _new_case(ctx, "Yusuf D.", pb, "en", t0), t0)
        b.run(0, "roaming_on", "transit", "Doha aktarması", country=974)
        b.run(180, "roaming_on", "airport", "Varış → SIM temiz, karşılama mesajı gönderildi", country=90)
        b.run(186, "driver_verify", "airport", "Sürücü cihazı doğrulandı → buluşma kodu", device_token=DRIVER_TOKEN)
        b.run(190, "driver_call", "airport", "Gerçek sürücü aradı — İLK TEMAS KURULDU", caller_phone=DRIVER_PHONE)
        b.run(200, "reachability_change", "corridor", "Cihaz ulaşılamıyor — ama temas kurulmuştu", reachable=False)
        b.run(215, "tick", "corridor", f"15 dk < {ctx.cfg.unreachable_after_contact_grace_min} dk tolerans → alarm DÜŞER, mesaj kanalı")
        return _out(ctx, "local-sim", [a, b], {
            "compare": {
                "signal": "device-reachability-status: reachable = false",
                "a": {"case_id": a.case.id, "first_contact": False, "level": "alarm",
                      "why": "İlk temas kurulmadan sessizlik → hasta karşılama zincirine hiç bağlanmadı."},
                "b": {"case_id": b.case.id, "first_contact": True, "level": "lower",
                      "why": "Temas sonrası sessizlik → muhtemelen yerel SIM/eSIM aldı; koordinatör uyandırılmaz."},
            },
            "headline": "Aynı ham sinyal, vakanın durumuna göre zıt anlam.",
        })


@router.post("/trouble")
def demo_trouble(body: DemoIn | None = None, ctx=Depends(get_ctx), _: Principal = Depends(require_admin)):
    """Yolculuk bütünlüğü: trafik mi, sorun mu? Düşük güven → vaka notu; yüksek güven → koordinatör + bütçe."""
    with ctx.lock:
        t0 = _start(ctx, body)
        phone = "+447700900001"
        _clean_sim(ctx, phone, t0)
        r = Runner(ctx, _new_case(ctx, "Nadia S.", phone, "en", t0), t0)
        r.run(0, "roaming_on", "transit", "Doha aktarması", country=974)
        r.run(180, "roaming_on", "airport", "Varış → SIM temiz, karşılama", country=90)
        r.run(186, "driver_verify", "airport", "Sürücü cihazı doğrulandı", device_token=DRIVER_TOKEN)
        r.run(190, "driver_call", "airport", "Gerçek sürücü — ilk temas", caller_phone=DRIVER_PHONE)
        r.run(195, "geofence_left", "corridor", "Havalimanından ayrıldı", zone="airport")
        r.run(205, "geofence_left", "corridor", "Koridordan sapma — ama araç hareketli (düşük güven)", zone="corridor", stationary_min=2)
        r.run(220, "tick", "corridor", "Koridor dışı + 12 dk hareketsiz → sorun adayı (güven %60)", stationary_min=12)
        r.run(230, "reachability_change", "corridor", "Hasta da ulaşılamıyor → temas sonrası tolerans: mesaj kanalına düşüldü", reachable=False)
        r.run(240, "tick", "corridor", "Koridor dışı + hareketsiz + ulaşılamıyor → SORUN (güven %85)", stationary_min=22)
        r.run(250, "tick", "corridor", "Aynı sorun sürüyor — 10 dk sonra yeniden eskalasyon", stationary_min=32)
        r.run(260, "tick", "corridor", "Bütçe doldu → yeni bildirim yok, açık uyarıya kanıt eklenir", stationary_min=42)
        return _out(ctx, "trouble", [r], {"headline": "Alarm yorgunluğu önlemi: vaka başına koordinatör uyandırma bütçesi "
                                                      f"{ctx.cfg.escalation_budget_per_case}, yeniden uyandırma en erken "
                                                      f"{ctx.cfg.reescalate_after_min} dk."})


@router.post("/api-down")
def demo_api_down(body: DemoIn | None = None, ctx=Depends(get_ctx), _: Principal = Depends(require_admin)):
    """Nokia API 500 döndüğünde: vaka çökmez, sinyal 'bilinmiyor' olur, kaynak explain'de error(...) yazar."""
    with ctx.lock:
        t0 = _start(ctx, body)
        phone = "+447700900006"
        _prime(ctx, phone, {"fail": 500, "roaming": True, "country_code": 90})
        r = Runner(ctx, _new_case(ctx, "Hassan T.", phone, "en", t0), t0)
        r.run(0, "roaming_on", "transit", "Doha aktarması (webhook — API'ye bağlı değil)", country=974)
        r.run(180, "roaming_on", "airport", "Varış → SIM Swap sorgusu 500 döndü; sinyal bilinmiyor, akış sürüyor", country=90)
        return _out(ctx, "api-down", [r], {"headline": "Kırılgan değil: şebeke sorgusu düşse de vaka akışı sürer ve eksik veri koordinatöre işaretlenir.",
                                           "breaker": ctx.nac.health()})


@router.post("/no-signal")
def demo_no_signal(body: DemoIn | None = None, ctx=Depends(get_ctx), _: Principal = Depends(require_admin)):
    """Roaming webhook'u hiç gelmedi: zamanlayıcı pencere kapanınca anlık sorgu yapar, koordinatör varışı teyit eder."""
    with ctx.lock:
        t0 = _start(ctx, body)
        phone = "+447700900001"
        _clean_sim(ctx, phone, t0)
        r = Runner(ctx, _new_case(ctx, "Karim B.", phone, "en", t0), t0)
        window = int(ctx.cfg.arrival_window_h * 60)
        r.run(120, "tick", "origin", "Zamanlayıcı: varış penceresi açık, bekleniyor", source="scheduler")
        r.run(180 + window + 5, "tick", "airport", "Pencere kapandı, olay yok → anlık roaming sorgusu: hedef ülkede", source="scheduler")
        r.run(180 + window + 12, "coordinator_action", "airport", "Koordinatör uçuş gecikmesini teyit etti → varış akışı başlar",
              action="confirm_arrival", actor="demo-coordinator")
        return _out(ctx, "no-signal", [r], {"headline": "Webhook kaybolsa bile vaka sessizce beklemez: yedek yol anlık sorgu + koordinatör."})


@router.post("/consent")
def demo_consent(body: DemoIn | None = None, ctx=Depends(get_ctx), _: Principal = Depends(require_admin)):
    """Rıza akışı: rıza yokken şebeke olayı işlenmez → hasta onaylar (abonelikler kurulur) → hasta geri çeker (silinir)."""
    with ctx.lock:
        t0 = _start(ctx, body)
        phone = "+447700900002"
        _clean_sim(ctx, phone, t0)
        r = Runner(ctx, _new_case(ctx, "Sara M.", phone, "tr", t0, consent=False), t0)
        r.run(1, "roaming_on", "origin", "Rıza yokken roaming olayı → İŞLENMEZ, yalnızca audit", country=974)
        r.run(30, "consent_granted", "origin", "Hasta rıza bağlantısından ONAYLADI → abonelikler kuruldu", method="patient_link", actor="patient")
        r.run(60, "consent_withdrawn", "origin", "Hasta rızasını GERİ ÇEKTİ → izleme durdu, abonelikler silindi, numara silindi",
              actor="patient")
        return _out(ctx, "consent", [r], {"headline": "Rıza yoksa izleme yok; geri çekme anında abonelikler ve ham numara silinir."})
