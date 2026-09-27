# ArrivalGuard — Medikal Turist Varış Koruması

**Şebeke sinyalleriyle, konum geçmişi tutmadan havalimanından kliniğe güvenli karşılama.** · [English](README.md)

> *Aynı sinyal, zıt anlam.* Şoförle ilk temastan **önce** susan hasta bir alarmdır. Aynı sessizlik ilk temastan
> **sonra** geliyorsa neredeyse her zaman yerel SIM kart demektir. ArrivalGuard bu farkı bilen, olay güdümlü bir vaka ajanıdır.

Terimsiz anlatım (sorun, pazar, kim öder, dürüst zayıf noktalar): [`docs/concept.tr.md`](docs/concept.tr.md)

## Hızlı başlangıç

```powershell
python -m pip install -e ".[dev]"
python -m pytest                    # 134 test
.\run.ps1 -Mode simulator           # demo: http://127.0.0.1:8000/demo · konsol: /console · API: /docs
```

`.\run.ps1 -Mode fixture` ile her şey bellekte çalışır (internet gerekmez). `docker compose up --build` API ile simülatörü birlikte kaldırır.
Canlı Nokia kurulumu için: [`docs/deployment.md`](docs/deployment.md).

## Akış

| Aşama | Nokia sinyali | Karar |
|---|---|---|
| Rıza | Hastanın açık onayı + Consent Info | Rıza yoksa izleme de abonelik de yok |
| İniş | Roaming aboneliği (`roaming-on`) | Itinerary ile karşılaştırılır: **varış mı, aktarma mı?** |
| Bütünlük kapısı | SIM Swap (24 sa) | Hat yakın zamanda el değiştirdiyse **sürücü adı ve plakası gönderilmez** |
| Sürücü | **Sürücünün kendi cihazında** Number Verification | Doğrulanırsa hastaya ve sürücüye aynı **buluşma kodu** gider |
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

## Bilinen sınırlar

Bu, testleri geçen çalışan bir prototip; sertifikalı bir üretim sistemi değil. Açık kalan konular:

- **Sürücü OIDC akışı:** sürücü sayfası Number Verification'ın 3-legged OIDC akışını çalıştırıyor (operatöre yönlendirme → kod → cihaz token'ı). Simülatörde ve sahte Nokia ile test edildi; gerçek bir telefonda mobil veriyle henüz denenmedi.
- **Canlı olay teslimatı:** Nokia'nın sabit simüle cihazları geofencing olayı üretmiyor. Canlı roaming ve reachability webhook'ları için public HTTPS sink gerekiyor.
- **Ölçeklenme:** tek süreçli zamanlayıcı ve SQLite ile tek düğüme uygun.

Tam liste: [`CHANGELOG.md`](CHANGELOG.md).

MENA Ignite Hackathon 2026 (GSMA × Nokia) için geliştirildi · [MIT](LICENSE)
