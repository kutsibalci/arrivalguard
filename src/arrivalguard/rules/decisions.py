"""ArrivalGuard karar kuralları — SAF fonksiyonlar. Yan etki yok, ağ yok, saat parametre olarak gelir.

Her fonksiyon bir `Decision` döner; `decision` alanı kararın kendisi, `explain[]` neden.
Ajan = deterministik durum makinesi (`agent/case_machine.py`) + bu kurallar. LLM karar vermez; yalnızca
isteğe bağlı olarak vaka özeti yazar (`agent/llm_adapter.py`).
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Config
from .explain import Decision, Explain

# ---------------------------------------------------------------- yardımcılar

def _dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _cc(v: Any) -> int | None:
    """Ülke kodunu int'e çevirir ('90', 90, '+90' → 90)."""
    if v is None:
        return None
    try:
        return int(str(v).lstrip("+"))
    except ValueError:
        return None


country_code = _cc  # dışa açık ad


# ---------------------------------------------------------------- 1) transit vs varış

def classify_roaming_event(event_country: Any, itinerary: dict, now: datetime, cfg: Config) -> Decision:
    """Roaming olayı geldi: gerçek varış mı, aktarma mı, beklenmeyen mi?

    itinerary = {"legs": [{"country": 974, "eta": "...Z"}, {"country": 90, "eta": "...Z"}], "destination_country": 90}
    - hedef ülke + ETA ± arrival_window_h  → arrival
    - itinerary'de aktarma bacağı olan ülke → transit (sürücü GÖNDERİLMEZ, kısa selam)
    - aksi                                   → unexpected (koordinatör teyidi)
    """
    now = _dt(now)
    cc = _cc(event_country)
    dest = _cc(itinerary.get("destination_country"))
    legs = itinerary.get("legs") or []
    ex: list[Explain] = [
        Explain("roaming.countryCode", cc, 0.4, "Şebekenin bildirdiği ülke", source="device-roaming-status"),
        Explain("itinerary.destination_country", dest, 0.2, "Rezervasyondaki hedef ülke", source="itinerary"),
    ]
    if cc is None:
        ex[0].triggered = True
        return Decision("unexpected", 0.5, "roaming.no_country", ex, ["note_case"], {"reason": "ülke kodu yok"})

    dest_legs = [leg for leg in legs if _cc(leg.get("country")) == cc and cc == dest]
    if dest_legs:
        eta = _dt(dest_legs[-1].get("eta"))
        window = timedelta(hours=cfg.arrival_window_h)
        in_window = eta is None or (eta - window) <= now <= (eta + window)
        delta_min = round((now - eta).total_seconds() / 60) if eta else None
        ex.append(Explain("itinerary.eta_delta_min", delta_min, 0.4,
                          f"Hedef bacağın ETA'sına göre fark (pencere ±{cfg.arrival_window_h:g} sa)", source="itinerary", triggered=in_window))
        if in_window:
            return Decision("arrival", 0.0, "arrival.destination_in_window", ex, ["open_arrival_case", "run_integrity_gate"],
                            {"note": "Hedef ülke + beklenen pencere → VARIŞ. Bütünlük kontrolü başlar."})
        return Decision("unexpected", 0.4, "arrival.destination_out_of_window", ex, ["notify_coordinator"],
                        {"note": "Hedef ülke ama beklenen pencere dışında → koordinatör teyidi; sürücü otomatik gönderilmez."})

    transit_legs = [leg for leg in legs if _cc(leg.get("country")) == cc]
    if transit_legs:
        eta = _dt(transit_legs[0].get("eta"))
        ex.append(Explain("itinerary.leg", {"country": cc, "eta": transit_legs[0].get("eta")}, 0.4,
                          "Bu ülke itinerary'de aktarma bacağı", source="itinerary", triggered=True))
        return Decision("transit", 0.0, "roaming.transit_leg", ex, ["greet_briefly", "keep_waiting"],
                        {"note": "Aktarma (layover). Kısa selam gönderilir, sürücü GÖNDERİLMEZ, vaka beklemede kalır."})

    ex.append(Explain("itinerary.match", None, 0.4, "Ülke itinerary'de yok", source="itinerary", triggered=True))
    return Decision("unexpected", 0.6, "roaming.unknown_country", ex, ["notify_coordinator"],
                    {"note": "Itinerary dışı ülke → koordinatöre not, sürücü gönderilmez."})


