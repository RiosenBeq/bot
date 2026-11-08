# Sonra yapılacaklar - site (01.11.2026)

Sitedeki bekçi ("sistemden haber yok" alarmı), çoklu tesis görünümü (aynı tesis kimliği
iki bilgisayardan gelince uyarı dahil), hesap başına iki adımlı doğrulama ve "bu ay
çalışma" satırı main'dedir; hepsi isteğe bağlıdır ve açılmadıkça site bugünkü gibi
çalışır. Bu dosya sitede KALAN işleri toplar. Programla birlikte bütün liste DALSAN
deposunda: `docs/SONRA-YAPILACAKLAR.md`.

## Sahibin yapacakları (kod gerekmez)

1. **Bekçiyi açmak (isteğe bağlı, önerilir).** Vercel, Settings, Environment Variables
   (Production): `BEKCI=acik`, `BEKCI_ESIK_DK`, `BEKCI_ALICILAR` (yalnız e-posta
   adresleri), `BEKCI_ANAHTARI`, e-posta için `SMTP_*`, Vercel Cron için `CRON_SECRET`;
   sonra Redeploy. Hobby'de cron günde bir çalışır: cron-job.org'da her 5 dakikada
   `/api/bekci` adresine `Authorization: Bearer <BEKCI_ANAHTARI>` başlığıyla istek kurun
   (UptimeRobot ücretsiz planı başlık ekleyemez, `?anahtar=` kullanın). Ayrıntı: README,
   "Bekçi" bölümü.
2. **İkinci fabrika gelince.** Her programa farklı `UZAK_PANO_TESIS_ID`; ana tesisi
   sabitlemek için Vercel'de `ANA_TESIS`. Kimlik göndermeyen (eski) bir program canlı
   rapor gönderdikçe hiçbir tesis komut almaz; Tesisler ekranı bunu uyarıyla söyler.
3. **Yayın sonrası bir kez:** Vercel panosunda son yayının Runtime Logs'una bakın. Bekçi
   açılmadıysa günde bir 403 satırı (Vercel Cron, CRON_SECRET yok) olağandır.
4. **Ayrı oturum anahtarı (isteğe bağlı, önerilir; 08.11.2026).** Vercel'e en az 32
   karakterlik rastgele bir `OTURUM_ANAHTARI` yazıp Redeploy edin: çerez imzasına katılır,
   aşağıdaki güvenlik maddesi 4 kapanır. Eklendiği an bütün oturumlar bir kez düşer.
5. **İki adımlı doğrulama (isteğe bağlı, yöneticiler için önerilir).** Her kişi kendi
   hesabında açar: Sistem, İki adımlı doğrulama, Aç (Google Authenticator ya da Microsoft
   Authenticator, "anahtarı elle gir"). Telefonu kaybedenin iki adımını yönetici
   Kullanıcılar ekranından sıfırlar; kurucuda Vercel'de PANO_SIFRESI değiştirilir. Ayrıntı:
   README, "İki adımlı doğrulama".

## Teknik işler

1. **Çoklu tesis tam ayrımı:** tesis başına pano, komut kuyruğu, bekçi eşiği ve hesap
   yetkisi (bir operatör yalnız kendi tesisine). İkinci saha gerçekten gelince.
2. **Vercel Pro'ya geçilirse** `vercel.json` cron'unu `*/5 * * * *` yapmak. Hobby'de
   alt-günlük cron yayını durdurur; değiştirmeyin.

## Güvenlik incelemesinden kalanlar (02.11.2026, hepsi düşük)

Aynı incelemede paralel denemeyle kilit aşma, kurucu onay şifresine sınırsız deneme,
başka siteden zorla çıkış, bozuk JSON'da çökme, bilinmeyen adı ele veren zaman farkı ve
kanıt fotoğrafının tarayıcı önbelleğinde kalması düzeltildi. **Eşzamanlı rol düşürme** de
kapandı (04.11.2026, rol ve yetki denetimi): oturum sürümünü artıran oku-değiştir-yaz
artık hesap kaydı kilidi altında ve kilit yeniden girilebilir, yani aynı anda yapılan bir
rol düşürme geri yazılamıyor. Kalanlar tasarım kararıdır:

1. **İmzalı fabrika isteğinin tekrarı:** ±300 sn içinde aynı rapor ya da komut sorusu
   tekrar gönderilebilir (TLS'i aşan biri gerekir). İmza karmasını `SET NX EX 600` ile
   saklamak kapatır; rapor başına bir Upstash komutu ekler. Denetimde (08.11.2026)
   bulunan ek: imza adresi kapsamıyor (`zaman.gövde`); imzalı bir `/api/foto` gövdesi
   `/api/rapor`'a da geçiyor ve panoyu bir rapor boyunca boşaltıyor. Sonraki sözleşme
   değişikliğinde imzalanan metne yöntem ve adres eklenmeli (iki depoda birlikte).
2. **İşlem kaydı:** kişi kendi başarılı girişleriyle 1000 satırlık kaydı doldurup
   reddedilen denemesini kaydın dışına itebilir. Ayrı liste ya da hesap başına sınır.
3. **Şifre özeti:** scrypt n=2^14; OWASP en az 2^17 öneriyor. Girişte yeniden özetleme
   ile 2^15-2^17'ye çıkarılabilir (Vercel'de giriş süresi ve bellek artar).
