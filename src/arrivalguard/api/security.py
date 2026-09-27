"""Kimlik doğrulama ve yetkilendirme.

- /v1 uçları: `X-API-Key` başlığı. Her anahtar bir kliniğe bağlıdır (tenant) ya da '*' = yönetici.
  API_KEYS tanımsızsa (yalnızca dev) erişim açıktır ve istek "dev" yöneticisi sayılır.
- Webhook'lar: CAMARA sinkCredential → `Authorization: Bearer <WEBHOOK_TOKEN>`, sabit süreli karşılaştırma.
- Rıza ve sürücü sayfaları: bağlantıdaki tek kullanımlık olmayan ama tahmin edilemez token (secrets.token_urlsafe(24)).
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from ..agent import Case


@dataclass(frozen=True)
class Principal:
    clinic_id: str          # '*' = tüm klinikler
    actor: str              # audit'te görünen kimlik (anahtarın kendisi değil, parmak izi)

    @property
    def is_admin(self) -> bool:
        return self.clinic_id == "*"

    def can_access(self, clinic_id: str) -> bool:
        return self.is_admin or self.clinic_id == clinic_id


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def get_ctx(request: Request):
    return request.app.state.ctx


def require_principal(request: Request, ctx=Depends(get_ctx)) -> Principal:
    keys: dict[str, str] = ctx.settings.api_keys
    if not keys:
        return Principal("*", "dev")
    supplied = request.headers.get("x-api-key", "")
    for key, clinic in keys.items():
        if supplied and hmac.compare_digest(supplied.encode(), key.encode()):
            return Principal(clinic, f"{clinic}/{hashlib.sha256(key.encode()).hexdigest()[:8]}")
    raise _err(401, "UNAUTHENTICATED", "geçerli X-API-Key gerekli")


def require_admin(principal: Principal = Depends(require_principal)) -> Principal:
    if not principal.is_admin:
        raise _err(403, "PERMISSION_DENIED", "bu uç yönetici anahtarı ister")
    return principal


def check_case_access(principal: Principal, case: Case | None) -> Case:
    # Başka kliniğin vakası da 404 döner: vaka kimliklerinin varlığı sızdırılmaz
    if case is None or not principal.can_access(case.clinic_id):
        raise _err(404, "NOT_FOUND", "vaka yok")
    return case


def check_webhook_token(ctx, authorization: str | None) -> None:
    token = ctx.settings.webhook_token
    if not token:
        return  # yalnızca dev — prod'da Settings.validate() boş token'ı reddeder
    supplied = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    if not supplied or not hmac.compare_digest(supplied.encode(), token.encode()):
        raise _err(401, "UNAUTHENTICATED", "geçersiz webhook token")


def require_demo(ctx=Depends(get_ctx)) -> None:
    if not ctx.settings.enable_demo:
        raise _err(404, "NOT_FOUND", "demo uçları kapalı (ENABLE_DEMO=0)")


def require_debug(ctx=Depends(get_ctx)) -> None:
    if not ctx.settings.enable_debug:
        raise _err(404, "NOT_FOUND", "debug uçları kapalı (ENABLE_DEBUG=0)")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Sayfalar CDN'siz ve inline script/style kullanır; dış kaynak yüklenmez."""

    CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
           "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")  # token'lı bağlantılar Referer ile sızmasın
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        response.headers.setdefault("Content-Security-Policy", self.CSP)
        if request.url.path.startswith(("/consent/", "/driver/", "/v1/")):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
