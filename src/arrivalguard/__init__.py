"""ArrivalGuard — medikal turist varış koruması. "Aynı sinyal, zıt anlam."

Paket düzeni:
  nac_client/  Nokia Network as Code (CAMARA) sarmalayıcısı — tek giriş noktası
  rules/       Saf karar fonksiyonları (explain[] üretir) + eşikler
  agent/       Deterministik vaka durum makinesi + mesaj şablonları
  api/         FastAPI uygulaması (vaka uçları, webhook'lar, zamanlayıcı, bildirim, kalıcılık)
  simulator/   Yerel Nokia NaC taklidi (gerçek path'ler)
  web/         Demo, koordinatör konsolu ve rıza sayfası (vanilla HTML/JS)
"""
from __future__ import annotations

import os
from pathlib import Path

__version__ = "0.2.0"

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]  # src/arrivalguard → repo kökü (kaynak ağacından çalışırken)


def data_path(name: str) -> Path:
    """fixtures/<name> yolunu çözer: önce AG_FIXTURES_DIR, sonra repo kökü, sonra çalışma dizini."""
    candidates = []
    if os.environ.get("AG_FIXTURES_DIR"):
        candidates.append(Path(os.environ["AG_FIXTURES_DIR"]) / name)
    candidates += [REPO_ROOT / "fixtures" / name, Path.cwd() / "fixtures" / name]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]
