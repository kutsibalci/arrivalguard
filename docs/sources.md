# Kaynaklar — rakamlar ve yasal dayanaklar

> Teyit tarihi: **17 Ağustos 2026**. Kural: ✅ olan iddia sunumda kullanılabilir. ⚠ olan iddia **kullanılmaz**, çünkü kaynaksız
> bir rakam jüri önünde en pahalı hatadır.

| İddia | Durum | Kaynak |
|---|:-:|---|
| Türkiye 2024'te **1,5 milyon+** yabancı hastaya hizmet verdi, **3 milyar dolar** gelir elde etti | ✅ | USHAŞ (Sağlık Bakanlığı Uluslararası Sağlık Hizmetleri A.Ş.), 2024. 2023 resmî rakamı: **1.538.643** kişi. 2025 hedefi: 12 milyar dolar |
| Aracı kuruluşlar **USHAŞ** yetki belgesine tabi ve **en az iki dilde 7/24 uluslararası çağrı merkezi** kurmak zorunda | ✅ | *Uluslararası Sağlık Turizmi ve Turistin Sağlığı Hakkında Yönetmelik*, yürürlük **26 Nisan 2025**. Diğer şartlar: en az 3 yetki belgeli tesisle protokol, dil yeterliliği belgeli en az 2 SGK'lı personel, en az 3 dilde web sitesi |
| Suudi Arabistan, Katar ve BAE turizme "milyarlar" yatırıyor | ⚠ | Strateji belgelerine (Vision 2030, Katar Ulusal Turizm Stratejisi) atıf yapılır; **rakam söylenmez** |
| Havalimanında hedef alınan yolcu dolandırıcılığının büyüklüğü | ⚠ **ölçüm yok** | Yayımlanmış bir rakam bulunamadı. Sunum bunu açıkça "ölçülmüyor, yönetilmiyor" diye söyler; ArrivalGuard'ın vaka kaydı bu problemi ilk kez ölçülebilir kılar |

## Ürünü etkileyen bulgu

Yönetmelik, alıcıyı **ruhsatlı** ve **zaten 7/24 çok dilli operasyon kurmakla yükümlü** hale getiriyor. ArrivalGuard yeni bir
maliyet kalemi değil, var olan bir yükümlülüğü verimli hale getiren bir araç. Ayrıca bir düzenleyici (USHAŞ) olduğu için
sektör standardı olarak konumlanabilir.

## Açık sorular

- Yönetmelik hastanın **transferi ve karşılanması** için ayrı bir standart getiriyor mu, yoksa yalnızca çağrı merkezi altyapısı mı isteniyor? Tam metin okunmalı.
- Yabancı hattın yabancı operatörde sorgulanması KVKK kapsamında **yurt dışına veri aktarımı** sayılır mı? Bkz. [privacy.md](privacy.md).
- Türkiye'de sağlık turistlerinin şikâyet verisi (USHAŞ, TÜRSAB) var mı? Varsa dolandırıcılık rakamının yerini alabilir.

## Teknik kaynaklar

- Nokia Network as Code: <https://networkascode.nokia.io> · Python SDK v10.0.0 (`network-as-code`)
- Nokia entegrasyon testleri: <https://github.com/nokia/network-as-code-ts/tree/main/integration-tests>
- CAMARA Device Status (Roaming / Reachability), Geofencing, SIM Swap, Number Verification, Location Verification, Consent Info API tanımları: <https://github.com/camaraproject>
- W3C Data Privacy Vocabulary (Consent Info `purpose`): <https://w3c.github.io/dpv/>
