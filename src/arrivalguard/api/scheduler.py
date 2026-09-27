"""Arka plan zamanlayıcısı — süreye bağlı kuralların gerçek hayatta çalışmasını sağlar.

"İlk temastan önce 5 dk sessizlik → alarm", "koridor dışında 10 dk hareketsiz", "varış penceresi geçti ama
roaming olayı gelmedi", "vaka süresi doldu" kuralları bir olay gelmesini beklemez; her SCHEDULER_INTERVAL_S
saniyede açık vakalara `tick(source=scheduler)` verilir. Aynı tur terminal vakaların temizliğini (abonelik
silme, mesaj yeniden deneme, ham numara silme) ve saklama süresi dolan vakaların silinmesini yapar.

Tek süreçli çalışma varsayımı: birden çok API kopyası çalıştırılacaksa zamanlayıcı yalnızca birinde açık
olmalı (diğerlerinde SCHEDULER_INTERVAL_S=0).
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("arrivalguard.scheduler")


class Scheduler:
    def __init__(self, ctx, interval_s: float):
        self.ctx = ctx
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.runs = 0
        self.last_stats: dict | None = None

    def run_once(self) -> dict:
        stats = self.ctx.run_scheduler_once()
        self.runs += 1
        self.last_stats = stats
        return stats

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 — zamanlayıcı ölmemeli; hata loglanır, bir sonraki turda tekrar dener
                log.exception("scheduler run failed")

    def start(self) -> None:
        if self.interval_s <= 0 or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="arrivalguard-scheduler", daemon=True)
        self._thread.start()
        log.info("scheduler started interval=%ss", self.interval_s)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def status(self) -> dict:
        return {"interval_s": self.interval_s, "running": self._thread is not None, "runs": self.runs, "last": self.last_stats}
