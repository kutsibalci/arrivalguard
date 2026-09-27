"""nac_client — Nokia Network as Code sarmalayıcı.

Tek giriş noktası. Nokia API çağrıları bu paketin dışından ASLA doğrudan yapılmaz.

Özellikler:
- Gerçek endpoint path'leri (network-as-code SDK v10.0.0'dan doğrulandı — docs/api-availability.md)
- İki katmanlı auth: x-rapidapi-key + (passthrough API'lerde) Bearer OAuth2 token
- Timeout + retry + circuit breaker (resilience.py)
- Hata normalizasyonu (errors.py)
- Telefon maskeleme / hash (privacy.py) — loglarda ham numara yok
- Üç mod: fixture (in-memory), simulator (yerel mock HTTP), live (RapidAPI)
- Number Verification için 3-legged OIDC akışı (oidc.py)
"""
from .client import (
    GEOFENCE_ENTERED,
    GEOFENCE_LEFT,
    REACHABILITY_DATA,
    REACHABILITY_DISCONNECTED,
    REACHABILITY_SMS,
    ROAMING_CHANGE_COUNTRY,
    ROAMING_OFF,
    ROAMING_ON,
    SIM_DEVICE_PREFIX,
    NacClient,
    NacConfig,
    NacResult,
)
from .errors import NacCircuitOpen, NacError, NacTimeout
from .fixtures import DEFAULT_PROFILE, FixtureBackend
from .oidc import SIM_CODE_PREFIX, NumberVerificationAuth
from .privacy import hash_phone, mask_phone, normalize_phone

__all__ = [
    "NacClient", "NacConfig", "NacResult",
    "NacError", "NacCircuitOpen", "NacTimeout",
    "FixtureBackend", "DEFAULT_PROFILE",
    "mask_phone", "hash_phone", "normalize_phone",
    "ROAMING_ON", "ROAMING_OFF", "ROAMING_CHANGE_COUNTRY",
    "REACHABILITY_DATA", "REACHABILITY_SMS", "REACHABILITY_DISCONNECTED",
    "GEOFENCE_ENTERED", "GEOFENCE_LEFT", "SIM_DEVICE_PREFIX",
    "NumberVerificationAuth", "SIM_CODE_PREFIX",
]
