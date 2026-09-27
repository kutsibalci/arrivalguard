"""Zamanlayıcı: olay gelmese de süreye bağlı kurallar çalışır; terminal temizlik ve saklama süresi."""
from datetime import datetime, timedelta, timezone

from arrivalguard.api.scheduler import Scheduler
from arrivalguard.nac_client import SIM_DEVICE_PREFIX

from .conftest import DRIVER, PATIENT


def _case(client, eta):
    body = {"patient_name": "Layla A.", "patient_phone": PATIENT, "clinic_id": "clinic-1", "consent": {"method": "clinic_form"},
            "itinerary": {"destination_country": 90, "legs": [{"country": 90, "eta": eta.isoformat()}]}}
    r = client.post("/v1/cases", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_scheduler_raises_alarm_without_manual_tick(app):
    client, ctx = app
    eta = datetime.now(timezone.utc)
    case = _case(client, eta)
    client.post(f"/v1/cases/{case['id']}/events", json={"type": "roaming_on", "now": eta.isoformat(), "data": {"country": 90}})
    client.post(f"/v1/cases/{case['id']}/events", json={"type": "reachability_change", "now": (eta + timedelta(minutes=1)).isoformat(),
                                                        "data": {"reachable": False}})
    stats = ctx.run_scheduler_once(eta + timedelta(minutes=8))
    c = ctx.store.get_case(case["id"])
    assert stats["ticked"] >= 1 and c.state == "escalated" and c.escalations_used == 1
    n = len(c.timeline)
    ctx.run_scheduler_once(eta + timedelta(minutes=9))
    assert len(ctx.store.get_case(case["id"]).timeline) == n  # değişiklik yok → audit şişmez


def test_scheduler_detects_missing_arrival_signal(app):
    client, ctx = app
    eta = datetime.now(timezone.utc) - timedelta(hours=4)
    case = _case(client, eta)
    ctx.run_scheduler_once(datetime.now(timezone.utc))
    c = ctx.store.get_case(case["id"])
    assert any(a["title"] == "Varış sinyali gelmedi" for a in c.alerts)


def test_scheduler_expires_finalizes_and_applies_retention(app):
    client, ctx = app
    eta = datetime.now(timezone.utc)
    case = _case(client, eta)
    later = eta + timedelta(hours=ctx.cfg.case_max_hours, minutes=5)
    ctx.run_scheduler_once(later)
    c = ctx.store.get_case(case["id"])
    assert c.state == "expired" and c.subscriptions_deleted and c.pii_purged_at and ctx.store.list_subs() == []
    stats = ctx.run_scheduler_once(later + timedelta(days=ctx.cfg.retention_days + 1))
    assert stats["deleted"] == 1 and ctx.store.get_case(case["id"]) is None


def test_scheduler_thread_starts_and_stops(app):
    _, ctx = app
    s = Scheduler(ctx, interval_s=0.05)
    s.start()
    try:
        import time

        deadline = time.time() + 3
        while s.runs == 0 and time.time() < deadline:
            time.sleep(0.02)
        assert s.runs >= 1 and s.status()["running"]
    finally:
        s.stop()
    assert not s.status()["running"]
    assert Scheduler(ctx, 0).start() is None  # 0 → kapalı


def test_sqlite_backend_end_to_end(make_app, tmp_path):
    client, ctx = make_app(store_backend="sqlite", db_path=str(tmp_path / "e2e.db"))
    eta = datetime.now(timezone.utc)
    case = _case(client, eta)
    client.post(f"/v1/cases/{case['id']}/events", json={"type": "roaming_on", "now": eta.isoformat(), "data": {"country": 90}})
    client.post(f"/v1/cases/{case['id']}/events", json={"type": "driver_verify", "data": {"device_token": SIM_DEVICE_PREFIX + DRIVER}})
    r = client.post(f"/v1/cases/{case['id']}/events", json={"type": "driver_call", "data": {"caller_phone": DRIVER}}).json()
    assert r["case"]["state"] == "contacted"
    assert ctx.store.get_case(case["id"]).first_contact_at  # kalıcı depoya yazıldı
    d = client.post("/v1/demo/happy-path", json={}).json()
    assert d["case"]["state"] == "closed"
