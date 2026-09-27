"""Number Verification için 3-legged OIDC (authorization code) akışı.

Number Verification, "bu isteği yapan CİHAZ hangi hatta?" sorusunu cevaplar. Operatör bunu, cihaz kendi
mobil veri bağlantısı üzerinden yetkilendirme adresini açtığında anlar (header enrichment / silent auth):

  1. Sunucu: authorization_url() → operatörün yetkilendirme adresi (login_hint = beklenen hat, state = tek kullanımlık)
  2. Sürücünün telefonu (Wi-Fi kapalı, mobil veri) o adrese gider → operatör redirect_uri'ye `code` ile döner
  3. Sunucu: exchange_code(code) → cihaza bağlı erişim token'ı
  4. Sunucu: NacClient.number_verify(phone, device_token=token) → devicePhoneNumberVerified

Uçlar network-as-code SDK v10.0.0'dan doğrulandı:
  GET  oauth2/v1/auth/clientcredentials       → {client_id, client_secret}   (x-rapidapi-key ile)
  GET  .well-known/openid-configuration        → {authorization_endpoint, token_endpoint, ...}
  POST <token_endpoint> (form, authorization_code)

Fixture modunda HTTP yoktur: yetkilendirme adresi doğrudan redirect_uri'ye `sim-code:<hat>` koduyla döner ve
kod `sim-device:<hat>` token'ına çevrilir. Simülatör aynı uçları (/.well-known, /oauth2/...) HTTP üzerinden sunar.
"""
from __future__ import annotations

import os
import time
from urllib.parse import urlencode

import httpx

from .client import SIM_DEVICE_PREFIX, NacClient
from .errors import NacError, NacTimeout, error_from_status
from .privacy import normalize_phone

API = "number-verification-auth"
SIM_CODE_PREFIX = "sim-code:"
DEFAULT_SCOPE = "dpv:FraudPreventionAndDetection number-verification:verify"
DISCOVERY_TTL_S = 3600.0


class NumberVerificationAuth:
    def __init__(self, nac: NacClient, scope: str | None = None):
        self.nac = nac
        self.scope = scope or os.environ.get("NAC_NV_SCOPE") or DEFAULT_SCOPE
        self._discovery: tuple[float, dict, dict] | None = None  # (zaman, openid-configuration, client credentials)

    @property
    def mode(self) -> str:
        return self.nac.cfg.mode

    # ---------------------------------------------------------------- HTTP yardımcıları
    def _get(self, path: str) -> dict:
        assert self.nac.http is not None
        headers = {k: v for k, v in self.nac._headers(path).items() if k != "content-type"}
        try:
            r = self.nac.http.get(path, headers=headers)
        except httpx.TimeoutException:
            raise NacTimeout(API, self.nac.cfg.timeout_s) from None
        except httpx.HTTPError as e:
            raise NacError("network", API, str(e), retryable=True) from e
        if r.status_code >= 400:
            raise error_from_status(API, r.status_code, r.text)
        return r.json()

    def _discover(self) -> tuple[dict, dict]:
        now = time.monotonic()
        if self._discovery and now - self._discovery[0] < DISCOVERY_TTL_S:
            return self._discovery[1], self._discovery[2]
        endpoints = self._get(".well-known/openid-configuration")
        creds = self._get("oauth2/v1/auth/clientcredentials")
        if not endpoints.get("authorization_endpoint") or not endpoints.get("token_endpoint"):
            raise NacError("bad_request", API, "openid-configuration eksik: authorization_endpoint/token_endpoint")
        if not creds.get("client_id") or not creds.get("client_secret"):
            raise NacError("auth", API, "client credentials alınamadı")
        self._discovery = (now, endpoints, creds)
        return endpoints, creds

    # ---------------------------------------------------------------- akış
    def authorization_url(self, *, login_hint: str, redirect_uri: str, state: str, sim_line: str | None = None) -> str:
        """Sürücünün telefonunun açacağı adres. `sim_line` yalnızca fixture/simülatörde: cihazın 'gerçek' hattı."""
        hint = normalize_phone(login_hint)
        if self.mode == "live":
            if sim_line:
                raise NacError("bad_request", API, "sim_line canlı modda kullanılamaz")
        device = normalize_phone(sim_line) if sim_line else hint
        if self.mode == "fixture":
            return f"{redirect_uri}?{urlencode({'code': SIM_CODE_PREFIX + device, 'state': state})}"
        endpoints, creds = self._discover()
        params = {"response_type": "code", "client_id": creds["client_id"], "redirect_uri": redirect_uri,
                  "scope": self.scope, "state": state, "login_hint": hint}
        if self.mode == "simulator" and sim_line:
            params["sim_line"] = device
        sep = "&" if "?" in endpoints["authorization_endpoint"] else "?"
        return f"{endpoints['authorization_endpoint']}{sep}{urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> str:
        """Yetkilendirme kodu → cihaza bağlı erişim token'ı (Number Verification çağrısında Bearer)."""
        if not code:
            raise NacError("bad_request", API, "code boş")
        if self.mode == "fixture":
            if not code.startswith(SIM_CODE_PREFIX):
                raise NacError("auth", API, "geçersiz kod")
            return SIM_DEVICE_PREFIX + normalize_phone(code[len(SIM_CODE_PREFIX):])
        endpoints, creds = self._discover()
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                "client_id": creds["client_id"], "client_secret": creds["client_secret"]}
        assert self.nac.http is not None
        try:
            r = self.nac.http.post(endpoints["token_endpoint"], data=form,
                                   headers={"content-type": "application/x-www-form-urlencoded", "accept": "application/json"})
        except httpx.TimeoutException:
            raise NacTimeout(API, self.nac.cfg.timeout_s) from None
        except httpx.HTTPError as e:
            raise NacError("network", API, str(e), retryable=True) from e
        if r.status_code >= 400:
            raise error_from_status(API, r.status_code, r.text)
        token = (r.json() or {}).get("access_token")
        if not token:
            raise NacError("auth", API, "token yanıtında access_token yok")
        return token
