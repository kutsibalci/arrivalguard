"""Case durum makinesi — ArrivalGuard ajanının deterministik çekirdeği.

    pending_consent → waiting → arrived → frozen | released → contacted → in_transit → closed
                         │                                  (her aktif durumdan) → escalated
                         └─ declined | withdrawn | expired  (terminal, izleme biter)

`on_event(case, event, now, cfg, nac_facade)` tek giriş noktasıdır. Olay tipleri:
  consent_granted / consent_declined / consent_withdrawn   hastanın rıza kararı (rıza sayfası veya klinik formu)
  roaming_on(country, source)      Device Roaming Status webhook'u / anlık sorgu
  sim_swap_result(swapped, at)     koordinatörün manuel yeniden kontrolü
  driver_verify(device_token)      sürücü KENDİ cihazında Number Verification → taze tasdik + buluşma kodu
  driver_call(caller_phone)        hastaya "sürücü" araması → sicil + taze tasdik kontrolü
  geofence_enter/left(zone)        zone ∈ {airport, corridor, clinic}
  reachability_change(reachable)   Device Reachability webhook'u / anlık sorgu
  tick(stationary_min?, moving?)   zaman ilerledi → süreye bağlı kurallar (zamanlayıcı ya da manuel)
  coordinator_action(action, ...)  uyarı onayı, manuel serbest bırakma, varış teyidi, sürücü değişimi, kapanış, not

Her geçiş `case.timeline`'a yazılır (audit = kliniğin hizmet kanıtı). Nokia çağrıları YALNIZCA
`nac_facade.call(<NacClient metodu>, ...)` ile yapılır; facade yoksa event içindeki veriyle çalışır (test).
Ham telefonlar vaka içinde yalnızca izleme sürerken tutulur; `to_dict()` asla ham numara sızdırmaz,
`purge_pii()` terminal durumda ham numaraları siler (mask + hash kalır).
"""
from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any

from ..nac_client.privacy import hash_phone, mask_phone, normalize_phone
from ..rules import Config, Decision
from ..rules import decisions as R
from ..rules.countries import resolve_country
from .messages import COUNTRY_NAMES, render

STATES = ["pending_consent", "waiting", "arrived", "frozen", "released", "contacted", "in_transit", "escalated",
          "closed", "expired", "declined", "withdrawn"]
TERMINAL_STATES = frozenset({"closed", "expired", "declined", "withdrawn"})
# UI'daki yatay adımlar (aktif adım vurgulanır)
STEP_LABELS = [
    ("consent", "Rıza"), ("waiting", "Bekleniyor"), ("arrived", "Vardı"), ("integrity", "SIM kontrol"),
    ("contacted", "Temas"), ("in_transit", "Yolda"), ("closed", "Kapandı"),
]
# Operatör Consent Info sorgusunda istenen işleme kapsamları (ArrivalGuard'ın kullandığı API'ler)
CONSENT_SCOPES = ["device-roaming-status-subscriptions", "device-reachability-status-subscriptions",
                  "geofencing-subscriptions", "sim-swap", "location-verification"]
CONSENT_PURPOSE = "dpv:ServiceProvision"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _contact_public(contact: dict | None) -> dict | None:
    """Sürücü/aile kişisinin dışa açık hali: ham numara yok, mask + hash."""
    if not contact:
        return None
    out = {k: v for k, v in contact.items() if k != "phone"}
    p = contact.get("phone")
    if p:
        out["phone_masked"], out["phone_hash"] = mask_phone(p), hash_phone(p)
    return out


# ---------------------------------------------------------------- veri modeli
@dataclass
class Event:
    type: str
    data: dict = field(default_factory=dict)


