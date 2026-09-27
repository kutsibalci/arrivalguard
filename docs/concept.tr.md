# ArrivalGuard — Fikir anlatımı (teknik olmayan)

> Bu belge fikri **teknik bilgisi olmayan birine** anlatmak için yazıldı. Terim kullanmıyor,
> kullanmak zorunda kaldığında parantez içinde açıklıyor.
> Adı İngilizce: *arrival guard* = varış koruyucusu.

---

## 1. Tek cümlede

Tedavi için yurt dışından gelen bir hastanın en tehlikeli anı **havalimanından çıktığı ilk saat** —
**ArrivalGuard hastanın ülkeye giriş anını telefonunun şebekeye bağlanmasından öğreniyor ve onu
kliniğe kadar güvenli şekilde eşlik ettiriyor.**

Projenin sloganı: **"Şebeke, indikleri anı biliyor."**

---

## 2. Sorun

Bir hasta düşünün: uzun uçuştan yeni inmiş, yorgun, yerel dili bilmiyor, telefonunun interneti henüz
yeni açıldı, nereye gideceğini tam bilmiyor.

Bölgedeki her havalimanının geliş salonunda **tam bu anı hedefleyen** bir ekosistem var:

- Korsan taksiler
- Kendini "klinik şoförü" olarak tanıtan sahte kişiler
- Yeni gelen yolcuları hedefleyen dolandırıcılık mesajları

**Medikal turist için bu, kötü bir taksi ücreti demek değil.** Kaçırılmış bir ameliyat randevusu,
bir sorumluluk davası, ve kliniğe sonraki yüz hastayı kaybettirecek bir yorum demek.

### Bugünkü savunma

Geliş salonunda **üzerinde isim yazan bir karton.**

Herkes karton basabilir. Bu, 19. yüzyıldan kalma bir kimlik doğrulama yöntemi.

### Bu pazar ne kadar büyük

