# ArrivalGuard — Medikal Turist Varış Koruması

**Şebeke sinyalleriyle, konum geçmişi tutmadan havalimanından kliniğe güvenli karşılama.** · [English](README.md)

[![ci](https://github.com/kutsibalci/arrivalguard/actions/workflows/ci.yml/badge.svg)](https://github.com/kutsibalci/arrivalguard/actions/workflows/ci.yml)

> *Aynı sinyal, zıt anlam.* Şoförle ilk temastan **önce** susan hasta bir alarmdır. Aynı sessizlik ilk temastan
> **sonra** geliyorsa neredeyse her zaman yerel SIM kart demektir. ArrivalGuard bu farkı bilen, olay güdümlü bir vaka ajanıdır.

Terimsiz anlatım (sorun, pazar, kim öder, dürüst zayıf noktalar): [`docs/concept.tr.md`](docs/concept.tr.md)

## Bir bakışta durum

| | |
|---|---|
| ✅ **Yapıldı** | Vaka ajanı, API, koordinatör konsolu, rıza sayfası (TR/EN/AR), sürücü doğrulama sayfası, yerel Nokia simülatörü, Docker, CI. 152 test, %90 kapsam |
| ✅ **Canlı Nokia'da doğrulandı** (27.09.2026) | Şebeke sorguları, rıza kontrolü, abonelikler ve **yalnızca gerçek Nokia olaylarıyla baştan sona bir vaka**: varış → SIM değişimi kapısı → ulaşılabilirlik → havalimanı, koridor ve klinik bölgeleri → vaka kapandı |
| ⏸ **Nerede durduk** | Kalan iki kontrol, Nokia'nın ücretsiz *Simulator* planının verdiğinden fazlasını istiyor: **gerçek telefonda sürücü doğrulama** (desteklenen bir operatörde gerçek SIM gerekiyor) ve **gerçekten hareket eden bir cihazla yolculuk mantığı** (Nokia'nın simüle bölge olayları gerçek bir konumu yansıtmıyor) |

Ayrıntılar: [Proje durumu](#proje-durumu).

## Hızlı başlangıç

```powershell
py -m pip install -e ".[dev]"
py -m pytest                                  # 152 test
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
| **Olay teslimatı:** Nokia → public HTTPS tünel → webhook anahtarıyla `/webhooks/*` → vaka ajanı | ✅ roaming, ulaşılabilirlik ve bölge (area-entered) olayları teslim edildi ve işlendi |
| **Canlı olaylarla baştan sona vaka:** roaming-on (Macaristan) → varış → SIM Swap kapısı sürücü bilgisini bekletti (Nokia bu cihaz için yakın zamanda SIM değişimi bildiriyor) → ulaşılabilirlik → havalimanı, koridor, klinik → vaka kapandı | ✅ her karar kurallarla uyumlu |
| Temizlik: vaka bitince bütün aboneliklerin silinmesi | ✅ açıkta abonelik kalmadı |

Canlı test, ne simülatörün ne de birim testlerin gösterebileceği hatalar buldu. Hepsi düzeltildi, her birine regresyon testi
eklendi ve simülatör artık Nokia'nın kurallarını uyguluyor:

- Cihaz durumu abonelikleri her seferinde **tek olay tipi** kabul ediyor (422).
- Consent Info, W3C DPV biçiminde bir `purpose` ve `requestCaptureUrl` alanı istiyor (422).
- Webhook kimliğinin bir **son kullanma zamanı** (`accessTokenExpiresUtc`) olmalı; bu alan olmadan Nokia bütün abonelikleri reddetti (422).
- **Nokia'nın kendi uçları farklı ülke kodu kullanıyor.** Anlık roaming sorgusu telefon kodunu döndürüyor (Macaristan = 36), roaming
  bildirimleri ise mobil ülke kodunu (Macaristan = 216). Gerçek bir varış "beklenmeyen ülke" sanılıyordu. Ülke artık ikisinde de
  bulunan ISO kodundan (`countryName: ["HU"]`) belirleniyor.
- **Uçuştaki sessizlik alarm üretiyordu.** Hastanın telefonu uçuşta kapalıdır, ama varıştan önceki "ulaşılamıyor" durumu "ilk temastan
  önce kayboldu" sayılıyor ve 5 dakika sonra alarma dönüşüyordu. Varış öncesi sessizlik artık beklenen durum, sayaç inişte başlıyor.
- Silinmiş vakaların `subscription-ends` bildirimlerine 404 dönülüyordu (Nokia tekrar dener); artık kabul ediliyor.

### Nerede durduk, neden

Kalan iki kontrolün kodu yazıldı ve yerelde test edildi. Eksik olan, ücretsiz planın vermediği erişim.

| Henüz doğrulanmayan | Neden durduk | Ne gerekiyor |
|---|---|---|
| **Gerçekten hareket eden cihazla yolculuk mantığı** (koridor dışı, hareketsizlik, "trafik mi, sorun mu?") | Bölge olayları canlıda teslim ediliyor, ama yapay: simüle cihaz Budapeşte'de dururken Nokia İstanbul'daki bölgelerimiz için "girdi" gönderdi. Bu, teslimatı ve işlenmeyi kanıtlıyor; gerçekten yolda olan bir hasta için yolculuk kararlarının doğru olduğunu kanıtlamıyor. | Nokia'nın desteklediği bir şebekede, gerçek bir güzergâhta hareket eden gerçek SIM |
| **Gerçek telefonda sürücü doğrulama** | Number Verification hattı, telefonun kendi mobil veri oturumu üzerinden tanıyor. Ücretsiz plan yalnızca simüle numaraları kapsıyor, bu yüzden yönlendirme → kod → token → doğrulama zinciri gerçek bir telefonda çalıştırılamıyor. Sunucu tarafı (OIDC keşfi) canlıda zaten çalışıyor. | Desteklenen bir operatörde gerçek SIM ve ücretsiz planın ötesinde erişim |

### Üretime geçmek için gerekenler

Bu, çalışan ve test edilmiş bir prototip; sertifikalı bir sağlık ya da güvenlik sistemi değil. Gerçek hastalardan önce:

- Ücretsiz planın ötesinde operatör erişimi (yukarıya bakın) ve kayıtlı bir OIDC dönüş adresi.
- Gerçek bir bildirim sağlayıcısı (`NOTIFY_CHANNEL=webhook` ya da `twilio`). Varsayılan ayar mesajları yalnızca loglar.
- Rıza metninin ve veri işlemenin hukuki incelemesi (KVKK / GDPR).
- TLS ve istek hızı sınırı olan tek düğümlü bir kurulum. Zamanlayıcı tek süreçli, SQLite de tek düğüme uygun.

Tüm geçmiş: [`CHANGELOG.md`](CHANGELOG.md) · API bazında sonuçlar: [`docs/api-availability.md`](docs/api-availability.md).

MENA Ignite Hackathon 2026 (GSMA × Nokia) için geliştirildi · [MIT](LICENSE)