@dataclass
class Case:
    id: str
    clinic_id: str
    clinic_name: str
    patient_name: str
    patient_phone: str | None               # ham — sadece NaC çağrıları ve bildirim için; purge_pii() siler
    language: str
    itinerary: dict                         # {"legs":[{"country":974,"eta":"..."}], "destination_country":90}
    driver: dict                            # {"id","name","plate","phone"} (ham telefon; dışarı mask/hash)
    zones: dict = field(default_factory=dict)  # {"airport":{lat,lng,radius,label}, "corridor":{...}, "clinic":{...}}
    family_contact: dict | None = None      # {"name","phone","language"}
    meeting_point: str = "Uluslararası Gelişler — Kapı 3"
    state: str = "pending_consent"
    consent: dict = field(default_factory=lambda: {"status": "pending"})
    consent_token: str | None = None        # rıza bağlantısının sırrı — to_dict() dönmez
    driver_token: str | None = None         # sürücü doğrulama bağlantısının sırrı — to_dict() dönmez
    public_base_url: str = ""               # rıza/sürücü bağlantılarının taban adresi
    subscribe: bool = True                  # rıza sonrası Nokia abonelikleri kurulsun mu (test/manuel akış için kapatılabilir)
    integrity: str | None = None            # frozen | released | released_manual
    arrived_at: str | None = None
    first_contact_at: str | None = None
    closed_at: str | None = None
    unreachable_since: str | None = None
    last_move_at: str | None = None
    off_corridor: bool = False
    corridor_events: list = field(default_factory=list)
    driver_verified_at: str | None = None
    meeting_code: str | None = None         # yüz yüze teyit kodu — to_dict() dönmez
    known_disruption: dict | None = None    # koordinatörün bildirdiği yol kapanması
    arrival_overdue_noted: bool = False
    escalations_used: int = 0
    last_escalation_at: str | None = None
    tick_marks: dict = field(default_factory=dict)   # zamanlayıcı tekrar kaydını önler: {"unreachable": rule, "journey": rule}
    alerts: list = field(default_factory=list)
    timeline: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    subscriptions: dict = field(default_factory=dict)   # {"roaming:roaming-on": id, "geofence:airport": id, ...}
    subscriptions_deleted: bool = False
    deleted_subscriptions: list = field(default_factory=list)
    last_decision: dict | None = None
    summary: str | None = None              # isteğe bağlı LLM özeti (karar değil)
    phone_masked: str | None = None
    phone_hash: str | None = None
    pii_purged_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if self.patient_phone:
            self.patient_phone = normalize_phone(self.patient_phone)
            self.phone_masked = self.phone_masked or mask_phone(self.patient_phone)
            self.phone_hash = self.phone_hash or hash_phone(self.patient_phone)

    # ---- gizlilik ----
    @property
    def patient_phone_hash(self) -> str | None:
        return self.phone_hash

    @property
    def patient_phone_masked(self) -> str | None:
        return self.phone_masked

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def monitoring(self) -> bool:
        """Şebeke izlemesi (abonelikler) sürmeli mi?"""
        return self.state not in TERMINAL_STATES and self.state != "pending_consent"

    def driver_public(self) -> dict:
        return _contact_public(self.driver) or {}

    def family_public(self) -> dict | None:
        return _contact_public(self.family_contact)

    def purge_pii(self, now: datetime) -> None:
        """Terminal durumda ham numaraları ve sırları siler; mask/hash ve audit kalır (veri minimizasyonu)."""
        if self.pii_purged_at:
            return
        for contact in (self.driver, self.family_contact):
            if contact and contact.get("phone"):
                contact["phone_masked"], contact["phone_hash"] = mask_phone(contact["phone"]), hash_phone(contact["phone"])
                contact.pop("phone")
        self.patient_phone = None
        self.consent_token = None
        self.driver_token = None
        self.meeting_code = None
        self.pii_purged_at = _iso(now)

    @property
    def step_index(self) -> int:
        """UI adımı: consent/waiting/arrived/integrity/contacted/in_transit/closed."""
        s = self.state
        if s in ("pending_consent", "declined", "withdrawn"):
            return 0
        if s in ("frozen", "released"):
            return 3
        if s == "escalated":
            return 5 if self.first_contact_at else 3
        if s == "expired":
            return 6
        return {"waiting": 1, "arrived": 2, "contacted": 4, "in_transit": 5, "closed": 6}.get(s, 1)

    def to_dict(self) -> dict:
        """Dışa açık görünüm — ham numara, rıza token'ı ve buluşma kodu YOK."""
        return {
            "id": self.id, "clinic_id": self.clinic_id, "clinic_name": self.clinic_name,
            "patient": {"name": self.patient_name, "phone_masked": self.phone_masked, "phone_hash": self.phone_hash, "language": self.language},
            "itinerary": self.itinerary, "driver": self.driver_public(), "family_contact": self.family_public(),
            "zones": self.zones, "meeting_point": self.meeting_point,
            "state": self.state, "step_index": self.step_index, "integrity": self.integrity,
            "consent": dict(self.consent),
            "arrived_at": self.arrived_at, "first_contact_at": self.first_contact_at, "closed_at": self.closed_at,
            "unreachable_since": self.unreachable_since, "off_corridor": self.off_corridor,
            "driver_verified_at": self.driver_verified_at, "meeting_code_issued": bool(self.meeting_code) or any(
                m.get("kind") == "driver_verified" for m in self.messages),
            "known_disruption": self.known_disruption,
            "escalations_used": self.escalations_used, "alerts": self.alerts, "timeline": self.timeline,
            "messages": [_public_message(m) for m in self.messages], "subscriptions": self.subscriptions,
            "subscriptions_deleted": self.subscriptions_deleted, "last_decision": self.last_decision,
            "summary": self.summary, "pii_purged_at": self.pii_purged_at,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    # ---- kalıcılık ----
    def to_record(self) -> dict:
        """Depolama için TAM kayıt (ham numaralar dahil — yalnızca store'a gider)."""
        return asdict(self)

    @classmethod
    def from_record(cls, rec: dict) -> Case:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in rec.items() if k in known})


def _public_message(m: dict) -> dict:
    """Mesajın dışa açık hali: buluşma kodu ve bağlantı token'ları koordinatör ekranında da maskelenir."""
    out = {k: v for k, v in m.items() if k != "secrets"}
    text = str(m.get("text", ""))
    for secret in m.get("secrets") or []:
        if secret:
            text = text.replace(secret, "••••")
    out["text"] = text
    return out


# ---------------------------------------------------------------- yardımcılar (yan etkiler vakaya yazılır)
def _record(case: Case, now: datetime, event: str, frm: str, to: str, decision: Decision | None, note: str = "",
            extra: dict | None = None) -> dict:
    entry = {
        "seq": len(case.timeline) + 1, "t": _iso(now), "event": event, "from": frm, "to": to,
        "decision": decision.decision if decision else None, "rule": decision.rule if decision else None,
        "note": note or (decision.meta.get("note") if decision else ""),
        "explain": [e.to_dict() for e in decision.explain] if decision else [],
        "actions": list(decision.actions) if decision else [],
        "confidence": decision.meta.get("confidence") if decision else None,
    }
    if extra:
        entry.update(extra)
    case.timeline.append(entry)
    case.updated_at = _iso(now)
    if decision:
        case.last_decision = decision.to_dict()
    return entry


def _ephemeral(case: Case, now: datetime, event: str, note: str) -> dict:
    """Kaydedilmeyen sonuç (ör. zamanlayıcı tick'inde değişiklik yok) — audit'i şişirmez."""
    return {"seq": None, "t": _iso(now), "event": event, "from": case.state, "to": case.state, "decision": None,
            "rule": None, "note": note, "explain": [], "actions": [], "confidence": None, "recorded": False}


def driver_link(case: Case) -> str:
    """Sürücünün kendi cihazında (mobil veriyle) açacağı doğrulama bağlantısı."""
    return f"{case.public_base_url.rstrip('/')}/driver/{case.driver_token}" if case.driver_token else ""


def consent_link(case: Case) -> str:
    """Hastanın rıza/geri çekme bağlantısı."""
    return f"{case.public_base_url.rstrip('/')}/consent/{case.consent_token}" if case.consent_token else ""


def _msg(case: Case, now: datetime, to: str, kind: str, text: str, lang: str | None = None, channel: str = "sms",
         secrets_: list | None = None) -> dict:
    """Giden mesajı vakanın outbox'ına yazar (status=queued). Gönderimi api/notify.py yapar."""
    m = {"id": f"{case.id}-m{len(case.messages) + 1}", "t": _iso(now), "case_id": case.id, "to": to, "kind": kind,
         "lang": lang or case.language, "channel": channel, "text": text, "status": "queued", "attempts": 0}
    hidden = [x for x in (secrets_ or []) if x] + [t for t in (case.consent_token, case.driver_token) if t and t in text]
    if hidden:
        m["secrets"] = hidden
    if to == "patient":
        m["to_masked"] = case.phone_masked
    elif to in ("family", "driver"):
        contact = case.family_contact if to == "family" else case.driver
        p = (contact or {}).get("phone")
        m["to_masked"] = mask_phone(p) if p else (contact or {}).get("phone_masked")
    case.messages.append(m)
    return m


