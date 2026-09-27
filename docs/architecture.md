# ArrivalGuard — Mimari

## 1. Tek cümle

Hasta rıza verdikten sonra ArrivalGuard, şebekenin ürettiği olayları dinler. İndiğinde gelen roaming olayını itinerary ile
karşılaştırıp **varış mı aktarma mı** olduğunu anlar. **Hattın ele geçirilmediğini** doğruladıktan sonra karşılama
detaylarını serbest bırakır. Sürücüyü **kendi cihazında** doğrular ve buluşma kodu verir. Klinik kapısına kadar zinciri izler.
Bunları konum geçmişi tutmadan yapar ve iş bitince abonelikleri de ham numaraları da siler.

## 2. Katmanlar

```
src/arrivalguard/
  api/app.py            create_app() — FastAPI, güvenlik başlıkları, zamanlayıcı yaşam döngüsü
  api/context.py        AppContext — TEK olay yolu: makine → bozulmuş sinyal notu → abonelik → bildirim → temizlik → kayıt
  api/routes/           cases (X-API-Key) · webhooks (Bearer) · public (rıza/sürücü token'ı) · demo · system
  api/store.py          MemoryStore | SqliteStore (vaka JSON + indeksler, abonelik eşlemesi, CloudEvent tekilleştirme, klinikler)
  api/notify.py         outbox gönderimi: log | imzalı webhook | Twilio; yeniden deneme
  api/scheduler.py      arka plan tick'i (süreye bağlı kurallar, terminal temizlik, saklama süresi)
  api/security.py       API anahtarı + klinik ayrımı, webhook token'ı, CSP
  api/facade.py         NacFacade (fixture yedeği, live'da kapalı) + SafeFacade (hata → "bilinmiyor", uydurma veri yok)
  agent/case_machine.py deterministik durum makinesi — vakayı değiştiren TEK yer
  agent/messages.py     TR/EN/AR şablonlar
  agent/llm_adapter.py  isteğe bağlı audit özeti (karar vermez)
  rules/decisions.py    saf karar fonksiyonları → Decision(explain[])
  rules/config.py       tüm eşikler (AG_* env)
  nac_client/           TEK Nokia giriş noktası: auth, timeout, retry, circuit breaker, maskeleme; fixture | simulator | live
  simulator/app.py      yerel Nokia taklidi: gerçek path'ler, tek tip abonelik kuralı, sinkCredential ile CloudEvent teslimi
  web/                  demo.html · console.html · consent.html · driver.html (vanilla, CDN yok)
```

Nokia'ya giden çağrılar yalnızca `nac_client` üzerinden yapılır. Durum makinesi de Nokia'yı doğrudan görmez: `nac_facade.call(<metot>)`
kullanır. Bu sayede testlerde facade'ı değiştirmek yeterli olur.

## 3. Durum makinesi

```
pending_consent ──consent_granted──▶ waiting ──roaming_on(varış)──▶ arrived ──SIM Swap──┬─▶ released ──driver_call(genuine)──▶ contacted
      │                                  │                                               └─▶ frozen ──manual_release──▶ released
      ├─consent_declined─▶ declined      └─(pencere geçti, olay yok)─▶ uyarı + anlık sorgu ─▶ coordinator confirm_arrival
      └─(süre doldu)─────▶ expired
contacted ──geofence_left(airport)──▶ in_transit ──geofence_enter(clinic)──▶ closed
aktif her durumdan: escalated (alarm) · consent_withdrawn ─▶ withdrawn · süre dolumu ─▶ expired · close_case ─▶ closed
```

Terminal durumlar (`closed`, `expired`, `declined`, `withdrawn`): abonelikler silinir, bekleyen mesaj kalmadıysa (en geç
24 saat içinde) ham numaralar ve token'lar silinir. Vaka kaydı `AG_RETENTION_DAYS` sonra tümüyle silinir.

## 4. Olay akışı

