# ArrivalGuard — Medikal Turist Varış Koruması

**Şebeke sinyalleriyle, konum geçmişi tutmadan havalimanından kliniğe güvenli karşılama.** · [English](README.md)

[![ci](https://github.com/kutsibalci/arrivalguard/actions/workflows/ci.yml/badge.svg)](https://github.com/kutsibalci/arrivalguard/actions/workflows/ci.yml)

> *Aynı sinyal, zıt anlam.* Şoförle ilk temastan **önce** susan hasta bir alarmdır. Aynı sessizlik ilk temastan
> **sonra** geliyorsa neredeyse her zaman yerel SIM kart demektir. ArrivalGuard bu farkı bilen, olay güdümlü bir vaka ajanıdır.

Terimsiz anlatım (sorun, pazar, kim öder, dürüst zayıf noktalar): [`docs/concept.tr.md`](docs/concept.tr.md)

## Bir bakışta durum

| | |
|---|---|
| ✅ **Yapıldı** | Vaka ajanı, API, koordinatör konsolu, rıza sayfası (TR/EN/AR), sürücü doğrulama sayfası, yerel Nokia simülatörü, Docker, CI. 149 test, %90 kapsam |
| ✅ **Canlı Nokia'da doğrulandı** (27.09.2026) | Şebeke sorguları, rıza kontrolü, abonelikler ve **gerçek olay teslimatı**: Nokia roaming ve ulaşılabilirlik olaylarını ArrivalGuard'a gönderdi, vaka ajanı da bunları işledi |
| ⏸ **Nerede durduk** | Kalan iki kontrol, Nokia'nın ücretsiz *Simulator* planının verdiğinden fazlasını istiyor: **bölge giriş-çıkış olayları** (simüle cihazlar hiç hareket etmiyor) ve **gerçek telefonda sürücü doğrulama** (desteklenen bir operatörde gerçek SIM gerekiyor) |

Ayrıntılar: [Proje durumu](#proje-durumu).

## Hızlı başlangıç

```powershell
py -m pip install -e ".[dev]"
py -m pytest                                  # 149 test
$env:PYTHON="py"; .\run.ps1 -Mode simulator   # demo: http://127.0.0.1:8000/demo · konsol: /console · API: /docs
```

`.\run.ps1 -Mode fixture` ile her şey bellekte çalışır (internet gerekmez). `docker compose up --build` API ile simülatörü birlikte kaldırır.
Canlı Nokia kurulumu için: [`docs/deployment.md`](docs/deployment.md).

## Akış

| Aşama | Nokia sinyali | Karar |
|---|---|---|
| Rıza | Hastanın açık onayı + Consent Info | Rıza yoksa izleme de abonelik de yok |
| İniş | Roaming aboneliği (`roaming-on`) | Itinerary ile karşılaştırılır: **varış mı, aktarma mı?** |
| Bütünlük kapısı | SIM Swap (24 sa) | Hat yakın zamanda el değiştirdiyse **sürücü adı ve plakası gönderilmez** |
| Sürücü | **Sürücünün kendi cihazında** Number Verification (3-legged OIDC) | Doğrulanırsa hastaya ve sürücüye aynı **buluşma kodu** gider |
| İlk arama | Sicil kaydı + taze doğrulama | Kayıtsız arayan için "açmayın"; doğrulaması olmayan sürücü numarası için numara taklidi uyarısı |
| Sessizlik | Reachability aboneliği | İlk temastan **önce** alarm, **sonra** alarm düşer |
| Yolculuk | Koridor geofence'i + zamanlayıcı | Güven skoruyla değerlendirilir; eskalasyon bütçesi ve yeniden uyandırma aralığı uygulanır |
| Kapanış | Klinik geofence'i | Vaka kapanır, aileye kendi dilinde bilgi gider, abonelikler ve ham numaralar silinir |

Demo senaryoları ve sunum metni: [`docs/demo-script.md`](docs/demo-script.md). Mimari: [`docs/architecture.md`](docs/architecture.md).

## Gizlilik

- Konum geçmişi tutulmaz. Yalnızca "bölgede mi?" hükmü alınır, koordinat alınmaz.
- Rıza verilmeden hiçbir işlem yapılmaz. Rıza geri çekilirse izleme anında durur.
- Ham numara hiçbir yanıtta, logda ya da raporda yer almaz; vaka bitince silinir. Buluşma kodu ve bağlantı token'ları koordinatör ekranında da maskelidir.
- Kapanmış vakalar 30 gün sonra silinir. Ayrıntı: [`docs/privacy.md`](docs/privacy.md).

## Proje durumu

### Buraya nasıl geldik

1. **Ağustos 2026: hackathon fikri ve prototip.** MENA Ignite Hackathon 2026 (GSMA × Nokia) için geliştirildi. 59 testli,
   sahte verilerle çalışan bir prototip.
2. **25.09.2026: sürdürülebilir bir projeye dönüştürüldü (v0.2.0).** Paket yapısı, rıza akışı, koordinatör konsolu, kalıcı kayıt,
   zamanlayıcı, bildirim kanalları, klinik bazlı API anahtarları, prod ayar koruması, CI ve Docker eklendi. Sürücü doğrulama,
   Number Verification'ın gerçekte neyi kanıtlayabildiğine göre yeniden tasarlandı.
3. **27.09.2026: sürücü OIDC akışı ve canlı doğrulama.** Sürücü sayfası cihaz token'ını artık Number Verification'ın 3-legged OIDC
   akışıyla alıyor. Ardından ücretsiz planın izin verdiği her şey canlı Nokia'da denendi.

### Canlı Nokia'da doğrulananlar

Nokia Network as Code, ücretsiz *Simulator* planı, simüle cihaz `+99999991000`. Raporlar: [`docs/live-probe/`](docs/live-probe/).

| Yetenek | Sonuç |
|---|---|
| Roaming ve ulaşılabilirlik durumu (anlık sorgu) | ✅ 200 |
| SIM Swap kontrolü ve tarihi | ✅ 200 |
| Location Verification (buluşma noktası hükmü) | ✅ 200 |
| Consent Info (operatör tarafı rıza kontrolü) | ✅ 200 |
| Number Verification OIDC keşfi (sürücü sayfasının operatöre yönlendirmesi) | ✅ 200 |
| Bir vakanın açtığı 7 aboneliğin hepsi (2 roaming, 2 ulaşılabilirlik, 3 bölge) | ✅ ACTIVE |
| **Olay teslimatı:** Nokia → public HTTPS tünel → webhook anahtarıyla `/webhooks/*` → vaka ajanı | ✅ roaming ve ulaşılabilirlik olayları teslim edildi ve işlendi |
| Temizlik: vaka bitince bütün aboneliklerin silinmesi | ✅ açıkta abonelik kalmadı |

Canlı test, simülatörün gösteremeyeceği üç hata buldu. Üçü de düzeltildi, simülatör de artık aynı kuralları uyguluyor:

- Cihaz durumu abonelikleri her seferinde **tek olay tipi** kabul ediyor (422).
- Consent Info, W3C DPV biçiminde bir `purpose` ve `requestCaptureUrl` alanı istiyor (422).
- Webhook kimliğinin bir **son kullanma zamanı** (`accessTokenExpiresUtc`) olmalı; bu alan olmadan Nokia bütün abonelikleri reddetti (422).

### Nerede durduk, neden

Kalan iki kontrolün kodu yazıldı ve yerelde test edildi. Eksik olan, ücretsiz planın vermediği erişim.

| Henüz doğrulanmayan | Neden durduk | Ne gerekiyor |
|---|---|---|
| **Bölge giriş-çıkış olayları** (havalimanı, koridor, klinik) | Abonelikler canlıda kabul ediliyor, ama Nokia'nın simüle cihazları Budapeşte'de sabit bir noktada duruyor. Bu yüzden "bölgeye girdi/çıktı" olayı hiç oluşmuyor. Nokia kendi entegrasyon testlerinde de bu durumları aynı sebeple atlıyor. | Gerçekten hareket eden bir cihaz: Nokia'nın desteklediği bir şebekede gerçek SIM, ya da simülatöre hareket desteği |
| **Gerçek telefonda sürücü doğrulama** | Number Verification hattı, telefonun kendi mobil veri oturumu üzerinden tanıyor. Ücretsiz plan yalnızca simüle numaraları kapsıyor, bu yüzden yönlendirme → kod → token → doğrulama zinciri gerçek bir telefonda çalıştırılamıyor. Sunucu tarafı (OIDC keşfi) canlıda zaten çalışıyor. | Desteklenen bir operatörde gerçek SIM ve ücretsiz planın ötesinde erişim |

### Üretime geçmek için gerekenler

Bu, çalışan ve test edilmiş bir prototip; sertifikalı bir sağlık ya da güvenlik sistemi değil. Gerçek hastalardan önce:

- Ücretsiz planın ötesinde operatör erişimi (yukarıya bakın) ve kayıtlı bir OIDC dönüş adresi.
- Gerçek bir bildirim sağlayıcısı (`NOTIFY_CHANNEL=webhook` ya da `twilio`). Varsayılan ayar mesajları yalnızca loglar.
- Rıza metninin ve veri işlemenin hukuki incelemesi (KVKK / GDPR).
- TLS ve istek hızı sınırı olan tek düğümlü bir kurulum. Zamanlayıcı tek süreçli, SQLite de tek düğüme uygun.

Tüm geçmiş: [`CHANGELOG.md`](CHANGELOG.md) · API bazında sonuçlar: [`docs/api-availability.md`](docs/api-availability.md).

MENA Ignite Hackathon 2026 (GSMA × Nokia) için geliştirildi · [MIT](LICENSE)