def _fmt(case: Case, key: str, lang: str | None = None, **kw) -> str:
    dest_cc = case.itinerary.get("destination_country")
    try:
        dest = COUNTRY_NAMES.get(int(dest_cc or 0), str(dest_cc))
    except (TypeError, ValueError):
        dest = str(dest_cc)
    base = dict(name=case.patient_name, driver=case.driver.get("name", "-"), plate=case.driver.get("plate", "-"),
                meeting=case.meeting_point, clinic=case.clinic_name, dest=dest, code=case.meeting_code or "----", link="")
    base.update(kw)
    return render(lang or case.language, key, **base)


def _alert(case: Case, now: datetime, level: str, title: str, decision: Decision | None, note: str = "") -> dict:
    return {"id": f"al-{len(case.alerts) + 1}", "t": _iso(now), "level": level, "title": title,
            "note": note or (decision.meta.get("note") if decision else ""),
            "confidence": decision.meta.get("confidence") if decision else None,
            "explain": [e.to_dict() for e in decision.explain] if decision else [], "budget": None,
            "acknowledged_at": None, "acknowledged_by": None}


def _escalate(case: Case, now: datetime, cfg: Config, level: str, title: str, decision: Decision | None, note: str = "") -> dict:
    """Koordinatöre uyarı. level ∈ {info, warn, alarm}. alarm seviyesi eskalasyon bütçesine tabidir."""
    alert = _alert(case, now, level, title, decision, note)
    if level == "alarm":
        gate = R.escalation_allowed(case, cfg)
        if gate.decision == "allow":
            case.escalations_used += 1
            case.last_escalation_at = _iso(now)
            alert["budget"] = f"{case.escalations_used}/{cfg.escalation_budget_per_case}"
            case.alerts.append(alert)
            _msg(case, now, "coordinator", "escalation", f"[{case.id}] {title} — {alert['note']}", lang="tr", channel="push")
        else:
            alert["level"] = "warn"
            alert["title"] = f"{title} (bütçe doldu → açık uyarıya eklendi)"
            alert["budget"] = f"{case.escalations_used}/{cfg.escalation_budget_per_case}"
            case.last_escalation_at = _iso(now)
            case.alerts.append(alert)
        _record(case, now, "escalation_gate", case.state, case.state, gate, extra={"alert_level": alert["level"], "alert_id": alert["id"]})
    else:
        case.alerts.append(alert)
        _msg(case, now, "coordinator", level, f"[{case.id}] {title} — {alert['note']}", lang="tr", channel="console")
    return alert


def _nac(nac_facade, name: str, *args, **kw):
    """Facade üzerinden NaC çağrısı; facade yoksa None."""
    if nac_facade is None:
        return None
    return nac_facade.call(name, *args, **kw)


def _set_state(case: Case, to: str) -> str:
    frm = case.state
    case.state = to
    return frm


def request_consent(case: Case, now: datetime) -> dict:
    """Hastaya rıza bağlantısını gönderir (outbox) ve audit'e yazar. İzleme rıza gelene kadar başlamaz."""
    _msg(case, now, "patient", "consent_request", _fmt(case, "consent_request", link=consent_link(case)))
    return _record(case, now, "consent_requested", case.state, case.state, None,
                   note=f"Rıza bağlantısı hastaya gönderildi (metin sürümü {case.consent.get('text_version')}). İzleme onaydan sonra başlar.")


# ---------------------------------------------------------------- tek giriş
def on_event(case: Case, event: Event | dict, now: datetime | str, cfg: Config, nac_facade=None) -> dict:
    """Tek olay işler; timeline'a yazar; işlenen son timeline girdisini (dict) döner."""
    if isinstance(event, dict):
        event = Event(event.get("type", ""), {k: v for k, v in event.items() if k not in ("type", "data")} | (event.get("data") or {}))
    now = _dt(now)
    if case.created_at is None:
        case.created_at = _iso(now)
    handler = _HANDLERS.get(event.type)
    if handler is None:
        return _record(case, now, event.type, case.state, case.state, None, note=f"bilinmeyen olay tipi: {event.type}")
    if case.terminal and event.type not in ("tick", "coordinator_action"):
        return _record(case, now, event.type, case.state, case.state, None, note=f"Vaka {case.state} — olay yalnızca audit'e eklendi.",
                       extra=_src(event))
    if case.state == "pending_consent" and event.type not in _PRE_CONSENT_EVENTS:
        return _record(case, now, event.type, case.state, case.state, None,
                       note="Rıza alınmadan şebeke olayı işlenmez — olay yalnızca audit'e eklendi.", extra=_src(event))
    return handler(case, event, now, cfg, nac_facade)


def _src(ev: Event) -> dict:
    out = {}
    if ev.data.get("source"):
        out["source"] = ev.data["source"]
    if ev.data.get("actor"):
        out["actor"] = ev.data["actor"]
    return out