# ---------------------------------------------------------------- 2) bütünlük kapısı (SIM swap)

def integrity_gate(sim_swapped_recent: bool | None, sim_swap_at: Any, cfg: Config, now: datetime | None = None) -> Decision:
    """İlk temastan önce: SIM son `sim_swap_freeze_window_h` saat içinde değiştiyse pickup detayları BEKLETİLİR."""
    at = _dt(sim_swap_at)
    hours_ago = None
    if at is not None and now is not None:
        hours_ago = round((_dt(now) - at).total_seconds() / 3600, 1)
    recent = bool(sim_swapped_recent) or (hours_ago is not None and 0 <= hours_ago <= cfg.sim_swap_freeze_window_h)
    ex = [
        Explain("sim_swap.swapped", sim_swapped_recent, 0.6, f"SIM Swap check (maxAge={cfg.sim_swap_freeze_window_h} sa)", source="sim-swap", triggered=bool(sim_swapped_recent)),
        Explain("sim_swap.latestSimChange", at.isoformat() if at else None, 0.4,
                f"Son SIM değişimi{'' if hours_ago is None else f' — {hours_ago} sa önce'}", source="sim-swap", triggered=recent and at is not None),
    ]
    if recent:
        return Decision("withhold_pickup", 0.9, "integrity.sim_swap_recent", ex, ["freeze_pickup_details", "notify_coordinator"],
                        {"note": "Numara son saatlerde ele geçirilmiş olabilir → sürücü adı/plaka GÖNDERİLMEZ, koordinatör devreye girer."})
    return Decision("release_pickup", 0.05, "integrity.clean", ex, ["send_welcome_with_pickup"],
                    {"note": "SIM temiz → karşılama mesajı ve sürücü detayları serbest."})


# ---------------------------------------------------------------- 3) sürücü doğrulama (Number Verification)
#
# Number Verification "beni arayan hat kimin?" sorusunu CEVAPLAYAMAZ: API, isteği yapan cihazın kendi
# hattını (mobil veri oturumu üzerinden) doğrular. Bu yüzden doğrulama iki aşamalıdır:
#   (a) authenticate_driver_device — sürücü KENDİ cihazında doğrulama bağlantısını açar; şebeke "bu cihaz
#       kayıtlı sürücünün hattında" der → taze bir tasdik (attestation) + hastaya giden buluşma kodu.
#   (b) assess_incoming_call — hastaya "sürücü" araması geldiğinde: numara kayıtlı mı ve taze tasdik var mı?
#       Arayan numara taklit edilebilir (CLI spoofing); asıl güvence yüz yüze söylenen buluşma kodudur.

def authenticate_driver_device(number_verified: bool | None, is_registered_driver: bool) -> Decision:
    """Sürücünün cihazı, vakaya atanmış sürücünün hattında mı? (Number Verification sonucu + sicil eşleşmesi)"""
    ex = [
        Explain("number_verification.devicePhoneNumberVerified", number_verified, 0.6,
                "Doğrulamayı yapan cihaz iddia edilen hatta mı (şebeke doğrulaması)", source="number-verification",
                triggered=not bool(number_verified)),
        Explain("driver_registry.match", is_registered_driver, 0.4,
                "İddia edilen numara bu vakaya atanmış sürücünün mü", source="registry", triggered=not is_registered_driver),
    ]
    if number_verified and is_registered_driver:
        return Decision("driver_verified", 0.0, "driver.device_verified", ex, ["issue_meeting_code", "notify_patient_verified_driver"],
                        {"note": "Sürücü cihazı şebeke tarafından doğrulandı ✓ — buluşma kodu hastaya ve sürücüye gönderildi."})
    reason = "not_registered" if not is_registered_driver else "not_verified"
    return Decision("driver_rejected", 0.9, f"driver.{reason}", ex, ["notify_coordinator"],
                    {"note": "Sürücü cihaz doğrulaması BAŞARISIZ — buluşma kodu verilmedi, koordinatör uyarıldı."})


