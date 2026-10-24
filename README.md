# NextGen Detector · Uzak izleme sitesi

DALSAN İSG Görüntü Analiz Sistemi'nin ([RiosenBeq/DALSAN](https://github.com/RiosenBeq/DALSAN))
Vercel'de duran sitesi. İki sayfası var:

| Adres | Ne |
|---|---|
| `/` | Tanıtım: sistemin ne yaptığı, nasıl çalıştığı, veri güvenliği notu |
| `/pano` | Şifreli **uzak izleme panosu**: bugünün özeti, son 14 günün eğilimi, kameraların anlık görüntüsü, kanıt fotoğraflı son olaylar, kurulu olduğu bilgisayar ve **Müdahale** (uzaktan anons, hoparlör denemesi) |

Fabrikadaki program bu siteye düzenli aralıkla (varsayılan 30 sn) kısa, **imzalı**
bir durum özeti, ihlallerin kanıt fotoğrafını ve (Kameralar ekranı açıkken)
kameraların anlık görüntüsünü gönderir. Bağlantı yalnız fabrikadan dışarı doğrudur: fabrikada
port açılmaz, modeme dokunulmaz. Fabrikadan 90 saniye haber gelmezse pano
kırmızıyla "haber yok" der; program kapatılırken son bir "kapatıldı" raporu
gönderdiği için bilerek kapatmayı bağlantı kopmasından ayırır.

## Siteye ne gelir, ne gelmez

| Siteye gelir | Ne kadar durur | Siteye gelmez |
|---|---|---|
| Sistem çalışıyor mu, analiz, model, sistem şeridindeki sorunlar, boş disk | 7 gün (her raporda yenilenir) | Kamera ve hoparlör adresleri, kullanıcı adları, şifreler |
| Kameraların adı, bölümü, bağlantı durumu, kare hızı | 7 gün | Video kaydı (yalnız tek kareler gelir) |
| Bugünkü ve dünkü ihlal, inceleme bekleyen, aktif kural, saatlik dağılım, son 14 gün | 7 gün | Kural ve kamera ayarları |
| Son 20 olayın adı, yeri, önemi, durumu, zamanı; sistem olayının açıklaması (şifresi gizlenmiş) | 7 gün | Takip numarası, olayın ayrıntı kaydı |
| İhlallerin **kanıt fotoğrafı** (en çok 960 px, ihlal başına bir kez) | 7 gün, en çok 60 fotoğraf | |
| Kameraların **anlık görüntüsü** (640 px, 10 saniyede bir) | 2 dakika; yalnız Kameralar ekranı açıkken gelir | |
| Kurulu olduğu bilgisayar: adı, IP adresi, işletim sistemi, donanım | 7 gün | Oturum açan kullanıcının adı |

**Akıcı canlı görüntü bu siteden geçmez.** Panodaki anlık görüntü 10 saniyede
bir yenilenir. Akıcı görüntü için fabrika ağına VPN ya da Tailscale ile
bağlanılır (DALSAN `docs/15-UZAKTAN-ERISIM.md` §4.1). O adres `FABRIKA_ADRESI`
olarak yazılırsa panoda "Fabrika ekranını aç" düğmesi çıkar.

> **Fabrika içi kullanım (operatör kararı 24.10.2026).** Pano fabrikanın kendi
> kullanımı içindir; görüntünün siteye gelmesi bu kararla açıldı. Bilinmesi
> gerekenler: Vercel ve Upstash'in sunucuları yurt dışındadır; görüntüler
> yalnız şifreyle giren kişiye gösterilir ve yukarıdaki sürelerin sonunda
> kendiliğinden silinir. Program tarafında uzak pano varsayılan olarak
> **kapalıdır**; açmak fabrikanın kararıdır.

## Yönetici (patron) görünümü