4. **Oturum anahtarı:** ~~`PANO_SIFRESI` ve `RAPOR_ANAHTARI`'ndan türer~~ İsteğe bağlı
   `OTURUM_ANAHTARI` eklendi (08.11.2026); Vercel'e yazılınca kapanır (yukarıda 4).
5. **Bekçi anahtarı adreste:** `?anahtar=` Vercel ve izleme servisi günlüğüne düşer;
   yanlış anahtar sınırlanmaz. Başlıkla gönderim yeğlenmeli (README'de yazıyor).

## Site denetiminden kalanlar (08.11.2026)

Denetimde düzeltilenler main'dedir: giriş kilidi sayacının süresiz kalması (bütün
girişleri kalıcı kapatabiliyordu), adres maskesinin genişletilmesi, Tesisler ekranında
bilgisayar adı sızıntısı, kullanıcı adındaki "İ", bozuk komşu çerez, bekçinin tek SMTP
oturumu, hesap kilidinin jetonla bırakılması, eski raporun "bugün" diye gösterilmesi,
tazelemede odak kaybı ve canlı bölge tekrarı, yüksek karşıtlık, yazdırma, istek zaman
aşımı, çıkışta veri kalması, yazı tipi altkümesi, `demo.js`'in yalnız `/demo`'da
yüklenmesi, 16:9 kamera kutusu, grafik ekseni, ana ekran simgeleri ve CI. Kalanlar:

**Karar ya da sözleşme gerektirenler**
1. **Telefona anlık bildirim (Web Push).** Kritik ihlal ve "haber yok" için. VAPID imzası
   ECDSA P-256 ister; Python standart kütüphanesinde yok: ya tek bağımlılık
   (`cryptography`) ya da saf Python. İçeriksiz bildirim gönderilip veri hizmet
   çalışanına oturumla çektirilirse içerik şifrelemesi gerekmez. iPhone'da yalnız ana
   ekrana eklenmiş uygulamada çalışır (manifest ve simgeler hazır).
2. **Yanlış alarm sebebi ve inceleme notu:** `olay_incele` komutuna `sebep` alanı (DALSAN
   ile birlikte).
3. **Kanıt fotoğrafının anahtarı:** yalnız `olay_id`; fabrika veritabanı sıfırlanır ya da
   ana tesis değişirse eski fotoğraf görünür. Anahtara tesis ve olay zamanı (sözleşme).
4. **Küçük resim:** olay listesindeki 88 px küçük, 960 px'lik asıl fotoğrafı indiriyor.
   Fabrika ~320 px'lik bir küçük de gönderebilir (sözleşme).
5. **Passkey ile giriş:** sunucu doğrulaması için incelenmiş bir kütüphane gerekir.

**Kod (karar gerekmez)**
1. **Giriş ucunun dayanıklılığı:** ad ve genel kilit, kötü niyetli denemelerle meşru
   kullanıcıyı da dışarıda bırakabiliyor; her deneme Upstash komutu harcıyor. Daha önce
   girilmiş cihaza imzalı "cihaz çerezi" verip onu ad ve genel kilitten muaf tutmak (OWASP
   kalıbı) ve Vercel Firewall'da `/api/giris` için hız sınırı kuralı (panelden).
2. **Upstash:** oturumlu her GET oturumu ve veriyi ayrı `MGET`'lerle okuyor; açık bırakılmış
   tek pano ayda ~345 bin komut. Tek okuma ve açık kalan HTTPS bağlantısı.
3. **İşlem kaydı aynı boru hattında:** hesap değişikliği ile kayıt satırı ayrı turda
   yazılıyor (arada Upstash hatasında değişiklik kayıtsız kalır).
4. **Haftalık özet e-postası:** veriler son raporda, SMTP bekçiyle ortak.
5. **Olay arşivi, süzgeç, arama ve CSV:** site gelen raporlardaki olayları biriktirebilir
   (sıralı küme), fabrika değişmeden.
6. **İnceleme modu:** bekleyen ihlaller büyük kanıtla sırayla; klavye kısayolları; toplu
   inceleme.
7. **"Diğer cihazlardan çık"** ve oturum listesi (`oturum_surumu` hazır).
8. **Yapı:** `api/_pano.py` (4.300+ satır) ve `pano.js` (3.700+ satır) modüllere; demo.js
   sunucu kurallarını kopyalıyor (test yok); stil.css ve pano.css ortak değişkenleri ayrı.
9. **Gözlemlenebilirlik ve yedek:** istek başına JSON günlük satırı, 5xx uyarısı; hesaplar,
   yetki tablosu ve işlem kaydı için Upstash yedeği ya da düzenli dışa aktarma.
10. **Erişilebilirlik:** tek seçimli dilimler `aria-pressed` yerine sekme / radyo; iki
    "Tümü" bağlantısının adı; OTP kutusunda ok tuşları; kaydedilmemiş yetki değişikliği
    görünmüyor; ekran okuyucuyla gerçek kullanıcı denemesi.

