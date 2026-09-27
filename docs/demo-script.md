# Demo senaryosu (jüri sunumu)

**Süre:** ~5 dakika · **Ekran:** `http://127.0.0.1:8000/demo` · **Hazırlık:** `.\run.ps1 -Mode simulator` (ya da `-Mode fixture`, internet gerekmez)

---

## 0. Açılış (20 sn)

> "Medikal turist bir uçaktan iniyor. Telefonu yabancı, dili yabancı, karşılayacağı kişiyi hiç görmemiş.
> Kliniğin tek bildiği şey uçuş numarası. İndiği andan klinik kapısına kadarki 90 dakika bugün tamamen kör bir alan."

Ekranın üst satırında kullanılan API'ler, sağ üstte de motto yazıyor: **"Aynı sinyal, zıt anlam."**

## 1. Tam zincir — `Tam zincir (varış → klinik)` (80 sn)

| Adım | Ekranda | Söylenecek |
|---|---|---|
| Doha aktarması | `transit`, kısa selam | "Şebeke Katar'da roaming olayı üretti. Sistem **itinerary'ye bakarak** bunun aktarma olduğunu anladı. Sürücü gönderilmiyor." |
| İstanbul varışı | `release_pickup` | "Hedef ülke ve ETA penceresi tuttu, yani **varış**. Hemen bütünlük kapısı çalışıyor: SIM Swap temiz, sürücü bilgisi serbest. Sürücüye doğrulama bağlantısı gitti." |
| Sürücü numarasından arama | sarı `unverified`, "kodu duymadan binmeyin" | "Arayan sürücünün numarası görünüyor, ama sürücü cihazını henüz doğrulamadı. **Arayan numara taklit edilebilir**; sistem buna güvenmiyor." |
| Başka cihazdan doğrulama denemesi | kırmızı `driver_rejected` | "Biri sürücünün numarasıyla doğrulama yapmaya çalıştı. Şebeke 'bu cihaz o hatta değil' dedi." |
| Sürücü cihazını doğruladı | yeşil `driver_verified`, hastaya buluşma kodu | "Number Verification **sürücünün kendi telefonunda** çalıştı. Hastaya ve sürücüye aynı 4 haneli kod gitti. Hasta, kodu söyleyen araca biniyor." |
| Sahte arama | kırmızı `impostor`, "AÇMAYIN" | "Kayıtlı olmayan bir numara 'sürücüyüm' diyor. Hasta konuşmadan önce uyarıldı." |
| Gerçek sürücü | yeşil `genuine` | "Kayıtlı numara ve taze doğrulama var: ilk temas kuruldu. Bu an birazdan çok önemli olacak." |
| Klinik | `close_case`, aileye mesaj | "Vaka kapandı, aileye kendi dilinde bilgi gitti. Abonelikler silindi, telefon numaraları silindi. Geriye kliniğin hizmet kanıtı kaldı." |

Bir satıra tıkla → `explain[]` açılır. **"Jüri 'neden bu karar?' diye sorunca cevap burada: sinyal, değer, ağırlık, kaynak."**

## 2. Ana gösteri — `Aynı sinyal, zıt anlam` (60 sn)

İki hasta yan yana akıyor ve ikisinde de **aynı** ham sinyal geliyor: `reachable = false`.

- **Fatima:** ilk temas kurulmadan sustu. 7 dakika sonra **ALARM** çaldı, koordinatör uyandırıldı.
- **Yusuf:** doğrulanmış sürücüyle temas kurduktan sonra sustu. Alarm **düşürüldü** ve mesaj kanalına geçildi.

> "Aynı sinyalin iki zıt anlamı var. Bu ayrımı yapmayan bir sistem, yerel SIM alan her hastada yanlış alarm üretir ve
> iki gün içinde kapatılır. Asıl zorluk sinyali almak değil, **ne zaman susulacağını bilmek**."

Karşılaştırma kartı ekranın üstünde kalıyor; ekran görüntüsü alınacak kare bu.

## 3. Varışta SIM değişmiş — `Varışta SIM değişmiş` (35 sn)

> "Bu hasta indiğinde SIM'i 3 saat önce değişmiş. Numara ele geçirilmiş olabilir."

Ekranda: kırmızı `withhold_pickup`, koordinatör alarmı `1/3`. Sürücü kendi cihazını doğrulasa bile **buluşma kodu bu hatta gönderilmiyor**.
Sürücü aradığında da ilk temas sayılmıyor, çünkü karşıdaki kişi hasta olmayabilir. Plaka hiçbir mesajda geçmiyor.

## 4. Trafik mi, sorun mu? — `Trafik mi, sorun mu?` (45 sn)

- Koridor dışında ama hareketli → `probable_traffic` **%25**, vaka notu yazılır, koordinatör **uyandırılmaz**.
- Koridor dışında ve 12 dk hareketsiz → `trouble` **%60**, bildirim `1/3`.
- Buna hastaya ulaşılamaması da eklenince → `trouble` **%85**, bildirim `2/3`. 10 dk sonra `3/3`.
- Sonraki turda **"bütçe doldu → açık uyarıya eklendi"**.

> "Koordinatör en fazla üç kez uyandırılıyor ve süren bir sorun için en erken 10 dakika sonra tekrar. Koordinatör bir yol kapanmasını
> konsoldan bildirirse sapmanın güven skoru düşüyor. Alarm yorgunluğu bu ürünün birinci ölüm nedeni."

## 5. Nokia API çöktü — `Nokia API çöktü` (30 sn)

Ekranda: devre kesici açık, karar `release_pickup` ama **kaynak `error(server)`**, koordinatör konsolunda sarı uyarı:
*"Şebeke sinyali alınamadı — karar eksik veriyle verildi"*.

> "Sinyal alınamayınca uydurma veri üretmiyoruz, 'bilinmiyor' diyoruz. Hasta havalimanında bekletilmiyor,
> ama karar sessizce temiz sayılmıyor; koordinatörün önüne düşüyor."

## 6. Varış sinyali gelmedi — `Varış sinyali gelmedi` (25 sn)

> "Webhook kaybolursa ne olur? Vaka sessizce beklemez. Varış penceresi kapanınca zamanlayıcı operatöre anlık sorgu atıyor:
> hasta hedef ülkede görünüyor. Koordinatör uçuş gecikmesini teyit ediyor ve akış devam ediyor."

## 7. Rıza — `Rıza akışı` (25 sn)

> "Rıza yoksa izleme de yok. Hasta onaylamadan gelen roaming olayı yalnızca audit'e yazılıyor. Hasta onaylayınca abonelikler kuruluyor.
> Geri çektiği anda abonelikler de telefon numarası da siliniyor."

Gerekirse `/console` açılır: vaka listesi, uyarıyı onaylama, gerekçeli manuel serbest bırakma, yol kapanması bildirme.

## 8. Kapanış (20 sn)

> "Konum geçmişi tutmuyoruz, koordinat istemiyoruz, ham numara hiçbir yanıtta yok ve vaka bitince siliniyor. Elimizde kalan tek şey,
> kliniğin hasta dosyasına koyabileceği bir kanıt: karşılama zinciri doğrulandı."

---

## Yedek plan

- İnternet yoksa `.\run.ps1 -Mode fixture` ile her şey aynı çalışır.
- Ekran donarsa `Sıfırla` ile senaryoyu yeniden başlat. Her demo kendi vakasını kurduğu için tekrar çalıştırmak güvenli.
- Sunucu API anahtarı isterse sayfanın üstünde anahtar çubuğu açılır; yönetici anahtarını gir.
