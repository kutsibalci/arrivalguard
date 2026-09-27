"""nac_client çekirdek testleri: fixture modu, retry/circuit breaker, maskeleme, simülatör HTTP yolu."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from arrivalguard.nac_client import (
    REACHABILITY_DISCONNECTED,
    ROAMING_CHANGE_COUNTRY,
    ROAMING_ON,
    SIM_DEVICE_PREFIX,
    FixtureBackend,
    NacCircuitOpen,
    NacClient,
    NacConfig,
    NacError,
    hash_phone,
    mask_phone,
)
from arrivalguard.nac_client.privacy import normalize_phone
from arrivalguard.nac_client.resilience import CircuitBreaker

NOW = datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)

PROFILES = {
    "+447700900201": {"recycled_date": "2026-06-30", "tenure_since": "2026-06-30", "call_forwarding": ["unconditional"], "sim_swap_at": "2026-08-15T20:00:00Z", "age_check": "false", "location": {"lat": 41.0, "lng": 29.0, "radius": 300}},
    "+447700900202": {"fail": 500},
    "+447700900203": {"latency_ms": 50},
}


@pytest.fixture
def client():
    return NacClient(NacConfig(mode="fixture", retries=1, breaker_threshold=2, breaker_cooldown_s=60), fixtures=FixtureBackend(PROFILES, now=lambda: NOW))


def test_mask_and_hash():
    assert mask_phone("+447700900301") == "+44770***0301"
    assert mask_phone("+44 7700 900301") == "+44770***0301" and mask_phone("abc") == "***"
    assert hash_phone("+447700900301", "s") == hash_phone("+44 7700 900301", "s")
    assert hash_phone("+447700900301", "s") != hash_phone("+447700900302", "s")
    with pytest.raises(ValueError):
        normalize_phone("abc")


def test_number_recycling_relative_to_specified_date(client):
    assert client.number_recycling("+447700900201", "2026-01-01").data["phoneNumberRecycled"] is True
    assert client.number_recycling("+447700900201", "2026-07-15").data["phoneNumberRecycled"] is False
    assert client.number_recycling("+447700900399", "2020-01-01").data["phoneNumberRecycled"] is False


def test_call_forwarding_and_sim_swap(client):
    assert client.unconditional_call_forwarding("+447700900201").data["active"] is True
    assert client.call_forwardings("+447700900399").data == ["inactive"]
    assert client.sim_swap_check("+447700900201", 72).data["swapped"] is True
    assert client.sim_swap_check("+447700900201", 1).data["swapped"] is False


def test_kyc(client):
    assert client.kyc_tenure("+447700900201", "2026-01-01").data["tenureDateCheck"] is False  # hat 30 Haziran'da alındı, Ocak'tan beri değil
    assert client.kyc_tenure("+447700900201", "2026-08-01").data["tenureDateCheck"] is True
    assert client.kyc_age("+447700900201", 18).data["ageCheck"] == "false"
    assert client.kyc_age("+447700900399", 18).data["ageCheck"] == "true"


def test_location_verify(client):
    assert client.location_verify("+447700900201", 41.0, 29.0, 1000).data["verificationResult"] == "TRUE"
    assert client.location_verify("+447700900201", 41.05, 29.0, 1000).data["verificationResult"] == "FALSE"
    assert client.location_verify("+447700900399", 41.0, 29.0, 1000).data["verificationResult"] == "UNKNOWN"


def test_result_masks_phone_in_request_summary(client):
    r = client.reachability("+447700900201")
    assert r.request["device"]["phoneNumber"] == "+44770***0201"
    assert r.source == "fixture" and r.latency_ms >= 0


def test_retry_then_circuit_opens(client):
    with pytest.raises(NacError) as e:
        client.reachability("+447700900202")
    assert e.value.kind == "server"
    # breaker_threshold=2 → ilk çağrı 1+1 retry = 2 hata → devre açık
    with pytest.raises(NacCircuitOpen):
        client.reachability("+447700900202")
    assert client.health()["breaker"]["device-reachability-status"]["open"] is True


def test_simulator_http_roundtrip():
    """NacClient (simulator modu) → yerel simülatör (TestClient) → aynı fixture; gerçek path'ler doğrulanır."""
    c, _ = _sim_client()
    assert c.number_recycling("+447700900201", "2026-01-01").data["phoneNumberRecycled"] is True
    assert c.unconditional_call_forwarding("+447700900201").data["active"] is True
    assert c.reachability("+447700900201").data["reachable"] is True
    sub = c.geofence_subscribe("+447700900201", 41.0, 29.0, 500, "http://sink.local/webhook", sink_token="abc").data
    assert sub["status"] == "ACTIVE" and sub["id"]
    assert c.geofence_get(sub["id"]).data["id"] == sub["id"]
    assert c.geofence_delete(sub["id"]).data["id"] == sub["id"]
    with pytest.raises(NacError) as e:
        c.reachability("+447700900202")
    assert e.value.kind == "server"


