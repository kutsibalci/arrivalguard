"""Sürücü cihaz doğrulaması: Number Verification 3-legged OIDC akışı (fixture, simülatör HTTP, canlı sahte HTTP)."""
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from arrivalguard.nac_client import SIM_CODE_PREFIX, SIM_DEVICE_PREFIX, FixtureBackend, NacClient, NacConfig, NacError, NumberVerificationAuth
from arrivalguard.nac_client.oidc import DEFAULT_SCOPE

from .conftest import DRIVER, IMPOSTOR
from .test_api import arrive, mk

REDIRECT = "https://ag.test/driver/nv/callback"


def _qs(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def _local(url: str) -> str:
    parts = urlsplit(url)
    return parts.path + (f"?{parts.query}" if parts.query else "")


def _open_case(client, ctx):
    case, eta = mk(client)
    arrive(client, case, eta)
    return case, ctx.store.get_case(case["id"]).driver_token


def _run_flow(client, token, sim_line=None):
    """Sürücü butona basar → operatör (fixture: doğrudan) → callback → sürücü sayfası. Son yönlendirmeyi döner."""
    start = client.get(f"/v1/driver/{token}/nv/start", params={"sim_line": sim_line} if sim_line else None, follow_redirects=False)
    assert start.status_code == 303, start.text
    assert start.headers["location"].startswith(REDIRECT)
    back = client.get(_local(start.headers["location"]), follow_redirects=False)
    assert back.status_code == 303
    return back.headers["location"]


# ------------------------------------------------------------------ API akışı (fixture modu)
def test_oidc_flow_verifies_driver_and_sends_meeting_code(client, ctx):
    case, token = _open_case(client, ctx)
    assert _run_flow(client, token) == f"/driver/{token}?nv=ok"
    stored = ctx.store.get_case(case["id"])
    assert stored.driver_verified_at and stored.meeting_code
    assert any(e.get("method") == "oidc" for e in stored.timeline if e.get("event") == "driver_verify")
    assert client.get(f"/v1/driver/{token}").json()["verified"] is True


def test_oidc_flow_rejects_other_device(client, ctx):
    case, token = _open_case(client, ctx)
    assert _run_flow(client, token, sim_line=IMPOSTOR) == f"/driver/{token}?nv=fail"
    stored = ctx.store.get_case(case["id"])
    assert not stored.driver_verified_at
    assert any("Sürücü cihaz doğrulaması başarısız" in a["title"] for a in stored.alerts)


def test_oidc_state_is_single_use_and_unknown_state_rejected(client, ctx):
    _, token = _open_case(client, ctx)
    start = client.get(f"/v1/driver/{token}/nv/start", follow_redirects=False)
    cb = _local(start.headers["location"])
    assert client.get(cb, follow_redirects=False).status_code == 303
    assert client.get(cb, follow_redirects=False).status_code == 400  # tekrar oynatma
    assert client.get("/driver/nv/callback?state=uydurma&code=sim-code:%2B447700900101").status_code == 400


def test_oidc_state_expires(client, ctx):
    from datetime import timedelta

    _, token = _open_case(client, ctx)
    start = client.get(f"/v1/driver/{token}/nv/start", follow_redirects=False)
    base = ctx.now()
    ctx.clock = lambda: base + timedelta(minutes=11)
    assert client.get(_local(start.headers["location"]), follow_redirects=False).status_code == 400


def test_oidc_operator_error_sends_driver_back_with_hint(client, ctx):
    _, token = _open_case(client, ctx)
    state = _qs(client.get(f"/v1/driver/{token}/nv/start", follow_redirects=False).headers["location"])["state"]
    r = client.get("/driver/nv/callback", params={"state": state, "error": "access_denied"}, follow_redirects=False)
    assert r.headers["location"] == f"/driver/{token}?nv=network"


def test_oidc_forged_code_is_not_verified(client, ctx):
    case, token = _open_case(client, ctx)
    state = _qs(client.get(f"/v1/driver/{token}/nv/start", follow_redirects=False).headers["location"])["state"]
    r = client.get("/driver/nv/callback", params={"state": state, "code": "uydurma"}, follow_redirects=False)
    assert r.headers["location"] == f"/driver/{token}?nv=error"
    assert not ctx.store.get_case(case["id"]).driver_verified_at


def test_oidc_start_with_invalid_link_or_line(client, ctx):
    assert client.get("/v1/driver/yok/nv/start", follow_redirects=False).status_code == 404
    _, token = _open_case(client, ctx)
    assert client.get(f"/v1/driver/{token}/nv/start", params={"sim_line": "abc"}, follow_redirects=False).status_code == 400


def test_redirect_uri_can_be_overridden(client, ctx, monkeypatch):
    monkeypatch.setenv("NAC_NV_REDIRECT_URI", "https://public.example/driver/nv/callback")
    _, token = _open_case(client, ctx)
    loc = client.get(f"/v1/driver/{token}/nv/start", follow_redirects=False).headers["location"]
    assert loc.startswith("https://public.example/driver/nv/callback?")


# ------------------------------------------------------------------ simülatör HTTP yolu
def test_simulator_serves_the_same_oidc_flow():
    import arrivalguard.simulator.app as sim

    sim.fx = FixtureBackend({DRIVER: {}, IMPOSTOR: {}})
    http = TestClient(sim.app, base_url="http://sim")
    nac = NacClient(NacConfig(mode="simulator", base_url="http://sim", rapidapi_key="k"), http=http)
    nv = NumberVerificationAuth(nac)
    for device, expected in ((None, True), (IMPOSTOR, False)):
        url = nv.authorization_url(login_hint=DRIVER, redirect_uri=REDIRECT, state="s1", sim_line=device)
        q = _qs(url)
        assert q["login_hint"] == DRIVER and q["scope"] == DEFAULT_SCOPE and q["client_id"] == "sim-client"
        back = http.get(_local(url), follow_redirects=False)
        assert back.status_code == 302 and back.headers["location"].startswith(REDIRECT)
        code = _qs(back.headers["location"])["code"]
        device_token = nv.exchange_code(code, REDIRECT)
        assert device_token == SIM_DEVICE_PREFIX + (device or DRIVER)
        assert nac.number_verify(DRIVER, device_token=device_token).data["devicePhoneNumberVerified"] is expected
    with pytest.raises(NacError) as e:
        nv.exchange_code("uydurma", REDIRECT)
    assert e.value.kind == "bad_request"


# ------------------------------------------------------------------ canlı mod (sahte Nokia)
def _live_nv(seen: list):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"authorization_endpoint": "https://op.example/authorize",
                                             "token_endpoint": "https://op.example/token"})
        if req.url.path == "/oauth2/v1/auth/clientcredentials":
            return httpx.Response(200, json={"client_id": "cid", "client_secret": "csecret"})
        if req.url.host == "op.example" and req.url.path == "/token":
            form = parse_qs(req.content.decode())
            if form.get("code") == ["good"] and form.get("client_secret") == ["csecret"]:
                return httpx.Response(200, json={"access_token": "live-device-token", "token_type": "Bearer"})
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(404)

    http = httpx.Client(base_url="https://nac.example/", transport=httpx.MockTransport(handler))
    nac = NacClient(NacConfig(mode="live", base_url="https://nac.example", rapidapi_key="rk"), http=http)
    return NumberVerificationAuth(nac)


