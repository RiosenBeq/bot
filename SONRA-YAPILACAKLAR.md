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
   "Bekçi" bölümü. Sahibi onayladı (19.11.2026, G46); Vercel'de yazılmayı bekliyor.
2. **İkinci fabrika gelince.** Her programa farklı `UZAK_PANO_TESIS_ID`; ana tesisi
   sabitlemek için Vercel'de `ANA_TESIS`. Kimlik göndermeyen (eski) bir program canlı
   rapor gönderdikçe hiçbir tesis komut almaz; Tesisler ekranı bunu uyarıyla söyler.
3. **Yayın sonrası bir kez:** Vercel panosunda son yayının Runtime Logs'una bakın. Bekçi
   açılmadıysa günde bir 403 satırı (Vercel Cron, CRON_SECRET yok) olağandır.
4. **Ayrı oturum anahtarı (isteğe bağlı, önerilir; 08.11.2026).** Vercel'e en az 32
   karakterlik rastgele bir `OTURUM_ANAHTARI` yazıp Redeploy edin: çerez imzasına katılır,
   aşağıdaki güvenlik maddesi 4 kapanır. Eklendiği an bütün oturumlar bir kez düşer. Sahibi
   onayladı (19.11.2026, G46); Vercel'de yazılmayı bekliyor.
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
3. **DALSAN `docs/19` site içi ayrıntısı (20.11.2026):** §3.1 yeni özetin n'sini 2^14
   yazıyor (site artık 2^15 yazar, 2^14..2^17 okur), §3.3 `komut_red`'i
   `dalsan:kayit:oturum`'da sayıyor (artık `dalsan:kayit:red`, 200 satır). Program bu
   ayrıntıları kullanmaz, sözleşme değişmedi; belge DALSAN'da düzeltilmeli.

## Kameralar ekranı, Yönetim ve Bilgisayar kartından kalanlar (17.11.2026)

Yönetim kartında kurulum adı, yalnız ekrandaki kameraların anlık görüntüsü (128 kamera) ve
Bilgisayar kartında seçilen donanım ile kart notu bu dalda (`site-entegrasyon`); DALSAN'da B10
#5-#7. Kalanlar küçüktür, hiçbiri uyarıyı kaybettirmez:

1. ~~**"Sorunlu" çipi bütün kutucukları gizlerse** ... fabrika bütün kameraları gönderir; ekran ilk
   açıldığında altıda bir olasılıkla bir rapor aralığı hepsi gider.~~ Yapıldı (17.11.2026): yeni
   panonun boş listesi ne "hepsi" ne "ekran açık" işaretini koyar, fabrikadan görüntü istenmez;
   kutucuklar çizilince pano listeyi hemen bildirir (`KARE_ILK_LISTE_MS`). Dolu ama çözülemeyen
   liste eskisi gibi "hepsi" sayılır.
2. ~~**Statik dosyalarda sürüm kuralı yok:** önbellekte kalmış eski `pano.js` açık bir sekmede
   "hepsi" işaretini koyar.~~ Yapıldı (17.11.2026): `/api/durum` sitenin sürümünü söyler
   (`VERCEL_GIT_COMMIT_SHA`), pano ilk gördüğü sürüm değişince sayfayı yeniler (yazı yazılırken ya
   da pencere açıkken değil; 5 dakikada en çok bir kez). Bu değişiklikten önce açılmış sekmeler
   bir kez elle yenilenmeli.
3. **Seçimi aynı anda yazan iki pano** bir okuma turu (5 sn) boyunca birinin eklediğini
   kaybedebilir; bir sonraki okumada kendiliğinden düzelir.
4. ~~**Kararı belgede olmayan iki değer:** yarım ekran payı (`GORUNUR_PAY = 0.5`) ve seçimin 45 sn
   tutulması (`KARE_SECIM_SURESI_SN`).~~ Sahibi onayladı (19.11.2026, G46); README ve kodda karar
   olarak yazılı, test değeri kilitler. Kalan: yük tablosu tek bakan kişiyle ve 45 KB'lık kareyle bir
   tahmindir; gerçek Upstash ve Vercel'de ölçülmedi.