def assess_incoming_call(caller_is_registered_driver: bool, attestation_age_min: float | None, cfg: Config) -> Decision:
    """Hastaya 'sürücü' araması geldi. attestation_age_min: son başarılı sürücü doğrulamasından bu yana dakika (yoksa None)."""
    fresh = attestation_age_min is not None and 0 <= attestation_age_min <= cfg.driver_attestation_ttl_min
    ex = [
        Explain("driver_registry.match", caller_is_registered_driver, 0.5,
                "Arayan numara bu vakaya atanmış sürücünün mü", source="registry", triggered=not caller_is_registered_driver),
        Explain("driver_attestation.age_min", attestation_age_min, 0.5,
                f"Sürücü cihaz doğrulamasının yaşı (geçerlilik {cfg.driver_attestation_ttl_min} dk)", source="number-verification",
                triggered=not fresh),
    ]
    if not caller_is_registered_driver:
        return Decision("impostor", 0.95, "caller.not_registered", ex, ["silent_reject", "warn_patient", "notify_coordinator"],
                        {"note": "Arayan kayıtlı sürücü değil — hastaya 'AÇMAYIN' kartı, koordinatöre uyarı."})
    if not fresh:
        return Decision("unverified", 0.7, "caller.no_fresh_attestation", ex, ["warn_patient", "notify_coordinator"],
                        {"note": "Numara sürücünün ama taze cihaz doğrulaması yok (numara taklidi olabilir) — hastaya "
                                 "'buluşma kodunu duymadan binmeyin' uyarısı."})
    return Decision("genuine", 0.0, "caller.registered_and_attested", ex, ["show_verified_badge", "mark_first_contact"],
                    {"note": "Kayıtlı sürücü + taze cihaz doğrulaması ✓ — ilk temas kuruldu. Buluşmada kod teyit edilir."})


# ---------------------------------------------------------------- 4) ulaşılamama — aynı sinyal, zıt anlam

def assess_unreachable(case_state: str, first_contact_done: bool, minutes_unreachable: float, cfg: Config) -> Decision:
    """Cihaz ulaşılamıyor. İlk temastan ÖNCE → alarm yükselir; SONRA → muhtemel yerel SIM, alarm DÜŞER.

    Dönen Decision.decision ∈ {lower, raise, alarm}; meta.note ekranda gösterilir.
    """
    ex = [
        Explain("reachability.reachable", False, 0.3, "Cihaz şebekede ulaşılamıyor", source="device-reachability-status", triggered=True),
        Explain("case.first_contact_done", first_contact_done, 0.4, "İlk temas (doğrulanmış sürücü / karşılama) tamamlandı mı", source="case"),
        Explain("case.state", case_state, 0.1, "Vaka durumu", source="case"),
        Explain("unreachable.minutes", minutes_unreachable, 0.2, "Ne kadar süredir ulaşılamıyor", source="case"),
    ]
    if case_state in ("closed",):
        return Decision("lower", 0.0, "unreachable.case_closed", ex, [], {"note": "Vaka kapalı — önemsiz.", "level": "lower"})
    if case_state in ("pending_consent", "waiting"):
        # Varıştan önce (uçuşta, telefon kapalı) sessizlik beklenen durumdur; alarm ancak varıştan sonra anlamlıdır
        return Decision("lower", 0.0, "unreachable.before_arrival", ex, [],
                        {"note": "Varıştan ÖNCE sessizlik beklenir (uçuş, telefon kapalı) — alarm yok.", "level": "lower"})
    if not first_contact_done:
        ex[1].triggered = True
        if minutes_unreachable >= cfg.unreachable_before_contact_alert_min:
            return Decision("alarm", 0.9, "unreachable.before_contact_alarm", ex, ["escalate_coordinator", "retry_channel"],
                            {"note": f"İlk temastan ÖNCE {minutes_unreachable:g} dk sessizlik (eşik {cfg.unreachable_before_contact_alert_min}) → ALARM: hasta henüz bağlanmadan kayboldu.", "level": "alarm"})
        return Decision("raise", 0.6, "unreachable.before_contact_raise", ex, ["watch_closely"],
                        {"note": "İlk temastan ÖNCE sessizlik → alarm seviyesi YÜKSELİR, yakın izleme.", "level": "raise"})
    # ilk temas tamam
    ex[1].triggered = True
    if minutes_unreachable <= cfg.unreachable_after_contact_grace_min:
        return Decision("lower", 0.1, "unreachable.after_contact_local_sim", ex, ["fallback_messaging_channel"],
                        {"note": f"İlk temastan SONRA sessizlik → muhtemelen yerel SIM/eSIM aldı. Alarm DÜŞÜRÜLÜR, mesaj kanalına düşülür ({cfg.unreachable_after_contact_grace_min} dk tolerans).", "level": "lower"})
    return Decision("raise", 0.5, "unreachable.after_contact_grace_exceeded", ex, ["ping_messaging_channel", "watch_closely"],
                    {"note": f"Temas sonrası sessizlik {minutes_unreachable:g} dk > {cfg.unreachable_after_contact_grace_min} dk tolerans → seviye YÜKSELİR (yolculuk kontrolüyle birlikte değerlendirilir).", "level": "raise"})


