"""Karar motorunun Nokia'yı gördüğü tek kapı.

NacFacade   HTTP modunda (simulator/live) hata olursa — izin verildiyse — fixture'a düşer ve kaynağı
            `fixture-fallback(<kind>)` diye işaretler. Canlı üretimde bu yedek KAPALI olmalı
            (NAC_FALLBACK_TO_FIXTURE=0): uydurma veriyle karar verilmez.
SafeFacade  NacFacade + hata yutma: çağrı tamamen başarısızsa vaka çökmez, sinyal "bilinmiyor" olur
            (`NacResult(data={}, source="error(<kind>)")`) ve olay `degraded` listesine düşer.
"""
from __future__ import annotations

import logging
import os
import uuid
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone

from ..nac_client import FixtureBackend, NacClient, NacConfig, NacError, NacResult

log = logging.getLogger("arrivalguard.facade")


def build_nac(fixture_path: str | None) -> NacClient:
    """NAC_MODE'a göre istemci. HTTP modlarında da fixture'ları yükler → yedek (izin verildiyse)."""
    from pathlib import Path

    cfg = NacConfig.from_env()
    if not cfg.fixture_path:
        cfg.fixture_path = fixture_path
    fx = FixtureBackend.from_json(cfg.fixture_path) if cfg.fixture_path and Path(cfg.fixture_path).exists() else FixtureBackend()
    return NacClient(cfg, fixtures=fx)


class NacFacade:
    def __init__(self, nac: NacClient, fallback_enabled: bool | None = None):
        self.nac = nac
        self.fallback = NacClient(NacConfig(mode="fixture"), fixtures=nac.fx) if nac.fx is not None and nac.cfg.mode != "fixture" else None
        default = "0" if nac.cfg.mode == "live" else "1"
        raw = (os.environ.get("NAC_FALLBACK_TO_FIXTURE") or default).strip()
        self.fallback_enabled = (raw == "1") if fallback_enabled is None else fallback_enabled

    def call(self, name: str, *args, **kwargs) -> NacResult:
        try:
            return getattr(self.nac, name)(*args, **kwargs)
        except NacError as e:
            if self.fallback_enabled and self.fallback is not None:
                res = getattr(self.fallback, name)(*args, **kwargs)
                res.source = f"fixture-fallback({e.kind})"
                return res
            raise


class SafeFacade(NacFacade):
    def __init__(self, nac: NacClient, clock: Callable[[], datetime] | None = None, fallback_enabled: bool | None = None):
        super().__init__(nac, fallback_enabled)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.degraded: deque[dict] = deque(maxlen=100)

    def call(self, name: str, *args, **kwargs) -> NacResult:
        try:
            return super().call(name, *args, **kwargs)
        except NacError as e:
            log.warning("nac degraded api=%s kind=%s", name, e.kind)
            self.degraded.append({"t": self.clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "api": name, **e.to_dict()})
            return NacResult(api=name, data={}, source=f"error({e.kind})", latency_ms=0, correlator=str(uuid.uuid4()))
