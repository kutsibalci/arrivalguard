"""ArrivalGuard API testleri — TestClient, NAC fixture modu (HTTP yok), her test kendi uygulaması."""
from datetime import datetime, timedelta, timezone

import pytest

from arrivalguard.api.settings import Settings
from arrivalguard.nac_client import GEOFENCE_ENTERED, GEOFENCE_LEFT, REACHABILITY_DISCONNECTED, ROAMING_CHANGE_COUNTRY, ROAMING_ON, SIM_DEVICE_PREFIX

from .conftest import DRIVER, IMPOSTOR, PATIENT, TOKEN

AUTH = {"Authorization": f"Bearer {TOKEN}"}


def mk(client, phone=PATIENT, eta=None, consent=True, headers=None, **kw):
    eta = eta or datetime.now(timezone.utc)
    body = {
        "patient_name": "Layla A.", "patient_phone": phone, "language": "en", "clinic_id": "clinic-1", "driver_id": "drv-1",
        "itinerary": {"destination_country": 90,
                      "legs": [{"country": 974, "eta": (eta - timedelta(hours=4)).isoformat()},
                               {"country": 90, "eta": eta.isoformat()}]},
        "family_contact": {"name": "Ahmed", "phone": "+447700900099", "language": "en"},
        **({"consent": {"method": "clinic_form"}} if consent else {}),
        **kw,
    }
    r = client.post("/v1/cases", json=body, headers=headers or {})
    assert r.status_code == 201, r.text
    return r.json(), eta


def ce(sub_id, etype, phone=PATIENT, at=None, ce_id="ce-1", **data):
    return {"id": ce_id, "source": "test", "specversion": "1.0", "type": etype,
            "time": (at or datetime.now(timezone.utc)).isoformat(),
            "data": {"subscriptionId": sub_id, "device": {"phoneNumber": phone}, **data}}


