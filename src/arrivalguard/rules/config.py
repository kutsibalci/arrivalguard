"""ArrivalGuard eşikleri — hard-code yok, hepsi burada; env ile override edilir (AG_* önekli)."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields


@dataclass
class Config:
    sim_swap_freeze_window_h: int = 24          # varışta SIM bu kadar saat içinde değiştiyse pickup detayları bekletilir
    arrival_window_h: float = 3.0               # itinerary ETA ± saat: bu pencere içindeki hedef-ülke roaming'i = varış
    corridor_radius_m: int = 1500               # havalimanı→klinik koridor geofence yarıçapı
    stationary_minutes_alert: int = 10          # koridor dışında bu kadar dakika hareketsizlik = sorun adayı
    unreachable_before_contact_alert_min: int = 5   # ilk temastan ÖNCE bu kadar dk ulaşılamıyorsa alarm
    unreachable_after_contact_grace_min: int = 30   # ilk temastan SONRA bu süre boyunca sessizlik = muhtemel yerel SIM (alarm düşer)
    escalation_budget_per_case: int = 3         # vaka başına koordinatörü uyandırma bütçesi
    reescalate_after_min: int = 10              # süren bir sorun için koordinatör en erken bu kadar dk sonra tekrar uyandırılır
    off_corridor_confidence_low: float = 0.25   # sadece koridor dışı → düşük güvenle "muhtemel trafik"
    off_corridor_stationary_confidence: float = 0.6  # koridor dışı + hareketsiz → sorun adayı
    trouble_confidence_high: float = 0.85       # koridor dışı + hareketsiz + ulaşılamıyor → yüksek güvenle "sorun"
    disruption_discount: float = 0.2            # koordinatörün bildirdiği yol kapanması/sapma varsa güven bu kadar düşer
    night_start_hour: int = 0                   # gece aralığı (yerel saat, yalnızca açıklama/bağlam için)
    night_end_hour: int = 6
    driver_attestation_ttl_min: int = 20        # sürücü cihaz doğrulaması (Number Verification) bu kadar dk geçerli
    arrival_overdue_poll: bool = True           # varış penceresi geçti ve webhook gelmediyse anlık roaming sorgusu yap
    case_max_hours: int = 12                    # hedef ETA'dan bu kadar saat sonra kapanmamış vaka "expired" olur
    retention_days: int = 30                    # kapanmış vakaların saklama süresi (sonra silinir)
    operator_consent_check: bool = True         # rıza alındıktan sonra operatör Consent Info sorgusu yapılır mı

    @classmethod
    def from_env(cls) -> Config:
        d = cls()
        values = {}
        for f in fields(cls):
            raw = os.environ.get("AG_" + f.name.upper())
            default = getattr(d, f.name)
            if raw is None or raw == "":
                values[f.name] = default
                continue
            try:
                if isinstance(default, bool):
                    values[f.name] = raw.strip().lower() in ("1", "true", "yes", "on")
                else:
                    values[f.name] = type(default)(raw)
            except ValueError:
                values[f.name] = default
        return cls(**values)

    def to_dict(self) -> dict:
        return asdict(self)