# ---------------------------------------------------------------- rıza
def _h_consent(case: Case, ev: Event, now: datetime, cfg: Config, nac) -> dict:
    status = {"consent_granted": "granted", "consent_declined": "declined", "consent_withdrawn": "withdrawn"}[ev.type]
    if status in ("granted", "declined") and case.state != "pending_consent":
        return _record(case, now, ev.type, case.state, case.state, None,
                       note="Rıza kararı zaten verilmiş (izleme sürerken vazgeçmek için: geri çekme).", extra=_src(ev))
    operator_valid, capture_url, src = None, None, "not-checked"
    if status == "granted" and cfg.operator_consent_check and nac is not None and case.patient_phone:
        r = _nac(nac, "consent", case.patient_phone, CONSENT_SCOPES, CONSENT_PURPOSE)
        info = (r.data or {}).get("statusInfo") if isinstance(r.data, dict) else None
        if info:
            operator_valid = all(i.get("statusValidForProcessing") for i in info)
            capture_url = r.data.get("captureUrl")
        src = r.source
    d = R.consent_gate(status, operator_valid, capture_url)
    for e in d.explain:
        if e.signal.startswith("consent_info"):
            e.source = src if src != "not-checked" else "consent-info (sorgulanmadı)"
    case.consent = {**case.consent, "status": status, "at": _iso(now),
                    "method": ev.data.get("method", case.consent.get("method")),
                    "text_version": ev.data.get("text_version", case.consent.get("text_version")),
                    "operator_valid": operator_valid}
    link = consent_link(case)
    if d.decision == "start_monitoring":
        frm = _set_state(case, "waiting")
        entry = _record(case, now, ev.type, frm, "waiting", d, extra=_src(ev))
        if ev.data.get("notify_patient", True):
            _msg(case, now, "patient", "consent_granted", _fmt(case, "consent_granted", link=link))
        return entry
    if d.decision == "await_operator_consent":
        case.consent["status"] = "operator_pending"
        entry = _record(case, now, ev.type, case.state, case.state, d, extra=_src(ev))
        _escalate(case, now, cfg, "warn", "Operatör rızası eksik — izleme başlamadı", d)
        return entry
    frm = _set_state(case, status)
    entry = _record(case, now, ev.type, frm, status, d, extra=_src(ev))
    _msg(case, now, "patient", f"consent_{status}", _fmt(case, f"consent_{status}"))
    if status == "withdrawn":
        _escalate(case, now, cfg, "info", "Hasta rızasını geri çekti — izleme durduruldu", d)
    return entry


# ---------------------------------------------------------------- varış
def _h_roaming_on(case: Case, ev: Event, now: datetime, cfg: Config, nac) -> dict:
    country = ev.data.get("country") or ev.data.get("countryCode")
    src = ev.data.get("source", "webhook")
    d = R.classify_roaming_event(country, case.itinerary, now, cfg)
    for e in d.explain:
        if e.signal == "roaming.countryCode":
            e.source = f"device-roaming-status/{src}"
    if d.decision == "transit":
        entry = _record(case, now, "roaming_on", case.state, case.state, d, extra=_src(ev))
        if not any(m["kind"] == "transit_greeting" for m in case.messages):
            _msg(case, now, "patient", "transit_greeting", _fmt(case, "transit", country=COUNTRY_NAMES.get(int(country), str(country))))
        return entry
    if d.decision == "unexpected":
        entry = _record(case, now, "roaming_on", case.state, case.state, d, extra=_src(ev))
        _escalate(case, now, cfg, "warn", "Beklenmeyen roaming olayı", d)
        return entry
    if case.state != "waiting":
        return _record(case, now, "roaming_on", case.state, case.state, d, note="Varış zaten işlendi (tekrar eden roaming olayı).", extra=_src(ev))
    return _arrive(case, now, cfg, nac, d, "roaming_on", ev)


def _arrive(case: Case, now: datetime, cfg: Config, nac, d: Decision | None, event_name: str, ev: Event) -> dict:
    frm = _set_state(case, "arrived")
    case.arrived_at = _iso(now)
    case.last_move_at = _iso(now)
    case.unreachable_since = None  # şebekeye bağlandı: uçuştaki sessizlik varış sonrası sayaca taşınmaz
    case.tick_marks.pop("unreachable", None)
    _record(case, now, event_name, frm, "arrived", d, note="" if d else "Koordinatör varışı teyit etti.", extra=_src(ev))
    # isteğe bağlı buluşma noktası spot kontrolü (Location Verification — koordinat değil, hüküm)
    ap = case.zones.get("airport")
    if nac is not None and ap and case.patient_phone:
        try:
            lv = _nac(nac, "location_verify", case.patient_phone, ap["lat"], ap["lng"], ap.get("radius", 2000))
            _record(case, now, "location_verify", "arrived", "arrived", None,
                    note=f"Buluşma noktası spot kontrolü: {lv.data.get('verificationResult')} (koordinat saklanmaz)",
                    extra={"explain": [{"signal": "location_verification.verificationResult", "value": lv.data.get("verificationResult"), "weight": 0.1,
                                        "note": "Hasta buluşma noktası çevresinde mi — sadece hüküm", "source": lv.source, "triggered": False}]})
        except Exception as e:  # noqa: BLE001 — spot kontrol kritik değil
            _record(case, now, "location_verify", "arrived", "arrived", None, note=f"Spot kontrol atlandı: {e}")
    return _integrity(case, now, cfg, nac, ev.data.get("sim_swapped"), ev.data.get("sim_swap_at"), trigger="arrival")


def _integrity(case: Case, now: datetime, cfg: Config, nac, swapped, swap_at, trigger: str) -> dict:
    src_check = src_date = "event"
    if nac is not None and case.patient_phone:
        chk = _nac(nac, "sim_swap_check", case.patient_phone, cfg.sim_swap_freeze_window_h)
        dt_ = _nac(nac, "sim_swap_date", case.patient_phone)
        swapped = bool(chk.data.get("swapped")) if chk.data else None
        swap_at = dt_.data.get("latestSimChange") if dt_.data else None
        src_check, src_date = chk.source, dt_.source
    d = R.integrity_gate(swapped, swap_at, cfg, now=now)
    for e in d.explain:
        e.source = src_check if e.signal == "sim_swap.swapped" else src_date
    frm = case.state
    if d.decision == "withhold_pickup":
        case.state = "frozen"
        case.integrity = "frozen"
        entry = _record(case, now, f"sim_swap_check[{trigger}]", frm, "frozen", d)
        _msg(case, now, "patient", "welcome_frozen", _fmt(case, "frozen"))
        _escalate(case, now, cfg, "alarm", "SIM değişimi tespit edildi — pickup detayları bekletiliyor", d)
        return entry
    return _release(case, now, d, f"sim_swap_check[{trigger}]", frm, integrity="released")


