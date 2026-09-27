"""Vaka durum makinesi testleri — fixture modunda gerçek nac_client ile (HTTP yok)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from arrivalguard.agent import Case, CaseMachine
from arrivalguard.agent.case_machine import request_consent
from arrivalguard.nac_client import SIM_DEVICE_PREFIX, FixtureBackend, NacClient, NacConfig
from arrivalguard.rules import Config

ROOT = Path(__file__).resolve().parents[1]
CFG = Config()
T0 = datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc)
PATIENT = "+447700900001"
DRIVER = {"id": "drv-1", "name": "Mehmet Y.", "plate": "34 ABC 123", "phone": "+447700900101"}
IMPOSTOR = "+447700900109"
DRIVER_TOKEN = SIM_DEVICE_PREFIX + DRIVER["phone"]


class Facade:
    """Testte NacFacade'ın yerine geçen ince sarmalayıcı (aynı arayüz: .call(name, *args))."""

    def __init__(self, nac: NacClient):
        self.nac = nac

    def call(self, name, *args, **kwargs):
        return getattr(self.nac, name)(*args, **kwargs)


@pytest.fixture
def nac():
    fx = FixtureBackend.from_json(ROOT / "fixtures" / "profiles.json")
    now = datetime.now(timezone.utc)
    fx.update_profile(PATIENT, {"sim_swap_at": (now - timedelta(days=120)).isoformat()})
    fx.update_profile("+447700900003", {"sim_swap_at": (now - timedelta(hours=3)).isoformat()})
    return NacClient(NacConfig(mode="fixture"), fixtures=fx)


@pytest.fixture
def machine(nac):
    return CaseMachine(CFG, Facade(nac))


def make_case(phone=PATIENT, lang="en", cid="case-1", family=True, consented=True) -> Case:
    c = Case(
        id=cid, clinic_id="clinic-1", clinic_name="İstanbul Estetik Kliniği",
        patient_name="Layla A.", patient_phone=phone, language=lang,
        itinerary={"destination_country": 90,
                   "legs": [{"country": 974, "eta": T0.isoformat()},
                            {"country": 90, "eta": (T0 + timedelta(hours=3)).isoformat()}]},
        driver=dict(DRIVER),
        zones={"airport": {"lat": 41.2753, "lng": 28.7519, "radius": 2000},
               "corridor": {"lat": 41.162, "lng": 28.87, "radius": 1500},
               "clinic": {"lat": 41.0615, "lng": 28.987, "radius": 600}},
        family_contact={"name": "Ahmed", "phone": "+447700900099", "language": "en"} if family else None,
        consent_token="consent-secret-token", driver_token="driver-secret-token", public_base_url="https://ag.example",
    )
    if consented:
        c.state, c.consent = "waiting", {"status": "granted"}
    return c


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def arrive(machine, case, minutes=180):
    machine.handle(case, {"type": "roaming_on", "country": 974}, at(0))
    return machine.handle(case, {"type": "roaming_on", "country": 90}, at(minutes))


def contact(machine, case, verify_at=186, call_at=190):
    machine.handle(case, {"type": "driver_verify", "device_token": DRIVER_TOKEN}, at(verify_at))
    return machine.handle(case, {"type": "driver_call", "caller_phone": DRIVER["phone"]}, at(call_at))


# ------------------------------------------------------------------ rıza
def test_no_network_event_is_processed_before_consent(machine):
    c = make_case(consented=False)
    request_consent(c, at(0))
    e = machine.handle(c, {"type": "roaming_on", "country": 90}, at(180))
    assert c.state == "pending_consent" and "Rıza alınmadan" in e["note"]
    assert [m["kind"] for m in c.messages] == ["consent_request"]
    assert "https://ag.example/consent/" in c.messages[0]["text"]


def test_consent_granted_starts_monitoring_with_operator_check(machine):
    c = make_case(consented=False)
    e = machine.handle(c, {"type": "consent_granted", "method": "patient_link"}, at(1))
    assert c.state == "waiting" and e["decision"] == "start_monitoring"
    assert c.consent["status"] == "granted" and c.consent["operator_valid"] is True