```
Nokia Roaming (roaming-on / change-country) ─▶ POST /webhooks/roaming ─┐  Bearer sinkCredential (sabit süreli karşılaştırma)
Nokia Reachability (disconnected / data)    ─▶ POST /webhooks/reachability ─┤  abonelik id → (vaka, hedef) indeksi
Nokia Geofencing (area-entered / left)      ─▶ POST /webhooks/geofence ────┤  CloudEvent id tekilleştirme (kalıcı, 2 gün)
Zamanlayıcı (her SCHEDULER_INTERVAL_S)      ─▶ tick(source=scheduler) ─────┤
Koordinatör konsolu                         ─▶ POST /v1/cases/{id}/actions ─┤
Hasta rıza sayfası                          ─▶ POST /v1/consent/{token} ────┤
Sürücü doğrulama sayfası                    ─▶ POST /v1/driver/{token}/verify ┘
                                                        │
                                                        ▼
                                   AppContext.handle → CaseMachine → rules/decisions (explain[])
```

**Tek tip kuralı:** Nokia `device-status` v0.8 abonelikleri `types` alanında tek eleman kabul ediyor (09.09.2026'da canlıda 422 döndü).
Bu yüzden her olay tipi için ayrı abonelik açılıyor: roaming ×2, reachability ×2 ve 3 geofence, toplam 7 abonelik.
Abonelikler en geç hedef ETA + `AG_CASE_MAX_HOURS` sonra sona erer ve vaka bittiğinde silinir.

## 5. Ürünün çekirdek fikri: aynı sinyal, zıt anlam

| Vaka durumu | Yorum | Karar |
|---|---|---|
| İlk temastan **önce** 5 dk ve üstü sessizlik | Hasta karşılama zincirine hiç bağlanmadı | `alarm`, koordinatör uyandırılır |
| İlk temastan **sonra** 30 dk'ya kadar sessizlik | Büyük olasılıkla yerel SIM/eSIM aldı | `lower`, alarm düşürülür ve mesaj kanalına geçilir |
| İlk temastan sonra 30 dk'yı aşan sessizlik | Tolerans aşıldı | `raise`, yolculuk kontrolüyle birlikte değerlendirilir |
| Sinyal **bilinmiyor** (şebeke cevap vermedi) | Karar verilemez | Durum değişmez; "eksik veri" uyarısı yazılır |

Alarm yorgunluğuna karşı iki önlem var:
- **Eskalasyon bütçesi** (`AG_ESCALATION_BUDGET_PER_CASE=3`): vaka başına koordinatör en fazla bu kadar uyandırılır.
- **Yeniden uyandırma aralığı** (`AG_REESCALATE_AFTER_MIN=10`): süren bir sorun için en erken bu kadar dakika sonra tekrar uyandırılır.

Bütçe dolduğunda yeni bildirim gönderilmez, kanıt açık uyarıya eklenir.

## 6. Sürücü doğrulama: iki aşamalı model

Number Verification, "beni arayan hat kimin?" sorusunu **cevaplayamaz**. API, isteği yapan cihazın kendi hattını mobil veri
oturumu üzerinden (3-legged OIDC) doğrular. Bu yüzden doğrulama iki aşamalı:

1. **Cihaz tasdiki** (`authenticate_driver_device`): hasta vardığında sürücüye bir bağlantı gider. Sürücü bağlantıyı mobil veriyle
   açar ve Number Verification "bu cihaz kayıtlı sürücünün hattında" der. Bunun sonucunda taze bir tasdik ve 4 haneli bir
   **buluşma kodu** oluşur. Kod hem hastaya hem sürücüye gider; koordinatör ekranında maskelidir. Vaka SIM değişimi yüzünden
   dondurulmuşsa kod hastaya gönderilmez.
2. **Gelen arama** (`assess_incoming_call`): numara sicilde yoksa sonuç `impostor`, hastaya "açmayın" denir. Numara sicilde var ama taze
   tasdik yoksa sonuç `unverified` olur, yani numara taklidi olabilir; hastaya "kodu duymadan binmeyin" denir. İkisi de tutuyorsa `genuine` ve ilk temas kurulur.

Arayan numara taklit edilebilir; asıl güvence yüz yüze söylenen koddur.

**Cihaz token'ı nasıl alınır (3-legged OIDC, `nac_client/oidc.py`):**

1. Sürücü sayfasında "Cihazımı doğrula" → `GET /v1/driver/{token}/nv/start`. Sunucu tek kullanımlık bir `state` üretir
   (10 dk geçerli) ve telefonu operatörün `authorization_endpoint`'ine yönlendirir (`login_hint` = kayıtlı sürücü hattı).
   Uç adresi ve istemci bilgileri `/.well-known/openid-configuration` ile `oauth2/v1/auth/clientcredentials`'tan alınır.
2. Telefon bu adresi **mobil veriyle** açtığı için operatör hattı ağdan tanır ve `/driver/nv/callback?code=…&state=…`'e döner.
   Wi-Fi'dayken operatör `error` ile döner; sayfa sürücüye mobil veriye geçmesini söyler.
3. Sunucu kodu `token_endpoint`'te cihaz token'ına çevirir, Number Verification'ı bu token'la çağırır ve sürücüyü
   `/driver/{token}?nv=ok|fail|network|error` sayfasına geri gönderir. Kod ve token tarayıcıya hiç verilmez.

Fixture modunda operatör adımı atlanır (`sim-code:<hat>`), simülatör aynı uçları HTTP üzerinden sunar. İkisinde de
`sim_line` parametresi cihazın hattını taklit eder; canlı modda bu parametre reddedilir. Operatör SDK'sı olan bir mobil
uygulama token'ı kendisi alıp doğrudan `POST /v1/driver/{token}/verify` ile gönderebilir.

## 7. Yolculuk bütünlüğü: trafik mi, sorun mu?

| Koridor dışı | Hareketsiz ≥ 10 dk | Hasta ulaşılamıyor | Bildirilmiş yol kapanması | Karar | Güven |
|---|---|---|---|---|---|
| ✓ | ✗ | – | – | `probable_traffic` (koordinatör uyandırılmaz) | 0.25 |
| ✓ | ✓ | ✗ | ✗ | `trouble` | 0.60 |
| ✓ | ✓ | ✗ | ✓ | `probable_traffic` (vaka notu) | 0.40 |
| ✓ | ✓ | ✓ | ✗ | `trouble` | 0.85 |
| ✓ | ✓ | ✓ | ✓ | `trouble` | 0.65 |
| ✗ | ✗ | – | – | `ok` | 0.95 |

Gece saati karara etki etmez; gece trafik az olduğu için hareketsizlik daha anlamlı hale gelir. Yine de bağlam olarak `explain[]`'a yazılır.
Güven değerleri sezgisel başlangıç değerleridir ve `AG_*` ile ayarlanabilir. Gerçek vaka verisiyle kalibrasyon yapılmadı.

## 8. Dayanıklılık

- **`nac_client`:** 4 sn timeout, 2 yeniden deneme (üstel geri çekilme), API başına devre kesici (3 hata sonrası 20 sn açık, yarı-açıkta tek deneme).
- **`SafeFacade`:** Nokia düşerse `data={}` ve `source="error(<kind>)"` döner. Karar eksik veriyle verilirse koordinatöre "Şebeke sinyali
  alınamadı" uyarısı gider (fail-open, ama sessiz değil). Live modda fixture yedeği **kapalıdır**; uydurma veriyle karar verilmez.
- **Kaçan webhook:** varış penceresi kapanınca bir kez anlık roaming sorgusu yapılır ve koordinatör uyarılır. `subscription-ends` olayı
  "izleme boşluğu" uyarısı üretir.
- **Bildirim hatası** akışı durdurmaz. Mesajlar outbox'ta kalır ve zamanlayıcı en fazla 5 kez yeniden dener.

## 9. Kalıcılık ve ölçek

`SqliteStore` tek düğüm içindir. Vaka, JSON kayıt olarak saklanır; arama için ek sütunlar tutulur (klinik, durum, telefon hash'i,
token hash'leri). Tüm erişim tek bir kilit altında yapılır. Zamanlayıcı süreç içinde çalışır; birden çok kopya çalıştırılacaksa
yalnızca birinde açık olmalıdır (`SCHEDULER_INTERVAL_S=0`). Yatay ölçek için bir sonraki adım: Postgres, satır kilidi ve ayrı bir
worker süreci.

## 10. LLM'in yeri

Ajan davranışı deterministiktir: test edilebilir, açıklanabilir ve maliyeti öngörülebilir. LLM (isteğe bağlı, `LLM_PROVIDER=anthropic`)
yalnızca kapanan vaka için kliniğin kaydına girecek **okunabilir bir özet** yazar. Modele giden metinde hasta ve sürücü adları takma adla
değiştirilir; numaralar zaten maskelidir. Model reddederse ya da hata olursa özet kural notlarından üretilir. Karar mantığı asla LLM'e taşınmaz.