# ---------------------------------------------------------------- 5) yolculuk bütünlüğü

def is_night(hour_of_day: int | None, cfg: Config) -> bool:
    if hour_of_day is None:
        return False
    a, b = cfg.night_start_hour, cfg.night_end_hour
    return a <= hour_of_day < b if a <= b else (hour_of_day >= a or hour_of_day < b)


def journey_check(corridor_events: Iterable[dict], stationary_min: float, off_corridor: bool, cfg: Config,
                  patient_unreachable: bool = False, hour_of_day: int | None = None,
                  known_disruption: dict | None = None) -> Decision:
    """Trafik mi, sorun mu? Kanıt + güven skoru döner (meta.confidence).

    known_disruption: koordinatörün bildirdiği yol kapanması/sapma ({"note": "..."}). Varsa koridor dışı sapma
    beklenen bir alternatif rotayla tutarlıdır → güven `disruption_discount` kadar düşer. Gece saati tek başına
    kararı değiştirmez (gece trafik azdır; hareketsizlik daha anlamlıdır) ama bağlam olarak explain'e yazılır.
    """
    events = list(corridor_events or [])
    lefts = sum(1 for e in events if str(e.get("type", "")).endswith("left") or e.get("type") == "geofence_left")
    ex = [
        Explain("geofence.off_corridor", off_corridor, 0.4, "Araç koridor geofence'inin dışında", source="geofencing-subscriptions", triggered=off_corridor),
        Explain("geofence.left_events", lefts, 0.1, "Koridordan çıkış olayı sayısı", source="geofencing-subscriptions"),
        Explain("journey.stationary_min", stationary_min, 0.3, f"Hareketsiz dakika (eşik {cfg.stationary_minutes_alert})", source="case",
                triggered=stationary_min >= cfg.stationary_minutes_alert),
        Explain("reachability.reachable", not patient_unreachable, 0.2, "Hasta cihazı ulaşılabilir mi", source="device-reachability-status", triggered=patient_unreachable),
    ]
    night = is_night(hour_of_day, cfg)
    if hour_of_day is not None:
        ex.append(Explain("context.hour", hour_of_day, 0.05, "Günün saati (UTC)" + (" — gece aralığı" if night else ""), source="clock", triggered=night))
    discount = 0.0
    if known_disruption:
        discount = cfg.disruption_discount
        ex.append(Explain("context.known_disruption", known_disruption.get("note") or True, 0.2,
                          f"Koordinatörün bildirdiği yol kapanması/sapma → güven −{discount:.0%}", source="coordinator", triggered=True))
    ctx = ""
    if known_disruption:
        ctx = " Bildirilmiş yol kapanmasıyla tutarlı" + (" (gece)" if night else "") + "."

    stationary = stationary_min >= cfg.stationary_minutes_alert
    if off_corridor and stationary and patient_unreachable:
        conf = round(max(0.0, cfg.trouble_confidence_high - discount), 2)
        return Decision("trouble", conf, "journey.off_corridor_stationary_unreachable", ex, ["escalate_coordinator"],
                        {"confidence": conf, "note": f"Koridor dışı, {stationary_min:g} dk hareketsiz, hasta ulaşılamıyor → SORUN (güven {conf:.0%}).{ctx}"})
    if off_corridor and stationary:
        conf = round(max(0.0, cfg.off_corridor_stationary_confidence - discount), 2)
        if known_disruption:  # hasta ulaşılabilir + bilinen kapanma → beklenen alternatif rotada bekleme
            return Decision("probable_traffic", conf, "journey.stationary_explained_by_disruption", ex, ["write_case_note"],
                            {"confidence": conf, "note": f"Koridor dışı ve {stationary_min:g} dk hareketsiz.{ctx} "
                                                         f"Koordinatör UYANDIRILMAZ, vaka notu yazılır (güven {conf:.0%})."})
        return Decision("trouble", conf, "journey.off_corridor_stationary", ex, ["escalate_coordinator"],
                        {"confidence": conf, "note": f"Koridor dışı ve {stationary_min:g} dk hareketsiz → sorun adayı (güven {conf:.0%}); koordinatöre kanıtla iletilir.{ctx}"})
    if off_corridor or stationary:
        conf = round(max(0.0, cfg.off_corridor_confidence_low - discount), 2)
        why = "koridor dışı sapma" if off_corridor else f"{stationary_min:g} dk hareketsiz (koridor üzerinde)"
        return Decision("probable_traffic", conf, "journey.deviation_low_confidence", ex, ["write_case_note"],
                        {"confidence": conf, "note": f"{why.capitalize()} — trafik/detour ile tutarlı (güven {conf:.0%}).{ctx} Koordinatör UYANDIRILMAZ, vaka notu yazılır."})
    return Decision("ok", 0.0, "journey.on_corridor", ex, [], {"confidence": 0.95, "note": "Koridor üzerinde, hareketli → normal."})


