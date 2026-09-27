"""AppContext — uygulamanın tüm bağımlılıklarını ve vaka yaşam döngüsünü tek yerde toplar.

Her olay aynı yoldan geçer: `ctx.handle(case, event, at)` →
  1. durum makinesi (saf kurallar + Nokia facade)
  2. bozulmuş sinyal notu (Nokia cevap vermediyse koordinatöre "eksik veriyle karar")
  3. rıza verildiyse abonelikleri kur (roaming ×2, reachability ×2, geofence ×3 — her tip ayrı abonelik)
  4. outbox'taki mesajları gönder (notify.dispatch)
  5. terminal durumda: abonelikleri sil, bekleyen mesaj kalmadıysa ham numaraları sil, isteğe bağlı özet yaz
  6. kaydet
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from .. import data_path
from ..agent import Case, CaseMachine
from ..agent.case_machine import request_consent
from ..agent.llm_adapter import LlmAdapter, NoopLlm, build_llm
from ..nac_client import (
    REACHABILITY_DATA,
    REACHABILITY_DISCONNECTED,
    ROAMING_CHANGE_COUNTRY,
    ROAMING_ON,
    NacClient,
    NacError,
    NumberVerificationAuth,
    hash_phone,
    mask_phone,
    normalize_phone,
)
from ..rules import Config
from ..rules import decisions as R
from .facade import SafeFacade, build_nac
from .notify import Notifier, build_notifier, dispatch, has_pending
from .settings import Settings
from .store import build_store

log = logging.getLogger("arrivalguard.context")

CONSENT_TEXT_VERSION = "2026-09-v1"
PII_GRACE = timedelta(hours=24)       # bekleyen mesaj olsa bile ham numaralar en geç bu süre sonra silinir
EVENT_DEDUPE_TTL = timedelta(days=2)
NV_STATE_TTL = timedelta(minutes=10)  # sürücü OIDC akışı: operatöre gidip dönme süresi
_PHONE_RE = re.compile(r"\+[0-9]{8,15}")

# abonelik anahtarı → (tür, CloudEvent tipi)
ROAMING_TYPES = {"roaming-on": ROAMING_ON, "roaming-change-country": ROAMING_CHANGE_COUNTRY}
REACHABILITY_TYPES = {"disconnected": REACHABILITY_DISCONNECTED, "data": REACHABILITY_DATA}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def mask_deep(value):
    """İç içe yapıdaki tüm E.164 numaraları maskeler (debug/degraded çıktısı için)."""
    if isinstance(value, dict):
        return {k: mask_deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_deep(v) for v in value]
    if isinstance(value, str):
        return _PHONE_RE.sub(lambda m: mask_phone(m.group(0)), value)
    return value


def clinic_public(clinic: dict) -> dict:
    """Klinik sicilinin dışa açık hali: sürücü/koordinatör numaraları maskeli."""
    out = {k: v for k, v in clinic.items() if k not in ("drivers", "coordinator")}
    out["drivers"] = [{k: v for k, v in d.items() if k != "phone"} | ({"phone_masked": mask_phone(d["phone"])} if d.get("phone") else {})
                      for d in clinic.get("drivers") or []]
    coord = dict(clinic.get("coordinator") or {})
    if coord.get("phone"):
        coord["phone_masked"] = mask_phone(coord.pop("phone"))
    out["coordinator"] = coord
    return out


class AppContext:
    def __init__(self, settings: Settings, cfg: Config | None = None, nac: NacClient | None = None,
                 notifier: Notifier | None = None, llm: LlmAdapter | None = None, clock: Callable[[], datetime] | None = None):
        self.settings = settings
        self.cfg = cfg or Config.from_env()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.nac = nac or build_nac(str(data_path("profiles.json")))
        self.facade = SafeFacade(self.nac, clock=self.now)
        self.machine = CaseMachine(self.cfg, self.facade)
        self.store = build_store(settings.store_backend, settings.db_path)
        self.lock: threading.RLock = self.store.lock
        self.notifier = notifier or build_notifier(settings)
        self.llm = llm or (build_llm(settings.llm_provider, settings.llm_model) if settings.llm_provider != "none" else NoopLlm())
        self.nv = NumberVerificationAuth(self.nac)
        self.nv_states: dict[str, dict] = {}  # state → {driver_token, expires}; tek kullanımlık, bellek içi

    def now(self) -> datetime:
        return self.clock()

    @property
    def degraded(self) -> list[dict]:
        return [mask_deep(d) for d in self.facade.degraded]

    # ------------------------------------------------------------------ klinikler
    def seed_clinics(self) -> None:
        """Depoda klinik yoksa fixtures/clinics.json'u yükler (demo kliniği)."""
        import json

        if self.store.list_clinics():
            return
        path = data_path("clinics.json")
        if path.exists():
            for c in json.loads(path.read_text(encoding="utf-8")).get("clinics", []):
                self.save_clinic(c)

    def save_clinic(self, clinic: dict) -> dict:
        clinic = dict(clinic)
        drivers = []
        for d in clinic.get("drivers") or []:
            d = dict(d)
            if not d.get("id") or not d.get("name") or not d.get("phone"):
                raise ValueError("her sürücü için id, name, phone zorunlu")
            d["phone"] = normalize_phone(d["phone"])
            drivers.append(d)
        clinic["drivers"] = drivers
        coord = dict(clinic.get("coordinator") or {})
        if coord.get("phone"):
            coord["phone"] = normalize_phone(coord["phone"])
        clinic["coordinator"] = coord
        for z in ("airport", "corridor", "clinic"):
            if z not in (clinic.get("zones") or {}):
                raise ValueError(f"klinik zonları eksik: {z}")
        self.store.save_clinic(clinic)
        return clinic

    # ------------------------------------------------------------------ vaka açma
    def create_case(self, body: dict, clinic: dict, at: datetime | None = None) -> Case:
        """body: CaseIn.model_dump(). Rıza verilmişse (klinik formu) izleme hemen başlar; yoksa hastaya rıza bağlantısı gider."""
        phone = normalize_phone(body["patient_phone"])
        t0 = at or self.now()
        driver = self._resolve_driver(body, clinic)
        family = dict(body["family_contact"]) if body.get("family_contact") else None
        if family and family.get("phone"):
            family["phone"] = normalize_phone(family["phone"])
        case = Case(
            id=f"case-{secrets.token_hex(4)}",
            clinic_id=clinic["id"], clinic_name=clinic.get("name", clinic["id"]),
            patient_name=body["patient_name"], patient_phone=phone, language=body.get("language") or "en",
            itinerary=body["itinerary"], driver=driver,
            zones=body.get("zones") or {k: dict(v) for k, v in clinic["zones"].items()},
            family_contact=family, meeting_point=body.get("meeting_point") or clinic.get("meeting_point", ""),
            consent={"status": "pending", "text_version": CONSENT_TEXT_VERSION},
            consent_token=secrets.token_urlsafe(24), driver_token=secrets.token_urlsafe(24),
            public_base_url=self.settings.public_base_url,
            created_at=iso(t0), updated_at=iso(t0),
        )
        if "corridor" in case.zones and not body.get("zones"):
            case.zones["corridor"]["radius"] = float(self.cfg.corridor_radius_m)
        case.subscribe = bool(body.get("subscribe", True))
        self.store.save_case(case)
        log.info("case created id=%s clinic=%s patient=%s", case.id, case.clinic_id, mask_phone(phone))
        consent = body.get("consent")
        if consent:
            self.handle(case, {"type": "consent_granted", "method": consent.get("method", "clinic_form"),
                               "text_version": consent.get("text_version") or CONSENT_TEXT_VERSION,
                               "source": "clinic", "actor": body.get("_actor")}, t0)
        else:
            request_consent(case, t0)
            self.finalize(case, t0)
        return case

    @staticmethod
    def _resolve_driver(body: dict, clinic: dict) -> dict:
        drivers = clinic.get("drivers") or []
        if body.get("driver"):
            d = dict(body["driver"])
            if not d.get("phone") or not d.get("name"):
                raise ValueError("driver için name ve phone zorunlu")
            d["phone"] = normalize_phone(d["phone"])
            return d
        if body.get("driver_id"):
            d = next((x for x in drivers if x["id"] == body["driver_id"]), None)
            if d is None:
                raise ValueError(f"klinikte sürücü yok: {body['driver_id']}")
            return dict(d)
        if not drivers:
            raise ValueError("klinikte kayıtlı sürücü yok; driver ya da driver_id verin")
        return dict(drivers[0])

    # ------------------------------------------------------------------ tek olay yolu
    def handle(self, case: Case, event: dict, at: datetime | None = None) -> dict:
        at = at or self.now()
        with self.lock:
            prev = case.state
            entry = self.machine.handle(case, event, at)
            self._note_degraded(case, entry, at)
            if prev == "pending_consent" and case.state == "waiting" and case.subscribe:
                self.subscribe(case, at)
            self.finalize(case, at)
            return entry

    def finalize(self, case: Case, at: datetime) -> None:
        """Gönderim + terminal temizlik + kayıt. Zamanlayıcı terminal vakalar için de çağırır (yeniden deneme)."""
        clinic = self.store.get_clinic(case.clinic_id)
        self._dispatch(case, clinic)
        if case.terminal:
            if not case.subscriptions_deleted:
                self.unsubscribe(case)
            if case.summary is None and case.state in ("closed", "expired"):
                case.summary = self.llm.summarize_case(case.timeline, "tr", redact=[case.patient_name, case.driver.get("name", "")])
            closed = datetime.fromisoformat((case.closed_at or case.updated_at or iso(at)).replace("Z", "+00:00"))
            if not case.pii_purged_at and (not has_pending(case) or at - closed >= PII_GRACE):
                case.purge_pii(at)
        self.store.save_case(case)

    def _dispatch(self, case: Case, clinic: dict | None) -> None:
        try:
            dispatch(case, self.notifier, clinic, self.now())
        except Exception:  # noqa: BLE001 — bildirim hatası vaka akışını durdurmaz; mesajlar outbox'ta kalır
            log.exception("notify dispatch crashed case=%s", case.id)

    def _note_degraded(self, case: Case, entry: dict, at: datetime) -> None:
        """Kararın dayandığı sinyallerden biri hata döndüyse koordinatöre 'eksik veriyle karar' uyarısı.

        Ürün kararı: şebeke sorgusu düştü diye hasta havalimanında bekletilmez (fail-open), ama karar
        "bilinmiyor" etiketiyle koordinatörün önüne düşer — sessizce temiz sayılmaz.
        """
        bad = sorted({str(e.get("source")) for e in (entry.get("explain") or []) if str(e.get("source", "")).startswith("error(")})
        if not bad:
            return
        case.alerts.append({
            "id": f"al-{len(case.alerts) + 1}", "t": iso(at), "level": "warn", "degraded": True,
            "title": "Şebeke sinyali alınamadı — karar eksik veriyle verildi",
            "note": f"Kaynaklar: {', '.join(bad)}. Akış durdurulmadı; koordinatör manuel teyit eder.",
            "confidence": None, "explain": entry.get("explain") or [], "budget": None,
            "acknowledged_at": None, "acknowledged_by": None,
        })

    # ------------------------------------------------------------------ abonelikler
    def _sink(self, name: str) -> str:
        return f"{self.settings.public_base_url.rstrip('/')}/webhooks/{name}"

    def subscribe(self, case: Case, at: datetime) -> None:
        """Rıza sonrası: her olay tipi için ayrı abonelik (Nokia v0.8 tek tip kuralı). Hata olursa vaka yine sürer."""
        phone = case.patient_phone
        if not phone:
            return
        eta = R.destination_eta(case.itinerary)
        expire = (eta + timedelta(hours=self.cfg.case_max_hours)) if eta and eta > at else at + timedelta(days=1)
        token = self.settings.webhook_token or None
        plan: list[tuple[str, str, Callable[[], object]]] = []
        for key, etype in ROAMING_TYPES.items():
            plan.append((f"roaming:{key}", "roaming",
                         lambda etype=etype: self.facade.call("roaming_subscribe", phone, self._sink("roaming"), etype, sink_token=token, expire=expire)))
        for key, etype in REACHABILITY_TYPES.items():
            plan.append((f"reachability:{key}", "reachability",
                         lambda etype=etype: self.facade.call("reachability_subscribe", phone, self._sink("reachability"), etype, sink_token=token, expire=expire)))
        for zone, z in case.zones.items():
            plan.append((f"geofence:{zone}", zone,
                         lambda z=z: self.facade.call("geofence_subscribe", phone, z["lat"], z["lng"], z.get("radius", 1000),
                                                      self._sink("geofence"), sink_token=token, expire=expire)))
        failed = []
        for key, target, fn in plan:
            r = fn()
            sid = (r.data or {}).get("id") if isinstance(r.data, dict) else None
            if sid:
                case.subscriptions[key] = sid
                self.store.add_sub(sid, case.id, target)
            else:
                failed.append(f"{key} ({r.source})")
        if failed:
            case.alerts.append({
                "id": f"al-{len(case.alerts) + 1}", "t": iso(at), "level": "warn", "degraded": True,
                "title": "Bazı Nokia abonelikleri kurulamadı — izleme eksik",
                "note": "Kurulamayanlar: " + ", ".join(failed) + ". Zamanlayıcı süreye bağlı kontrolleri yapar; koordinatör manuel takip etmeli.",
                "confidence": None, "explain": [], "budget": None, "acknowledged_at": None, "acknowledged_by": None,
            })

    def unsubscribe(self, case: Case) -> None:
        """Terminal durumda tüm abonelikleri siler (izleme biter). Başarısız olanlar zamanlayıcıda yeniden denenir."""
        ops = {"roaming": "roaming_unsubscribe", "reachability": "reachability_unsubscribe", "geofence": "geofence_delete"}
        remaining = False
        for key, sid in case.subscriptions.items():
            if sid in case.deleted_subscriptions:
                continue
            try:
                getattr(self.nac, ops[key.split(":", 1)[0]])(sid)
            except NacError as e:
                if e.kind != "not_found":
                    log.warning("unsubscribe failed case=%s sub=%s kind=%s", case.id, key, e.kind)
                    remaining = True
                    continue
            case.deleted_subscriptions.append(sid)
            self.store.remove_sub(sid)
        case.subscriptions_deleted = not remaining

    # ------------------------------------------------------------------ webhook eşleme
    def resolve_webhook_case(self, data: dict) -> tuple[Case | None, str]:
        sub = self.store.get_sub(data.get("subscriptionId") or "")
        if sub:
            return self.store.get_case(sub[0]), sub[1]
        phone = (data.get("device") or {}).get("phoneNumber")
        if phone:
            try:
                return self.store.find_monitoring_case_by_phone_hash(hash_phone(phone)), ""
            except ValueError:
                pass
        return None, ""

    # ------------------------------------------------------------------ sürücü OIDC (Number Verification)
    @property
    def nv_redirect_uri(self) -> str:
        return os.environ.get("NAC_NV_REDIRECT_URI") or f"{self.settings.public_base_url.rstrip('/')}/driver/nv/callback"

    def nv_begin(self, case: Case, sim_line: str | None = None) -> str:
        """Sürücü akışını başlatır → operatörün yetkilendirme adresi. state tek kullanımlık ve NV_STATE_TTL ile sınırlı."""
        now = self.now()
        with self.lock:
            for k in [k for k, v in self.nv_states.items() if v["expires"] <= now]:
                del self.nv_states[k]
            state = secrets.token_urlsafe(24)
            self.nv_states[state] = {"driver_token": case.driver_token, "expires": now + NV_STATE_TTL}
        return self.nv.authorization_url(login_hint=case.driver["phone"], redirect_uri=self.nv_redirect_uri,
                                         state=state, sim_line=sim_line)

    def nv_take_state(self, state: str) -> str | None:
        """state → sürücü bağlantı token'ı (bir kez). Bilinmeyen/süresi dolmuş → None."""
        with self.lock:
            entry = self.nv_states.pop(state or "", None)
        if entry is None or entry["expires"] <= self.now():
            return None
        return entry["driver_token"]

    # ------------------------------------------------------------------ zamanlayıcı işi
    def run_scheduler_once(self, now: datetime | None = None) -> dict:
        now = now or self.now()
        stats = {"ticked": 0, "finalized": 0, "deleted": 0, "events_purged": 0}
        with self.lock:
            for case in self.store.list_cases():
                if not case.terminal:
                    entry = self.handle(case, {"type": "tick", "source": "scheduler"}, now)
                    stats["ticked"] += 1 if entry.get("recorded", True) else 0
                    continue
                needs = not case.subscriptions_deleted or not case.pii_purged_at or has_pending(case)
                if needs:
                    self.finalize(case, now)
                    stats["finalized"] += 1
                closed = datetime.fromisoformat((case.closed_at or case.updated_at or iso(now)).replace("Z", "+00:00"))
                if now - closed > timedelta(days=self.cfg.retention_days):
                    self.store.delete_case(case.id)
                    stats["deleted"] += 1
            stats["events_purged"] = self.store.purge_events(now - EVENT_DEDUPE_TTL)
        return stats
