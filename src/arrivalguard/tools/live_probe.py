"""ArrivalGuard canlı Nokia sondası — kullanılan API'leri tek tek dener, maskeli rapor yazar.

    arrivalguard-probe                                  # .env'deki NAC_* ile, okuma uçları
    arrivalguard-probe --include-write --sink https://<tünel>/webhooks
                                                        # abonelikleri de kurar ve SİLER
    arrivalguard-probe --mode simulator --base http://127.0.0.1:8081

Rapor: docs/live-probe/probe-<zaman>.md ve .json. Ham telefon numarası raporda yoktur.
Varsayılan numara Nokia'nın simüle cihazıdır (+99999991000); gerçek bir hattı yalnızca sahibinin izniyle deneyin.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import REPO_ROOT
from ..api.context import mask_deep
from ..nac_client import (
    REACHABILITY_DISCONNECTED,
    ROAMING_CHANGE_COUNTRY,
    ROAMING_ON,
    NacClient,
    NacConfig,
    NacError,
    NacResult,
    NumberVerificationAuth,
    mask_phone,
)

DEFAULT_PHONE = "+99999991000"          # Nokia simüle cihazı
BUDAPEST = (47.48627616952785, 19.07915612501993)  # Nokia simüle cihazının sabit konumu


@dataclass
class Probe:
    key: str
    label: str
    role: str
    ok: bool = False
    status: str = ""
    latency_ms: int | None = None
    fields: list = field(default_factory=list)
    note: str = ""


def _run(p: Probe, fn) -> Probe:
    try:
        r = fn()
        p.ok, p.status, p.latency_ms = True, "200", r.latency_ms
        data = r.data
        p.fields = sorted(data.keys()) if isinstance(data, dict) else [f"list[{len(data)}]"]
        return p
    except NacError as e:
        p.status = f"{e.kind} {e.status or ''}".strip()
        p.note = (p.note + " " if p.note else "") + mask_deep(str(e))[:240]
        return p


def _oidc_discovery(nac: NacClient) -> NacResult:
    """Sürücü OIDC akışının sunucu tarafı: openid-configuration + client credentials → yetkilendirme adresi kurulabiliyor mu?"""
    import time
    from urllib.parse import urlsplit

    t0 = time.perf_counter()
    nv = NumberVerificationAuth(nac)
    url = nv.authorization_url(login_hint=DEFAULT_PHONE, redirect_uri="https://example.invalid/driver/nv/callback", state="probe")
    endpoints, _ = nv._discover()
    data = {"authorization_host": urlsplit(url).netloc, "token_host": urlsplit(endpoints["token_endpoint"]).netloc, "scope": nv.scope}
    return NacResult(api="number-verification-auth", data=data, source=nac.cfg.mode,
                     latency_ms=int((time.perf_counter() - t0) * 1000), correlator="-")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["live", "simulator"], default=os.environ.get("NAC_MODE") if os.environ.get("NAC_MODE") in ("live", "simulator") else "live")
    ap.add_argument("--base", default=None, help="NaC taban URL (varsayılan: NAC_BASE_URL / RapidAPI)")
    ap.add_argument("--phone", default=DEFAULT_PHONE)
    ap.add_argument("--sink", default=None, help="public HTTPS taban (…/webhooks); --include-write için")
    ap.add_argument("--include-write", action="store_true", help="abonelikleri kur, doğrula ve sil")
    ap.add_argument("--out", default=str(REPO_ROOT / "docs" / "live-probe"))
    args = ap.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass
    cfg = NacConfig.from_env()
    cfg.mode = args.mode
    if args.base:
        cfg.base_url = args.base
    elif args.mode == "simulator" and not os.environ.get("NAC_BASE_URL"):
        cfg.base_url = "http://127.0.0.1:8081"
    cfg.retries = 0
    if args.mode == "live" and not cfg.rapidapi_key:
        print("NAC_RAPIDAPI_KEY yok — .env.example'ı .env'ye kopyalayıp doldurun.", file=sys.stderr)
        return 2
    nac = NacClient(cfg)
    phone = args.phone
    lat, lng = BUDAPEST
    probes: list[Probe] = [
        _run(Probe("roaming", "Device Roaming Status (anlık)", "webhook yedeği + roaming-on ülke tamamlama"), lambda: nac.roaming(phone)),
        _run(Probe("reachability", "Device Reachability Status (anlık)", "ulaşılabilirlik sorgusu"), lambda: nac.reachability(phone)),
        _run(Probe("sim_swap_check", "SIM Swap check", "bütünlük kapısı"), lambda: nac.sim_swap_check(phone, 24)),
        _run(Probe("sim_swap_date", "SIM Swap retrieve-date", "bütünlük kapısı (tarih)"), lambda: nac.sim_swap_date(phone)),
        _run(Probe("location_verify", "Location Verification (Budapeşte, TRUE beklenir)", "buluşma noktası hükmü"),
             lambda: nac.location_verify(phone, lat, lng, 2000)),
        _run(Probe("consent", "Consent Info (purpose=dpv:ServiceProvision)", "operatör rıza kontrolü"),
             lambda: nac.consent(phone, ["device-roaming-status-subscriptions"], "dpv:ServiceProvision")),
        _run(Probe("number_verify", "Number Verification (cihaz token'ı olmadan)", "sürücü cihaz doğrulaması",
                   note="401 beklenir: gerçek çağrı sürücü cihazının 3-legged OIDC token'ı ile yapılır."),
             lambda: nac.number_verify(phone)),
        _run(Probe("number_verify_oidc", "Number Verification OIDC keşfi (openid-configuration + client credentials)",
                   "sürücü sayfasının operatöre yönlendirmesi"), lambda: _oidc_discovery(nac)),
    ]
    cleanup: list[str] = []
    if args.include_write:
        if not args.sink or (args.mode == "live" and not args.sink.startswith("https://")):
            print("--include-write için public HTTPS --sink gerekli (ör. https://abc.trycloudflare.com/webhooks)", file=sys.stderr)
            return 2
        sink = args.sink.rstrip("/")
        # canlı API'nin sink'e göndereceği Bearer — API ile aynı WEBHOOK_TOKEN kullanılırsa teslimat uçtan uca doğrulanır
        probe_token = os.environ.get("WEBHOOK_TOKEN") or secrets.token_urlsafe(24)
        expire = datetime.now(timezone.utc) + timedelta(hours=1)
        subs: list[tuple[str, str]] = []

        def sub(kind: str, fn):
            def inner():
                r = fn()
                if isinstance(r.data, dict) and r.data.get("id"):
                    subs.append((kind, r.data["id"]))
                return r
            return inner

        for key, label, fn in (
            ("roaming_sub_on", "Roaming aboneliği — roaming-on (tek tip)",
             sub("roaming", lambda: nac.roaming_subscribe(phone, f"{sink}/roaming", ROAMING_ON, sink_token=probe_token, expire=expire))),
            ("roaming_sub_cc", "Roaming aboneliği — roaming-change-country (tek tip)",
             sub("roaming", lambda: nac.roaming_subscribe(phone, f"{sink}/roaming", ROAMING_CHANGE_COUNTRY, sink_token=probe_token, expire=expire))),
            ("reach_sub", "Reachability aboneliği — disconnected (tek tip)",
             sub("reachability", lambda: nac.reachability_subscribe(phone, f"{sink}/reachability", REACHABILITY_DISCONNECTED, sink_token=probe_token, expire=expire))),
            ("geo_sub", "Geofencing aboneliği (CIRCLE)",
             sub("geofence", lambda: nac.geofence_subscribe(phone, lat, lng, 2000, f"{sink}/geofence", sink_token=probe_token, expire=expire))),
        ):
            probes.append(_run(Probe(key, label, "olay güdümlü akış"), fn))
        ops = {"roaming": nac.roaming_unsubscribe, "reachability": nac.reachability_unsubscribe, "geofence": nac.geofence_delete}
        for kind, sid in subs:
            try:
                ops[kind](sid)
                cleanup.append(f"{kind} `{sid}` → silindi")
            except NacError as e:
                cleanup.append(f"{kind} `{sid}` → SİLİNEMEDİ ({e.kind}) — portaldan elle silin")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ok = sum(p.ok for p in probes)
    lines = [
        f"# ArrivalGuard canlı sonda — {stamp} UTC", "",
        f"- Mod: **{cfg.mode}** · taban: `{cfg.base_url}` · numara: `{mask_phone(phone)}`",
        f"- RapidAPI anahtarı: {'var' if cfg.rapidapi_key else 'YOK'} · Bearer token: {'var' if cfg.oauth_token else 'YOK'}",
        f"- Sonuç: **{ok}/{len(probes)}** uç 200 döndü", "",
        "| API | ArrivalGuard'daki rolü | Sonuç | Yanıt alanları / not |", "|---|---|---|---|",
    ]
    for p in probes:
        res = f"✅ 200 · {p.latency_ms} ms" if p.ok else f"⚠ {p.status}"
        lines.append(f"| {p.label} | {p.role} | {res} | {', '.join(p.fields) if p.ok else p.note} |")
    if cleanup:
        lines += ["", "## Temizlik", *[f"- {c}" for c in cleanup]]
    lines += ["", "> Ham telefon numarası bu raporda yoktur."]
    (out / f"probe-{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / f"probe-{stamp}.json").write_text(json.dumps(
        {"mode": cfg.mode, "base_url": cfg.base_url, "phone": mask_phone(phone), "results": [p.__dict__ for p in probes], "cleanup": cleanup},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nRapor: {out / f'probe-{stamp}.md'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