# ---------------------------------------------------------------- 6) eskalasyon bütçesi

def escalation_allowed(case: Any, cfg: Config) -> Decision:
    """Vaka başına koordinatör uyandırma bütçesi. case: dict veya .escalations_used alanı olan nesne."""
    used = case.get("escalations_used", 0) if isinstance(case, dict) else getattr(case, "escalations_used", 0)
    ex = [Explain("case.escalations_used", used, 1.0, f"Kullanılan / bütçe: {used}/{cfg.escalation_budget_per_case}", source="case", triggered=used >= cfg.escalation_budget_per_case)]
    if used < cfg.escalation_budget_per_case:
        return Decision("allow", 0.0, "escalation.within_budget", ex, ["escalate"], {"remaining": cfg.escalation_budget_per_case - used - 1})
    return Decision("deny", 0.0, "escalation.budget_exhausted", ex, ["append_to_open_alert"],
                    {"remaining": 0, "note": "Bütçe bitti → yeni bildirim yerine açık uyarıya kanıt eklenir (alarm yorgunluğu önlemi)."})


def should_reescalate(last_escalation_at: Any, now: datetime, cfg: Config) -> bool:
    """Süren bir sorun için koordinatör tekrar uyandırılmalı mı? (zamanlayıcı her tick'te sormaz, aralık bekler)"""
    last = _dt(last_escalation_at)
    if last is None:
        return True
    return (_dt(now) - last) >= timedelta(minutes=cfg.reescalate_after_min)


# ---------------------------------------------------------------- 7) varış sinyali gelmedi / vaka süresi