def _release(case: Case, now: datetime, d: Decision | None, event_name: str, frm: str, integrity: str, extra: dict | None = None) -> dict:
    case.state = "released"
    case.integrity = integrity
    entry = _record(case, now, event_name, frm, "released", d, note="" if d else "Koordinatör pickup detaylarını manuel serbest bıraktı.", extra=extra)
    _msg(case, now, "patient", "welcome_pickup", _fmt(case, "welcome"))
    if case.driver_token and not case.driver_verified_at and not any(m["kind"] == "driver_link" for m in case.messages):
        _msg(case, now, "driver", "driver_link", _fmt(case, "driver_link", lang="tr", link=driver_link(case)), lang="tr")
    if case.meeting_code and _attestation_age(case, now) is not None:
        _send_meeting_code(case, now)  # sürücü hastadan önce doğrulanmışsa kod şimdi gider
    return entry


def _h_sim_swap_result(case: Case, ev: Event, now: datetime, cfg: Config, nac) -> dict:
    if case.state not in ("arrived", "frozen"):
        return _record(case, now, "sim_swap_result", case.state, case.state, None, note="Bütünlük kapısı bu durumda uygulanmaz.")
    # dış sonuç verildiyse facade'ı atla (koordinatör manuel yeniden kontrol vb.)
    external = "swapped" in ev.data or "sim_swapped" in ev.data
    return _integrity(case, now, cfg, None if external else nac,
                      ev.data.get("swapped", ev.data.get("sim_swapped")), ev.data.get("sim_swap_at"), trigger="recheck")


# ---------------------------------------------------------------- sürücü doğrulama
def _attestation_age(case: Case, now: datetime) -> float | None:
    if not case.driver_verified_at:
        return None
    return round((now - _dt(case.driver_verified_at)).total_seconds() / 60, 1)


def _send_meeting_code(case: Case, now: datetime) -> None:
    if any(m["kind"] == "driver_verified" for m in case.messages):
        return
    _msg(case, now, "patient", "driver_verified", _fmt(case, "driver_verified"), channel="sms", secrets_=[case.meeting_code])


def _h_driver_verify(case: Case, ev: Event, now: datetime, cfg: Config, nac) -> dict:
    """Sürücü kendi cihazında doğrulama bağlantısını açtı → Number Verification (cihazın hattı = kayıtlı sürücü mü?)."""
    claimed = ev.data.get("phone") or case.driver.get("phone") or ""
    try:
        claimed_n = normalize_phone(claimed)
    except ValueError:
        claimed_n = None
    registered = bool(claimed_n and case.driver.get("phone") and hash_phone(claimed_n) == hash_phone(case.driver["phone"]))
    verified = ev.data.get("number_verified")
    src = "event"
    if nac is not None and claimed_n:
        r = _nac(nac, "number_verify", claimed_n, device_token=ev.data.get("device_token"))
        verified = bool(r.data.get("devicePhoneNumberVerified")) if r.data else None
        src = r.source
    d = R.authenticate_driver_device(verified, registered)
    for e in d.explain:
        if e.signal.startswith("number_verification"):
            e.source = src
    masked = mask_phone(claimed_n) if claimed_n else "***"
    extra = {"driver_masked": masked, **_src(ev), **({"method": ev.data["method"]} if ev.data.get("method") else {})}
    if d.decision == "driver_verified":
        case.driver_verified_at = _iso(now)
        if not case.meeting_code:
            case.meeting_code = f"{secrets.randbelow(10000):04d}"
        entry = _record(case, now, "driver_verify", case.state, case.state, d, extra=extra)
        _msg(case, now, "driver", "driver_code", _fmt(case, "driver_code", lang="tr"), lang="tr", secrets_=[case.meeting_code])
        if case.integrity in ("released", "released_manual"):
            _send_meeting_code(case, now)
        else:
            entry["note"] += " Hastaya kod, pickup detayları serbest bırakıldığında gönderilecek."
        return entry
    entry = _record(case, now, "driver_verify", case.state, case.state, d, extra=extra)
    _escalate(case, now, cfg, "warn", f"Sürücü cihaz doğrulaması başarısız ({masked})", d)
    return entry


def _h_driver_call(case: Case, ev: Event, now: datetime, cfg: Config, nac) -> dict:
    caller = ev.data.get("caller_phone", "")
    try:
        caller_n = normalize_phone(caller)
    except ValueError:
        caller_n = None
    registered = bool(caller_n and case.driver.get("phone") and hash_phone(caller_n) == hash_phone(case.driver["phone"]))
    d = R.assess_incoming_call(registered, _attestation_age(case, now), cfg)
    masked = mask_phone(caller_n) if caller_n else "***"
    extra = {"caller_masked": masked, **_src(ev)}
    if d.decision == "genuine" and case.state == "frozen":
        # SIM'i yeni değişmiş hat saldırganın elinde olabilir: sürücü doğru kişi olsa da karşısındaki hasta olmayabilir
        entry = _record(case, now, "driver_call", case.state, case.state, d, extra=extra,
                        note="Doğrulanmış sürücü aradı AMA vaka dondurulmuş (SIM değişimi) — ilk temas sayılmaz; "
                             "koordinatör hastanın hattını teyit edip manuel serbest bırakmalı.")
        _escalate(case, now, cfg, "warn", "Dondurulmuş vakada sürücü araması", d, note=entry["note"])
        return entry
    if d.decision == "genuine":
        frm = case.state
        if case.state in ("arrived", "released"):
            case.state = "contacted"
        if not case.first_contact_at:
            case.first_contact_at = _iso(now)
        entry = _record(case, now, "driver_call", frm, case.state, d, extra=extra)
        _msg(case, now, "patient", "call_verified", _fmt(case, "driver_ok"), channel="call-screen", secrets_=[case.meeting_code])
        return entry
    entry = _record(case, now, "driver_call", case.state, case.state, d, extra=extra)
    if d.decision == "impostor":
        _msg(case, now, "patient", "call_rejected", _fmt(case, "driver_bad"), channel="call-screen")
        _escalate(case, now, cfg, "warn", f"Sahte sürücü araması reddedildi ({masked})", d)
    else:
        _msg(case, now, "patient", "call_unverified", _fmt(case, "driver_unverified"), channel="call-screen")
        _escalate(case, now, cfg, "warn", f"Doğrulanmamış 'sürücü' araması ({masked}) — numara taklidi olabilir", d)
    return entry