def test_live_authorization_url_and_token_exchange():
    seen: list[httpx.Request] = []
    nv = _live_nv(seen)
    url = nv.authorization_url(login_hint="+44 7700 900101", redirect_uri=REDIRECT, state="st")
    assert url.startswith("https://op.example/authorize?")
    q = _qs(url)
    assert q == {"response_type": "code", "client_id": "cid", "redirect_uri": REDIRECT, "scope": DEFAULT_SCOPE,
                 "state": "st", "login_hint": DRIVER}
    assert all(r.headers.get("x-rapidapi-key") == "rk" for r in seen)
    assert nv.exchange_code("good", REDIRECT) == "live-device-token"
    with pytest.raises(NacError) as e:
        nv.exchange_code("bad", REDIRECT)
    assert e.value.kind == "bad_request"
    discovery_calls = [r for r in seen if r.url.host == "nac.example"]
    assert len(discovery_calls) == 2  # keşif önbellekte: yeniden çağrılmaz


def test_live_mode_refuses_simulated_device_line():
    nv = _live_nv([])
    with pytest.raises(NacError):
        nv.authorization_url(login_hint=DRIVER, redirect_uri=REDIRECT, state="st", sim_line=IMPOSTOR)
    with pytest.raises(NacError):
        nv.exchange_code(SIM_CODE_PREFIX + DRIVER, REDIRECT)


def test_live_route_rejects_sim_line(make_app):
    client, ctx = make_app()
    case, token = _open_case(client, ctx)
    ctx.nac.cfg.mode = "live"
    try:
        r = client.get(f"/v1/driver/{token}/nv/start", params={"sim_line": IMPOSTOR}, follow_redirects=False)
        assert r.status_code == 400
    finally:
        ctx.nac.cfg.mode = "fixture"


def test_empty_env_values_fall_back_to_defaults(monkeypatch):
    """`.env`'de boş bırakılan PUBLIC_BASE_URL bağlantıları göreli yapmamalı (SMS'teki sürücü/rıza linki, OIDC redirect)."""
    from arrivalguard.api.settings import Settings

    for name in ("PUBLIC_BASE_URL", "DB_PATH", "LLM_MODEL"):
        monkeypatch.setenv(name, "")
    s = Settings.from_env()
    assert s.public_base_url == "http://127.0.0.1:8000" and s.db_path and s.llm_model