def destination_eta(itinerary: dict) -> datetime | None:
    dest = _cc(itinerary.get("destination_country"))
    legs = [leg for leg in (itinerary.get("legs") or []) if _cc(leg.get("country")) == dest]
    return _dt(legs[-1].get("eta")) if legs else None


def arrival_overdue(now: datetime, itinerary: dict, cfg: Config) -> Decision:
    """Vaka hâlâ 'waiting' ve hedef ETA + pencere geçti mi? Webhook kaybolmuş olabilir → anlık sorgu + koordinatör notu."""
    eta = destination_eta(itinerary)
    now = _dt(now)
    ex = [Explain("itinerary.destination_eta", eta.isoformat() if eta else None, 0.5, "Hedef bacağın beklenen varış saati", source="itinerary")]
    if eta is None:
        return Decision("on_time", 0.0, "arrival.no_eta", ex, [], {"note": "Itinerary'de hedef ETA yok."})
    late_min = round((now - (eta + timedelta(hours=cfg.arrival_window_h))).total_seconds() / 60)
    ex.append(Explain("arrival.overdue_min", late_min, 0.5, f"Pencere (ETA +{cfg.arrival_window_h:g} sa) sonrası geçen dakika",
                      source="clock", triggered=late_min > 0))
    if late_min > 0:
        return Decision("overdue", 0.5, "arrival.signal_overdue", ex, ["poll_roaming_status", "notify_coordinator"],
                        {"note": f"Varış penceresi {late_min} dk önce kapandı ve roaming olayı gelmedi → anlık roaming sorgusu; "
                                 "sonuç yoksa koordinatör uçuşu teyit eder."})
    return Decision("on_time", 0.0, "arrival.within_window", ex, [], {"note": "Varış penceresi henüz kapanmadı."})


def case_expired(now: datetime, itinerary: dict, cfg: Config) -> bool:
    """Hedef ETA + case_max_hours geçtiyse vaka izlemesi biter (abonelikler silinir, veri minimize edilir)."""
    eta = destination_eta(itinerary)
    return eta is not None and _dt(now) > eta + timedelta(hours=cfg.case_max_hours)


# ---------------------------------------------------------------- 8) rıza kapısı

def consent_gate(app_consent: str, operator_valid: bool | None, capture_url: str | None = None) -> Decision:
    """Hastanın uygulama içi rızası + operatörün Consent Info cevabı → izleme başlasın mı?

    app_consent ∈ {granted, declined, withdrawn}. operator_valid None = sorgu yapılmadı/cevap alınamadı
    (hastanın açık rızası elde olduğu için izleme başlar, ama explain'de "operatör teyidi yok" görünür).
    """
    ex = [
        Explain("consent.patient", app_consent, 0.6, "Hastanın açık rızası (aydınlatma metni onayı)", source="patient", triggered=app_consent != "granted"),
        Explain("consent_info.statusValidForProcessing", operator_valid, 0.4, "Operatör tarafında işleme izni (Consent Info)",
                source="consent-info", triggered=operator_valid is False),
    ]
    if app_consent != "granted":
        return Decision("no_monitoring", 0.0, f"consent.{app_consent}", ex, ["delete_subscriptions", "minimize_data"],
                        {"note": "Hasta rıza vermedi/geri çekti → izleme yok, abonelik yok, koordinatör telefonla ilerler."})
    if operator_valid is False:
        return Decision("await_operator_consent", 0.3, "consent.operator_pending", ex, ["notify_coordinator"],
                        {"note": "Hasta onayladı ama operatör işleme izni vermedi → izleme başlamaz; operatör rıza akışı gerekli.",
                         "capture_url": capture_url})
    return Decision("start_monitoring", 0.0, "consent.granted", ex, ["create_subscriptions"],
                    {"note": "Rıza tamam → roaming, ulaşılabilirlik ve geofence abonelikleri kurulur."
                             + ("" if operator_valid else " (Operatör teyidi alınamadı; hasta rızasıyla ilerlendi.)")})
