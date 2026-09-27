"""Mesaj şablonları (TR/EN/AR) ve ülke adları. Hasta kendi dilinde, sürücü ve koordinatör klinik dilinde (TR) alır."""
from __future__ import annotations

MSG: dict[str, dict[str, str]] = {
    "tr": {
        "consent_request": "Merhaba {name}, {clinic} varışınızda sizi havalimanından kliniğe kadar güvenle karşılamak için "
                           "operatörünüzün şebeke sinyallerini (konum geçmişi TUTULMADAN) kullanmak istiyor. Onay veya ret: {link}",
        "consent_granted": "Teşekkürler {name}. Varış korumanız etkin; istediğiniz an bu bağlantıdan geri çekebilirsiniz: {link}",
        "consent_declined": "Anlaşıldı {name}. Varış koruması etkinleştirilmedi; koordinatörünüz sizinle telefonla iletişim kuracak.",
        "consent_withdrawn": "Rızanızı geri çektiniz {name}. İzleme durduruldu ve abonelikler silindi.",
        "transit": "Merhaba {name}, {country} aktarmanız görüldü. Yolunuz açık olsun — {dest}'e vardığınızda sürücü bilgilerinizi göndereceğiz.",
        "welcome": "Hoş geldiniz {name}! Sürücünüz: {driver} · Plaka: {plate} · Buluşma: {meeting}. Sürücünüz doğrulandığında size bir "
                   "BULUŞMA KODU göndereceğiz — kodu söylemeyen kimsenin aracına binmeyin.",
        "frozen": "Hoş geldiniz {name}. Güvenliğiniz için karşılama detaylarını koordinatörümüz sizi doğrudan arayarak paylaşacak. Lütfen kimsenin aracına binmeyin.",
        "driver_verified": "Sürücünüz {driver} ({plate}) şebeke tarafından doğrulandı ✓ Buluşma kodunuz: {code}. Size bu kodu söylemeyen kimseyle gitmeyin.",
        "driver_ok": "Arayan doğrulanmış sürücünüz ✓ — {driver} ({plate}). Buluşmada kodu ({code}) sizden önce o söylemeli.",
        "driver_bad": "DOĞRULANAMADI ✗ — Bu arayan kayıtlı sürücünüz değil. AÇMAYIN, araca binmeyin. Sürücünüz: {driver} · {plate}.",
        "driver_unverified": "DİKKAT — Arama sürücünüzün numarasından görünüyor ama sürücü doğrulaması yok. Buluşma kodunu duymadan araca binmeyin.",
        "local_sim": "Yerel SIM aldıysanız sorun yok — sizinle bu mesaj kanalından devam ediyoruz. Sürücünüz: {driver} · {plate}.",
        "family": "{name} {clinic}'e güvenle vardı ({time}). Karşılama zinciri doğrulandı. — ArrivalGuard",
        "closed": "{clinic}'e hoş geldiniz {name}. Vaka kapandı; iyi günler dileriz.",
        "driver_code": "ArrivalGuard: {name} için buluşma kodunuz {code}. Hastayla buluştuğunuzda kodu siz söyleyin. Plaka: {plate}.",
        "driver_link": "ArrivalGuard: {name} indi. Hastayı aramadan önce bu bağlantıyı MOBİL VERİ ile açıp cihazınızı doğrulayın: {link}",
    },
    "en": {
        "consent_request": "Hello {name}, to meet you safely from the airport to {clinic}, the clinic would like to use network signals "
                           "from your operator (NO location history is kept). Accept or decline: {link}",
        "consent_granted": "Thank you {name}. Your arrival protection is active; you can withdraw at any time here: {link}",
        "consent_declined": "Understood {name}. Arrival protection is off; your coordinator will contact you by phone.",
        "consent_withdrawn": "You withdrew your consent, {name}. Monitoring has stopped and all subscriptions were deleted.",
        "transit": "Hello {name}, we noticed your layover in {country}. Safe travels — we'll send your driver details when you land in {dest}.",
        "welcome": "Welcome {name}! Your driver: {driver} · Plate: {plate} · Meeting point: {meeting}. Once your driver is verified we will "
                   "send you a MEETING CODE — do not board with anyone who cannot tell you that code.",
        "frozen": "Welcome {name}. For your safety our coordinator will call you directly with pickup details. Please do not board any vehicle yet.",
        "driver_verified": "Your driver {driver} ({plate}) has been verified by the network ✓ Your meeting code: {code}. Do not leave with anyone who cannot say it.",
        "driver_ok": "The caller is your verified driver ✓ — {driver} ({plate}). At pickup they must say the code ({code}) first.",
        "driver_bad": "NOT VERIFIED ✗ — This caller is not your registered driver. Do NOT answer, do not board. Your driver: {driver} · {plate}.",
        "driver_unverified": "CAUTION — This call shows your driver's number but the driver has not been verified. Do not board until you hear your meeting code.",
        "local_sim": "Bought a local SIM? No problem — we continue on this message channel. Your driver: {driver} · {plate}.",
        "family": "{name} arrived safely at {clinic} ({time}). Arrival chain verified. — ArrivalGuard",
        "closed": "Welcome to {clinic}, {name}. Your case is closed; take care.",
        "driver_code": "ArrivalGuard: meeting code for {name} is {code}. Say it first when you meet the patient. Plate: {plate}.",
        "driver_link": "ArrivalGuard: {name} has landed. Before calling, open this link on MOBILE DATA to verify your device: {link}",
    },
    "ar": {
        "consent_request": "مرحباً {name}، لاستقبالك بأمان من المطار إلى {clinic} تود العيادة استخدام إشارات الشبكة من مشغّلك "
                           "(دون الاحتفاظ بسجل المواقع). للموافقة أو الرفض: {link}",
        "consent_granted": "شكراً {name}. حماية وصولك مفعّلة؛ يمكنك سحب الموافقة في أي وقت من هنا: {link}",
        "consent_declined": "مفهوم يا {name}. لم يتم تفعيل حماية الوصول؛ سيتصل بك المنسق هاتفياً.",
        "consent_withdrawn": "لقد سحبت موافقتك يا {name}. توقفت المتابعة وحُذفت جميع الاشتراكات.",
        "transit": "مرحباً {name}، لاحظنا توقفك في {country}. رحلة سعيدة — سنرسل بيانات السائق عند وصولك إلى {dest}.",
        "welcome": "أهلاً بك {name}! سائقك: {driver} · اللوحة: {plate} · نقطة اللقاء: {meeting}. عند التحقق من سائقك سنرسل لك "
                   "رمز لقاء — لا تركب مع أي شخص لا يعرف هذا الرمز.",
        "frozen": "أهلاً بك {name}. لسلامتك سيتصل بك منسقنا مباشرة بتفاصيل الاستقبال. من فضلك لا تركب أي مركبة الآن.",
        "driver_verified": "تم التحقق من سائقك {driver} ({plate}) عبر الشبكة ✓ رمز اللقاء: {code}. لا تغادر مع من لا يعرف الرمز.",
        "driver_ok": "المتصل هو سائقك الموثّق ✓ — {driver} ({plate}). عند اللقاء يجب أن يقول الرمز ({code}) أولاً.",
        "driver_bad": "غير موثّق ✗ — هذا المتصل ليس سائقك المسجّل. لا تردّ ولا تركب. سائقك: {driver} · {plate}.",
        "driver_unverified": "تنبيه — تظهر المكالمة برقم سائقك لكن السائق لم يُتحقق منه. لا تركب قبل سماع رمز اللقاء.",
        "local_sim": "اشتريت شريحة محلية؟ لا مشكلة — نتابع معك عبر هذه القناة. سائقك: {driver} · {plate}.",
        "family": "وصل {name} بأمان إلى {clinic} ({time}). تم التحقق من سلسلة الاستقبال. — ArrivalGuard",
        "closed": "أهلاً بك في {clinic} يا {name}. أُغلقت الحالة؛ نتمنى لك الشفاء.",
        "driver_code": "ArrivalGuard: رمز اللقاء لـ {name} هو {code}. قله أولاً عند اللقاء. اللوحة: {plate}.",
        "driver_link": "ArrivalGuard: وصل {name}. قبل الاتصال افتح هذا الرابط عبر بيانات الجوال للتحقق من جهازك: {link}",
    },
}

COUNTRY_NAMES = {90: "Türkiye", 974: "Katar", 971: "BAE", 966: "Suudi Arabistan", 44: "Birleşik Krallık", 49: "Almanya",
                 20: "Mısır", 962: "Ürdün", 965: "Kuveyt", 968: "Umman", 973: "Bahreyn", 36: "Macaristan"}

SUPPORTED_LANGUAGES = tuple(MSG)


def render(lang: str | None, key: str, **kw) -> str:
    table = MSG.get((lang or "tr").lower()[:2], MSG["tr"])
    return table[key].format(**kw)
