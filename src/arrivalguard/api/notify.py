"""Bildirim kanalları — vakanın outbox'ındaki (case.messages, status=queued) mesajları gönderir.

Kanallar (NOTIFY_CHANNEL):
  log      Gönderim yok, maskeli log. Geliştirme/demo varsayılanı.
  webhook  Mesajı HMAC-SHA256 imzalı JSON olarak NOTIFY_WEBHOOK_URL'e POST'lar (kendi SMS/WhatsApp/push köprünüz).
  twilio   Twilio Programmable Messaging ile SMS.

Durumlar: queued → sent | failed (yeniden denenir, en çok MAX_ATTEMPTS) | undeliverable (alıcı numarası yok)
| console (koordinatör konsolunda gösterilir, dışarı gönderilmez).
Ham numara yalnızca gönderim anında kanala verilir; loglarda ve API yanıtlarında maskelidir.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Protocol

import httpx

from ..agent import Case
from ..nac_client.privacy import mask_phone

log = logging.getLogger("arrivalguard.notify")

MAX_ATTEMPTS = 5
PENDING = ("queued", "failed")


class NotifyError(Exception):
    pass


class Notifier(Protocol):
    name: str

    def send(self, message: dict, to_phone: str) -> str | None:
        """Mesajı gönderir; sağlayıcının mesaj kimliğini (varsa) döner. Başarısızlıkta NotifyError."""


class LogNotifier:
    name = "log"

    def send(self, message: dict, to_phone: str) -> str | None:
        log.info("notify[log] case=%s to=%s kind=%s lang=%s", message.get("case_id"), mask_phone(to_phone), message.get("kind"), message.get("lang"))
        return None


class WebhookNotifier:
    """Kendi mesaj köprünüze imzalı teslim. Alıcı `X-ArrivalGuard-Signature: sha256=<hex>` başlığını doğrulamalı."""

    name = "webhook"

    def __init__(self, url: str, secret: str, http: httpx.Client | None = None):
        self.url, self.secret = url, secret
        self.http = http or httpx.Client(timeout=5)

    def send(self, message: dict, to_phone: str) -> str | None:
        payload = {k: v for k, v in message.items() if k not in ("secrets", "to_masked")} | {"to_phone": to_phone}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        headers = {"content-type": "application/json"}
        if self.secret:
            headers["x-arrivalguard-signature"] = "sha256=" + hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            r = self.http.post(self.url, content=body, headers=headers)
        except httpx.HTTPError as e:
            raise NotifyError(f"webhook ağ hatası: {e}") from e
        if r.status_code >= 300:
            raise NotifyError(f"webhook HTTP {r.status_code}")
        return r.headers.get("x-message-id")


class TwilioNotifier:
    name = "twilio"
    API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"

    def __init__(self, account_sid: str, auth_token: str, from_: str, http: httpx.Client | None = None):
        self.sid, self.token, self.from_ = account_sid, auth_token, from_
        self.http = http or httpx.Client(timeout=10)

    def send(self, message: dict, to_phone: str) -> str | None:
        try:
            r = self.http.post(self.API.format(sid=self.sid), auth=(self.sid, self.token),
                               data={"To": to_phone, "From": self.from_, "Body": message["text"]})
        except httpx.HTTPError as e:
            raise NotifyError(f"twilio ağ hatası: {e}") from e
        if r.status_code >= 300:
            raise NotifyError(f"twilio HTTP {r.status_code}: {r.text[:200]}")
        return (r.json() or {}).get("sid")


def build_notifier(settings) -> Notifier:
    if settings.notify_channel == "webhook":
        return WebhookNotifier(settings.notify_webhook_url, settings.notify_webhook_secret)
    if settings.notify_channel == "twilio":
        return TwilioNotifier(settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_from)
    return LogNotifier()


def _recipient_phone(case: Case, message: dict, clinic: dict | None) -> str | None:
    to = message.get("to")
    if to == "patient":
        return case.patient_phone
    if to == "family":
        return (case.family_contact or {}).get("phone")
    if to == "driver":
        return (case.driver or {}).get("phone")
    if to == "coordinator":
        return ((clinic or {}).get("coordinator") or {}).get("phone")
    return None


def has_pending(case: Case) -> bool:
    return any(m.get("status") in PENDING and m.get("attempts", 0) < MAX_ATTEMPTS for m in case.messages)


def dispatch(case: Case, notifier: Notifier, clinic: dict | None, now: datetime | None = None) -> dict:
    """Vakadaki bekleyen mesajları gönderir. Koordinatör mesajları: yalnızca 'escalation' (alarm) ve klinikte
    koordinatör telefonu tanımlıysa dışarı gider; diğerleri konsolda gösterilir."""
    now = now or datetime.now(timezone.utc)
    stats = {"sent": 0, "failed": 0, "undeliverable": 0, "console": 0}
    for m in case.messages:
        if m.get("status") not in PENDING or m.get("attempts", 0) >= MAX_ATTEMPTS:
            continue
        phone = _recipient_phone(case, m, clinic)
        if m.get("to") == "coordinator" and (m.get("kind") != "escalation" or not phone):
            m["status"] = "console"
            stats["console"] += 1
            continue
        if not phone:
            m["status"] = "undeliverable"
            m["error"] = "alıcı numarası yok (silinmiş ya da tanımsız)"
            stats["undeliverable"] += 1
            continue
        m["attempts"] = m.get("attempts", 0) + 1
        m["channel_provider"] = notifier.name
        try:
            provider_id = notifier.send(m, phone)
        except NotifyError as e:
            m["status"], m["error"] = "failed", str(e)
            stats["failed"] += 1
            log.warning("notify failed case=%s msg=%s attempt=%d err=%s", case.id, m.get("id"), m["attempts"], e)
            continue
        m["status"], m["sent_at"] = "sent", now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        m.pop("error", None)
        if provider_id:
            m["provider_id"] = provider_id
        stats["sent"] += 1
    return stats