def test_operator_consent_missing_blocks_monitoring(machine, nac):
    nac.fx.update_profile(PATIENT, {"consent": {"sim-swap": "PENDING"}})
    c = make_case(consented=False)
    e = machine.handle(c, {"type": "consent_granted"}, at(1))
    assert e["decision"] == "await_operator_consent" and c.state == "pending_consent"
    assert c.consent["status"] == "operator_pending" and c.alerts[-1]["level"] == "warn"


def test_decline_and_withdraw_are_terminal(machine):
    d = make_case(consented=False, cid="d")
    machine.handle(d, {"type": "consent_declined"}, at(1))
    assert d.state == "declined" and d.terminal
    w = make_case(cid="w")
    arrive(machine, w)
    machine.handle(w, {"type": "consent_withdrawn"}, at(190))
    assert w.state == "withdrawn" and any(m["kind"] == "consent_withdrawn" and m["to"] == "patient" for m in w.messages)
    # geri çekilmiş vakada şebeke olayı işlenmez
    e = machine.handle(w, {"type": "reachability_change", "reachable": False}, at(200))
    assert w.state == "withdrawn" and "yalnızca audit" in e["note"]


def test_consent_link_token_masked_in_public_view(machine):
    c = make_case(consented=False)
    request_consent(c, at(0))
    blob = str(c.to_dict())
    assert "consent-secret-token" not in blob and "••••" in c.to_dict()["messages"][0]["text"]


# ------------------------------------------------------------------ varış
def test_transit_greets_without_pickup_details(machine):
    c = make_case()
    machine.handle(c, {"type": "roaming_on", "country": 974}, at(0))
    assert c.state == "waiting"
    assert [m["kind"] for m in c.messages] == ["transit_greeting"] and "34 ABC 123" not in c.messages[0]["text"]


def test_arrival_runs_integrity_gate_releases_pickup_and_sends_driver_link(machine):
    c = make_case()
    entry = arrive(machine, c)
    assert c.state == "released" and c.integrity == "released" and entry["decision"] == "release_pickup"
    assert any(m["kind"] == "welcome_pickup" and DRIVER["plate"] in m["text"] for m in c.messages)
    link = next(m for m in c.messages if m["kind"] == "driver_link")
    assert link["to"] == "driver" and "https://ag.example/driver/driver-secret-token" in link["text"]
    lv = [e for e in c.timeline if e["event"] == "location_verify"]
    assert lv and "TRUE" in lv[0]["note"]  # varışta tek seferlik konum HÜKMÜ (koordinat kaydı yok)


def test_recent_sim_swap_freezes_pickup_and_alarms(machine):
    c = make_case(phone="+447700900003")
    arrive(machine, c)
    assert c.state == "frozen" and c.integrity == "frozen"
    assert [a["level"] for a in c.alerts] == ["alarm"] and c.escalations_used == 1
    assert DRIVER["plate"] not in " ".join(m["text"] for m in c.messages if m["to"] == "patient")
    assert not any(m["kind"] == "driver_link" for m in c.messages)


def test_coordinator_manual_release_requires_reason(machine):
    c = make_case(phone="+447700900003")
    arrive(machine, c)
    with pytest.raises(ValueError):
        machine.handle(c, {"type": "coordinator_action", "action": "manual_release"}, at(200))
    e = machine.handle(c, {"type": "coordinator_action", "action": "manual_release", "reason": "hasta geri arandı", "actor": "k1"}, at(200))
    assert c.state == "released" and c.integrity == "released_manual" and e["actor"] == "k1"


# ------------------------------------------------------------------ sürücü doğrulama
def test_driver_verification_issues_meeting_code_to_both_sides(machine):
    c = make_case()
    arrive(machine, c)
    e = machine.handle(c, {"type": "driver_verify", "device_token": DRIVER_TOKEN}, at(186))
    assert e["decision"] == "driver_verified" and c.driver_verified_at and len(c.meeting_code) == 4
    to_patient = next(m for m in c.messages if m["kind"] == "driver_verified")
    to_driver = next(m for m in c.messages if m["kind"] == "driver_code")
    assert c.meeting_code in to_patient["text"] and c.meeting_code in to_driver["text"]
    # koordinatör görünümünde kod maskeli
    assert c.meeting_code not in str(c.to_dict()["messages"]) and c.to_dict()["meeting_code_issued"] is True


