"""Yerel Nokia NaC simülatörü.

Gerçek path'leri (docs/nac-api-reference.md) aynı gövde/yanıt şemasıyla sunar; veriyi FixtureBackend üretir.
NAC_MODE=simulator iken NacClient buraya (http://127.0.0.1:8081) bağlanır → HTTP katmanı uçtan uca test edilir.

Ek kontrol uçları (gerçek API'de YOK, sadece demo):
  GET  /_sim/profiles                 tüm profiller
  PUT  /_sim/profiles/{phone}         profil yaz/güncelle (patch)
  POST /_sim/emit                     {subscription_id | phone, type, extra} → sink'e CloudEvent POST'lar
  POST /_sim/reset                    fixture dosyasını yeniden yükle

Number Verification OIDC (gerçek API ile aynı uçlar; simüle cihaz, kodu anında döner):
  GET  /.well-known/openid-configuration
  GET  /oauth2/v1/auth/clientcredentials
  GET  /oauth2/v1/authorize?...&sim_line=   → redirect_uri?code=sim-code:<hat>&state=
  POST /oauth2/v1/token                      → access_token = sim-device:<hat>
SIM_PUBLIC_URL: tarayıcının simülatöre ulaştığı adres (docker'da http://127.0.0.1:8081).
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import httpx
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import data_path
from ..nac_client.client import SIM_DEVICE_PREFIX, sim_device_line
from ..nac_client.errors import NacError
from ..nac_client.fixtures import FixtureBackend
from ..nac_client.oidc import SIM_CODE_PREFIX
from ..nac_client.privacy import normalize_phone

FIXTURE_PATH = os.environ.get("NAC_FIXTURE_PATH") or str(data_path("profiles.json"))

app = FastAPI(title="Local NaC Simulator", version="0.2")
fx = FixtureBackend.from_json(FIXTURE_PATH) if Path(FIXTURE_PATH).exists() else FixtureBackend()


@app.exception_handler(NacError)
def _nac_err(_: Request, e: NacError):
    return JSONResponse(status_code=e.status or 500, content={"status": e.status or 500, "code": e.kind.upper(), "message": str(e)})


def _phone(body: dict) -> str:
    p = body.get("phoneNumber") or (body.get("device") or {}).get("phoneNumber")
    if not p:
        raise HTTPException(400, {"code": "INVALID_ARGUMENT", "message": "phoneNumber gerekli"})
    fail = fx.get(p).get("fail")
    if fail == "timeout":
        time.sleep(30)
    if isinstance(fail, int):
        raise HTTPException(fail, {"code": "INJECTED", "message": "simülatör: enjekte edilmiş hata"})
    lat = fx.get(p).get("latency_ms", 0)
    if lat:
        time.sleep(lat / 1000)
    return p


def _require_bearer(request: Request):
    # Passthrough API'ler canlıda Bearer ister; simülatörde sadece uyarı üretiriz (SIM_STRICT_AUTH=1 ile zorunlu).
    if os.environ.get("SIM_STRICT_AUTH") == "1" and not request.headers.get("authorization", "").startswith("Bearer "):
        raise HTTPException(401, {"code": "UNAUTHENTICATED", "message": "Bearer token gerekli"})


# ------------------------------------------------------------------ Number Verification OIDC
SIM_CLIENT_ID = "sim-client"
SIM_CLIENT_SECRET = "sim-secret"  # noqa: S105 — yalnızca yerel simülatör


@app.get("/.well-known/openid-configuration")
def openid_configuration(request: Request):
    public = (os.environ.get("SIM_PUBLIC_URL") or str(request.base_url)).rstrip("/")
    internal = str(request.base_url).rstrip("/")
    return {"issuer": public, "authorization_endpoint": f"{public}/oauth2/v1/authorize",
            "token_endpoint": f"{internal}/oauth2/v1/token", "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "client_credentials"]}


@app.get("/oauth2/v1/auth/clientcredentials")
def client_credentials():
    return {"client_id": SIM_CLIENT_ID, "client_secret": SIM_CLIENT_SECRET}


@app.get("/oauth2/v1/authorize")
def authorize(redirect_uri: str, state: str, client_id: str, login_hint: str = "", sim_line: str = "",
              response_type: str = "code", scope: str = ""):
    """Gerçekte operatör cihazı mobil veri oturumundan tanır. Simülatörde cihazın hattı = sim_line (yoksa login_hint)."""
    if client_id != SIM_CLIENT_ID or response_type != "code":
        return RedirectResponse(f"{redirect_uri}?{urlencode({'error': 'unauthorized_client', 'state': state})}", status_code=302)
    line = sim_line or login_hint
    if not line:
        return RedirectResponse(f"{redirect_uri}?{urlencode({'error': 'access_denied', 'state': state})}", status_code=302)
    return RedirectResponse(f"{redirect_uri}?{urlencode({'code': SIM_CODE_PREFIX + normalize_phone(line), 'state': state})}",
                            status_code=302)


@app.post("/oauth2/v1/token")
async def token(request: Request):
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}  # python-multipart bağımlılığı olmadan
    grant_type, code = form.get("grant_type", ""), form.get("code", "")
    client_id, client_secret = form.get("client_id", ""), form.get("client_secret", "")
    if client_id != SIM_CLIENT_ID or client_secret != SIM_CLIENT_SECRET:
        raise HTTPException(401, {"error": "invalid_client"})
    if grant_type != "authorization_code" or not code.startswith(SIM_CODE_PREFIX):
        raise HTTPException(400, {"error": "invalid_grant"})
    return {"access_token": SIM_DEVICE_PREFIX + code[len(SIM_CODE_PREFIX):], "token_type": "Bearer", "expires_in": 300}


PT = "/passthrough/camara/v1"


@app.post(f"{PT}/number-recycling/number-recycling/v0.2/check")
def number_recycling(request: Request, body: dict = Body(...)):
    _require_bearer(request)
    return fx.number_recycling(_phone(body), body.get("specifiedDate"))


@app.post(f"{PT}/call-forwarding-signal/call-forwarding-signal/v0.3/call-forwardings")
def call_forwardings(request: Request, body: dict = Body(...)):
    _require_bearer(request)
    return fx.call_forwardings(_phone(body))


@app.post(f"{PT}/call-forwarding-signal/call-forwarding-signal/v0.3/unconditional-call-forwardings")
def unconditional_cf(request: Request, body: dict = Body(...)):
    _require_bearer(request)
    return fx.unconditional_call_forwarding(_phone(body))


@app.post(f"{PT}/kyc-tenure/kyc-tenure/v0.1/check-tenure")
def kyc_tenure(request: Request, body: dict = Body(...)):
    _require_bearer(request)
    return fx.kyc_tenure(_phone(body), body.get("tenureDate"))


def _snake_fields(body: dict, exclude=("phoneNumber", "ageThreshold", "includeContentLock", "includeParentalControl")) -> dict:
    import re
    return {re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower(): v for k, v in body.items() if k not in exclude}


@app.post(f"{PT}/kyc-age-verification/kyc-age-verification/v0.1/verify")
def kyc_age(request: Request, body: dict = Body(...)):
    _require_bearer(request)
    return fx.kyc_age(_phone(body), int(body.get("ageThreshold", 18)), **_snake_fields(body))


@app.post(f"{PT}/kyc-match/kyc-match/v0.3/match")
def kyc_match(request: Request, body: dict = Body(...)):
    _require_bearer(request)
    return fx.kyc_match(_phone(body), **_snake_fields(body))


@app.post(f"{PT}/number-verification/number-verification/v2/verify")
def number_verify(request: Request, body: dict = Body(...)):
    # Canlıda Bearer = doğrulanan cihazın OIDC token'ı. Simülatörde `sim-device:<hat>` token'ı cihazın hattını taklit eder.
    _require_bearer(request)
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else None
    return fx.number_verify(_phone(body), device_line=sim_device_line(token))


@app.post(f"{PT}/sim-swap/sim-swap/v0/check")
def sim_swap_check(request: Request, body: dict = Body(...)):
    _require_bearer(request)
    return fx.sim_swap_check(_phone(body), body.get("maxAge"))


@app.post(f"{PT}/sim-swap/sim-swap/v0/retrieve-date")
def sim_swap_date(request: Request, body: dict = Body(...)):
    _require_bearer(request)
    return fx.sim_swap_date(_phone(body))


@app.post(f"{PT}/device-swap/device-swap/v1/check")
def device_swap_check(request: Request, body: dict = Body(...)):
    _require_bearer(request)
    return fx.device_swap_check(_phone(body), body.get("maxAge"))


@app.post(f"{PT}/device-swap/device-swap/v1/retrieve-date")
def device_swap_date(request: Request, body: dict = Body(...)):
    _require_bearer(request)
    return fx.device_swap_date(_phone(body))


@app.post(f"{PT}/consent-info/consent-info/v0.1/retrieve")
def consent(request: Request, body: dict = Body(...)):
    _require_bearer(request)
    if not isinstance(body.get("requestCaptureUrl"), bool):  # Nokia'da zorunlu (canlı 422, 27.09.2026)
        raise HTTPException(422, {"code": "INVALID_ARGUMENT", "message": "requestCaptureUrl (bool) gerekli"})
    return fx.consent(_phone(body), body.get("scopes") or [], body.get("purpose", ""))


@app.post("/device-status/device-reachability-status/v1/retrieve")
def reachability(body: dict = Body(...)):
    return fx.reachability(_phone(body))


@app.post("/device-status/device-roaming-status/v1/retrieve")
def roaming(body: dict = Body(...)):
    return fx.roaming(_phone(body))


@app.post("/location-retrieval/v0/retrieve")
def location_retrieve(body: dict = Body(...)):
    return fx.location_retrieve(_phone(body), body.get("maxAge"))


@app.post("/location-verification/v1/verify")
def location_verify(body: dict = Body(...)):
    area = body.get("area") or {}
    c = area.get("center") or {}
    return fx.location_verify(_phone(body), float(c.get("latitude")), float(c.get("longitude")), float(area.get("radius", 500)), body.get("maxAge"))


@app.post("/congestion-insights/v0/query")
def congestion_query(body: dict = Body(...)):
    return fx.congestion_query(_phone(body), body.get("start"), body.get("end"))


# ---- abonelikler -------------------------------------------------------------
def _sub_routes(prefix: str, kind: str, single_type: bool):
    @app.post(prefix, name=f"create_{kind}")
    def create(body: dict = Body(...)):
        # Nokia device-status v0.8 abonelikleri `types` içinde TEK eleman kabul eder (canlı 422, 09.09.2026)
        if single_type and len(body.get("types") or []) != 1:
            raise HTTPException(422, {"detail": [{"type": "value_error", "loc": ["body", "types"],
                                                  "msg": "Value error, types must be a list of length 1"}]})
        cred = body.get("sinkCredential")
        if cred and cred.get("credentialType") == "ACCESSTOKEN" and not cred.get("accessTokenExpiresUtc"):
            # Nokia: ACCESSTOKEN kimliğinde son kullanma zamanı zorunlu (canlı 422, 27.09.2026)
            raise HTTPException(422, {"detail": [{"type": "missing", "loc": ["body", "sinkCredential", "ACCESSTOKEN", "accessTokenExpiresUtc"],
                                                  "msg": "Field required"}]})
        return fx.create_subscription(kind, body)

    @app.get(prefix, name=f"list_{kind}")
    def list_():
        return fx.list_subscriptions(kind)

    @app.get(prefix + "/{sid}", name=f"get_{kind}")
    def get(sid: str):
        return fx.get_subscription(sid)

    @app.delete(prefix + "/{sid}", name=f"delete_{kind}")
    def delete(sid: str):
        return fx.delete_subscription(sid)


_sub_routes("/geofencing-subscriptions/v0.3/subscriptions", "geofencing", single_type=False)
_sub_routes("/device-status/device-reachability-status-subscriptions/v0.8/subscriptions", "reachability", single_type=True)
_sub_routes("/device-status/device-roaming-status-subscriptions/v0.8/subscriptions", "roaming", single_type=True)


# ---- QoD ---------------------------------------------------------------------
@app.post("/quality-on-demand/v1/sessions")
def qod_create(body: dict = Body(...)):
    return fx.qod_create(_phone(body), body)


@app.get("/quality-on-demand/v1/sessions/{sid}")
def qod_get(sid: str):
    return fx.qod_get(sid)


@app.delete("/quality-on-demand/v1/sessions/{sid}")
def qod_delete(sid: str):
    return fx.qod_delete(sid)


@app.post("/quality-on-demand/v1/retrieve-sessions")
def qod_list(body: dict = Body(...)):
    return fx.qod_list(_phone(body))


# ---- simülatör kontrol uçları (gerçek API'de yok) ------------------------------
@app.get("/_sim/profiles")
def sim_profiles():
    return fx.profiles


@app.put("/_sim/profiles/{phone}")
def sim_put_profile(phone: str, patch: dict = Body(...)):
    return fx.update_profile(phone, patch)


@app.post("/_sim/reset")
def sim_reset():
    global fx
    fx = FixtureBackend.from_json(FIXTURE_PATH) if Path(FIXTURE_PATH).exists() else FixtureBackend()
    return {"ok": True, "profiles": len(fx.profiles)}


@app.post("/_sim/emit")
def sim_emit(body: dict = Body(...)):
    """Bir aboneliğin sink'ine CloudEvent gönderir. body: {subscription_id?, phone?, type, extra?}"""
    sid = body.get("subscription_id")
    subs = [fx.subscriptions[sid]] if sid and sid in fx.subscriptions else [
        s for s in fx.subscriptions.values() if (s.get("config") or {}).get("subscriptionDetail", {}).get("device", {}).get("phoneNumber") == body.get("phone")
    ]
    if not subs:
        raise HTTPException(404, "abonelik bulunamadı")
    delivered = []
    for s in subs:
        phone = (s.get("config") or {}).get("subscriptionDetail", {}).get("device", {}).get("phoneNumber")
        ev = fx.cloud_event(body["type"], s["id"], phone, body.get("extra"))
        headers = {"content-type": "application/cloudevents+json"}
        cred = s.get("sinkCredential") or {}
        if cred.get("credentialType") == "ACCESSTOKEN" and cred.get("accessToken"):
            headers["authorization"] = f"Bearer {cred['accessToken']}"  # CAMARA: sink'e sinkCredential ile teslim
        try:
            r = httpx.post(s["sink"], json=ev, headers=headers, timeout=5)
            delivered.append({"subscription_id": s["id"], "status": r.status_code})
        except Exception as e:  # noqa: BLE001
            delivered.append({"subscription_id": s["id"], "error": str(e)})
    return {"delivered": delivered}


@app.get("/")
def root():
    return {"simulator": "local-nac", "profiles": len(fx.profiles), "fixture": FIXTURE_PATH}
