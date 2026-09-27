# API erişilebilirlik kaydı

> Path'ler `network-as-code` Python SDK v10.0.0'ın `raw_client.py` dosyalarından çıkarıldı. Canlı sonuçlar Nokia Network as Code
> SIMULATOR planında, simüle cihaz `+99999991000` ile alındı. Kendi sondanızı çalıştırmak için bkz. [Canlı sonda](#canlı-sonda).
> Ham raporlar: [`live-probe/probe-20260909.md`](live-probe/probe-20260909.md) · [`live-probe/probe-20260927-103250.md`](live-probe/probe-20260927-103250.md).

| API | Path | ArrivalGuard'daki rolü | Canlı sonuç (09.09 → 27.09.2026) | Durum / düzeltme |
|---|---|---|---|---|
| Device Roaming Status Subscriptions | `POST /device-status/device-roaming-status-subscriptions/v0.8/subscriptions`, `DELETE …/{id}` | **Ana tetikleyici** (`roaming-on`); aktarma bacağı için `roaming-change-country` | ⚠ 422 `types must be a list of length 1` | ✅ **Düzeltildi (0.2.0):** her olay tipi ayrı abonelik. Canlıda ✅ ACTIVE, olay teslim edildi (27.09) |
| Device Roaming Status (anlık) | `POST /device-status/device-roaming-status/v1/retrieve` | `roaming-on` ülke taşımazsa tamamlar; varış penceresi kaçarsa yedek yol | ✅ 200 · 142 ms → ✅ 200 (27.09) | |
| Device Reachability Status Subscriptions | `POST /device-status/device-reachability-status-subscriptions/v0.8/subscriptions` | Ulaşılamama olayı (`reachability-disconnected` / `-data`) | ⚠ 422 (aynı tek tip kuralı) | ✅ **Düzeltildi (0.2.0)**. Canlıda ✅ ACTIVE, olay teslim edildi (27.09) |
| Device Reachability Status (anlık) | `POST /device-status/device-reachability-status/v1/retrieve` | Olay verisi eksikse anlık sorgu | ✅ 200 · 145 ms → ✅ 200 (27.09) | |
| SIM Swap | `POST passthrough/camara/v1/sim-swap/sim-swap/v0/check` (+ `/retrieve-date`) | **Bütünlük kapısı** (`maxAge` = `AG_SIM_SWAP_FREEZE_WINDOW_H`) | ✅ 200 · 141 ms / 130 ms → ✅ 200 (27.09) | Passthrough → `Authorization: Bearer` |
| Number Verification | `POST passthrough/camara/v1/number-verification/number-verification/v2/verify` | **Sürücünün kendi cihazı** kayıtlı hatta mı | ⚠ 401 `Authorization header is missing` | Beklenen durum: çağrı cihazın 3-legged OIDC token'ıyla yapılır. Akış `nac_client/oidc.py`'de. OIDC keşfi (`/.well-known/openid-configuration` + client credentials) canlıda ✅ 200 (27.09); gerçek telefonla henüz denenmedi (bkz. [mimari §6](architecture.md#6-sürücü-doğrulama-iki-aşamalı-model)) |
| Geofencing Subscriptions | `POST /geofencing-subscriptions/v0.3/subscriptions`, `GET/DELETE …/{id}` | Havalimanı, koridor, klinik | ✅ 200 · 228 ms (abonelik yaşam döngüsü) | Canlıda `area-entered` olayları teslim edildi ve işlendi (27.09). Olaylar yapay: simüle cihaz hareket etmiyor, gerçek güzergâh mantığı doğrulanmadı |
| Location Verification | `POST /location-verification/v1/verify` | Varışta tek seferlik "buluşma noktasında mı?" hükmü | ✅ 200 · 152 ms → ✅ 200 (27.09) | Simüle cihaz Budapeşte'de sabit; sonda bu koordinatı kullanır |
| Consent Info | `POST passthrough/camara/v1/consent-info/consent-info/v0.1/retrieve` | Rıza sonrası operatör tarafı işleme izni | ⚠ 422 `purpose` biçimi → ⚠ 422 `requestCaptureUrl` eksik → ✅ 200 (27.09) | ✅ **Düzeltildi:** `purpose=dpv:ServiceProvision` (W3C DPV) + zorunlu `requestCaptureUrl=false` |

Bilinçli olarak kullanılmayanlar:
- **Location Retrieval:** koordinat almak sürekli takip anlamına gelir. ArrivalGuard yalnızca "bölgede mi?" hükmüyle çalışır.
- **KYC Match / Tenure:** hasta kimliği kliniğin sözleşme sürecinde zaten doğrulanmış olur; tekrar sorgulamak veri minimizasyonuna aykırı.

## MOCK işaretleri

- `simulator/` ve `FixtureBackend`, Nokia SIMULATOR planının yerel taklididir. **Gerçek path'leri** kullanır, aynı gövde ve yanıt şemalarını üretir, device-status
  aboneliklerinde tek tip kuralını uygular ve CloudEvent'i `sinkCredential` Bearer'ı ile teslim eder. `/_sim/*` uçları gerçek API'de yoktur.
- Fixture ve simülatörde Number Verification `device_token` değeri `sim-device:<E.164>` biçimindedir ve doğrulamayı yapan cihazın hattını taklit eder.
- Demo senaryoları fixture profillerini çalışma anında günceller (`_prime`); böylece "SIM 3 saat önce değişti" gibi durumlar takvim tarihine bağlı kalmaz.

## Canlı test kontrol listesi

- [x] networkascode.nokia.io kaydı, SIMULATOR planı _(22.08.2026)_
- [x] Okuma uçları canlıda 200 döndü: roaming, reachability, SIM Swap, Location Verification _(09.09.2026)_
- [x] Tek tipli roaming ve reachability abonelikleri canlıda `status=ACTIVE` _(27.09.2026; `sinkCredential.accessTokenExpiresUtc` zorunlu)_
- [x] Roaming CloudEvent'lerinde `countryCode` MCC'dir (HU → 216); ülke `countryName` (ISO) ile çözülüyor _(27.09.2026)_
- [x] Yalnızca canlı olaylarla baştan sona vaka: varış → SIM Swap kapısı → reachability → geofence → kapanış _(27.09.2026)_
- [x] Roaming ve reachability CloudEvent'leri public sink'e `Authorization: Bearer <WEBHOOK_TOKEN>` ile ulaştı, vaka ajanı işledi _(27.09.2026)_
- [x] Consent Info `dpv:ServiceProvision` + `requestCaptureUrl` ile 200 _(27.09.2026)_
- [x] Number Verification OIDC keşfi canlıda 200 _(27.09.2026)_
- [ ] Number Verification: sürücü cihazında OIDC akışıyla alınan token ile 200

## Canlı sonda

```bash
cp .env.example .env            # NAC_MODE=live, NAC_RAPIDAPI_KEY, NAC_OAUTH_TOKEN
arrivalguard-probe                                              # okuma uçları
arrivalguard-probe --include-write --sink https://<tünel>/webhooks   # abonelikleri kur, doğrula, SİL
arrivalguard-probe --mode simulator --base http://127.0.0.1:8081    # anahtarsız prova
```

Rapor `docs/live-probe/probe-<zaman>.md` dosyasına yazılır. Ham numara raporda yer almaz. Public HTTPS sink için bkz. [deployment.md](deployment.md#public-https-sink).