def test_other_device_claiming_driver_number_is_rejected(machine):
    c = make_case()
    arrive(machine, c)
    e = machine.handle(c, {"type": "driver_verify", "device_token": SIM_DEVICE_PREFIX + IMPOSTOR}, at(186))
    assert e["decision"] == "driver_rejected" and c.driver_verified_at is None and c.meeting_code is None
    assert c.alerts[-1]["level"] == "warn"


def test_driver_verified_before_release_gets_code_on_release(machine):
    c = make_case()
    machine.handle(c, {"type": "driver_verify", "device_token": DRIVER_TOKEN}, at(170))
    assert not any(m["kind"] == "driver_verified" for m in c.messages)
    arrive(machine, c, minutes=180)
    assert any(m["kind"] == "driver_verified" for m in c.messages)


def test_spoofed_driver_number_without_attestation_is_unverified(machine):
    c = make_case()
    arrive(machine, c)
    e = machine.handle(c, {"type": "driver_call", "caller_phone": DRIVER["phone"]}, at(184))
    assert e["decision"] == "unverified" and c.first_contact_at is None
    assert any(m["kind"] == "call_unverified" for m in c.messages)


def test_impostor_call_rejected_then_real_driver_contact(machine):
    c = make_case()
    arrive(machine, c)
    e1 = machine.handle(c, {"type": "driver_call", "caller_phone": IMPOSTOR}, at(188))
    assert e1["decision"] == "impostor" and c.first_contact_at is None and e1["caller_masked"] == "+44770***0109"
    e2 = contact(machine, c)
    assert e2["decision"] == "genuine" and c.state == "contacted" and c.first_contact_at


def test_stale_attestation_makes_call_unverified(machine):
    c = make_case()
    arrive(machine, c)
    machine.handle(c, {"type": "driver_verify", "device_token": DRIVER_TOKEN}, at(181))
    e = machine.handle(c, {"type": "driver_call", "caller_phone": DRIVER["phone"]}, at(181 + CFG.driver_attestation_ttl_min + 5))
    assert e["decision"] == "unverified"


def test_genuine_call_on_frozen_case_is_not_first_contact(machine):
    c = make_case(phone="+447700900003")
    arrive(machine, c)
    machine.handle(c, {"type": "driver_verify", "device_token": DRIVER_TOKEN}, at(186))
    assert not any(m["kind"] == "driver_verified" for m in c.messages)  # kod şüpheli hatta gönderilmez
    e = machine.handle(c, {"type": "driver_call", "caller_phone": DRIVER["phone"]}, at(190))
    assert c.state == "frozen" and c.first_contact_at is None and "dondurulmuş" in e["note"]


def test_reassign_driver_resets_attestation(machine):
    c = make_case()
    arrive(machine, c)
    machine.handle(c, {"type": "driver_verify", "device_token": DRIVER_TOKEN}, at(186))
    machine.handle(c, {"type": "coordinator_action", "action": "reassign_driver",
                       "driver": {"id": "drv-2", "name": "Ayşe K.", "plate": "34 XYZ 789", "phone": "+447700900102"}}, at(187))
    assert c.driver["name"] == "Ayşe K." and c.driver_verified_at is None and c.meeting_code is None
    e = machine.handle(c, {"type": "driver_call", "caller_phone": DRIVER["phone"]}, at(190))
    assert e["decision"] == "impostor"  # eski sürücü artık kayıtlı değil


# ------------------------------------------------------------------ aynı sinyal, zıt anlam
def test_unreachable_before_contact_alarms_after_contact_lowers(machine):
    a = make_case(cid="case-a")
    arrive(machine, a)
    machine.handle(a, {"type": "reachability_change", "reachable": False}, at(185))
    entry = machine.handle(a, {"type": "tick"}, at(192))
    assert entry["decision"] == "alarm" and a.state == "escalated"

    b = make_case(cid="case-b")
    arrive(machine, b)
    contact(machine, b)
    machine.handle(b, {"type": "reachability_change", "reachable": False}, at(200))
    entry = machine.handle(b, {"type": "tick"}, at(215))
    assert entry["decision"] == "lower" and b.state == "contacted" and not b.alerts
    assert any(m["kind"] == "local_sim_fallback" for m in b.messages)


