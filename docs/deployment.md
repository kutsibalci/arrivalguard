# Kurulum ve işletim

## 1. Yerel geliştirme

```bash
pip install -e ".[dev]"
./run.sh simulator          # Windows: .\run.ps1 -Mode simulator
```

`NAC_MODE=simulator` iken API, yerel Nokia taklidine (`:8081`) gerçek path'lerle bağlanır. Simülatörden webhook tetiklemek için:

```bash
curl -X POST http://127.0.0.1:8081/_sim/emit -H 'content-type: application/json' \
  -d '{"subscription_id": "<vakanın subscriptions alanından>", "type": "org.camaraproject.device-roaming-status-subscriptions.v0.roaming-on", "extra": {"countryCode": 90}}'
```

Docker ile: `docker compose up --build` komutu API ile simülatörü birlikte kaldırır ve SQLite verisi `ag-data` volume'unda kalır.

## 2. Canlı Nokia (SIMULATOR planı)

1. <https://networkascode.nokia.io> üzerinden kayıt ol ve SIMULATOR planını seç. RapidAPI anahtarını ve OAuth token'ını al.
2. `.env.example` dosyasını `.env` olarak kopyala: `NAC_MODE=live`, `NAC_RAPIDAPI_KEY`, `NAC_OAUTH_TOKEN`.
3. Önce sondayı çalıştır: `arrivalguard-probe`. Rapor `docs/live-probe/` altına yazılır.

### Public HTTPS sink

CAMARA abonelikleri olayları `PUBLIC_BASE_URL/webhooks/{roaming,reachability,geofence}` adreslerine gönderir. Bu adres internetten
erişilebilen bir **HTTPS** adresi olmalı:

```bash
cloudflared tunnel --url http://127.0.0.1:8000     # → https://<rastgele>.trycloudflare.com
# .env: PUBLIC_BASE_URL=https://<rastgele>.trycloudflare.com
arrivalguard-probe --include-write --sink https://<rastgele>.trycloudflare.com/webhooks
```

Nokia abonelik açarken sink adresinin DNS'te çözüldüğünü kontrol eder. Çözülmeyen bir adres `400 INVALID_SINK` ("Unresolvable callback hostname") döner, bu yüzden sahte bir adresle abonelik denenemez (27.09.2026).

Webhook'lar `Authorization: Bearer $WEBHOOK_TOKEN` başlığıyla doğrulanır. Bu değer abonelik gövdesinde `sinkCredential` olarak Nokia'ya iletilir.

## 3. Üretim kontrol listesi

`APP_ENV=prod` iken aşağıdakilerden biri eksikse uygulama **başlamaz** (`Settings.validate`):

- [ ] `PHONE_HASH_SALT`: uzun, rastgele ve kalıcı bir değer. Değiştirilirse eski hash'ler eşleşmez.
- [ ] `WEBHOOK_TOKEN`: en az 24 karakter, rastgele.
- [ ] `API_KEYS`: her klinik için ayrı anahtar (`clinic-1:<anahtar>`) ve ayrı bir yönetici anahtarı (`*:<anahtar>`). Anahtarlar en az 24 karakter olmalı.
- [ ] `PUBLIC_BASE_URL`: HTTPS olmalı.
- [ ] `STORE_BACKEND=sqlite` (prod varsayılanı) ve kalıcı bir `DB_PATH` volume'u.
- [ ] `NOTIFY_CHANNEL=webhook` (kendi SMS/WhatsApp köprünüz, `NOTIFY_WEBHOOK_SECRET` ile imza doğrulaması) ya da `twilio`.
- [ ] Demo, debug ve manuel olay uçları kapalı olmalı (prod varsayılanı).

Ek öneriler:
- Önde TLS sonlandıran ve istek hızını sınırlayan bir ters vekil kullanın (Caddy, nginx, API gateway). Uygulamada yerleşik hız sınırı yok.
- Tek kopya çalıştırın. Birden çok kopya gerekiyorsa zamanlayıcıyı yalnızca birinde açın (diğerlerinde `SCHEDULER_INTERVAL_S=0`).
  SQLite ağ diskinde paylaşılmamalı.
- `/health` uç noktası prod'da yalnızca `ok` ve sürüm bilgisini döndürür; izleme sistemine bağlanabilir.
- Klinik sicilini `PUT /v1/clinics/{id}` ile yönetici anahtarıyla kurun: zonlar, sürücüler, koordinatör telefonu (alarm SMS'i için, isteğe bağlı).

## 4. Bildirim köprüsü sözleşmesi (`NOTIFY_CHANNEL=webhook`)

```http
POST $NOTIFY_WEBHOOK_URL
content-type: application/json
x-arrivalguard-signature: sha256=<HMAC-SHA256(NOTIFY_WEBHOOK_SECRET, gövde)>

{"id": "case-…-m3", "case_id": "case-…", "to": "patient|driver|family|coordinator", "kind": "welcome_pickup",
 "lang": "en", "channel": "sms", "text": "…", "to_phone": "+44…", "t": "…Z", "status": "queued", "attempts": 1}
```

2xx dönmeyen her yanıt gönderimi `failed` olarak işaretler. Zamanlayıcı en fazla 5 kez yeniden dener. Yanıttaki `x-message-id` başlığı
`provider_id` olarak saklanır.

## 5. Yedekleme ve silme

- SQLite dosyası (`DB_PATH`) ve WAL dosyaları birlikte yedeklenmeli. Yedekler de 30 günlük saklama süresine tabidir.
- Silme talebi: `DELETE /v1/cases/{id}`. İzleme sürüyorsa önce Nokia abonelikleri silinir, ardından vaka kaydı tümüyle kaldırılır.
  Bu işlem geri alınamaz; audit kaydı da silinir. Kliniğin hizmet kanıtını saklama yükümlülüğü varsa önce audit raporunu
  (`GET /v1/cases/{id}/audit`) dışa aktarın.