def _sim_client(**cfg):
    import arrivalguard.simulator.app as sim

    sim.fx = FixtureBackend(PROFILES | {"+447700900101": {"number_verified": True}}, now=lambda: NOW)
    http = TestClient(sim.app, base_url="http://sim")
    return NacClient(NacConfig(mode="simulator", base_url="http://sim", rapidapi_key="k", oauth_token="t", **cfg), http=http), sim


def test_number_verify_uses_device_token_as_the_device_line(client):
    """Number Verification isteği yapan CİHAZIN hattını doğrular: token başka hattınsa false."""
    assert client.number_verify("+447700900101", device_token=SIM_DEVICE_PREFIX + "+447700900101").data["devicePhoneNumberVerified"] is True
    assert client.number_verify("+447700900101", device_token=SIM_DEVICE_PREFIX + "+447700900109").data["devicePhoneNumberVerified"] is False


def test_number_verify_sends_device_token_as_bearer_over_http():
    c, _ = _sim_client()
    ok = c.number_verify("+447700900101", device_token=SIM_DEVICE_PREFIX + "+447700900101")
    bad = c.number_verify("+447700900101", device_token=SIM_DEVICE_PREFIX + "+447700900100")
    assert ok.data["devicePhoneNumberVerified"] is True and bad.data["devicePhoneNumberVerified"] is False
    assert c._headers("passthrough/x", "dev-tok")["authorization"] == "Bearer dev-tok"
    assert c._headers("passthrough/x")["authorization"] == "Bearer t"
    assert "authorization" not in c._headers("device-status/x")


def test_device_status_subscriptions_are_single_type_and_simulator_enforces_it():
    c, sim = _sim_client()
    for t in (ROAMING_ON, ROAMING_CHANGE_COUNTRY):
        body = c.roaming_subscribe("+447700900201", "http://sink.local/roaming", t, sink_token="tok").request
        assert body["types"] == [t]
    assert c.reachability_subscribe("+447700900201", "http://sink.local/r", REACHABILITY_DISCONNECTED).request["types"] == [REACHABILITY_DISCONNECTED]
    http = TestClient(sim.app)
    r = http.post("/device-status/device-roaming-status-subscriptions/v0.8/subscriptions",
                  json={"sink": "http://x", "types": [ROAMING_ON, ROAMING_CHANGE_COUNTRY], "config": {}})
    assert r.status_code == 422  # Nokia canlı davranışı (09.09.2026)


def test_simulator_emit_delivers_with_sink_credential(monkeypatch):
    c, sim = _sim_client()
    sub = c.roaming_subscribe("+447700900201", "http://sink.local/roaming", ROAMING_ON, sink_token="sink-secret").data
    assert "sinkCredential" not in sub  # yanıtta kimlik bilgisi yok
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, headers=headers, body=json)

        class R:
            status_code = 200
        return R()

    monkeypatch.setattr(sim.httpx, "post", fake_post)
    out = TestClient(sim.app).post("/_sim/emit", json={"subscription_id": sub["id"], "type": ROAMING_ON, "extra": {"countryCode": 90}}).json()
    assert out["delivered"][0]["status"] == 200
    assert seen["headers"]["authorization"] == "Bearer sink-secret" and seen["body"]["data"]["countryCode"] == 90


def test_consent_purpose_is_dpv_term(client):
    r = client.consent("+447700900201", ["sim-swap"])
    assert r.request["purpose"] == "dpv:ServiceProvision" and r.data["statusInfo"][0]["statusValidForProcessing"] is True


def test_breaker_half_open_allows_single_trial():
    b = CircuitBreaker(failure_threshold=1, cooldown_s=0)
    b.failure("api")
    b.before("api")  # soğuma bitti → tek deneme izni
    with pytest.raises(NacCircuitOpen):
        b.before("api")  # deneme sürerken ikinci çağrı reddedilir
    b.success("api")
    b.before("api")
    assert b.snapshot()["api"]["open"] is False
    b.reset()
    assert b.snapshot() == {}