def test_reachability_unknown_when_network_silent_does_not_alarm(machine):
    c = make_case()
    arrive(machine, c)
    e = CaseMachine(CFG, None).handle(c, {"type": "reachability_change"}, at(191))  # sinyal yok, sorgu yok
    assert "bilinmiyor" in e["note"] and c.unreachable_since is None


# ------------------------------------------------------------------ zamanlayıcı tick'leri
def test_scheduler_ticks_do_not_flood_timeline_and_reescalate_on_interval(machine):
    c = make_case()
    arrive(machine, c)
    machine.handle(c, {"type": "reachability_change", "reachable": False}, at(185))
    n = len(c.timeline)
    e = machine.handle(c, {"type": "tick", "source": "scheduler"}, at(186))
    assert e.get("recorded") is False and len(c.timeline) == n  # "raise" değişmedi → audit'e yazılmaz
    machine.handle(c, {"type": "tick", "source": "scheduler"}, at(191))  # 6 dk → alarm (kural değişti)
    assert c.escalations_used == 1 and c.state == "escalated"
    for m in range(192, 200):
        machine.handle(c, {"type": "tick", "source": "scheduler"}, at(m))
    assert c.escalations_used == 1  # aralık dolmadan yeniden uyandırma yok
    machine.handle(c, {"type": "tick", "source": "scheduler"}, at(191 + CFG.reescalate_after_min))
    assert c.escalations_used == 2


def test_arrival_overdue_polls_roaming_once_and_warns(machine):
    c = make_case()
    e = machine.handle(c, {"type": "tick", "source": "scheduler"}, at(180 + CFG.arrival_window_h * 60 + 5))
    assert e["decision"] == "overdue" and "HEDEF ÜLKEDE" in e["note"]
    assert c.alerts[-1]["title"] == "Varış sinyali gelmedi"
    machine.handle(c, {"type": "tick", "source": "scheduler"}, at(180 + CFG.arrival_window_h * 60 + 15))
    assert len([a for a in c.alerts if a["title"] == "Varış sinyali gelmedi"]) == 1
    machine.handle(c, {"type": "coordinator_action", "action": "confirm_arrival"}, at(400))
    assert c.state == "released"


def test_case_expires_after_max_hours(machine):
    c = make_case()
    arrive(machine, c)
    e = machine.handle(c, {"type": "tick", "source": "scheduler"}, at(180 + CFG.case_max_hours * 60 + 1))
    assert c.state == "expired" and c.terminal and e["to"] == "expired"


def test_pending_consent_case_also_expires(machine):
    c = make_case(consented=False)
    machine.handle(c, {"type": "tick", "source": "scheduler"}, at(180 + CFG.case_max_hours * 60 + 1))
    assert c.state == "expired"


# ------------------------------------------------------------------ yolculuk
def test_clinic_entry_closes_case_and_notifies_family(machine):
    c = make_case()
    arrive(machine, c)
    contact(machine, c)
    machine.handle(c, {"type": "geofence_left", "zone": "airport"}, at(200))
    machine.handle(c, {"type": "geofence_enter", "zone": "corridor"}, at(210))
    machine.handle(c, {"type": "geofence_enter", "zone": "clinic"}, at(245))
    assert c.state == "closed" and c.closed_at
    assert [m["kind"] for m in c.messages][-1] == "arrived_safely"
    e = machine.handle(c, {"type": "driver_call", "caller_phone": IMPOSTOR}, at(300))
    assert c.state == "closed" and "yalnızca audit" in e["note"]


def test_escalation_budget_caps_coordinator_wakeups(machine):
    c = make_case()
    arrive(machine, c)
    contact(machine, c)
    machine.handle(c, {"type": "geofence_left", "zone": "airport"}, at(195))
    machine.handle(c, {"type": "geofence_left", "zone": "corridor", "stationary_min": 2}, at(205))
    for i, m in enumerate([220, 240, 250, 260]):
        machine.handle(c, {"type": "tick", "stationary_min": 12 + i * 10}, at(m))
    alarms = [a for a in c.alerts if a["level"] == "alarm"]
    assert c.escalations_used == CFG.escalation_budget_per_case == len(alarms)
    assert any("bütçe doldu" in a["title"] for a in c.alerts if a["level"] == "warn")


