"""Uygulama ayarları — hepsi ortam değişkeninden (.env desteklenir). Karar eşikleri ayrı: rules/config.py (AG_*).

APP_ENV=prod iken güvensiz yapılandırma ile başlamak REDDEDİLİR (validate()): varsayılan hash tuzu,
boş/zayıf webhook token'ı, tanımsız API anahtarı, açık demo/debug uçları, HTTPS olmayan public adres.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from ..nac_client.privacy import DEV_SALT

log = logging.getLogger("arrivalguard.settings")

DEV_WEBHOOK_TOKEN = "arrivalguard-dev-token"  # noqa: S105 — yalnızca dev; prod bu değerle başlamaz


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _parse_api_keys(raw: str) -> dict[str, str]:
    """API_KEYS="clinic-1:anahtar1,*:yonetici-anahtari" → {anahtar: clinic_id}. '*' = tüm klinikler (yönetici)."""
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError("API_KEYS biçimi: <clinic_id|*>:<anahtar>[,...]")
        clinic, key = part.split(":", 1)
        if not key.strip():
            raise ValueError("API_KEYS içinde boş anahtar var")
        out[key.strip()] = clinic.strip()
    return out


@dataclass
class Settings:
    app_env: str = "dev"                          # dev | prod
    public_base_url: str = "http://127.0.0.1:8000"
    webhook_token: str = DEV_WEBHOOK_TOKEN        # CAMARA sinkCredential; boş → webhook doğrulaması KAPALI (yalnızca dev)
    api_keys: dict[str, str] = field(default_factory=dict)
    enable_demo: bool = True                      # /v1/demo/*, /v1/reset
    enable_debug: bool = True                     # /v1/_debug/*
    enable_manual_events: bool = True             # POST /v1/cases/{id}/events (şebeke olayını elle besleme)
    store_backend: str = "memory"                 # memory | sqlite
    db_path: str = "data/arrivalguard.db"
    scheduler_interval_s: float = 30.0            # 0 → zamanlayıcı kapalı
    notify_channel: str = "log"                   # log | webhook | twilio
    notify_webhook_url: str = ""
    notify_webhook_secret: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""
    cors_origins: list[str] = field(default_factory=list)
    llm_provider: str = "none"                    # none | anthropic
    llm_model: str = "claude-opus-5"
    phone_hash_salt_set: bool = False

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys)

    @classmethod
    def from_env(cls) -> Settings:
        env = (os.environ.get("APP_ENV") or "dev").strip().lower()
        prod = env == "prod"
        return cls(
            app_env=env,
            public_base_url=(os.environ.get("PUBLIC_BASE_URL") or "http://127.0.0.1:8000").strip(),
            webhook_token=os.environ.get("WEBHOOK_TOKEN", "" if prod else DEV_WEBHOOK_TOKEN),
            api_keys=_parse_api_keys(os.environ.get("API_KEYS", "")),
            enable_demo=_bool("ENABLE_DEMO", not prod),
            enable_debug=_bool("ENABLE_DEBUG", not prod),
            enable_manual_events=_bool("ENABLE_MANUAL_EVENTS", not prod),
            store_backend=(os.environ.get("STORE_BACKEND") or ("sqlite" if prod else "memory")).strip().lower(),
            db_path=os.environ.get("DB_PATH") or "data/arrivalguard.db",
            scheduler_interval_s=float(os.environ.get("SCHEDULER_INTERVAL_S", "30") or 0),
            notify_channel=(os.environ.get("NOTIFY_CHANNEL") or "log").strip().lower(),
            notify_webhook_url=os.environ.get("NOTIFY_WEBHOOK_URL", ""),
            notify_webhook_secret=os.environ.get("NOTIFY_WEBHOOK_SECRET", ""),
            twilio_account_sid=os.environ.get("TWILIO_ACCOUNT_SID", ""),
            twilio_auth_token=os.environ.get("TWILIO_AUTH_TOKEN", ""),
            twilio_from=os.environ.get("TWILIO_FROM", ""),
            cors_origins=[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()],
            llm_provider=(os.environ.get("LLM_PROVIDER") or "none").strip().lower(),
            llm_model=os.environ.get("LLM_MODEL") or "claude-opus-5",
            phone_hash_salt_set=(os.environ.get("PHONE_HASH_SALT") or "") not in ("", DEV_SALT, "change-me"),
        )

    def problems(self) -> list[str]:
        """Güvenlik/yapılandırma sorunları. prod'da hepsi ölümcül, dev'de uyarı olarak loglanır."""
        out: list[str] = []
        if self.app_env not in ("dev", "prod"):
            out.append(f"APP_ENV '{self.app_env}' geçersiz (dev | prod)")
        if not self.phone_hash_salt_set:
            out.append("PHONE_HASH_SALT tanımsız ya da geliştirme varsayılanı — telefon hash'leri tahmin edilebilir")
        if not self.webhook_token:
            out.append("WEBHOOK_TOKEN boş — webhook'lar kimlik doğrulamasız kabul edilir")
        elif self.webhook_token == DEV_WEBHOOK_TOKEN or len(self.webhook_token) < 24:
            out.append("WEBHOOK_TOKEN geliştirme varsayılanı ya da 24 karakterden kısa")
        if not self.api_keys:
            out.append("API_KEYS tanımsız — /v1 uçları kimlik doğrulamasız açık")
        if any(len(k) < 24 for k in self.api_keys):
            out.append("API_KEYS içinde 24 karakterden kısa anahtar var")
        if self.enable_demo:
            out.append("ENABLE_DEMO açık — /v1/demo/* ve /v1/reset erişilebilir")
        if self.enable_debug:
            out.append("ENABLE_DEBUG açık — /v1/_debug/* erişilebilir")
        if self.enable_manual_events:
            out.append("ENABLE_MANUAL_EVENTS açık — şebeke olayları elle beslenebilir")
        if not self.public_base_url.startswith("https://"):
            out.append("PUBLIC_BASE_URL HTTPS değil — CAMARA sink'i public HTTPS olmalı")
        if self.store_backend not in ("memory", "sqlite"):
            out.append(f"STORE_BACKEND '{self.store_backend}' geçersiz (memory | sqlite)")
        elif self.store_backend == "memory":
            out.append("STORE_BACKEND=memory — yeniden başlatmada vakalar ve abonelik eşlemesi kaybolur")
        if self.notify_channel not in ("log", "webhook", "twilio"):
            out.append(f"NOTIFY_CHANNEL '{self.notify_channel}' geçersiz (log | webhook | twilio)")
        elif self.notify_channel == "log":
            out.append("NOTIFY_CHANNEL=log — hasta/aile/sürücü mesajları gerçekten gönderilmez")
        elif self.notify_channel == "webhook" and not self.notify_webhook_url.startswith("https://"):
            out.append("NOTIFY_WEBHOOK_URL HTTPS değil")
        elif self.notify_channel == "twilio" and not (self.twilio_account_sid and self.twilio_auth_token and self.twilio_from):
            out.append("NOTIFY_CHANNEL=twilio ama TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM eksik")
        return out

    def validate(self) -> None:
        """prod: sorun varsa başlamayı reddeder. dev: uyarı loglar."""
        issues = self.problems()
        if self.is_prod and issues:
            raise RuntimeError("APP_ENV=prod güvensiz yapılandırmayla başlatılamaz:\n  - " + "\n  - ".join(issues))
        for i in issues:
            log.warning("config: %s", i)

    def public_dict(self) -> dict:
        """/v1/config için — sır içermez."""
        return {
            "app_env": self.app_env, "public_base_url": self.public_base_url, "auth_enabled": self.auth_enabled,
            "webhook_token_required": bool(self.webhook_token), "enable_demo": self.enable_demo,
            "enable_debug": self.enable_debug, "enable_manual_events": self.enable_manual_events,
            "store_backend": self.store_backend, "scheduler_interval_s": self.scheduler_interval_s,
            "notify_channel": self.notify_channel, "llm_provider": self.llm_provider,
        }
