"""LLM adaptörü: karar vermez; takma adla özet yazar; hata/ret durumunda kural notlarına düşer."""
from types import SimpleNamespace

import pytest

from arrivalguard.agent.llm_adapter import AnthropicLlm, NoopLlm, _timeline_text, build_llm

TIMELINE = [
    {"t": "2026-09-01T10:00:00Z", "event": "roaming_on", "from": "waiting", "to": "arrived", "decision": "arrival", "note": "Layla A. indi"},
    {"t": "2026-09-01T10:05:00Z", "event": "driver_call", "from": "released", "to": "contacted", "decision": "genuine",
     "note": "Mehmet Y. aradı", "confidence": None},
]


def test_noop_joins_notes():
    assert NoopLlm().summarize_case(TIMELINE, "tr") == "Layla A. indi | Mehmet Y. aradı"


def test_timeline_text_pseudonymizes_names():
    text = _timeline_text(TIMELINE, ["Layla A.", "Mehmet Y."])
    assert "Layla" not in text and "Mehmet" not in text and "Hasta indi" in text and "Sürücü aradı" in text


def test_build_llm_falls_back_when_provider_unavailable(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "anthropic":
            raise ImportError("yok")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert isinstance(build_llm("anthropic", "claude-opus-5"), NoopLlm)
    assert isinstance(build_llm("none", "x"), NoopLlm)


class _FakeMessages:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.kwargs = response, exc, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.response


def _llm(messages):
    anthropic = pytest.importorskip("anthropic")
    llm = AnthropicLlm.__new__(AnthropicLlm)
    llm.anthropic, llm.model, llm.fallback = anthropic, "claude-opus-5", NoopLlm()
    llm.client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return llm


def test_anthropic_summary_request_shape_and_text():
    resp = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Hasta güvenle vardı.")], _request_id="r1")
    msgs = _FakeMessages(resp)
    out = _llm(msgs).summarize_case(TIMELINE, "tr", redact=["Layla A.", "Mehmet Y."])
    assert out == "Hasta güvenle vardı."
    kw = msgs.kwargs
    assert kw["model"] == "claude-opus-5" and kw["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in kw["betas"]
    assert "Turkish" in kw["system"] and "Layla" not in kw["messages"][0]["content"]


def test_anthropic_refusal_falls_back_to_rule_notes():
    resp = SimpleNamespace(stop_reason="refusal", content=[], _request_id="r2")
    assert _llm(_FakeMessages(resp)).summarize_case(TIMELINE, "en") == NoopLlm().summarize_case(TIMELINE)


def test_anthropic_connection_error_falls_back():
    anthropic = pytest.importorskip("anthropic")
    import httpx

    err = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    assert _llm(_FakeMessages(exc=err)).summarize_case(TIMELINE, "en") == NoopLlm().summarize_case(TIMELINE)