def test_journey_low_confidence_does_not_escalate(machine):
    c = make_case()
    arrive(machine, c)
    contact(machine, c)
    machine.handle(c, {"type": "geofence_left", "zone": "airport"}, at(195))
    e = machine.handle(c, {"type": "geofence_left", "zone": "corridor", "stationary_min": 2}, at(205))
    assert e["decision"] == "probable_traffic" and not [a for a in c.alerts if a["level"] == "alarm"]


def test_reported_disruption_prevents_wakeup(machine):
    c = make_case()
    arrive(machine, c)
    contact(machine, c)
    machine.handle(c, {"type": "geofence_left", "zone": "airport"}, at(195))
    machine.handle(c, {"type": "coordinator_action", "action": "report_disruption", "note": "O-3 kapalı"}, at(196))
    e = machine.handle(c, {"type": "geofence_left", "zone": "corridor", "stationary_min": 15}, at(205))
    assert e["decision"] == "probable_traffic" and c.escalations_used == 0


def test_subscription_ended_while_monitoring_warns(machine):
    c = make_case()
    arrive(machine, c)
    machine.handle(c, {"type": "subscription_ended", "target": "roaming"}, at(190))
    assert "İzleme boşluğu" in c.alerts[-1]["title"]


def test_unknown_event_type_is_recorded_not_crashed(machine):
    c = make_case()
    e = machine.handle(c, {"type": "hava_durumu"}, at(1))
    assert "bilinmeyen olay" in e["note"] and c.state == "waiting"


def test_ack_alert_records_actor(machine):
    c = make_case(phone="+447700900003")
    arrive(machine, c)
    aid = c.alerts[0]["id"]
    machine.handle(c, {"type": "coordinator_action", "action": "ack_alert", "alert_id": aid, "actor": "clinic-1/abcd"}, at(200))
    assert c.alerts[0]["acknowledged_by"] == "clinic-1/abcd" and CaseMachine.audit(c)["alerts_acknowledged"] == 1
    with pytest.raises(ValueError):
        machine.handle(c, {"type": "coordinator_action", "action": "ack_alert", "alert_id": "yok"}, at(201))


# ------------------------------------------------------------------ gizlilik / audit / kalıcılık
def test_case_dict_never_leaks_raw_phone_or_secrets(machine):
    c = make_case()
    arrive(machine, c)
    contact(machine, c)
    blob = str(c.to_dict())
    for secret in (PATIENT, DRIVER["phone"], "+447700900099", "consent-secret-token", "driver-secret-token", c.meeting_code):
        assert secret not in blob
    assert c.to_dict()["patient"]["phone_masked"] == "+44770***0001"
    assert len(c.to_dict()["patient"]["phone_hash"]) == 64


def test_purge_pii_keeps_mask_and_hash(machine):
    c = make_case()
    arrive(machine, c)
    h = c.phone_hash
    c.purge_pii(at(300))
    assert c.patient_phone is None and "phone" not in c.driver and "phone" not in c.family_contact
    assert c.consent_token is None and c.driver_token is None and c.meeting_code is None
    d = c.to_dict()
    assert d["patient"]["phone_hash"] == h and d["driver"]["phone_masked"] == "+44770***0101" and d["pii_purged_at"]


def test_record_roundtrip():
    c = make_case()
    again = Case.from_record(c.to_record())
    assert again.to_dict() == c.to_dict() and again.patient_phone == PATIENT


def test_audit_report_counts_calls_and_hides_phone(machine):
    c = make_case()
    arrive(machine, c)
    machine.handle(c, {"type": "driver_call", "caller_phone": IMPOSTOR}, at(188))
    contact(machine, c)
    a = CaseMachine.audit(c)
    assert a["impostor_attempts"] == 1 and a["verified_calls"] == 1 and a["driver_verified_at"]
    assert a["patient_masked"] == "+44770***0001" and PATIENT not in str(a) and a["stored_locations_count"] == 0
    assert a["timeline"] and "explain" not in a["timeline"][0]


def test_step_index_tracks_ui_stepper(machine):
    c = make_case(consented=False)
    assert c.step_index == 0
    machine.handle(c, {"type": "consent_granted"}, at(0))
    assert c.step_index == 1
    arrive(machine, c)
    assert c.step_index == 3  # SIM kontrol adımı
    contact(machine, c)
    assert c.step_index == 4
    machine.handle(c, {"type": "geofence_left", "zone": "airport"}, at(200))
    assert c.step_index == 5