# ---------------------------------------------------------------- yolculuk
def _journey(case: Case, now: datetime, cfg: Config, stationary: float, off_corridor: bool) -> Decision:
    return R.journey_check(case.corridor_events, round(float(stationary), 1), off_corridor, cfg,
                           patient_unreachable=bool(case.unreachable_since), hour_of_day=now.hour,
                           known_disruption=case.known_disruption)


def _h_geofence_enter(case: Case, ev: Event, now: datetime, cfg: Config, nac) -> dict:
    zone = ev.data.get("zone", "?")
    case.corridor_events.append({"t": _iso(now), "type": "geofence_enter", "zone": zone})
    case.last_move_at = _iso(now)
    frm = case.state
    if zone == "clinic":
        case.state = "closed"
        case.closed_at = _iso(now)
        d = Decision("close_case", 0.0, "geofence.clinic_entered",
                     [R.Explain("geofence.area-entered", "clinic", 1.0, "Klinik geofence'ine giriş", source="geofencing-subscriptions", triggered=True)],
                     ["close_case", "write_audit", "notify_family", "delete_subscriptions"],
                     {"note": "Klinik kapısı → vaka KAPANDI, audit yazıldı, abonelikler silinir."})
        entry = _record(case, now, "geofence_enter", frm, "closed", d, extra=_src(ev))
        _msg(case, now, "patient", "closed", _fmt(case, "closed"))
        if case.family_contact:
            fl = case.family_contact.get("language", "tr")
            _msg(case, now, "family", "arrived_safely", _fmt(case, "family", lang=fl, time=now.strftime("%H:%M UTC")), lang=fl)
        return entry
    if zone == "corridor":
        case.off_corridor = False
        if case.state in ("contacted", "escalated") and case.first_contact_at:
            case.state = "in_transit"
        d = _journey(case, now, cfg, 0, False)
        case.tick_marks["journey"] = d.rule
        return _record(case, now, "geofence_enter", frm, case.state, d,
                       note="Koridora giriş — transfer başladı." if frm != case.state else d.meta.get("note"), extra=_src(ev))
    if zone == "airport":
        return _record(case, now, "geofence_enter", frm, case.state, None, note="Havalimanı geofence'ine giriş (buluşma noktası).", extra=_src(ev))
    return _record(case, now, "geofence_enter", frm, case.state, None, note=f"Bölgeye giriş: {zone}", extra=_src(ev))


def _h_geofence_left(case: Case, ev: Event, now: datetime, cfg: Config, nac) -> dict:
    zone = ev.data.get("zone", "?")
    case.corridor_events.append({"t": _iso(now), "type": "geofence_left", "zone": zone})
    frm = case.state
    if zone == "airport":
        if case.state == "contacted":
            case.state = "in_transit"
        case.last_move_at = _iso(now)
        return _record(case, now, "geofence_left", frm, case.state, None, note="Havalimanından ayrıldı — transfer başladı.", extra=_src(ev))
    if zone == "corridor":
        case.off_corridor = True
        d = _journey(case, now, cfg, float(ev.data.get("stationary_min", 0)), True)
        case.tick_marks["journey"] = d.rule
        entry = _record(case, now, "geofence_left", frm, case.state, d, extra=_src(ev))
        if d.decision == "trouble":
            case.state = "escalated"
            entry["to"] = "escalated"
            _escalate(case, now, cfg, "alarm", "Yolculuk sorunu", d)
        return entry
    return _record(case, now, "geofence_left", frm, case.state, None, note=f"Bölgeden çıkış: {zone}", extra=_src(ev))


# ---------------------------------------------------------------- ulaşılabilirlik
def _h_reachability(case: Case, ev: Event, now: datetime, cfg: Config, nac) -> dict:
    reachable = ev.data.get("reachable")
    if reachable is None and nac is not None and case.patient_phone:
        r = _nac(nac, "reachability", case.patient_phone)
        reachable = bool(r.data.get("reachable")) if r.data else None
    frm = case.state
    if reachable is None:
        return _record(case, now, "reachability_change", frm, case.state, None,
                       note="Ulaşılabilirlik bilinmiyor (şebeke sorgusu cevapsız) — durum değiştirilmedi.", extra=_src(ev))
    if reachable:
        case.unreachable_since = None
        case.tick_marks.pop("unreachable", None)
        return _record(case, now, "reachability_change", frm, case.state, None, note="Cihaz yeniden ulaşılabilir.", extra=_src(ev))
    if case.state in ("pending_consent", "waiting"):
        d = R.assess_unreachable(case.state, False, 0.0, cfg)  # varış öncesi: kayıt, sayaç başlamaz
        return _record(case, now, "reachability_change", frm, case.state, d, extra=_src(ev))
    if not case.unreachable_since:
        case.unreachable_since = _iso(now)
    minutes = (now - _dt(case.unreachable_since)).total_seconds() / 60
    d = R.assess_unreachable(case.state, bool(case.first_contact_at), round(minutes, 1), cfg)
    entry = _record(case, now, "reachability_change", frm, case.state, d, extra=_src(ev))
    _apply_unreachable_level(case, now, cfg, d, first=case.tick_marks.get("unreachable") != d.rule)
    case.tick_marks["unreachable"] = d.rule
    return entry


def _apply_unreachable_level(case: Case, now: datetime, cfg: Config, d: Decision, first: bool) -> None:
    lvl = d.decision
    if lvl == "lower":
        if d.rule == "unreachable.after_contact_local_sim" and not any(m["kind"] == "local_sim_fallback" for m in case.messages):
            _msg(case, now, "patient", "local_sim_fallback", _fmt(case, "local_sim"), channel="messaging")
    elif lvl == "alarm":
        if case.state != "escalated":
            frm = _set_state(case, "escalated")
            _record(case, now, "state_change", frm, "escalated", None, note="Ulaşılamama alarmı → eskalasyon.")
        if first or R.should_reescalate(case.last_escalation_at, now, cfg):
            _escalate(case, now, cfg, "alarm", "Hasta ilk temastan önce ulaşılamıyor", d)
    elif first:  # raise — yalnızca seviye ilk kez yükseldiğinde bilgi notu
        _escalate(case, now, cfg, "info", "Ulaşılamama — seviye yükseltildi", d)