def arrive(client, case, eta):
    r = client.post("/webhooks/roaming", json=ce(case["subscriptions"]["roaming:roaming-on"], ROAMING_ON, at=eta, ce_id="arr", countryCode=90),
                    headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ vaka kurulumu + abonelikler
def test_create_case_subscribes_one_type_per_subscription_and_masks_phone(client):
    case, _ = mk(client)
    assert case["state"] == "waiting" and case["consent"]["status"] == "granted"
    assert set(case["subscriptions"]) == {"roaming:roaming-on", "roaming:roaming-change-country", "reachability:disconnected",
                                          "reachability:data", "geofence:airport", "geofence:corridor", "geofence:clinic"}
    assert case["patient"]["phone_masked"] == "+44770***0001" and PATIENT not in str(case)
    assert case["driver"]["phone_masked"] == "+44770***0101" and DRIVER not in str(case)
    calls = client.get("/v1/_debug/calls?limit=50").json()
    subs = [c for c in calls if c["api"].endswith("-subscriptions")]
    status_subs = [c for c in subs if c["api"].startswith("device-")]
    assert len(status_subs) == 4 and all(len(c["request"]["types"]) == 1 for c in status_subs)  # Nokia device-status v0.8: types tek eleman
    roam = next(c for c in subs if c["api"] == "device-roaming-status-subscriptions")
    assert roam["request"]["sink"] == "https://ag.test/webhooks/roaming"
    assert roam["request"]["sinkCredential"]["accessToken"] == TOKEN
    assert roam["request"]["config"]["subscriptionDetail"]["device"]["phoneNumber"] == "+44770***0001"
    assert "sinkCredential" not in roam["response"]  # kimlik bilgisi geri dönmez
    assert PATIENT not in client.get("/v1/_debug/calls").text


def test_create_case_validation(client):
    body = {"patient_name": "X", "patient_phone": "abc", "clinic_id": "clinic-1",
            "itinerary": {"destination_country": 90, "legs": [{"country": 90, "eta": "2026-09-01T10:00:00Z"}]}}
    r = client.post("/v1/cases", json=body)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_ARGUMENT"
    assert client.post("/v1/cases", json=body | {"patient_phone": PATIENT, "language": "de"}).status_code == 422
    bad_itin = body | {"patient_phone": PATIENT, "itinerary": {"destination_country": 90, "legs": [{"country": 974, "eta": "2026-09-01T10:00:00Z"}]}}
    assert client.post("/v1/cases", json=bad_itin).status_code == 422
    assert client.post("/v1/cases", json=body | {"patient_phone": PATIENT, "clinic_id": "yok"}).status_code == 404
    assert client.post("/v1/cases", json=body | {"patient_phone": PATIENT, "driver_id": "drv-99"}).status_code == 400


# ------------------------------------------------------------------ rıza akışı
def test_consent_flow_accept_then_withdraw_deletes_subscriptions_and_pii(client, ctx):
    case, _ = mk(client, consent=False)
    assert case["state"] == "pending_consent" and case["subscriptions"] == {}
    token = case["consent_link"].rsplit("/", 1)[1]
    assert case["messages"][0]["kind"] == "consent_request" and token not in str(case["messages"])
    info = client.get(f"/v1/consent/{token}").json()
    assert info["clinic_name"] == "İstanbul Estetik Kliniği" and info["stored_locations"] == 0 and info["status"] == "pending"
    assert client.get(f"/consent/{token}").status_code == 200

    r = client.post(f"/v1/consent/{token}", json={"decision": "accept"})
    assert r.status_code == 200 and r.json()["state"] == "waiting"
    assert len(client.get(f"/v1/cases/{case['id']}").json()["subscriptions"]) == 7
    assert client.post(f"/v1/consent/{token}", json={"decision": "accept"}).status_code == 409

    r = client.post(f"/v1/consent/{token}", json={"decision": "withdraw"})
    assert r.json()["state"] == "withdrawn"
    after = client.get(f"/v1/cases/{case['id']}").json()
    assert after["subscriptions_deleted"] and after["pii_purged_at"]
    assert ctx.store.list_subs() == [] and ctx.store.get_case(case["id"]).patient_phone is None
    assert client.get(f"/v1/consent/{token}").status_code == 404  # token silindi


def test_consent_decline_and_bad_token(client):
    case, _ = mk(client, consent=False)
    token = case["consent_link"].rsplit("/", 1)[1]
    assert client.post(f"/v1/consent/{token}", json={"decision": "decline"}).json()["state"] == "declined"
    assert client.get("/v1/consent/uydurma-token").status_code == 404
    assert client.post(f"/v1/cases/{case['id']}/events", json={"type": "consent_granted"}).status_code == 400


# ------------------------------------------------------------------ webhook'lar
def test_roaming_webhook_requires_bearer(client):
    case, eta = mk(client)
    body = ce(case["subscriptions"]["roaming:roaming-on"], ROAMING_ON, at=eta, countryCode=90)
    assert client.post("/webhooks/roaming", json=body).status_code == 401
    assert client.post("/webhooks/roaming", json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = client.post("/webhooks/roaming", json=body, headers=AUTH)
    assert r.status_code == 200 and r.json()["case"]["state"] == "released"


def test_roaming_on_without_country_is_completed_by_poll(client):
    case, eta = mk(client)
    r = client.post("/webhooks/roaming", json=ce(case["subscriptions"]["roaming:roaming-on"], ROAMING_ON, at=eta), headers=AUTH).json()
    assert r["case"]["state"] == "released"
    roaming_entry = next(e for e in r["case"]["timeline"] if e["event"] == "roaming_on")
    assert roaming_entry["source"].startswith("webhook+poll(")


def test_unknown_subscription_404_and_dedupe(client):
    case, eta = mk(client)
    assert client.post("/webhooks/roaming", json=ce("nope", ROAMING_ON, phone="+447700900199"), headers=AUTH).status_code == 404
    body = ce(case["subscriptions"]["roaming:roaming-change-country"], ROAMING_CHANGE_COUNTRY, at=eta, ce_id="dup", countryCode=90)
    assert client.post("/webhooks/roaming", json=body, headers=AUTH).status_code == 200
    assert client.post("/webhooks/roaming", json=body, headers=AUTH).json()["duplicate"] is True


def test_transit_country_does_not_release_pickup(client):
    case, eta = mk(client)
    body = ce(case["subscriptions"]["roaming:roaming-change-country"], ROAMING_CHANGE_COUNTRY, at=eta - timedelta(hours=4), ce_id="t", countryCode=974)
    r = client.post("/webhooks/roaming", json=body, headers=AUTH).json()
    assert r["entry"]["decision"] == "transit" and r["case"]["state"] == "waiting"
    assert [m["kind"] for m in r["case"]["messages"]][-1] == "transit_greeting"


def test_geofence_clinic_closes_case_and_cleans_up(client, ctx):
    case, eta = mk(client)
    arrive(client, case, eta)
    r = client.post("/webhooks/geofence", json=ce(case["subscriptions"]["geofence:clinic"], GEOFENCE_ENTERED, ce_id="g"), headers=AUTH).json()
    assert r["case"]["state"] == "closed" and r["entry"]["rule"] == "geofence.clinic_entered"
    assert r["case"]["subscriptions_deleted"] and r["case"]["pii_purged_at"]
    assert ctx.store.list_subs() == [] and ctx.nac.fx.subscriptions == {}
    fam = [m for m in r["case"]["messages"] if m["to"] == "family"]
    assert fam and fam[0]["status"] == "sent"


def test_geofence_left_corridor_uses_stationary_minutes(client):
    case, eta = mk(client)
    arrive(client, case, eta)
    client.post(f"/v1/cases/{case['id']}/events", json={"type": "driver_verify", "data": {"device_token": SIM_DEVICE_PREFIX + DRIVER}})
    client.post(f"/v1/cases/{case['id']}/events", json={"type": "driver_call", "data": {"caller_phone": DRIVER}})
    client.post(f"/v1/cases/{case['id']}/events", json={"type": "geofence_left", "data": {"zone": "airport"}})
    r = client.post("/webhooks/geofence", json=ce(case["subscriptions"]["geofence:corridor"], GEOFENCE_LEFT, ce_id="l", stationary_min=15),
                    headers=AUTH).json()
    assert r["entry"]["decision"] == "trouble" and r["case"]["state"] == "escalated"


def test_reachability_webhook_feeds_same_signal_logic(client):
    case, eta = mk(client)
    arrive(client, case, eta)
    r = client.post("/webhooks/reachability", json=ce(case["subscriptions"]["reachability:disconnected"], REACHABILITY_DISCONNECTED, ce_id="r"),
                    headers=AUTH).json()
    assert r["entry"]["decision"] == "raise" and r["case"]["unreachable_since"]


def test_unsupported_type_and_subscription_end(client):
    case, eta = mk(client)
    bad = ce(case["subscriptions"]["geofence:clinic"], "org.example.nonsense", ce_id="bad")
    assert client.post("/webhooks/geofence", json=bad, headers=AUTH).status_code == 400
    ends = ce(case["subscriptions"]["roaming:roaming-on"], "org.camaraproject.device-roaming-status-subscriptions.v0.subscription-ends", ce_id="e")
    r = client.post("/webhooks/roaming", json=ends, headers=AUTH).json()
    assert r["handled"] == "subscription-ends"
    assert "İzleme boşluğu" in client.get(f"/v1/cases/{case['id']}").json()["alerts"][-1]["title"]


# ------------------------------------------------------------------ sürücü bağlantısı
def test_driver_link_verification(client, ctx):
    case, eta = mk(client)
    arrive(client, case, eta)
    token = ctx.store.get_case(case["id"]).driver_token
    info = client.get(f"/v1/driver/{token}").json()
    assert info["verified"] is False and info["sim_device_prefix"] == SIM_DEVICE_PREFIX and "phone" not in str(info)
    assert client.get(f"/driver/{token}").status_code == 200
    bad = client.post(f"/v1/driver/{token}/verify", json={"device_token": SIM_DEVICE_PREFIX + IMPOSTOR}).json()
    assert bad["ok"] is False and bad["decision"] == "driver_rejected"
    ok = client.post(f"/v1/driver/{token}/verify", json={"device_token": SIM_DEVICE_PREFIX + DRIVER}).json()
    assert ok["ok"] is True and ok["meeting_code_sent"]
    msgs = client.get(f"/v1/cases/{case['id']}").json()["messages"]
    assert any(m["kind"] == "driver_verified" and "••••" in m["text"] for m in msgs)
    assert client.post("/v1/driver/yok/verify", json={}).status_code == 404


# ------------------------------------------------------------------ koordinatör aksiyonları
def test_coordinator_actions(client):
    case, eta = mk(client, phone="+447700900003")  # SIM yeni değişmiş → frozen
    frozen = arrive(client, case, eta)["case"]
    assert frozen["state"] == "frozen"
    alert_id = frozen["alerts"][0]["id"]
    r = client.post(f"/v1/cases/{case['id']}/actions", json={"action": "ack_alert", "alert_id": alert_id}).json()
    assert r["case"]["alerts"][0]["acknowledged_by"] == "dev"
    assert client.post(f"/v1/cases/{case['id']}/actions", json={"action": "manual_release"}).status_code == 400
    r = client.post(f"/v1/cases/{case['id']}/actions", json={"action": "manual_release", "reason": "Hasta geri arandı, kimlik teyit"})
    assert r.json()["case"]["integrity"] == "released_manual"
    assert client.post(f"/v1/cases/{case['id']}/actions", json={"action": "reassign_driver", "driver_id": "drv-2"}).json()["case"]["driver"]["name"] == "Ayşe K."
    assert client.post(f"/v1/cases/{case['id']}/actions", json={"action": "uydur"}).status_code == 422
    r = client.post(f"/v1/cases/{case['id']}/actions", json={"action": "close_case", "reason": "hasta kendi geldi"}).json()
    assert r["case"]["state"] == "closed" and r["case"]["subscriptions_deleted"]


def test_delete_case_on_request_removes_subscriptions_and_record(client, ctx):
    case, _ = mk(client)
    assert len(ctx.store.list_subs()) == 7
    assert client.delete(f"/v1/cases/{case['id']}").status_code == 204
    assert client.get(f"/v1/cases/{case['id']}").status_code == 404
    assert ctx.store.list_subs() == [] and ctx.nac.fx.subscriptions == {}
    assert client.delete(f"/v1/cases/{case['id']}").status_code == 404


def test_event_endpoint_and_audit(client):
    case, eta = mk(client)
    client.post(f"/v1/cases/{case['id']}/events", json={"type": "roaming_on", "now": eta.isoformat(), "data": {"country": 90}})
    r = client.post(f"/v1/cases/{case['id']}/events", json={"type": "driver_call", "data": {"caller_phone": IMPOSTOR}}).json()
    assert r["entry"]["decision"] == "impostor" and r["entry"]["source"] == "manual"
    a = client.get(f"/v1/cases/{case['id']}/audit").json()
    assert a["impostor_attempts"] == 1 and a["integrity"] == "released" and PATIENT not in str(a)
    assert client.get("/v1/cases").json()[0]["id"] == case["id"]
    assert client.get("/v1/cases?state=closed").json() == []
    assert client.get("/v1/cases/yok").status_code == 404
    assert client.post(f"/v1/cases/{case['id']}/events", json={"type": "uydur"}).status_code == 422


def test_state_config_reset(client):
    mk(client)
    st = client.get("/v1/state").json()
    assert st["stored_locations_count"] == 0 and len(st["subscriptions"]) == 7
    assert st["webhooks"]["token_required"] is True and set(st["webhooks"]) >= {"roaming", "geofence", "reachability"}
    assert [s["key"] for s in st["steps"]][0] == "consent"
    cfg = client.get("/v1/config").json()
    assert cfg["rules"]["escalation_budget_per_case"] == 3 and cfg["app"]["auth_enabled"] is False
    assert client.post("/v1/reset").json()["ok"] is True
    assert client.get("/v1/state").json()["cases"] == []


def test_clinics_registry_masks_phones(client):
    clinics = client.get("/v1/clinics").json()
    assert clinics[0]["id"] == "clinic-1" and DRIVER not in str(clinics) and clinics[0]["drivers"][0]["phone_masked"]
    new = {"id": "clinic-2", "name": "Ankara Göz", "zones": {z: {"lat": 39.9, "lng": 32.8, "radius": 800} for z in ("airport", "corridor", "clinic")},
           "drivers": [{"id": "d1", "name": "Ali", "phone": "+447700900102", "plate": "06 AB 1"}]}
    assert client.put("/v1/clinics/clinic-2", json=new).status_code == 200
    assert client.put("/v1/clinics/clinic-3", json=new).status_code == 400  # id uyuşmazlığı
    no_zones = new | {"id": "clinic-4", "zones": {"airport": {"lat": 1, "lng": 1, "radius": 1}}}
    assert client.put("/v1/clinics/clinic-4", json=no_zones).status_code == 400


# ------------------------------------------------------------------ kimlik doğrulama ve klinik ayrımı
ADMIN_KEY = "admin-key-0123456789abcdefgh"
CLINIC1_KEY = "clinic1-key-0123456789abcdef"
CLINIC2_KEY = "clinic2-key-0123456789abcdef"


@pytest.fixture
def secured(make_app):
    client, ctx = make_app(api_keys={ADMIN_KEY: "*", CLINIC1_KEY: "clinic-1", CLINIC2_KEY: "clinic-2"})
    ctx.save_clinic(ctx.store.get_clinic("clinic-1") | {"id": "clinic-2", "name": "İkinci Klinik"})
    return client


def test_api_key_required_and_tenant_isolation(secured):
    c = secured
    assert c.get("/v1/cases").status_code == 401
    assert c.get("/v1/cases", headers={"X-API-Key": "yanlis"}).status_code == 401
    case, _ = mk(c, headers={"X-API-Key": CLINIC1_KEY})
    assert c.get(f"/v1/cases/{case['id']}", headers={"X-API-Key": CLINIC1_KEY}).status_code == 200
    assert c.get(f"/v1/cases/{case['id']}", headers={"X-API-Key": CLINIC2_KEY}).status_code == 404
    assert c.get("/v1/cases", headers={"X-API-Key": CLINIC2_KEY}).json() == []
    assert c.get(f"/v1/cases/{case['id']}", headers={"X-API-Key": ADMIN_KEY}).status_code == 200
    r = c.post("/v1/cases", json={"patient_name": "X", "patient_phone": PATIENT, "clinic_id": "clinic-2",
                                  "itinerary": {"destination_country": 90, "legs": [{"country": 90, "eta": "2026-09-01T10:00:00Z"}]}},
               headers={"X-API-Key": CLINIC1_KEY})
    assert r.status_code == 403
    assert [x["id"] for x in c.get("/v1/clinics", headers={"X-API-Key": CLINIC2_KEY}).json()] == ["clinic-2"]


def test_admin_only_endpoints(secured):
    c = secured
    assert c.post("/v1/demo/happy-path", json={}, headers={"X-API-Key": CLINIC1_KEY}).status_code == 403
    assert c.post("/v1/demo/happy-path", json={}, headers={"X-API-Key": ADMIN_KEY}).status_code == 200
    assert c.get("/v1/_debug/calls", headers={"X-API-Key": CLINIC1_KEY}).status_code == 403
    assert c.post("/v1/scheduler/run", headers={"X-API-Key": ADMIN_KEY}).status_code == 200
    assert c.put("/v1/clinics/clinic-9", json={"id": "clinic-9", "name": "Y", "zones": {}}, headers={"X-API-Key": CLINIC1_KEY}).status_code in (403, 422)
    actor = mk(c, headers={"X-API-Key": CLINIC1_KEY})[0]["timeline"][0]["actor"]
    assert actor.startswith("clinic-1/") and CLINIC1_KEY not in actor


def test_prod_like_settings_close_demo_debug_manual(make_app):
    c, _ = make_app(enable_demo=False, enable_debug=False, enable_manual_events=False)
    assert c.post("/v1/demo/happy-path", json={}).status_code == 404
    assert c.get("/demo").status_code == 404
    assert c.get("/v1/_debug/calls").status_code == 404
    assert c.post("/v1/reset").status_code == 404
    case, _ = mk(c)
    assert c.post(f"/v1/cases/{case['id']}/events", json={"type": "tick"}).status_code == 404
    assert "scenarios" not in c.get("/").json()


def test_prod_refuses_insecure_settings(monkeypatch):
    s = Settings(app_env="prod", webhook_token="kisa")
    problems = s.problems()
    assert any("PHONE_HASH_SALT" in p for p in problems) and any("API_KEYS" in p for p in problems)
    assert any("WEBHOOK_TOKEN" in p for p in problems) and any("HTTPS" in p for p in problems)
    with pytest.raises(RuntimeError):
        s.validate()
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("PHONE_HASH_SALT", "x" * 32)
    monkeypatch.setenv("WEBHOOK_TOKEN", "w" * 32)
    monkeypatch.setenv("API_KEYS", "*:" + "a" * 32)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://ag.example")
    monkeypatch.setenv("NOTIFY_CHANNEL", "webhook")
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://bridge.example/sms")
    ok = Settings.from_env()
    assert ok.problems() == [] and ok.store_backend == "sqlite" and not ok.enable_demo and not ok.enable_debug
    ok.validate()


def test_api_keys_parse_errors():
    from arrivalguard.api.settings import _parse_api_keys

    assert _parse_api_keys("clinic-1:k1, *:k2") == {"k1": "clinic-1", "k2": "*"}
    with pytest.raises(ValueError):
        _parse_api_keys("anahtar-tek-basina")


# ------------------------------------------------------------------ demolar
def test_demo_happy_path(client):
    d = client.post("/v1/demo/happy-path", json={}).json()
    c = d["case"]
    assert c["state"] == "closed" and c["integrity"] == "released"
    decisions = [s["decision"] for s in d["timeline_steps"]]
    assert decisions[:7] == ["transit", "release_pickup", "unverified", "driver_rejected", "driver_verified", "impostor", "genuine"]
    assert decisions[-1] == "close_case"
    assert [a["level"] for a in c["alerts"]] == ["warn", "warn", "warn"]  # koordinatör hiç uyandırılmadı
    audit = d["audits"][0]
    assert audit["verified_calls"] == 1 and audit["impostor_attempts"] == 1 and audit["unverified_calls"] == 1
    assert audit["subscriptions_deleted"] and audit["pii_purged_at"] and audit["summary"]
    assert PATIENT not in str(d) and DRIVER not in str(d)


def test_demo_sim_swap_freezes(client):
    d = client.post("/v1/demo/sim-swap", json={}).json()
    c = d["case"]
    assert c["state"] == "frozen" and c["first_contact_at"] is None
    texts = " ".join(m["text"] for m in c["messages"] if m["to"] == "patient")
    assert "34 ABC 123" not in texts and not any(m["kind"] == "driver_verified" for m in c["messages"])
    assert c["escalations_used"] == 2


def test_demo_local_sim_same_signal_opposite_meaning(client):
    d = client.post("/v1/demo/local-sim", json={}).json()
    a, b = d["cases"]
    assert d["compare"]["a"]["level"] == "alarm" and d["compare"]["b"]["level"] == "lower"
    assert a["state"] == "escalated" and b["state"] == "contacted"
    assert [x["decision"] for x in d["steps"][0]][-1] == "alarm"
    assert [x["decision"] for x in d["steps"][1]][-1] == "lower"
    assert any(al["level"] == "alarm" for al in a["alerts"]) and not b["alerts"]
    assert any(m["kind"] == "local_sim_fallback" for m in b["messages"])


def test_demo_trouble_budget_exhausts(client):
    d = client.post("/v1/demo/trouble", json={}).json()
    c = d["case"]
    alarms = [al for al in c["alerts"] if al["level"] == "alarm"]
    assert len(alarms) == 3 and c["escalations_used"] == 3
    assert any("bütçe doldu" in al["title"] for al in c["alerts"] if al["level"] == "warn")
    confs = [s["confidence"] for s in d["timeline_steps"] if s["confidence"] is not None]
    assert 0.25 in confs and 0.6 in confs and 0.85 in confs


def test_demo_api_down_keeps_flow_and_flags_degraded(client):
    d = client.post("/v1/demo/api-down", json={}).json()
    assert d["case"]["state"] == "released"
    assert "server" in {x["kind"] for x in d["degraded"]}
    sources = {e["source"] for e in d["case"]["timeline"][-1]["explain"]}
    assert any(s.startswith("error(") for s in sources)
    assert any(al.get("degraded") for al in d["case"]["alerts"])
    assert d["breaker"]["breaker"]["sim-swap"]["failures"] >= 2  # testte retries=0; demo varsayılanında (retries=2) devre açılır
    assert "+447700900006" not in str(d)


def test_demo_no_signal_and_consent(client):
    d = client.post("/v1/demo/no-signal", json={}).json()
    assert d["case"]["state"] == "released" and any(a["title"] == "Varış sinyali gelmedi" for a in d["case"]["alerts"])
    d = client.post("/v1/demo/consent", json={}).json()
    c = d["case"]
    assert c["state"] == "withdrawn" and c["subscriptions_deleted"] and c["pii_purged_at"]
    assert "Rıza alınmadan" in c["timeline"][1]["note"]


# ------------------------------------------------------------------ sayfalar ve başlıklar
def test_pages_health_and_security_headers(client):
    h = client.get("/health").json()
    assert h["ok"] is True and h["store"] == "memory"
    for path, marker in (("/demo", "Aynı sinyal, zıt anlam"), ("/console", "Koordinatör"), ("/consent/x", "ArrivalGuard"), ("/driver/x", "ArrivalGuard")):
        r = client.get(path)
        assert r.status_code == 200 and marker in r.text, path
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "DENY"
    assert client.get("/consent/x").headers["cache-control"] == "no-store"
    assert client.get("/").json()["scenarios"][0] == "happy-path"


def test_subscription_ends_after_case_deleted_is_acknowledged(client):
    """Vaka silinince Nokia `subscription-ends` gönderir; 404 yerine 200 dönülür ki Nokia tekrar denemesin."""
    ends = ce("sub-gone", "org.camaraproject.geofencing-subscriptions.v0.subscription-ends", ce_id="gone")
    r = client.post("/webhooks/geofence", json=ends, headers=AUTH)
    assert r.status_code == 200 and r.json()["case_id"] is None
    other = ce("sub-gone", GEOFENCE_ENTERED, ce_id="gone-2")
    assert client.post("/webhooks/geofence", json=other, headers=AUTH).status_code == 404


# ------------------------------------------------------------------ canlı Nokia bulguları (27.09.2026)
def test_roaming_event_with_mcc_country_code_is_resolved_by_country_name(client):
    """Nokia roaming CloudEvent'i countryCode'u MCC olarak gönderir (TR → 286); countryName (ISO) esas alınır."""
    case, eta = mk(client)
    ev = ce(case["subscriptions"]["roaming:roaming-on"], ROAMING_ON, at=eta, ce_id="mcc", countryCode=286, countryName=["TR"])
    out = client.post("/webhooks/roaming", json=ev, headers=AUTH).json()
    assert out["case"]["state"] != "waiting"
    assert any(t["event"] == "roaming_on" and t["decision"] == "arrival" for t in out["case"]["timeline"])
    assert not any("Beklenmeyen roaming" in a["title"] for a in out["case"]["alerts"])


def test_silence_before_arrival_is_expected_and_does_not_carry_over(client, ctx):
    """Uçuştaki hasta ulaşılamaz: varıştan önce alarm yok; inişte sayaç sıfırdan başlar."""
    case, eta = mk(client)
    before = ce(case["subscriptions"]["reachability:disconnected"], REACHABILITY_DISCONNECTED, at=eta - timedelta(hours=3), ce_id="fly")
    r = client.post("/webhooks/reachability", json=before, headers=AUTH).json()
    assert r["entry"]["rule"] == "unreachable.before_arrival"
    ctx.run_scheduler_once(eta - timedelta(hours=1))
    stored = ctx.store.get_case(case["id"])
    assert stored.state == "waiting" and stored.unreachable_since is None
    assert not any(a["level"] == "alarm" for a in stored.alerts)
    arrive(client, case, eta)
    assert ctx.store.get_case(case["id"]).unreachable_since is None
