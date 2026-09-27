# Gizlilik ve veri koruma

> Bu belge bir **tasarım kaydıdır**, hukuki görüş değildir. Canlıya geçmeden önce KVKK/GDPR uzmanı ile bir veri koruma etki
> değerlendirmesi (DPIA) yapılmalı ve aydınlatma metni hukukçu tarafından onaylanmalıdır.

## İlkeler ve uygulamadaki karşılıkları

| İlke | Uygulama | Nerede |
|---|---|---|
| **Açık rıza önce gelir** | Vaka `pending_consent` durumunda başlar. Hasta TR/EN/AR rıza sayfasından onay verene kadar şebeke olayı işlenmez ve abonelik açılmaz. Klinik rızayı kendi imzalı formuyla aldıysa `consent.method` olarak kaydedilir | `agent/case_machine.py` `_h_consent`, `web/consent.html` |
| **Rızayı geri çekme** | Aynı bağlantıdan her an geri çekilebilir. İzleme anında durur, abonelikler silinir, ham numaralar silinir | `consent_withdrawn` → `AppContext.finalize` |
| **Operatör tarafı rıza** | Rıza verildikten sonra Consent Info sorgulanır (`purpose=dpv:ServiceProvision`). Operatör işleme izni vermezse izleme başlamaz | `rules.consent_gate` |
| **Konum geçmişi yok** | Sürekli konum takibi yapılmaz. Geofence olayları yalnızca "bölgeye girdi/çıktı" bilgisi taşır. Location **Verification** varışta tek seferlik doğru/yanlış hükmü döndürür. Location Retrieval kullanılmaz. `stored_locations_count` her zaman 0'dır | `rules`, `/v1/state` |
| **Veri minimizasyonu** | KYC sorgusu yapılmaz. Hastanın kimliği kliniğin kendi sürecinde zaten doğrulanmıştır | [api-availability.md](api-availability.md) |
| **Ham numara yalnızca gerektiği sürece** | Numara, izleme süresince Nokia çağrıları ve mesaj gönderimi için tutulur. Vaka terminal duruma geçip bekleyen mesaj kalmayınca (en geç 24 saat içinde) hasta, sürücü ve aile numaraları, rıza ve sürücü token'ları ile buluşma kodu silinir. Geriye maske ve HMAC-SHA256 hash kalır | `Case.purge_pii` |
| **Çıktılarda maskeleme** | API yanıtları, audit raporu, loglar (`MaskingFilter`) ve debug uçları yalnızca maskeli numara gösterir (`+44770***0001`). Buluşma kodu ve bağlantı token'ları koordinatör ekranında da `••••` olarak görünür | `Case.to_dict`, `mask_deep` |
| **Saklama süresi** | Kapanan vaka `AG_RETENTION_DAYS` (varsayılan 30) gün sonra tümüyle silinir. CloudEvent tekilleştirme kayıtları 2 gün sonra silinir | `run_scheduler_once` |
| **Amaçla sınırlılık** | Veri yalnızca varış güvenliği için kullanılır. Pazarlama ya da profil çıkarma yoktur. İsteğe bağlı LLM özetine takma adlı metin gider ve bu özellik varsayılan olarak kapalıdır | `agent/llm_adapter.py` |
| **Silme hakkı** | `DELETE /v1/cases/{id}`: abonelikler ve vaka kaydı hemen, tümüyle silinir | `routes/cases.py` |
| **Erişim kontrolü** | Klinik bazlı API anahtarı kullanılır; bir klinik başka kliniğin vakasını göremez. Rıza ve sürücü sayfaları yalnızca kendi kararını verebilir, vaka ayrıntısı görmez | `api/security.py`, `routes/public.py` |

## İşlenen veri envanteri

| Veri | Kaynak | Amaç | Saklama |
|---|---|---|---|
| Hasta adı, dili, itinerary (ülke kodları ve ETA'lar) | Klinik | Varış eşleme, kendi dilinde mesaj | Vaka kaydı (30 gün) |
| Hasta, sürücü ve aile telefonları | Klinik | Nokia sorguları, mesaj gönderimi | Ham hali: izleme bitene kadar. Maske ve hash: vaka kaydıyla birlikte |
| Roaming ülkesi, ulaşılabilirlik, SIM değişim tarihi, bölge giriş/çıkış, konum hükmü | Operatör (CAMARA) | Karar kuralları | Timeline içinde, karar gerekçesi olarak |
| Mesaj metinleri | Sistem | Hasta, sürücü ve aileye bildirim | Vaka kaydı; kod ve token'lar maskeli |
| Koordinatör aksiyonları (aktör = anahtar parmak izi) | Klinik | Hesap verebilirlik | Vaka kaydı |

## Açık hukuki sorular

1. **Rızanın geçerliliği:** klinik rızayı "hizmetin parçası" olarak sunarsa bu özgür irade sayılır mı? Bu yüzden rıza ayrı bir sayfada
   isteniyor ve reddetmek hizmeti engellemiyor; koordinatör telefonla devam ediyor.
2. **Yurt dışına aktarım:** hastanın hattı yabancı operatörde olduğu için sorgu o operatöre gidiyor. KVKK m.9 kapsamında değerlendirilmeli.
3. **Hassas veri:** sağlık turizmi bağlamı, kişinin tedavi göreceği bilgisini dolaylı olarak ortaya koyar. Klinik adı mesajlarda geçtiği için
   aileye gidecek mesajın içeriği hasta tarafından onaylanmalı.
4. **Sürücünün verisi:** sürücü de ilgili kişidir. Cihaz doğrulaması için sürücüye de aydınlatma yapılmalı.
