# Canlı fizibilite ve risk kaydı

> Hackathon sürecinde (Ağustos 2026) yazıldı; 0.2.0'da yapılan düzeltmeler en altta. Güncel uç durumu: [api-availability.md](api-availability.md).

> Araştırma tarihi: **22 Ağustos 2026** · Soru: "Bu ürünü prototip fazının sonuna kadar gerçekten
> bitirebilir miyiz, fikir çöp olur mu?"
>
> Kaynak önceliği: Nokia'nın **kendi açık kaynak entegrasyon testleri**
> ([`nokia/network-as-code-ts`](https://github.com/nokia/network-as-code-ts)) — pazarlama sayfası
> değil, Nokia'nın gerçek API'ye karşı koşturduğu testler. Bir uç Nokia'nın kendi testinde
> **aktifse** çalışıyor demektir; **`it.skip()` ile kapatılmışsa** Nokia bile CI'da güvenemiyor demektir.

---

## 1. En kritik sorunun cevabı: olay bildirimi çalışıyor mu?

ArrivalGuard'ın tüm akışı tek bir şeye bağlı: hasta indiğinde operatörün bize **kendiliğinden haber
göndermesi.** Bu çalışmazsa ürün çalışmaz.

**Çalışıyor.** Nokia'nın `deviceStatus.itest.ts` dosyasındaki 11 testin **hiçbiri kapatılmamış**.
Testler dolaşım aboneliği açıyor, 5 saniye bekliyor, bildirim sunucusundan bildirimi çekiyor ve
`expect(data).not.toBeNull()` ile geldiğini doğruluyor. Yani Nokia bu akışı her derlemede kendi
üzerinde deniyor.

Kullanılan olay tipi: `org.camaraproject.device-roaming-status-subscriptions.v0.**roaming-on**`.

### Buradan çıkan tasarım kararı

**Ana tetikleyiciyi `roaming-change-country` değil `roaming-on` yapmalıyız.**

| | `roaming-on` | `roaming-change-country` |
|---|---|---|
| Nokia'nın kendi testinde | ✅ aktif olarak test ediliyor | ✖ test edilmiyor |
| Ne zaman tetiklenir | Cihaz yurt dışı bir şebekeye bağlandığında | Cihaz bir yabancı ülkeden diğerine geçtiğinde |
| Bizim senaryomuzda | **Uçak inip telefon açıldığı an** — tam olarak istediğimiz an | Aktarmalı uçuşta ara durak |

Zaten istediğimiz an `roaming-on`. Hasta uçakta telefonu kapalı, indiğinde Türk şebekesine bağlanıyor
→ olay geliyor → vaka açılıyor. `roaming-change-country` aktarma bacağını ayırmak için **ikincil**
kalır ve "destekleniyor ama canlıda doğrulanmadı" diye işaretlenir.

Bu değişiklik kodda küçük (`types` listesi), riskte büyük.

---

## 2. Uç uç fizibilite tablosu

| Uç | Nokia'nın kendi testi | Faz 2'de canlı gösterilebilir mi | Not |
|---|---|---|---|
| **Roaming aboneliği (bildirim)** | ✅ aktif, bildirim geldiği doğrulanıyor | ✅ evet | Ana tetikleyici. Risk kalktı |
| **Roaming anlık sorgu** | ✅ aktif ("can poll device roaming status true") | ✅ evet | Yedek yol |
| **Reachability aboneliği + anlık** | ✅ aktif (3 farklı simüle numara) | ✅ evet | Ürünün ana sinyali |
| **SIM Swap** | ✅ aktif | ✅ evet | Sabit numara → sabit cevap |
| **Number Verification** | ✅ aktif | ✅ evet | OIDC linki test içinde programatik alınıyor — **demo için gerçek cihaz/mobil veri gerekmiyor** |
| **Location Verification** | ✅ aktif, `TRUE` dönüyor | ✅ evet ama şartlı | ↓ 3. bölüm |
| **Geofencing aboneliği** | ⚠ **tüm testler `it.skip()`** | ◐ abonelik evet, olay hayır | ↓ 4. bölüm |

Yani ArrivalGuard'ın altı API'sinden **beşi** Nokia'nın kendi CI'ında yeşil.

---

## 3. Simüle cihaz sabit bir yerde duruyor

Nokia'nın konum testi `+36719991001` numarasını kullanıyor ve cihaz **Budapeşte'de sabit**
(47.48627616952785, 19.07915612501993). Konum doğrulama bu koordinat etrafında `TRUE` dönüyor.

Bunun iki sonucu var:

**İyi haber:** Konum doğrulamayı canlıda gerçekten çalıştırabiliriz. Demo coğrafyasını simülatörün
kendi koordinatına oturtursak `TRUE` alırız; uzak bir alan verirsek `FALSE` alırız. Yani "buluşma
noktasında mı?" sorusunun **iki cevabını da canlı gösterebiliriz.**

**Kötü haber:** Simüle cihaz **hareket etmiyor.** "Hasta havalimanından çıktı, koridordan saptı"
senaryosu canlı olarak sürülemez. Bu senaryolar yerel simülatörümüzde kalır.

Uygulama: canlı sonda (`arrivalguard-probe`) konum doğrulamayı Budapeşte koordinatıyla dener.

---

## 4. Tek gerçek teknik risk: geofencing

Nokia'nın geofencing entegrasyon testlerinin **tamamı kapatılmış** (`it.skip()`). Sebebi belli:
cihaz hareket etmiyorsa `area-entered` / `area-left` olayı hiç doğmaz.

ArrivalGuard'da geofencing **koridor sapması** ve **klinikte vaka kapanışı** için kullanılıyor.

**Karar:** geofencing'i "canlı kanıt" listesinden çıkar, "abonelik yaşam döngüsü canlı doğrulandı,
olay teslimatı yerel simülatörde gösterildi" diye yaz. Ürünün ana iddiası zaten geofencing değil;
tetikleyici dolaşım, karar ise ulaşılabilirlik yorumu. İkisi de sağlam.

Not: geofencing `POI` alan tipini de destekliyor (`{areaType: "POI", poiName: "..."}`) — havalimanı
gibi tanımlı noktalar için dairesel alandan daha temiz olabilir. Faz 2'de denenmeye değer.

---

## 5. Canlı doğrulama


`networkascode.nokia.io` → SIMULATOR planı → `.env` (`NAC_MODE=live`, `NAC_RAPIDAPI_KEY`, `NAC_OAUTH_TOKEN`) → `arrivalguard-probe`.
Abonelikler için public HTTPS sink ile `arrivalguard-probe --include-write --sink https://…/webhooks` ([deployment.md](deployment.md)).

---

## 6. Sonradan (0.2.0) — canlı sondanın öğrettikleri

- 09.09.2026 sondasında roaming ve reachability abonelikleri **422** döndü: `types must be a list of length 1`. Her olay tipi artık ayrı
  abonelik olarak açılıyor. Yerel simülatör de aynı kuralı uyguluyor, böylece regresyon testte yakalanıyor.
- Consent Info **422**: `purpose` bir W3C DPV terimi olmalı (`^dpv:[a-zA-Z0-9]+$`). Artık `dpv:ServiceProvision` gönderiliyor.
- Number Verification'ın gerçek anlamı: API, isteği yapan cihazın hattını doğruluyor, arayanı değil. Bu yüzden doğrulama sürücünün
  kendi cihazına taşındı ve buluşma kodu eklendi ([mimari §6](architecture.md#6-sürücü-doğrulama-iki-aşamalı-model)).
- Cihaz token'ı, Number Verification'ın 3-legged OIDC akışıyla alınıyor (`nac_client/oidc.py`). Simülatörde ve sahte Nokia ile uçtan uca
  test edildi. Gerçek telefonda mobil veriyle denemek için canlı hesap gerekiyor.

## Kaynaklar

- Nokia entegrasyon testleri: [`deviceStatus.itest.ts`](https://raw.githubusercontent.com/nokia/network-as-code-ts/main/integration-tests/deviceStatus.itest.ts) ·
  [`geofencing.itest.ts`](https://raw.githubusercontent.com/nokia/network-as-code-ts/main/integration-tests/geofencing.itest.ts) ·
  [`location.itest.ts`](https://raw.githubusercontent.com/nokia/network-as-code-ts/main/integration-tests/location.itest.ts) ·
  [`numberVerification.itest.ts`](https://raw.githubusercontent.com/nokia/network-as-code-ts/main/integration-tests/numberVerification.itest.ts)
- Simüle cihaz numaraları: [Device Swap dokümanı](https://networkascode.nokia.io/_docs/device-swap/device-swap) —
  `+99999991000` / `+99999991001` sabit cevap döndürür