Pano, fabrikaya hiç gitmeyen birinin bir dakikada okuyacağı biçimde kuruldu.
Yurt dışındaki benzer ürünlerin yönetici ekranlarına bakıldı: Intenseye'ın
[Global View'u](https://www.intenseye.com/software/) tesis başına eğilimi ve
tehlike türlerini, [Protex AI](https://www.protex.ai/reporting/reporting-and-workflows)
alan ve vardiya karşılaştırmasını, [Voxel](https://www.voxelai.com/news/voxel-launches-impact-boards-ai-powered-dashboards-to-improve-workplace-safety-management-and-operational-efficiency)
risk eğilimini, Visionify ([G2](https://www.g2.com/products/visionify/reviews))
günlük ve haftalık eğilimle "incelenen" sayısını öne koyuyor. İş güvenliği
ölçümü üzerine yazılanlar da yöneticiye az ve güvenilir gösterge vermeyi,
eğilimi haftadan haftaya karşılaştırmayı öneriyor
([NSC](https://www.nsc.org/getmedia/a3f19e6b-6688-4474-84ed-54325c16155f/wp-practicalguidetoli.pdf),
[EcoOnline](https://www.ecoonline.com/en-us/blog/leading-indicators/)).

Buradan alınanlar, sade haliyle:

- **Bugünün özeti:** 4-6 kısa cümle; önce sorun, sonra bugün, haftalık eğilim,
  en çok ihlal görülen yer, inceleme ve kameralar.
- **Son 14 gün:** günlük çubuk grafiği, son 7 günü önceki 7 günle karşılaştıran
  rozet (azalma yeşil) ve inceleme oranı.
- **En çok ihlal görülen yerler** (son 7 gün, kamera başına) ve ihlal türleri.
- **Kurulu olduğu bilgisayar:** kurulum adı, bilgisayar adı, IP adresi,
  işletim sistemi, işlemci, bellek, ekran kartı, disk, kurulum türü ve tarihi.
- **Kanıt fotoğrafı ve anlık görüntü:** her ihlalin yanında fotoğrafı durur
  (dokununca büyür); Kameralar ekranında kameraların 10 saniyede bir yenilenen
  görüntüsü, köşesinde bağlantı durumu.

Bilerek alınmayan: ürünlerin "güvenlik puanı". O puanın formülü her üreticide
farklı ve gizli; uydurulmuş bir puan yerine her sayı gerçek bir sayımdır.

## Uzaktan müdahale

Panonun **Müdahale** ekranından iki küçük iş yapılır: fabrikanın Anons
sayfasındaki **hazır** bir mesajı "Tüm fabrika" kanallarından ya da seçilen
kanaldan çaldırmak ve bir kanaldan **deneme sesi** vermek. Başka hiçbir şey
(serbest metin, kural, kamera, ayar) yapılamaz.

- Fabrikaya dışarıdan bağlanılmaz. Ekran açıkken site, programın raporuna "sık
  sor" der; program birkaç saniyede bir `/api/komut`'a imzalı istek gönderip
  komutu alır, yürütür ve sonucu bildirir. Ekran kapalıyken program sormaz;
  ekrana 10 dakika dokunulmazsa dinleme bekler.
- Komut 2 dakika içinde alınmazsa düşer. 5 dakikada en çok 10 komut.
- Anonsta onay, denemede çift dokunuş istenir (cepte yanlışlıkla ses çıkmasın).
- Her müdahale fabrikadaki Olaylar'a yazılır ve izleme ekranlarında görünür.
- Program tarafında ayrıca açılır (Ayarlar → Uzak izleme panosu → Uzaktan
  müdahale); kapalıyken ekran nasıl açılacağını söyler.

## Kanıt fotoğrafı ve anlık görüntü

İkisi de raporla aynı anahtarla, aynı başlıklarla imzalı `POST` olarak gelir;
pano onları yalnız oturumla görür (`GET /api/foto?olay=ID`, `GET
/api/kare?kamera=ID`). Site JPEG olmayan içeriği (`FF D8 FF` ile başlamayan)
ve sınırı aşanı depoya hiç yazmaz.

- **Kanıt fotoğrafı:** `POST /api/foto`, gövde `{surum: 1, olay_id, jpeg:
  "<base64>"}`, en çok 400 KB. Site hangi olayların fotoğrafını tuttuğunu
  kendisi bilir ve raporun cevabında söyler: `foto.var` = raporundaki
  olaylardan fotoğrafı sitede zaten olanların kimliği. Fabrika her rapordan
  sonra, `son_olaylar`'daki fotoğraflı **ihlallerden** `foto.var`'da olmayanları
  gönderir (en yenisi önce, turda en çok 5; genişlik en çok 960 px). Böylece
  program yeniden başlasa da fotoğraf iki kez gitmez. Site en çok 60 fotoğraf
  tutar, en eskisini siler; fotoğraf 7 gün sonra kendiliğinden silinir.
- **Anlık görüntü:** panoda Kameralar ekranı açıkken raporun cevabı
  `kare.iste: true` der. Fabrika o zaman 10 saniyede bir, görüntü veren her
  kamera için `POST /api/kare` gönderir: `{surum: 1, kamera_id, jpeg}`, en çok
  300 KB (640 px önerilir). Cevaptaki `iste` yanlışa dönünce ya da 60 saniye
  boyunca doğru gelmezse bırakır. Görüntü 2 dakikada silinir; ekrana 10
  dakika dokunulmazsa pano istemeyi bırakır.

Raporun cevabı: `{tamam, alindi, komut: {hizli}, kare: {iste}, foto: {var: []}}`.
Cevapta `foto` ya da `kare` yoksa site eskidir: fabrika görüntü göndermemelidir.

## Raporun biçimi (fabrika programı ile bağlarken)

Fabrika programı `/api/rapor`'a JSON gönderir. Site yalnız aşağıdaki alanları
tanır; gerisini atar. Kalın olanları fabrika programı henüz göndermiyor (DALSAN
tarafındaki iş: kameranın ve olayın kimliği, sistem olayının açıklaması,
bilgisayarın IP adresi, fotoğraf ve anlık görüntü gönderimi). Gelmeyen alanın
kartını pano gizler ya da "henüz gönderilmiyor" der.

| Alan | Biçim |
|---|---|
| `surum`, `uretildi`, `aralik_sn`, `kapanis` | 1, ISO zaman, saniye, true/false |
| `program` | `{ad, surum}` |
| `sistem` | `{analiz, hazir, model, uyari_garantisi, sorunlar[], bos_disk_gb, calisma_suresi_sn}` |
| `kameralar[]` | `{ad, bolum, durum, okunan_fps, islenen_fps, hedef_fps, yavas, son_kare_yasi_sn}` ve **`id`** (veritabanındaki kamera kimliği; anlık görüntünün anahtarı) |
| `sayilar` | `{bugun_ihlal, dun_ihlal, bekleyen, aktif_kural, kamera_toplam, kamera_canli}` |
| `saatlik` | bugünün 24 saati, ihlal sayısı |
| `ogeler[]` | son 7 günün ihlal türleri `{ad, sayi}` |
| `son_olaylar[]` | `{zaman, tur, baslik, yer, onem, onem_adi, durum_adi, suruyor, sure}` ve **`id`** (olay kimliği; kanıt fotoğrafının anahtarı), **`ayrinti`** (sistem olayının açıklaması, adresteki şifre gizlenmiş, en çok 300 karakter) |
| `mudahale` | `{acik, mesajlar[{id, metin}], kanallar[{id, ad, bolum}]}` |
| `gunluk` | son 14 günün ihlal sayısı, en eskisi başta, sonuncusu bugün (Türkiye günü) |
| `yedi_gun` | `{ihlal, incelenen, yanlis_alarm}`: son 7 gün |
| `yerler[]` | son 7 gün, kamera başına `{ad, bolum, sayi}`, çoktan aza, en çok 10 |
| `bilgisayar` | `{ad, bilgisayar_adi, isletim_sistemi, islemci, cekirdek, bellek_gb, ekran_karti, cikarim, disk_toplam_gb, kurulum_turu, kurulum_tarihi, acilis}` ve **`ip`** (yerel ağdaki adresleri, en çok 4) |

`bilgisayar.ad`, kurulumun okunur adıdır ("Gebze fabrikası"); fabrika
programında elle yazılan bir ayardır. `olay.foto` fabrikadan okunmaz: sitede
fotoğrafı olup olmadığını site kendisi yazar.

Komut yoklaması (`/api/komut`): istek `{surum: 1, sonuclar: [{id, durum:
"yapildi"|"hata", mesaj}]}`, cevap `{komutlar: [{id, tur: "anons"|"ses_dene",
mesaj_id, kanal_id, son_gecerlilik, kalan_sn}], hizli}`. İkisi de raporla aynı
anahtarla, aynı başlıklarla imzalanır; program imzası tutmayan cevaptaki komutu
yürütmez. Raporun cevabı `{komut: {hizli}}` taşır.

## Vercel'e kurulum (bir kez)

1. **Projeyi açın.** [vercel.com](https://vercel.com)'a GitHub hesabıyla girin:
   **Add New → Project → `RiosenBeq/bot` → Import**. Ayarlara dokunmadan
   **Deploy**'a basın (Framework Preset "Other" kalır, derleme adımı yoktur).
2. **Veri deposunu bağlayın.** Projede **Storage** sekmesi → **Create Database** →
   **Upstash** (Redis). Bölge olarak Avrupa'yı (Frankfurt) seçin ve bu projeye
   bağlayın. Bağlantı ayarlarını Vercel projeye kendisi ekler.
3. **İki ayarı yazın.** **Settings → Environment Variables**:

   | Ad | Değer |
   |---|---|
   | `PANO_SIFRESI` | Panoya giriş şifresi, en az 10 karakter (öneri: 16) |
   | `RAPOR_ANAHTARI` | En az 32 karakterlik rastgele anahtar. Pano sayfası, site kurulmamışken bir tane önerir |
   | `FABRIKA_ADRESI` | *(isteğe bağlı)* Fabrika ekranının VPN/Tailscale adresi, ör. `http://100.64.0.7:8080` |

4. **Yeniden yayınlayın.** **Deployments** → son yayının menüsü → **Redeploy**.
   Ayarlar ancak yeniden yayından sonra geçerli olur.
5. **Bölgeyi seçin (önerilir).** **Settings → Functions → Region**: Frankfurt
   (`fra1`). İşlevler veri deposuna yakın çalışır.
6. **Panoyu açın:** `https://<projeniz>.vercel.app/pano`. Giriş ekranı gelmeli. Ayar
   eksikse sayfa neyin eksik olduğunu yazar.
7. **Fabrika programını bağlayın.** Programda **Ayarlar → Uzak izleme panosu**:
   - **Site adresi:** `https://<projeniz>.vercel.app` (Vercel'in verdiği ana adres)
   - **Uzak pano anahtarı:** `RAPOR_ANAHTARI`'nın aynısı

   Kaydedin ve sistemi yeniden başlatın. Ayarlar sayfasının aynı bölümünde
   "Çalışıyor: son durum özeti ... saatinde gönderildi" yazmalı; panoda
   **Sistem çalışıyor** görünmeli.

### Plan ve maliyet

- **Vercel:** ücretsiz Hobby planı Vercel'in şartlarına göre yalnız kişisel ve
  ticari olmayan kullanım içindir. Bir fabrika için **Pro** planı gerekir.
- **Upstash:** her rapor 1 istekte 3 komuttur: 30 sn aralıkla ayda yaklaşık
  260 bin. Pano açıkken saatte yaklaşık 240 komut okur. Kanıt fotoğrafı başına
  3-4 komut. Kameralar ekranı açıkken 4 kamerada saatte yaklaşık 8 bin komut ve
  dakikada 3 MB kadar veri akar; ekrana 10 dakika dokunulmazsa durur. Ücretsiz
  plan (ayda 500 bin komut) günde birkaç kez bakmaya yeter. Pano bir ekranda
  sürekli açık kalacaksa ya da Kameralar sık açılacaksa kullandıkça öde planına
  geçip harcama sınırı koyun. Depoda en çok 60 fotoğraf durur (24 MB'tan az).
  Güncel sınırları Upstash'in fiyat sayfasında kontrol edin.

## Nasıl çalışır

```
fabrika programı ──(HTTPS POST, imzalı JSON)──> /api/rapor, /api/foto, /api/kare ──> Upstash Redis
tarayıcı ──(şifreyle giriş, oturum çerezi)──> /api/durum, /api/foto, /api/kare <── Upstash Redis
```

| Dosya | İşi |
|---|---|
| `api/rapor.py` | Fabrikanın raporunu alır: imza ve zaman denetimi, alan süzme, kayıt |
| `api/giris.py`, `api/cikis.py` | Panoya giriş ve çıkış (oturum çerezi) |
| `api/durum.py` | Panonun verisi; oturum ister (`?mudahale=1`: son komutlar da gelir; `?kare=1`: kameraların son görüntüsünün zamanı da gelir ve fabrikaya "anlık görüntü gönder" denir) |
| `api/foto.py` | Kanıt fotoğrafı: fabrikadan imzalı `POST`, panoya oturumlu `GET` |
| `api/kare.py` | Anlık görüntü: fabrikadan imzalı `POST`, panoya oturumlu `GET` |
| `api/mudahale.py` | Panodan komut (anons, hoparlör denemesi); oturum ister |
| `api/komut.py` | Fabrika programının komut yoklaması (imzalı istek ve cevap) |
| `api/_pano.py` | Ortak çekirdek (adres değildir): imza, depo, kilit, rapor biçimi |
| `public/` | Sayfalar: `index.html`, `pano.html`, `pano.js`, `stil.css` |
| `vercel.json` | Güvenlik başlıkları, `public/`'in yayınlanması |
| `yerel_sunucu.py` | Siteyi Vercel'siz, bu bilgisayarda denemek için |

Yalnız Python'un standart kütüphanesi ve sade HTML/CSS/JS kullanılır: kurulacak
paket, npm, derleme adımı yoktur. Yazı tipi (Inter) ve logo fabrika ekranındakiyle
aynıdır ve siteyle birlikte gelir (CDN yok).

Görünüm: bilgisayarda laffogato yönetim panelinin Innex düzeni (kenar çubuğu ve
sayfa kartı, sayı şeridi, tablo, rozetler), telefonda lafmobil'in mobil dili
(altta yüzen sekme çubuğu, en az 44 px dokunma alanı, çentik ve alt çizgi payı).
Simgeler Lucide'dendir ve sayfanın içindedir; lisanslar `public/LISANSLAR.md`.

## Güvenlik

- **İmza:** her rapor `RAPOR_ANAHTARI` ile HMAC-SHA256 imzalanır (başlıklar
  `X-Dalsan-Zaman`, `X-Dalsan-Imza`). İmza tutmayan ya da saati 5 dakikadan fazla
  kaymış rapor reddedilir; gövde imzadan önce okunmaz.
- **Alan süzme:** rapordaki alanlar tek tek tip ve uzunluk denetiminden geçer;
  bilinmeyen alan depoya yazılmaz. Görüntü yalnız kendi imzalı adresinden gelir:
  base64 sıkı çözülür, boyut sınırı aşılmaz, JPEG olmayan içerik reddedilir.
  Panoya `image/jpeg` ve `nosniff` ile, yalnız oturumla verilir.
- **Giriş:** şifre sabit sürede karşılaştırılır. Aynı adresten 5 yanlış denemede
  5 dakika, bütün adreslerden 15 dakikada 100 yanlış denemede 15 dakika kilit.
  Kilit sayacında IP adresinin kendisi değil, geri çevrilemeyen özeti tutulur.
- **Oturum:** çerez `HttpOnly`, `Secure`, `SameSite=Strict`, 12 saat. İmzası
  şifreden ve rapor anahtarından türer: şifre değişince bütün oturumlar düşer.
- **Sayfa:** sıkı Content-Security-Policy (yalnız sitenin kendi dosyaları), çerçeve
  içine alınamaz, arama motorlarına kapalı (`noindex`, `robots.txt`). Veri sayfaya
  yalnız `textContent` ile yazılır.
- **Saklama:** son durum ve kanıt fotoğrafları 7 gün (en çok 60 fotoğraf),
  anlık görüntü 2 dakika tutulur; rapor kesilirse hiçbiri süresiz kalmaz.

## Sorun giderme

| Görülen | Sebep ve çözüm |
|---|---|
| Pano: "Site henüz kurulmadı" | Listedeki ayarları yazın, sonra Redeploy |
| Pano: "Fabrikadan henüz rapor gelmedi" | Fabrika programında Ayarlar → Uzak izleme panosu doldurulmadı ya da sistem yeniden başlatılmadı |
| Program: "İmza tutmadı" | Programdaki anahtar ile `RAPOR_ANAHTARI` aynı değil |
| Program: "saati yaklaşık ... saniye geri" | Fabrika bilgisayarının tarih ve saatinde "otomatik ayarla"yı açın |
| Program: "beklenmeyen bir cevap verdi (HTTP 401)" | Önizleme adresi yazılmış; Vercel'in ana (Production) adresini yazın |
| Program: "Siteye ulaşılamadı" | İnternet yok ya da şirket güvenlik duvarı `vercel.app` adreslerini engelliyor |
| Pano: "Veri deposuna ulaşılamadı" | Storage sekmesinde Upstash bağlantısını kontrol edin; Vercel → Logs |
| Kameralar: "Fabrika programı anlık görüntü göndermiyor" | Programın uzak pano bağlantısı eski; güncellenince kameralar görüntüsüyle çıkar |
| Kameralar: "Görüntü beklemede" | Ekrana 10 dakikadır dokunulmadı; Sürdür'e basın |
| Kameralar: "Fabrika bir sonraki raporunda göndermeye başlar" uzun sürüyor | Program rapor aralığı kadar (varsayılan 30 sn) bekler; sürüyorsa programın Ayarlar → Uzak izleme panosu bölümündeki durum satırına bakın |
| Olaylar: "Fotoğraf alınamadı" | Fotoğraf sitede silinmiş (7 gün, en çok 60) ya da henüz gelmedi; asılları fabrikadaki bilgisayardadır |

## Bu bilgisayarda denemek

```bash
python3 yerel_sunucu.py          # http://127.0.0.1:3000 - şifre ve anahtar ekrana yazılır
```

Fabrika programında site adresi olarak `http://127.0.0.1:3000` yazılabilir (düz
http yalnız bu bilgisayar için kabul edilir). Yerel sunucu Upstash yerine bellek
kullanır; kapatınca her şey silinir.

Testler ve biçim denetimi:

```bash
python3 -m pip install pytest ruff
python3 -m pytest
ruff check . && ruff format --check .
```

Rapor biçimi iki depoda birlikte değişir: sitede `api/_pano.py` (`RAPOR_SURUMU`,
`rapor_temizle`), programda `backend/app/uzak_pano.py`. İmzanın ortak deneme değeri
iki deponun testlerinde de vardır.