# ---------------------------------------------------------------- zaman
def _h_tick(case: Case, ev: Event, now: datetime, cfg: Config, nac) -> dict:
    """Zaman ilerledi: süreye bağlı kuralları yeniden değerlendir.

    source="scheduler" olan tick'ler yalnızca bir şey DEĞİŞTİĞİNDE audit'e yazılır (kural değişti, eskalasyon
    yapıldı). Manuel/demo tick'leri her zaman yazılır. Eskalasyon politikası ikisinde de aynıdır: süren bir
    sorun için koordinatör en erken `reescalate_after_min` dakika sonra tekrar uyandırılır (bütçeye tabi).
    """
    quiet = ev.data.get("source") == "scheduler"
    if case.terminal:
        return _ephemeral(case, now, "tick", f"Vaka {case.state} — zaman kuralı yok.")
    if case.state == "pending_consent" and not R.case_expired(now, case.itinerary, cfg):
        return _ephemeral(case, now, "tick", "Rıza bekleniyor — izleme yok.")
    if R.case_expired(now, case.itinerary, cfg):
        frm = _set_state(case, "expired")
        case.closed_at = _iso(now)
        entry = _record(case, now, "tick", frm, "expired", None,
                        note=f"Hedef ETA + {cfg.case_max_hours} sa geçti → vaka süresi doldu; abonelikler silinir, veri minimize edilir.",
                        extra=_src(ev))
        _escalate(case, now, cfg, "warn", "Vaka süresi doldu (klinikte kapanış olmadı)", None,
                  note="Hasta klinik alanına girmeden izleme süresi bitti — koordinatör hastanın durumunu teyit etmeli.")
        return entry
    last: dict | None = None
    if case.state == "waiting":
        last = _tick_waiting(case, ev, now, cfg, nac)
    if case.unreachable_since:
        minutes = round((now - _dt(case.unreachable_since)).total_seconds() / 60, 1)
        d = R.assess_unreachable(case.state, bool(case.first_contact_at), minutes, cfg)
        changed = case.tick_marks.get("unreachable") != d.rule
        due = d.decision == "alarm" and R.should_reescalate(case.last_escalation_at, now, cfg)
        if not quiet or changed or due:
            last = _record(case, now, "tick", case.state, case.state, d, extra=_src(ev))
            _apply_unreachable_level(case, now, cfg, d, first=changed)
            last["to"] = case.state
        case.tick_marks["unreachable"] = d.rule
    if case.state in ("in_transit", "escalated") and case.first_contact_at:
        stationary = ev.data.get("stationary_min")
        if ev.data.get("moving"):
            case.last_move_at = _iso(now)
            stationary = 0
        if stationary is None:
            stationary = (now - _dt(case.last_move_at)).total_seconds() / 60 if case.last_move_at else 0
        d = _journey(case, now, cfg, stationary, case.off_corridor)
        changed = case.tick_marks.get("journey") != d.rule
        due = d.decision == "trouble" and R.should_reescalate(case.last_escalation_at, now, cfg)
        if not quiet or changed or due:
            last = _record(case, now, "tick", case.state, case.state, d, extra=_src(ev))
            if d.decision == "trouble" and case.state != "escalated":
                case.state = "escalated"
                last["to"] = "escalated"
                _escalate(case, now, cfg, "alarm", "Yolculuk sorunu", d)
            elif d.decision == "trouble" and (changed or due):
                _escalate(case, now, cfg, "alarm", "Yolculuk sorunu sürüyor", d)
        case.tick_marks["journey"] = d.rule
    if last is None:
        return _ephemeral(case, now, "tick", "Değişiklik yok.") if quiet else _record(case, now, "tick", case.state, case.state, None,
                                                                                      note="Değişiklik yok.", extra=_src(ev))
    return last


def _tick_waiting(case: Case, ev: Event, now: datetime, cfg: Config, nac) -> dict | None:
    """Varış penceresi geçti ama roaming olayı gelmedi → bir kez anlık roaming sorgusu + koordinatör notu."""
    if case.arrival_overdue_noted:
        return None
    d = R.arrival_overdue(now, case.itinerary, cfg)
    if d.decision != "overdue":
        return None
    case.arrival_overdue_noted = True
    poll_note = ""
    if cfg.arrival_overdue_poll and nac is not None and case.patient_phone:
        r = _nac(nac, "roaming", case.patient_phone)
        if r.data:
            cc = resolve_country(r.data.get("countryCode"), r.data.get("countryName"))
            d.explain.append(R.Explain("roaming.poll", {"roaming": r.data.get("roaming"), "countryCode": cc}, 0.4,
                                       "Anlık roaming sorgusu (webhook kaybına karşı yedek yol)", source=r.source, triggered=True))
            in_dest = bool(r.data.get("roaming")) and R.country_code(cc) == R.country_code(case.itinerary.get("destination_country"))
            poll_note = (" Anlık sorgu: hasta HEDEF ÜLKEDE görünüyor — koordinatör 'varışı teyit et' ile akışı başlatabilir."
                         if in_dest else " Anlık sorgu: hedef ülkede görünmüyor (uçuş gecikmiş olabilir).")
    entry = _record(case, now, "tick", case.state, case.state, d, note=d.meta["note"] + poll_note, extra=_src(ev))
    _escalate(case, now, cfg, "warn", "Varış sinyali gelmedi", d, note=d.meta["note"] + poll_note)
    return entry


# ---------------------------------------------------------------- koordinatör aksiyonları
COORDINATOR_ACTIONS = ("ack_alert", "manual_release", "confirm_arrival", "reassign_driver", "report_disruption",
                       "clear_disruption", "close_case", "note")