- Türkiye **2024'te 1,5 milyondan fazla** yabancı hastaya sağlık hizmeti verdi ve **3 milyar dolar**
  gelir elde etti (USHAŞ — Sağlık Bakanlığı'nın uluslararası sağlık hizmetleri şirketi).
  2023 rakamı **1.538.643** kişi. 2025 hedefi **12 milyar dolar**
- Suudi Arabistan, Katar ve BAE ulusal turizm stratejilerinde ziyaretçi güvenliğini ve deneyimini
  adı konmuş sütunlar olarak sayıyor (Vision 2030, Katar Ulusal Turizm Stratejisi)
- Havalimanında kaçırılma bu stratejilerin üzerine binen **doğrudan bir vergi** — ve şu an
  ölçülmüyor, yönetilmiyor

**Son madde bir zayıflık gibi görünüyor ama değil.** Bu problemin yayımlanmış bir rakamı yok, çünkü
kimse ölçmüyor. Ölçülmeyen bir problem yönetilemez — ve ArrivalGuard'ın ürettiği vaka kaydı, ilk kez
bu problemi ölçülebilir hâle getiriyor. Argümanı böyle kurmak, rakam uydurmaktan çok daha güçlü.

### 2.1. Teyit sırasında bulunan şey: alıcı ruhsatlı ve denetlenen bir sektör

Türkiye'de bu iş serbest değil. **Uluslararası Sağlık Turizmi ve Turistin Sağlığı Hakkında
Yönetmelik**, 26 Nisan 2025'te yürürlüğe girdi:

- Sağlık kuruluşları hizmet verebilmek için Bakanlık'tan **yetki belgesi** almak zorunda
- **Aracı kuruluşların** yetki belgesini **USHAŞ** veriyor — yani bir düzenleyicisi var
- Aracı kuruluşun sağlaması gereken şartlar arasında: en az 3 yetki belgeli sağlık tesisiyle
  protokol · **uluslararası çağrıları karşılayan, en az iki dilde 7/24 çalışan bir çağrı merkezi
  altyapısı** · yabancı dil yeterliliği belgeli en az 2 SGK'lı personel · en az 3 dilde web sitesi

**Bu, ArrivalGuard'ın satışını tamamen değiştiriyor.** Alıcı:

1. **Ruhsatlı** — kaybedecek bir belgesi var, yani uyum argümanı işliyor
2. **Zaten 7/24 çok dilli bir operasyon kurmak zorunda** — ArrivalGuard tam olarak o operasyonun
   aleti. Yeni bir maliyet kalemi değil, zorunlu bir maliyeti verimli hâle getiren şey
3. **Bir düzenleyicisi var (USHAŞ)** — sektör çapında bir standart olarak konumlanabilir

Yani ArrivalGuard "iyi fikir" değil, **var olan bir yükümlülüğün aracı**.

Bütün rakamların kaynağı: [`sources.md`](sources.md)

---

## 3. Bugün bu nasıl çözülüyor, neden yetmiyor

**Uçuş takibi.** Uçağın ne zaman indiğini söylüyor — ama *bu kişinin* kapıdan çalışan bir telefonla
ne zaman çıktığını söylemiyor. Aktarmalı uçuşlarda tamamen bozuluyor.

**Telefon uygulaması.** Yabancı bir havalimanında, yorgun bir hastanın uygulama kurup açmasını
varsayıyor. Kurmuyorlar.

**Karton tutan personel.** Hiçbir doğrulama yok. Dolandırıcının kartonu birebir aynı görünüyor.

Buradan tek sonuç çıkıyor:

> **Yolcunun ulaşılabilir — ve savunmasız — hâle geldiği anı tam olarak yakalayan tek sensör,
> şebekenin kendisi.**

Telefonun yerel bir şebekeye bağlanması demek: **kişi artık ülkede ve telefonu açık.** Başka hiçbir
sinyal bunu vermiyor.

---

## 4. Fikir nasıl çalışıyor

Sistem her hasta için bir "vaka" açıyor ve yedi adımda yürütüyor:

0. **Rıza.** Hastaya kendi dilinde bir bağlantı gidiyor. Ne kullanılacağını ve neyin asla yapılmayacağını okuyup onaylıyor. Onay
   yoksa hiçbir şey izlenmiyor; istediği an geri çekebiliyor
1. **Tespit.** Hastanın telefonu yerel şebekeye bağlanıyor → operatör haber veriyor → vaka "vardı" oluyor
2. **Kapı.** Buluşma bilgileri gönderilmeden **önce**, hastanın hattının son saatlerde ele geçirilip
   geçirilmediği kontrol ediliyor. Şüphe varsa vaka donduruluyor
3. **Çapa.** Hastaya **kendi dilinde** karşılama mesajı gidiyor: şoför adı, plaka, buluşma noktası
4. **Şoför doğrulama.** Şoför, hastayı aramadan önce kendi telefonundan bir bağlantı açıyor; şebeke "bu telefon gerçekten kayıtlı
   şoförün hattı" diyor. O anda hastaya ve şoföre **aynı 4 haneli buluşma kodu** gidiyor. Hasta, kodu söyleyen araca biniyor.
   Şoförün numarasını taklit ederek arayan biri kodu bilemez
5. **Eşlik.** Beklenen güzergâh bir koridor olarak tanımlanıyor. Koridordan çıkma, uzun duraklama
   veya yol ortasında sessizlik incelemeye alınıyor
6. **Kapanış.** Klinik alanına varış vakayı kapatıyor, zaman damgalı kaydı yazıyor; izleme bitiyor, telefon numaraları siliniyor

Hastanın telefonuna uygulama yok. Kimsenin basacağı düğme yok.

---

## 5. İşin en zor kısmı: aynı sinyal, zıt anlam

Bu, projenin en özgün tarafı ve neden bir "karar veren sistem" olduğunun cevabı.

Bir sinyal düşünün: **"hastanın telefonuna ulaşılamıyor."**

Bu sinyalin anlamı, **ne zaman geldiğine** bağlı olarak tamamen tersine dönüyor:

| Ne zaman | Muhtemel sebep | Ne yapmalı |
|---|---|---|
| Şoförle ilk temastan **önce** | Hasta kaybolmuş, telefonu alınmış, bir sorun var | **Alarmı yükselt** |
| İlk temastan **sonra** | Muhtemelen yerel SIM kart aldı, eski hattı kapattı | **Alarmı düşür** |

Basit bir "olay gelirse alarm çal" sistemi bu ayrımı yapamaz — çünkü olayın anlamını bilmek için
**vakanın o ana kadarki hikâyesini** hatırlaması gerekiyor. Sistem tam bunu yapıyor.

### Alarm çalmamaya karar vermek de bir karar

Gerçek bir örnek akış:

```
21:14  Katar'da şebekeye bağlandı
       → yolculuk planında Doha aktarması var, İstanbul bacağı 01:40
       → hastayı selamla, ŞOFÖRÜ GÖNDERME. Vaka "transit" durumunda kalıyor.
02:55  Türkiye'de şebekeye bağlandı → varış ülkesi + beklenen saat → vaka "varış"
02:55  Hattın ele geçirilip geçirilmediği kontrol edildi → temiz → buluşma bilgileri açıldı
02:57  Hastaya "şoför" diye bir çağrı geldi → kayıtlı hat mı? → EVET
03:20  Araç güzergâh koridorundan çıktı
       → sistem düşünüyor: saat gece 3, çevre yolu kapanması biliniyor,
         sapma bir alternatif rotayla tutarlı
       → güven düşük, KOORDİNATÖRÜ UYANDIRMA. Vakaya not yazıldı.
03:41  Klinik alanına varış → vaka kapandı, kayıt yazıldı
```

Saat 03:20 satırı bu projenin kalbi: sistem **alarm çalmamaya** karar veriyor ve gerekçesini yazıyor.
Alarm yorgunluğu (sürekli yanlış alarm veren sistemin bir süre sonra kimse tarafından
dinlenmemesi) gerçek bir problem ve sistem bunu biliyor.

---

## 6. Bunu şimdi mümkün kılan şey

Telefon operatörleri bir hattın yurt dışı dolaşımına girdiğini, SIM kartın değiştiğini, bir telefonun
gerçekten iddia ettiği hatta olup olmadığını, hattın belirli bir alanda olup olmadığını bilir. Bu bilgi hep
vardı ama **dışarıdan sorulamıyordu**.

Son yıllarda operatörler ortak bir standart (CAMARA) üzerinde anlaştı. ArrivalGuard bu standarttan **yedi ayrı
soru** kullanıyor (dolaşım, ulaşılabilirlik, alan geçişi, SIM değişimi, numara doğrulama, konum hükmü, rıza bilgisi).

**En özgün tarafı:** "bu hat yurt dışı dolaşımına girdi mi" bilgisini bir **tetikleyici** olarak
kullanmak. Bu soru genelde faturalama tarafında akla gelir, ürünün merkezi olarak kullanılmaz.

Türkiye'den Körfez'e operatörler (Turkcell, Türk Telekom, Ooredoo, stc, e&, du, Zain, Omantel) bu
standardı destekliyor.

---

## 7. Kim kullanır, kim para öder

**Kullanan:** Sağlık turizmi aracı kurumu, hastane/klinik koordinasyon birimi, lüks otel karşılama
servisi, hac/umre organizatörü.

**Ödeyen:** Klinik ya da aracı kurum, **hasta başına** (yolculuk başına).

Neden ödemeye değer:

- Bir kaçırılmış ameliyat randevusu, bir yolculuğun maliyetinin kat kat üzerinde
- **Zaman damgalı vaka kaydı** kliniğin özen yükümlülüğü kanıtı — ve sorumluluk davasında kalkanı
- Hasta deneyimi doğrudan yoruma dönüyor; yorum doğrudan sonraki hastalara

**Operatör açısından:** Bu sorular şu an düşük hacimle satılıyor. ArrivalGuard her gelen hastayı bir
vakaya, her vakayı birkaç sorguya çeviriyor — bölgedeki sağlık turizmi hacminde tekrarlayan bir yük.
Ayrıca turizm stratejilerinin içine oturduğu için kamu tarafında da bir muhatabı var.

---

## 8. Bilerek yapmadığımız şeyler

- **Konum sorusu koordinat döndürmüyor.** "Buluşma noktasında mı?" sorusuna **evet/hayır** cevabı
  alıyoruz
- **Hastanın yolculuğu boyunca sürekli konum takibi yok.** Sadece tanımlı koridor ve noktalar
- **Buluşma bilgileri hattın güvenliği doğrulanmadan gönderilmiyor.** Dolandırıcının hattı ele
  geçirmek isteyeceği tek an tam bu an — biz de tam o anda kontrol ediyoruz
- **Ham telefon numarası hiçbir cevapta, hiçbir kayıtta yok** — geri çevrilemeyen parmak izi +
  maskeli gösterim
- **Operatör çökerse hasta "vardı" ya da "güvende" sayılmıyor.** Cevap alınamadıysa koordinatöre
  "şebeke sinyali alınamadı, karar eksik veriyle verildi" uyarısı düşüyor
- **Şüpheli SIM değişiminde sistem fail-open davranıyor ama işaretliyor:** yani akış durmuyor ama
  koordinatör uyarılıyor. Bu bilinçli bir ürün kararı — hastayı havalimanında mahsur bırakmamak için

---

## 9. Şu an elimizde ne var

- Rıza sayfası, vaka açma, üç ayrı şebeke haberi (dolaşım, ulaşılabilirlik, alan geçişi), zamanlayıcı, kalıcı kayıt, bildirim kanalı,
  denetim kaydı — çalışıyor
- **Koordinatör konsolu:** açık vakalar, uyarıları onaylama, dondurulmuş vakayı gerekçeyle serbest bırakma, şoför değiştirme,
  yol kapanması bildirme, yeni vaka formu
- **Demo ekranı:** varış haritası, hastanın telefonu (Türkçe/İngilizce/Arapça, Arapça sağdan sola), tıklanabilir karar günlüğü;
  yedi senaryo tek tuşla
- **134 otomatik test**

**Demonun can alıcı anı:** "Aynı sinyal, zıt anlam" — iki hastada birebir aynı sinyal, iki zıt karar, yan yana ekranda.

---

## 10. Dürüst zayıf noktalar

- **Şoför doğrulamasının canlı hali eksik.** Şebekenin "bu telefon kayıtlı hat" demesi için şoförün telefonunda operatörün yetkilendirme
  akışının çalışması gerekiyor (mobil veriyle; Wi-Fi'da çalışmaz). Sistem bu cevabı kabul etmeye hazır, ama akışı operatörle birlikte
  kurmak gerekiyor
- **Canlıda operatörün bize haber gönderebilmesi için internetten erişilebilir bir adres gerekiyor.** Kurulum belgelendi
  ([`deployment.md`](deployment.md)) ama gerçek bildirim teslimatı henüz canlıda denenmedi
- **Güven skorları sezgisel.** Gerçek vaka verisiyle ayarlanmadı
- **Sistem hastayı korurken hastayı da izliyor.** İyi niyetle bile bu bir gözetim. Rıza ayrı bir sayfada isteniyor, reddetmek hizmeti
  engellemiyor, geri çekmek anında izlemeyi durduruyor — ama hukuki değerlendirme hâlâ gerekli ([`privacy.md`](privacy.md))

---

## 11. Açık sorular

1. **Rıza tasarımı:** Klinik bu izlemeyi "hizmetin parçası" diye sunarsa bu geçerli rıza olur mu?
2. **Yönetmelik:** hastanın *transferi* ve karşılanması için ayrı bir standart var mı, yoksa yalnızca çağrı merkezi altyapısı mı isteniyor?
3. **KVKK ve yurt dışı aktarım:** hasta yabancı, telefonu yabancı operatörde; sorgu o operatöre gidiyor. Bu hangi şartlara tabi?
4. **Problemin büyüklüğü:** havalimanı dolandırıcılığının ölçülmüş bir rakamı yok. Sağlık turisti şikâyet verisi (USHAŞ, TÜRSAB) var mı?
5. **Kalibrasyon:** "aynı sinyal, zıt anlam" akademik olarak bağlama duyarlı karar verme problemi. Güven skorları nasıl kalibre edilmeli?

---

## Ek: teknik ayrıntıya girmek isteyene

- Nasıl çalıştırılır: [`README.tr.md`](../README.tr.md)
- Vaka makinesi ve karar kuralları: [`architecture.md`](architecture.md)
- Hangi operatör soruları kullanılıyor ve canlı sonuçlar: [`api-availability.md`](api-availability.md)
- Demo akışı: [`demo-script.md`](demo-script.md)