5. **Görünüm:** ~~Bilgisayar kartında uzun "Kart notu"nun yanındaki etiket satırın dikey ortasında
   durur~~ (17.11.2026: etiket değerin ilk satırıyla hizalanır); ~~Yönetim kartında git kaynak
   kurulumu artık "(git)" bilgisini göstermez (adı program yazar)~~ Yapıldı (19.11.2026, G46):
   `yonetim.kurulum` `git` ise ada "git" eklenir ("Kaynak kurulumu (Başlat betiği, git)").
6. ~~**Otomatik güncelleme panoda yalnız Olaylar ve Teşhis'te görünür**~~ Yapıldı (19.11.2026,
   G46): program raporun `yonetim.otomatik_guncelleme`'sinde Teşhis'teki satırı (başlıksız,
   ayrıntısı süzülmüş, en çok 200 karakter) gönderir; site onu süzer ve Yönetim ekranının
   Güncelle kartında "Otomatik güncelleme: ..." olarak gösterir. Ortak örnek
   `tests/sozlesme/rapor-otomatik-guncelleme.json`.

## Güvenlik incelemesinden kalanlar (02.11.2026, hepsi düşük)

Aynı incelemede paralel denemeyle kilit aşma, kurucu onay şifresine sınırsız deneme,
başka siteden zorla çıkış, bozuk JSON'da çökme, bilinmeyen adı ele veren zaman farkı ve
kanıt fotoğrafının tarayıcı önbelleğinde kalması düzeltildi. **Eşzamanlı rol düşürme** de
kapandı (04.11.2026, rol ve yetki denetimi): oturum sürümünü artıran oku-değiştir-yaz
artık hesap kaydı kilidi altında ve kilit yeniden girilebilir, yani aynı anda yapılan bir
rol düşürme geri yazılamıyor. Kalanlar tasarım kararıdır:

1. ~~**İmzalı fabrika isteğinin tekrarı:** ±300 sn içinde aynı rapor ya da komut sorusu
   tekrar gönderilebilir (TLS'i aşan biri gerekir).~~ Yapıldı (20.11.2026): imza
   karması `SET NX EX 600` ile saklanır, tekrar 409 `tekrar` alır; karma adresten
   bağımsız olduğu için imzalı bir `/api/foto` gövdesi `/api/rapor`'a da geçemez. Program
   her gönderimi (yeniden deneme dahil) yeni damgayla imzalıyor (`_imzali_post`), etkilenmez.
   Bedel: fabrika isteği başına bir komut ve bir tur (30 sn raporla ayda ~86 bin). Kalan:
   özgün istek hiç ulaşmadan (araya giren biri onu durdurup) başka adrese gönderilirse
   yine geçer; sonraki sözleşme değişikliğinde imzalanan metne yöntem ve adres eklenmeli
   (iki depoda birlikte).
2. ~~**İşlem kaydı:** kişi kendi başarılı girişleriyle 1000 satırlık kaydı doldurup
   reddedilen denemesini kaydın dışına itebilir.~~ Yapıldı (20.11.2026): `komut_red`
   kendi listesinde (`dalsan:kayit:red`, 200); hatalı girişler zaten ayrıydı. Ekrandaki
   300 satırlık kesme yalnız başarılı satırlara uygulanır.
3. ~~**Şifre özeti:** scrypt n=2^14; OWASP en az 2^17 öneriyor.~~ Yapıldı (20.11.2026):
   yeni özet n=2^15 (~32 MB, ~65 ms); eski özet geçerli ve ilk başarılı girişte hesap
   kilidi altında yeniden yazılır. Kalan: 2^17 (128 MB, ~0,3 sn) Vercel'de ölçülmedi;
   girişte yenilenmemiş eski hesap bilinmeyen addan biraz hızlı cevap verir.
4. **Oturum anahtarı:** ~~`PANO_SIFRESI` ve `RAPOR_ANAHTARI`'ndan türer~~ İsteğe bağlı
   `OTURUM_ANAHTARI` eklendi (08.11.2026); Vercel'e yazılınca kapanır (yukarıda 4).
5. **Bekçi anahtarı adreste:** `?anahtar=` Vercel ve izleme servisi günlüğüne düşer;
   ~~yanlış anahtar sınırlanmaz~~ (Yapıldı (20.11.2026): adres başına 15 dakikada 10
   yanlıştan sonra o adres doğru anahtarla da 429 alır; sitenin istek günlüğü sorgu
   değerini yazmaz). Kalan: başlıkla gönderim yeğlenmeli (README'de yazıyor).

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
1. **Giriş ucunun dayanıklılığı:** ~~ad ve genel kilit, kötü niyetli denemelerle meşru
   kullanıcıyı da dışarıda bırakabiliyor~~ Yapıldı (20.11.2026): başarılı girişte imzalı
   `pano_cihaz` çerezi (OWASP kalıbı, 180 gün, yalnız `/api/giris`); o adla geçerli
   çerezi olan cihaz ad ve genel kilitten muaf, kendi sayacına (15 dk'da 5) takılır.
   Kalan: her deneme yine Upstash komutu harcıyor; Vercel Firewall'da `/api/giris` için
   hız sınırı kuralı (panelden, kod gerekmez).
2. **Upstash:** ~~oturumlu her GET oturumu ve veriyi ayrı `MGET`'lerle okuyor~~ Yapıldı
   (20.11.2026): pano tazelemesi (`GET /api/durum`) oturumu ve veriyi tek `MGET`'te okur
   (ölçüldü: istek başına 2 tur ve 2 komut yerine 1). Kalan: açık kalan HTTPS bağlantısı
   (urllib her istekte yeni bağlantı açar; Vercel işlevi kısa ömürlü, kazanç belirsiz) ve
   öbür oturumlu GET'ler (hesap, kare) ayrı okuyor.
3. ~~**İşlem kaydı aynı boru hattında:** hesap değişikliği ile kayıt satırı ayrı turda
   yazılıyor (arada Upstash hatasında değişiklik kayıtsız kalır).~~ Yapıldı (20.11.2026):
   hesap ekleme / rol / şifre / kapatma / silme / iki adım / rol yetkileri, giriş ve
   çıkış değişikliği satırıyla tek boru hattında yazar.
4. **Haftalık özet e-postası:** veriler son raporda, SMTP bekçiyle ortak.
5. **Olay arşivi, süzgeç, arama ve CSV:** site gelen raporlardaki olayları biriktirebilir
   (sıralı küme), fabrika değişmeden.
6. **İnceleme modu:** bekleyen ihlaller büyük kanıtla sırayla; klavye kısayolları; toplu
   inceleme.
7. **"Diğer cihazlardan çık"** ve oturum listesi (`oturum_surumu` hazır).
8. **Yapı:** `api/_pano.py` (4.300+ satır) ve `pano.js` (3.700+ satır) modüllere; demo.js
   sunucu kurallarını kopyalıyor (test yok); stil.css ve pano.css ortak değişkenleri ayrı.
9. **Gözlemlenebilirlik ve yedek:** ~~istek başına JSON günlük satırı~~ (Yapıldı
   (20.11.2026): yol, sorgu alan adları, kod, ms, rol, hata kodu; sır ve ad yazılmaz).
   Kalan: 5xx uyarısı; hesaplar, yetki tablosu ve işlem kaydı için Upstash yedeği ya da
   düzenli dışa aktarma.
10. **Erişilebilirlik:** tek seçimli dilimler `aria-pressed` yerine sekme / radyo; iki
    "Tümü" bağlantısının adı; OTP kutusunda ok tuşları; kaydedilmemiş yetki değişikliği
    görünmüyor; ekran okuyucuyla gerçek kullanıcı denemesi.

