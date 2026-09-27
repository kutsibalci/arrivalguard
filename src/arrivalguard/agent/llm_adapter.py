"""LLM adaptörü — isteğe bağlı vaka özeti. KARAR VERMEZ.

Kararlar saf kurallarda (rules/decisions.py) ve durum makinesinde kalır. LLM yalnızca kapanmış bir vakanın
timeline'ından koordinatör/klinik için okunabilir bir audit özeti yazar. Özet yoksa sistem aynen çalışır.

Sağlayıcılar (LLM_PROVIDER):
  none       NoopLlm — timeline notlarını birleştirir (varsayılan, dış çağrı yok)
  anthropic  AnthropicLlm — Claude ile kısa özet. `pip install arrivalguard[llm]` + ANTHROPIC_API_KEY
             (ya da `ant auth login` profili). SDK/kimlik yoksa ya da çağrı başarısızsa NoopLlm'e düşer.

Gizlilik: modele giden metin takma adlıdır — hasta ve sürücü adları "Hasta" / "Sürücü" ile değiştirilir,
numaralar zaten maskelidir, buluşma kodu ve token'lar timeline'da yoktur. Yine de bu bir üçüncü taraf veri
aktarımıdır: canlıda veri işleme sözleşmesi (DPA) olmadan açmayın.
"""
from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger("arrivalguard.llm")

SYSTEM_PROMPT = (
    "You write short audit summaries for a medical-tourism arrival-safety service. You receive the event "
    "timeline of one closed case (network signals, rule decisions, coordinator actions). Write 3-5 plain "
    "sentences in {language} for the clinic's records: what happened from landing to closure, any risk "
    "signals (SIM swap, impostor or unverified calls, unreachability, route deviation) and how they were "
    "resolved, and whether the coordinator was woken. State only facts present in the timeline; do not "
    "speculate, do not add advice, and do not invent names, times or numbers."
)
LANGUAGE_NAMES = {"tr": "Turkish", "en": "English", "ar": "Arabic"}


class LlmAdapter(Protocol):
    name: str

    def summarize_case(self, timeline: list[dict], language: str, redact: list[str] | None = None) -> str: ...


def _timeline_text(timeline: list[dict], redact: list[str] | None) -> str:
    lines = []
    for e in timeline:
        parts = [str(e.get("t", "")), str(e.get("event", "")), f"{e.get('from')}->{e.get('to')}"]
        if e.get("decision"):
            parts.append(f"decision={e['decision']}")
        if e.get("confidence") is not None:
            parts.append(f"confidence={e['confidence']}")
        if e.get("note"):
            parts.append(str(e["note"]))
        lines.append(" | ".join(parts))
    text = "\n".join(lines)
    for i, word in enumerate(w for w in (redact or []) if w):
        text = text.replace(word, "Hasta" if i == 0 else "Sürücü")
    return text


class NoopLlm:
    """Varsayılan: dış çağrı yok; timeline notlarını birleştirir."""

    name = "none"

    def summarize_case(self, timeline: list[dict], language: str = "tr", redact: list[str] | None = None) -> str:
        return " | ".join(str(e.get("note", "")) for e in timeline if e.get("note"))


class AnthropicLlm:
    name = "anthropic"

    def __init__(self, model: str = "claude-opus-5", client=None):
        import anthropic  # isteğe bağlı bağımlılık — yoksa ImportError, build_llm Noop'a düşer

        self.anthropic = anthropic
        self.model = model
        self.client = client or anthropic.Anthropic(max_retries=2, timeout=60.0)
        self.fallback = NoopLlm()

    def summarize_case(self, timeline: list[dict], language: str = "tr", redact: list[str] | None = None) -> str:
        lang = LANGUAGE_NAMES.get((language or "tr")[:2], "Turkish")
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=4000,
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=SYSTEM_PROMPT.format(language=lang),
                messages=[{"role": "user", "content": "Case timeline:\n" + _timeline_text(timeline, redact)}],
            )
        except self.anthropic.APIStatusError as e:
            log.warning("llm summary failed status=%s request_id=%s", e.status_code, getattr(e, "request_id", None))
            return self.fallback.summarize_case(timeline, language)
        except self.anthropic.APIConnectionError:
            log.warning("llm summary failed: connection error")
            return self.fallback.summarize_case(timeline, language)
        if response.stop_reason == "refusal":
            log.warning("llm summary refused request_id=%s", response._request_id)
            return self.fallback.summarize_case(timeline, language)
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or self.fallback.summarize_case(timeline, language)


def build_llm(provider: str, model: str) -> LlmAdapter:
    if provider == "anthropic":
        try:
            return AnthropicLlm(model=model)
        except Exception as e:  # noqa: BLE001 — SDK yok ya da kimlik bilgisi yok → sistem LLM'siz çalışır
            log.warning("LLM_PROVIDER=anthropic ama istemci kurulamadı (%s) — özetler kural notlarından üretilecek", e)
    return NoopLlm()