def _h_coordinator(case: Case, ev: Event, now: datetime, cfg: Config, nac) -> dict:
    action = ev.data.get("action")
    actor = ev.data.get("actor") or "coordinator"
    extra = {"actor": actor, "action": action}
    if action not in COORDINATOR_ACTIONS:
        raise ValueError(f"bilinmeyen koordinatör aksiyonu: {action}")
    if case.terminal and action not in ("ack_alert", "note"):
        raise ValueError(f"vaka {case.state} — '{action}' uygulanamaz")
    if action == "ack_alert":
        alert = next((a for a in case.alerts if a.get("id") == ev.data.get("alert_id")), None)
        if alert is None:
            raise ValueError("uyarı bulunamadı")
        alert["acknowledged_at"], alert["acknowledged_by"] = _iso(now), actor
        return _record(case, now, "coordinator_action", case.state, case.state, None, note=f"Uyarı onaylandı: {alert['title']}", extra=extra)
    if action == "note":
        return _record(case, now, "coordinator_action", case.state, case.state, None, note=str(ev.data.get("text", ""))[:500], extra=extra)
    if action == "manual_release":
        if case.state != "frozen":
            raise ValueError("manuel serbest bırakma yalnızca 'frozen' vakada yapılır")
        reason = str(ev.data.get("reason") or "").strip()
        if not reason:
            raise ValueError("gerekçe zorunlu (ör. 'hasta geri arandı, kimlik teyit edildi')")
        return _release(case, now, None, "coordinator_action", "frozen", integrity="released_manual", extra={**extra, "reason": reason})
    if action == "confirm_arrival":
        if case.state != "waiting":
            raise ValueError("varış teyidi yalnızca 'waiting' vakada yapılır")
        return _arrive(case, now, cfg, nac, None, "coordinator_action", Event("coordinator_action", {"actor": actor, "source": "coordinator"}))
    if action == "reassign_driver":
        drv = ev.data.get("driver") or {}
        if not drv.get("phone") or not drv.get("name"):
            raise ValueError("yeni sürücü için name ve phone zorunlu")
        drv = {**drv, "phone": normalize_phone(drv["phone"])}
        case.driver, case.driver_verified_at, case.meeting_code = drv, None, None
        case.messages = [m for m in case.messages if not (m["kind"] == "driver_verified" and m["status"] == "queued")]
        return _record(case, now, "coordinator_action", case.state, case.state, None,
                       note=f"Sürücü değişti: {drv['name']} — yeni cihaz doğrulaması ve buluşma kodu gerekir.", extra=extra)
    if action == "report_disruption":
        case.known_disruption = {"note": str(ev.data.get("note") or "yol kapanması")[:200], "at": _iso(now), "by": actor}
        return _record(case, now, "coordinator_action", case.state, case.state, None,
                       note=f"Yol kapanması bildirildi: {case.known_disruption['note']} — sapma güveni düşürülür.", extra=extra)
    if action == "clear_disruption":
        case.known_disruption = None
        return _record(case, now, "coordinator_action", case.state, case.state, None, note="Yol kapanması kaldırıldı.", extra=extra)
    # close_case
    reason = str(ev.data.get("reason") or "").strip()
    if not reason:
        raise ValueError("kapanış gerekçesi zorunlu")
    frm = _set_state(case, "closed")
    case.closed_at = _iso(now)
    return _record(case, now, "coordinator_action", frm, "closed", None, note=f"Vaka koordinatör tarafından kapatıldı: {reason}",
                   extra={**extra, "reason": reason})


def _h_subscription_ended(case: Case, ev: Event, now: datetime, cfg: Config, nac) -> dict:
    target = ev.data.get("target", "?")
    entry = _record(case, now, "subscription_ended", case.state, case.state, None,
                    note=f"Nokia aboneliği sona erdi ({target}).", extra=_src(ev))
    if case.monitoring:
        _escalate(case, now, cfg, "warn", f"İzleme boşluğu: {target} aboneliği vaka bitmeden sona erdi", None,
                  note="Bu sinyal artık gelmeyecek; koordinatör hastayı manuel takip etmeli veya vakayı yeniden kurmalı.")
    return entry


_HANDLERS = {
    "consent_granted": _h_consent,
    "consent_declined": _h_consent,
    "consent_withdrawn": _h_consent,
    "roaming_on": _h_roaming_on,
    "sim_swap_result": _h_sim_swap_result,
    "driver_verify": _h_driver_verify,
    "driver_call": _h_driver_call,
    "geofence_enter": _h_geofence_enter,
    "geofence_left": _h_geofence_left,
    "reachability_change": _h_reachability,
    "tick": _h_tick,
    "coordinator_action": _h_coordinator,
    "subscription_ended": _h_subscription_ended,
}
EVENT_TYPES = tuple(_HANDLERS)
_PRE_CONSENT_EVENTS = frozenset({"consent_granted", "consent_declined", "consent_withdrawn", "tick", "coordinator_action"})


class CaseMachine:
    """İnce sarmalayıcı: cfg + facade tutar; `handle(case, event, now)`."""

    def __init__(self, cfg: Config | None = None, nac_facade=None):
        self.cfg = cfg or Config()
        self.nac = nac_facade

    def handle(self, case: Case, event: Event | dict, now: datetime | str) -> dict:
        return on_event(case, event, now, self.cfg, self.nac)

    @staticmethod
    def audit(case: Case) -> dict:
        """Kapanış raporu — kliniğin hizmet kanıtı (ham numara, buluşma kodu ve rıza token'ı yok)."""
        tl = case.timeline
        return {
            "case_id": case.id, "clinic": case.clinic_name, "patient_masked": case.phone_masked,
            "patient_hash": case.phone_hash, "state": case.state, "consent": dict(case.consent),
            "landed_at": case.arrived_at, "first_contact_at": case.first_contact_at, "closed_at": case.closed_at,
            "driver": case.driver_public(), "integrity": case.integrity,
            "driver_verified_at": case.driver_verified_at,
            "impostor_attempts": sum(1 for e in tl if e["event"] == "driver_call" and e["decision"] == "impostor"),
            "unverified_calls": sum(1 for e in tl if e["event"] == "driver_call" and e["decision"] == "unverified"),
            "verified_calls": sum(1 for e in tl if e["event"] == "driver_call" and e["decision"] == "genuine"),
            "escalations_used": case.escalations_used, "alerts": len(case.alerts),
            "alerts_acknowledged": sum(1 for a in case.alerts if a.get("acknowledged_at")),
            "messages_sent": sum(1 for m in case.messages if m.get("status") == "sent"),
            "messages_total": len(case.messages),
            "subscriptions_deleted": case.subscriptions_deleted, "pii_purged_at": case.pii_purged_at,
            "stored_locations_count": 0,
            "summary": case.summary,
            "timeline": [{k: v for k, v in e.items() if k != "explain"} for e in tl],
        }
