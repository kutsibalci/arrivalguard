"""Bildirim kanalları: imzalı webhook, Twilio, yeniden deneme, alıcısız mesaj, koordinatör konsolu."""
import hashlib
import hmac
import json

import httpx

from arrivalguard.agent import Case
from arrivalguard.api.notify import MAX_ATTEMPTS, LogNotifier, TwilioNotifier, WebhookNotifier, dispatch, has_pending


def make_case() -> Case:
    c = Case(id="c1", clinic_id="clinic-1", clinic_name="K", patient_name="Layla", patient_phone="+447700900001", language="en",
             itinerary={}, driver={"name": "M", "phone": "+447700900101"}, family_contact={"name": "A", "phone": "+447700900099"})
    c.messages = [
        {"id": "c1-m1", "case_id": "c1", "to": "patient", "kind": "welcome_pickup", "text": "Welcome", "status": "queued", "attempts": 0, "lang": "en"},
        {"id": "c1-m2", "case_id": "c1", "to": "driver", "kind": "driver_code", "text": "Kod 1234", "status": "queued", "attempts": 0,
         "secrets": ["1234"], "lang": "tr"},
        {"id": "c1-m3", "case_id": "c1", "to": "coordinator", "kind": "warn", "text": "uyarı", "status": "queued", "attempts": 0},
        {"id": "c1-m4", "case_id": "c1", "to": "coordinator", "kind": "escalation", "text": "ALARM", "status": "queued", "attempts": 0},
    ]
    return c


def test_webhook_notifier_signs_body_and_sends_raw_number_only_to_bridge():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(200, headers={"x-message-id": "m-1"})

    n = WebhookNotifier("https://bridge.test/send", "s3cret", http=httpx.Client(transport=httpx.MockTransport(handler)))
    c = make_case()
    stats = dispatch(c, n, {"coordinator": {"phone": "+447700900198"}})
    assert stats == {"sent": 3, "failed": 0, "undeliverable": 0, "console": 1}
    req = seen[0]
    sig = "sha256=" + hmac.new(b"s3cret", req.content, hashlib.sha256).hexdigest()
    assert req.headers["x-arrivalguard-signature"] == sig
    body = json.loads(req.content)
    assert body["to_phone"] == "+447700900001" and "secrets" not in body
    assert c.messages[0]["provider_id"] == "m-1" and c.messages[2]["status"] == "console"
    assert json.loads(seen[2].content)["to_phone"] == "+447700900198"  # alarm koordinatör telefonuna gider


def test_failed_send_is_retried_until_max_attempts():
    n = WebhookNotifier("https://bridge.test/send", "", http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    c = make_case()
    for _ in range(MAX_ATTEMPTS + 2):
        dispatch(c, n, None)
    m = c.messages[0]
    assert m["status"] == "failed" and m["attempts"] == MAX_ATTEMPTS and "503" in m["error"]
    assert not has_pending(c)  # deneme hakkı bitti


def test_missing_recipient_is_undeliverable_and_coordinator_without_phone_goes_to_console():
    c = make_case()
    c.purge_pii(__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    stats = dispatch(c, LogNotifier(), None)
    assert stats["undeliverable"] == 2 and stats["console"] == 2
    assert c.messages[0]["error"].startswith("alıcı numarası yok")


def test_twilio_notifier_posts_form_with_basic_auth():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers["authorization"], req.content.decode()
        return httpx.Response(201, json={"sid": "SM123"})

    n = TwilioNotifier("AC1", "tok", "+15550001111", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert n.send({"text": "Merhaba"}, "+447700900001") == "SM123"
    assert seen["url"].endswith("/Accounts/AC1/Messages.json") and seen["auth"].startswith("Basic ")
    assert "To=%2B447700900001" in seen["body"] and "Body=Merhaba" in seen["body"]
