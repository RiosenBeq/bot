# NextGen Detector · Uzak izleme sitesi

DALSAN İSG Görüntü Analiz Sistemi'nin ([RiosenBeq/DALSAN](https://github.com/RiosenBeq/DALSAN))
Vercel'de duran sitesi. İki sayfası var:

| Adres | Ne |
|---|---|
| `/` | Tanıtım: sistemin ne yaptığı, nasıl çalıştığı, veri güvenliği notu |
| `/pano` | **Kişisel hesapla** giren uzak izleme ve yönetim panosu: bugünün özeti, son 14 günün eğilimi, kameraların anlık görüntüsü, kanıt fotoğraflı son olaylar, kurulu olduğu bilgisayar ve role göre **Müdahale** (anons, hoparlör denemesi, olay inceleme) ile **Yönetim** (teşhis, yeniden başlatma, güncelleme) |
| `/demo` | Aynı pano, **örnek verilerle** ve girişsiz: tasarımı denetlemek için (aşağıda Demo) |

## Demo

`/demo` adresi panoyu örnek bir fabrikanın verisiyle açar: 6 kamera (biri yavaş,
biri yeniden bağlanıyor, biri kopuk), kanıt fotoğraflı 20 olay, son 14 gün,
saatlik dağılım, müdahale ve yönetim geçmişi, kullanıcılar, işlem kaydı ve
üç tesisli Tesisler ekranı.
Üstteki demo bandından **rol** (Yönetici / Operatör / İzleyici) ve **bağlantı**
(Canlı / Haber yok / Kapatıldı) seçilir; anons, hoparlör denemesi, olay
inceleme, teşhis, yeniden başlatma, güncelleme ve hesap işleri birkaç saniyede
sonuçlanır.

Demo gerçek veriye **dokunmaz**: sayfadaki `/api/...` istekleri tarayıcıda
`public/demo.js` tarafından karşılanır, siteye ve fabrikaya hiçbir istek gitmez,
hiçbir şey kaydedilmez (sayfa yenilenince başa döner). Kamera görüntüleri ve
kanıt fotoğrafları tarayıcıda çizilir. `/pano` adresinde `demo.js` hiçbir şey
yapmaz. Yönlendirme `vercel.json`'daki `rewrites` satırıdır; demoyu kaldırmak
için o satırı ve `pano.html`'deki `demo.js` etiketini silmek yeter.

Fabrikadaki program bu siteye düzenli aralıkla (varsayılan 30 sn) kısa, **imzalı**
bir durum özeti, ihlallerin kanıt fotoğrafını ve (Kameralar ekranı açıkken)
kameraların anlık görüntüsünü gönderir. Bağlantı yalnız fabrikadan dışarı doğrudur: fabrikada
port açılmaz, modeme dokunulmaz. Fabrikadan 90 saniye haber gelmezse pano
kırmızıyla "haber yok" der; program kapatılırken son bir "kapatıldı" raporu
gönderdiği için bilerek kapatmayı bağlantı kopmasından ayırır.

Komut (anons, yeniden başlatma, güncelleme ...) fabrikaya ancak program sorduğunda
gider; site fabrikaya hiç bağlanmaz. İki depo arasındaki sözleşme DALSAN
`docs/19-SITEDEN-YONETIM.md`'dir; bu README aynı tabloları site gözünden tekrar
eder.

## Hesaplar ve roller

Panoya artık ortak bir şifreyle değil, **kişiye özel hesapla** girilir. Her
hesabın bir rolü vardır; rol her istekte hesap kaydından okunur. Yetkisi olmayan
düğme ekranda gizlenir, istek yine rolle denetlenir.

| İş | İzleyici | Operatör | Yönetici |
|---|:-:|:-:|:-:|
| Durum, özet, olaylar, kanıt fotoğrafı, kameraların anlık görüntüsü | var | var | var |
| Kendi şifresini değiştirme | var | var | var |
| Hazır anons, hoparlör denemesi, olay inceleme | | var | var |
| Teşhis, yeniden başlatma, güncelleme | | | var |
| Hesap açma, rol, yeni şifre, girişi kapatma / açma, silme | | | var |
| İşlem kaydını görme | | | var |

- **İzleyici** - durumu, olayları ve kamera görüntülerini görür; hiçbir şey
  değiştiremez. Bilgisayarın IP adreslerini ve bilgisayar adını göremez.
- **Operatör** - izleyiciye ek olarak hazır anons çaldırır, hoparlörü dener,
  olayları İncelendi ya da Yanlış alarm diye işaretler.
- **Yönetici** - operatöre ek olarak programı yeniden başlatır, günceller, teşhis
  alır, hesapları ve işlem kaydını yönetir.

**Kurucu hesap.** Site ilk kurulduğunda tek hesap vardır: kullanıcı adı `kurucu`,
şifresi Vercel'deki `PANO_SIFRESI`. Kurucu tam yetkilidir, silinemez, düşürülemez;
şifresi yalnız Vercel'de değişir. Yönetici hesaplarına dokunan her işi (yönetici
yapma / düşürme, yöneticiye yeni şifre, kapatma, silme) yalnız kurucu yapar:
çalınan bir yönetici hesabı kendine kalıcı yetki açamaz. Kurucuyla girince her
ekranda bir bant çıkar ("... Kullanıcılar ekranından herkese kendi hesabını açın,
sonra Vercel'de PANO_SIFRESI'ni değiştirin."), çünkü ortak şifreyle yapılan işin
sahibi işlem kaydında görünmez.

### Geçiş sırası (ilk kurulumda bir kez)

1. Siteye `kurucu` + bugünkü `PANO_SIFRESI` ile girin; **Kullanıcılar**'dan
   kendinize bir **Yönetici** hesabı açın.
2. Herkese kendi hesabını açın (İzleyici / Operatör).
3. Vercel'de `PANO_SIFRESI`'ni yalnız sizin bildiğiniz yeni bir değerle (en az 16
   karakter) değiştirip **Redeploy** edin: bütün oturumlar düşer, eski ortak
   şifre artık hiçbir şey açmaz.
4. Programda "Uzaktan yönetim"i ancak bundan sonra açın (Ayarlar → Uzak izleme
   panosu).

## Siteye ne gelir, ne gelmez

| Siteye gelir | Ne kadar durur | Siteye gelmez |
|---|---|---|
| Sistem çalışıyor mu, analiz, model, sistem şeridindeki sorunlar, boş disk | 7 gün (her raporda yenilenir) | Kamera ve hoparlör adresleri, fabrikadaki kullanıcı adları ve şifreler |
| Kameraların adı, bölümü, bağlantı durumu, kare hızı | 7 gün | Video kaydı (yalnız tek kareler gelir) |
| Bugünkü ve dünkü ihlal, inceleme bekleyen, aktif kural, saatlik dağılım, son 14 gün | 7 gün | Kural ve kamera ayarları |
| Son 20 olayın adı, yeri, önemi, durumu, zamanı; sistem olayının açıklaması (adres ve dosya yolu çıkarılmış) | 7 gün | Takip numarası, olayın ayrıntı kaydı |
| İhlallerin **kanıt fotoğrafı** (en çok 960 px, ihlal başına bir kez) | 7 gün, en çok 60 fotoğraf | |
| Kameraların **anlık görüntüsü** (640 px, 10 saniyede bir) | 2 dakika; yalnız Kameralar ekranı açıkken gelir | |
| Kurulu olduğu bilgisayar: adı, IP adresi, işletim sistemi, donanım | 7 gün | Oturum açan kullanıcının adı |

Pano hesapları siteye ait ayrı hesaplardır; şifreleri yalnız geri çevrilemeyen
`scrypt` özetiyle saklanır (aşağıda Güvenlik). Fabrikanın kendi kullanıcı adları
ve şifreleri siteye hiç gelmez.

**Akıcı canlı görüntü bu siteden geçmez.** Panodaki anlık görüntü 10 saniyede
bir yenilenir. Akıcı görüntü için fabrika ağına VPN ya da Tailscale ile
bağlanılır (DALSAN `docs/15-UZAKTAN-ERISIM.md` §4.1). O adres `FABRIKA_ADRESI`
olarak yazılırsa panoda "Fabrika ekranını aç" düğmesi çıkar.

> **Fabrika içi kullanım (operatör kararı 24.10.2026).** Pano fabrikanın kendi
> kullanımı içindir; görüntünün siteye gelmesi bu kararla açıldı. Bilinmesi
> gerekenler: Vercel ve Upstash'in sunucuları yurt dışındadır; görüntüler
> yalnız hesabıyla giren kişiye gösterilir ve yukarıdaki sürelerin sonunda
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

## Uzaktan müdahale ve yönetim

Panonun **Müdahale** (operatör ve üstü) ve **Yönetim** (yönetici) ekranlarından
sayılı iş istenebilir. Hepsi aşağıdaki tabloyla sınırlıdır:

| Komut | Ekran | En az rol | Ne yapar | Onay |
|---|---|---|---|---|
| Anons (`anons`) | Müdahale | Operatör | Anons sayfasındaki **hazır** bir mesajı seçilen kanaldan ya da "Tüm fabrika"dan çaldırır | Onay kutusu |
| Hoparlör denemesi (`ses_dene`) | Müdahale | Operatör | Bir kanaldan deneme sesi verir | Çift dokunuş |
| Olay inceleme (`olay_incele`) | Olaylar | Operatör | Son rapordaki bir ihlali İncelendi ya da Yanlış alarm işaretler | Çift dokunuş |
| Teşhis (`teshis`) | Yönetim | Yönetici | Programdan tek seferlik durum metni ister (adres ve dosya yolu süzülür) | Tek dokunuş |
| Yeniden başlat (`yeniden_baslat`) | Yönetim | Yönetici | Programı yeniden başlatır (1-3 dakika kameralar izlenmez) | Kendi şifresi |
| Güncelle (`guncelle`) | Yönetim | Yönetici | GitHub'daki resmi son sürüme günceller (önce veritabanı yedeklenir, açılmazsa eski sürüme dönülür) | Kendi şifresi |

**Hâlâ yapılamayanlar (sözleşme §0).** Serbest metin okutma; kural, kamera,
bölge ya da ayar değiştirme; fabrikada keyfi komut ya da betik çalıştırma; dosya
yükleme; GitHub'daki resmi depo dışından kod ya da paket kurma; siteden fabrikaya
bağlanma. Yeni bir iş eklemek ayrı karardır.

Nasıl yürür:

- Fabrikaya dışarıdan bağlanılmaz. Ekran açıkken site, programın raporuna "sık
  sor" der; program birkaç saniyede bir `/api/komut`'a **imzalı** ve o soruya
  özgü bir `nonce` taşıyan istek gönderip komutu alır, yürütür ve sonucunu
  bildirir. Cevap da imzalıdır ve aynı `nonce`'u taşır: eski bir cevap yeniden
  oynatılamaz. Ekran kapalıyken program sormaz; ekrana 10 dakika dokunulmazsa
  dinleme bekler.
- Komut 2 dakika içinde alınmazsa düşer. Sınırlar (site ve program aynı sayıyla):
  anons ve hoparlör denemesi 5 dakikada 10; olay inceleme 5 dakikada 60; teşhis
  5 dakikada 3; yeniden başlatma ve güncelleme birlikte saatte 3, aynı anda tek
  iş.
- Yeniden başlatma, güncelleme ve her hesap işi, işi yapanın **kendi şifresini**
  ister (cepte yanlışlıkla iş yapılmasın; çalınan açık bir oturum tek başına
  fabrikayı yeniden başlatamasın).
- Her müdahale ve yönetim işi fabrikadaki Olaylar'a ve sitedeki işlem kaydına
  kim yaptığıyla yazılır. Teşhis izleme ekranında bant göstermez (fabrikada bir
  şey değiştirmez).
- Program tarafında ayrıca açılır: Müdahale için Ayarlar → Uzak izleme panosu →
  "Uzaktan müdahale"; Yönetim için "Uzaktan yönetim" (varsayılan kapalı). Kapalı
  bir program siteden açılamaz.

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
Tesis taşıyan raporda ana tesisin cevabına `filo: {ana: true}` eklenir; öbür
tesisin cevabı yalnız `{tamam, alindi, filo: {ana: false}}`'dır.

## Birden çok fabrika (Tesisler)

Tek fabrika varsa hiçbir şey yapmanız gerekmez: program `tesis` alanını
göndermez, site bugünkü gibi çalışır. İkinci bir fabrika eklenince:

1. **Her fabrikanın programında** Ayarlar → Uzak izleme panosu bölümüne kısa bir
   **tesis kimliği** yazın (`UZAK_PANO_TESIS_ID`, ör. `gebze`, `izmir`: küçük
   harf, rakam, `-` ve `_`, en çok 32 karakter). Program raporuna
   `"tesis": {"id": "gebze", "ad": "Gebze fabrikası"}` ekler. Kimliği bozuk
   rapor 400 ile reddedilir; program hatayı Ayarlar sayfasında gösterir. Önce
   **mevcut** fabrikaya kimlik verin, sonra yenisini bağlayın. **Her fabrika
   farklı bir kimlik kullanmalı:** bir bilgisayarın `.env` dosyasını öbürüne
   kopyalarsanız kimliği değiştirin. Aynı kimliği gönderen iki bilgisayar sitede
   tek tesis sayılır ve ikisi de ana olur: ikisi de komut alır, panoyu sırayla
   ezer, Tesisler ekranında tek satır görünür.
2. **Ana tesis** komut alan tek tesistir: anons, hoparlör denemesi, olay
   inceleme, teşhis, yeniden başlatma ve güncelleme yalnız ona gider; Genel
   bakış, Kameralar, Olaylar, Müdahale ve Yönetim ekranları onu gösterir.
   Vercel'de `ANA_TESIS` (ör. `gebze`) yazılıysa ana tesis odur; Türkçe harf de
   yazılabilir (`İzmir` kimlik olarak `izmir` okunur). Kimlik olamayan bir değer
   (ör. boşluklu `İzmir fabrikası`) yok sayılır ve Tesisler ekranı uyarır.
   `ANA_TESIS` yazılı değilse **ilk rapor veren tesis** ana olur; ana tesis 7 gün
   hiç rapor göndermezse sıradaki tesis devralır.
   **Komut alan her zaman tek fabrikadır:** tesis kimliği yazılmamış (eski) bir
   program canlı rapor gönderdiği sürece hiçbir tesis ana olmaz. `ANA_TESIS`
   yazılı olsa da, bir tesis daha önce ana olmuş olsa da komutları ve panoyu
   eski program alır, tesisler yalnız izlenir ve Tesisler ekranı uyarır. Eski
   program susunca ya da kapanınca ana tesis geri döner; kimliksiz yeniden
   başlarsa yine bırakır.
3. **Öbür tesisler yalnız izlenir:** raporları yalnız tesis kütüğüne yazılır,
   panonun durumunu ezmez. Raporun cevabı yalnız `{"filo": {"ana": false}}`
   taşır (`komut`, `kare`, `foto` yok): program komut sormaz, anlık görüntü ve
   kanıt fotoğrafı göndermez. Komut sorusu `tesis` taşıyıp ana tesisten
   gelmiyorsa site imzalı ama boş bir cevap verir; kuyruktan hiçbir şey çekilmez.
4. **Tesisler ekranı** (yalnız Yönetici; kenar menüsü, telefonda Sistem →
   Fabrika yönetimi): her tesisin durumu (Canlı / Haber yok / Kapandı), son
   rapordan bu yana geçen süre, bugünkü ihlal sayısı ve "Ana tesis - komut
   alır" ya da "Yalnız izleme". Veri `/api/durum?filo=1` ile yalnız bu ekran
   açıkken istenir. Kütükte tesis yoksa bugünkü fabrika tek satır görünür.
   Kimliksiz bir program canlıyken (o komut alan satırdır) ya da `ANA_TESIS`
   geçersizken ekranın üstünde bir uyarı çıkar (`filo.uyarilar`).

Ana tesisi değiştirmek için Vercel'de `ANA_TESIS`'e tesisin kimliğini yazıp
yeniden yayınlayın (**Settings → Environment Variables**, yalnız Production,
sonra **Redeploy**). Ayar sonradan silinirse o tesis ana kalır. Değiştirmeden
önce Müdahale ve Yönetim ekranında bekleyen komut olmasın: bekleyen komut 2
dakika içinde yeni ana tesise gidebilir (sonra kendiliğinden düşer).

> **Karışık kurulumdan kaçının:** birden çok fabrikada her programa farklı bir
> tesis kimliği yazın. Kimliksiz program her zaman bugünkü gibi komut alır;
> canlıyken hiçbir tesis komut almaz.

Depoda: `dalsan:tesis:<id>` (tesis başına küçük özet, 7 gün), `dalsan:tesisler`
(dizin, en çok 50 tesis), `dalsan:ana_tesis` (ana tesis; onun her raporunda 7
güne tazelenir).

## Sistemden haber yok uyarısı (bekçi)

Pano açık olmasa da fabrika bilgisayarı kapanır, program durur ya da internet
uzun süre giderse site seçtiğiniz kişilere **bir kez** e-posta ve/veya Telegram
bildirimi gönderir. Bağlantı geri gelince (ilk taze rapor) işaret sıfırlanır ve
bir sonraki kesintide yeniden uyarır. Kesinti 24 saatten uzun sürerse günde bir
hatırlatma gider. Ana pano ve izlenen her tesis ayrı işaret taşır; aynı fabrika
iki kez sayılmaz. `ANA_TESIS` değişmişse ve pano hâlâ eski ana tesisin son
raporunu gösteriyorsa uyarı susan yeni ana tesisi adıyla anar.

Bekçi `GET /api/bekci` adresidir ve **kendiliğinden çalışmaz**: bir zamanlayıcı
çağırır (aşağıda). Ayarlar yoksa hiçbir şey yapmaz; hepsi isteğe bağlıdır ve
eksik ayar listesine girmez.

| Ad | Not |
|---|---|
| `BEKCI` | `acik` (ya da `açık`) yazılmadıkça bekçi çalışmaz (`{"atlandi": true}` döner). Tanınmayan bir değer (ör. `evet`) bekçiyi açmaz; `/api/bekci` onu 503 `bekci_ayari` ile bildirir |
| `BEKCI_ESIK_DK` | Kaç dakika haber gelmezse uyarsın; varsayılan 20 (1-1440). Dalgalı internette uzun tutun |
| `BEKCI_ALICILAR` | Virgülle ayrık e-posta adresleri ve/veya `tg:<sohbet_id>`; en çok 20 |
| `CRON_SECRET` | Vercel Cron'un gizli değeri, en az 16 karakter. Vercel onu `Authorization: Bearer` başlığıyla kendisi yollar |
| `BEKCI_ANAHTARI` | Dış izleme servisinin gizli anahtarı, en az 16 karakter |
| `SMTP_SUNUCU`, `SMTP_PORT` | E-posta sunucusu. Port 465 ise doğrudan TLS, başka port (varsayılan 587) ise STARTTLS; şifresiz bağlantıyla gönderilmez |
| `SMTP_KULLANICI`, `SMTP_SIFRESI` | SMTP girişi |
| `SMTP_KIMDEN` | Gönderen adresi (boşsa `SMTP_KULLANICI`) |
| `TELEGRAM_BOT` | Telegram bot jetonu (`123456:ABC...`) |
| `TELEGRAM_SOHBET` | *(isteğe bağlı)* Bildirimin gideceği sohbet; `BEKCI_ALICILAR`'a `tg:` ile de yazılabilir |

Hepsini **yalnız Production**'a ekleyin ve yeniden yayınlayın.

**Kim çağırır?**

- **Vercel Cron:** `vercel.json` `/api/bekci`'yi her gün bir kez, 05:00 UTC
  (08:00 Türkiye) saatinde çağırır (Hobby'de o saatin içinde herhangi bir
  dakikada). Hobby planı günde birden sık cron kabul etmez (daha sık bir
  zaman yazılırsa yayın başarısız olur); Hobby'de bu yalnız günlük bir
  denetimdir. `CRON_SECRET`'ı tanımlayın: Vercel onu her çağrıda başlıkta yollar.
  **Pro planda** `vercel.json`'daki zamanı `"*/5 * * * *"` yapın (5 dakikada bir).
- **Dış izleme servisi (Hobby'de önerilen):** bir servis
  `https://<projeniz>.vercel.app/api/bekci` adresini 5 dakikada bir çağırsın.
  Başlık eklenebiliyorsa onu kullanın: `?anahtar=` adresi servisin ve Vercel'in
  günlüklerine düşebilir. `CRON_SECRET` adreste kabul edilmez.
  - **cron-job.org** başlık ekleyebilir: `Authorization: Bearer <BEKCI_ANAHTARI>`.
  - **UptimeRobot**'un ücretsiz planı başlık ekleyemez ve HEAD isteği gönderir:
    adrese `?anahtar=<BEKCI_ANAHTARI>` ekleyin. Site HEAD'i GET gibi cevaplar
    (aynı durum kodu, gövdesiz).

**Cevap:** `{uyarildi, gonderilen, durum: [{ad, baglanti, gecikme_dk, bayat}]}`.
Bir hedef eşikten uzun süredir sessizse durum kodu **503**, değilse **200**:
e-posta ya da Telegram kurmasanız da izleme servisi 503'te kendisi alarm verir.
Anahtar yoksa 401, yanlışsa ya da sitede hiç tanımlanmamışsa 403 döner; anahtar
doğru ama `BEKCI` tanınmayan bir değerse 503 `bekci_ayari`. Cevapta sır, alıcı
adresi ya da görüntü yoktur.

Bildirim kısa bir metindir: tesisin adı, son rapordan bu yana geçen dakika, son
raporun saati (Türkiye) ve neye bakılacağı (bilgisayar açık mı, program çalışıyor
mu, internet var mı). Bir alıcıya gidemezse öbürleri yine denenir; hiçbir alıcıya
gidemezse işaret bırakılır ve sonraki çağrı yeniden dener. Hata Vercel
günlüğüne yalnız türüyle yazılır, alıcı kısmen gizlenir; şifre ve jeton yazılmaz.
Program kapatılıp açılmadıysa (Kapandı) da eşik dolunca uyarır; hiç rapor
gelmemiş kurulumda uyarmaz.

## Raporun biçimi (fabrika programı ile bağlarken)

Fabrika programı `/api/rapor`'a JSON gönderir. Site yalnız aşağıdaki alanları
tanır; gerisini atar. Her alan tip ve uzunluk denetiminden geçer.

| Alan | Biçim |
|---|---|
| `surum`, `uretildi`, `aralik_sn`, `kapanis` | 1, ISO zaman, saniye (5-3600), true/false |
| `kapanis_sebebi` | `""` / `guncelleme` / `yeniden_baslatma` (yalnız kapanış raporunda dolu) |
| `program` | `{ad, surum, yapi: {commit (7-40 küçük hex ya da boş), tarih (ISO ya da boş), calistirma}}` |
| `sistem` | `{analiz, hazir, model, uyari_garantisi, sorunlar[], bos_disk_gb, calisma_suresi_sn}` |
| `kameralar[]` | `{id, ad, bolum, durum, okunan_fps, islenen_fps, hedef_fps, yavas, son_kare_yasi_sn}` (`id` anlık görüntünün anahtarı) |
| `sayilar` | `{bugun_ihlal, dun_ihlal, bekleyen, aktif_kural, kamera_toplam, kamera_canli}` |
| `saatlik` | bugünün 24 saati, ihlal sayısı |
| `ogeler[]` | son 7 günün ihlal türleri `{ad, sayi}` |
| `son_olaylar[]` | `{id, zaman, tur, baslik, yer, onem, onem_adi, durum_adi, durum, suruyor, sure, ayrinti}` (`id` kanıt fotoğrafının anahtarı; `ayrinti` sistem olayının açıklaması, en çok 300 karakter, adres ve dosya yolu çıkarılmış; `durum` = `new` / `reviewed` / `false_alarm`) |
| `mudahale` | `{acik, isler, mesajlar[{id, metin}], kanallar[{id, ad, bolum}]}`; `isler` ⊆ (`anons`, `ses_dene`, `olay_incele`) |
| `yonetim` | `{acik, isler, kurulum, yeniden_baslatma: {mumkun, sebep}, guncelleme: {mumkun, sebep}}`; `isler` ⊆ (`teshis`, `yeniden_baslat`, `guncelle`), `kurulum` = `paket` / `git` / `diger` |
| `gunluk` | son 14 günün ihlal sayısı, en eskisi başta, sonuncusu bugün (Türkiye günü) |
| `yedi_gun` | `{ihlal, incelenen, yanlis_alarm}`: son 7 gün |
| `yerler[]` | son 7 gün, kamera başına `{ad, bolum, sayi}`, çoktan aza, en çok 10 |
| `bilgisayar` | `{ad, bilgisayar_adi, isletim_sistemi, islemci, cekirdek, bellek_gb, ekran_karti, cikarim, disk_toplam_gb, kurulum_turu, kurulum_tarihi, acilis, ip[]}` (`ip` yerel ağdaki adresler, en çok 4) |
| `tesis` | *(isteğe bağlı)* `{id, ad}`: `id` küçük harf, rakam, `-`, `_` (1-32 karakter), `ad` en çok 80 karakter. Yoksa site tek fabrika gibi davranır; bozuk `id` 400 alır (yukarıda **Birden çok fabrika**) |

`bilgisayar.ad`, kurulumun okunur adıdır ("Gebze fabrikası"); fabrika
programında elle yazılan bir ayardır. `son_olaylar[].foto` fabrikadan okunmaz:
sitede fotoğrafı olup olmadığını site kendisi yazar.

**Eski bir program** `program.yapi`, `son_olaylar[].durum`, `mudahale.isler`,
`yonetim` ve `kapanis_sebebi` alanlarını göndermez: site o kartları gizler ya da
Yönetim ve inceleme düğmelerini pasif bırakır ("Fabrika programı bu işi bilmiyor;
programı güncelleyin."). Anons ve hoparlör denemesi bugünkü gibi çalışır.

### Komut sözleşmesi (`/api/komut`)

Komut sorusu ve cevabı da raporla aynı anahtarla, aynı başlıklarla imzalanır;
program imzası ya da `nonce`'u tutmayan cevaptaki komutu yürütmez.

- **İstek:** `{surum: 1, nonce: "<32 küçük hex>", sonuclar: [<sonuç>...]}`. Gövde
  en çok 64 KB; site bir istekte en çok 10 sonucu işler.
- **Cevap:** `{tamam: true, nonce: "<istekteki>", alinan: ["<id>", ...],
  komutlar: [<komut>...], hizli}`. `alinan` = sitenin yazdığı ya da zaten bitmiş
  bulduğu sonuç kimlikleri (program kalıcı sonuç dosyasını ancak kimlik burada
  görününce siler). `hizli`, fabrikaya "sık sor" demektir.
- **Komut** alan alan kurulur; başka alan gitmez: `{id, tur, son_gecerlilik,
  kalan_sn, kim: {ad, rol}}` ve türe özgü alanlar (`anons` → `mesaj_id`,
  `kanal_id`; `ses_dene` → `kanal_id`; `olay_incele` → `olay_id`, `olay_zaman`,
  `karar`; `teshis` / `yeniden_baslat` / `guncelle` → yok).
- **Sonuç:** `{id: "<16 hex>", durum: "yapildi" | "hata" | "suruyor", mesaj:
  "<tek satır, en çok 300>", ek: "<yalnız teshis; çok satır, en çok 8192 bayt>"}`.
  Site `mesaj`'ı tek satıra indirir; `ek`'teki denetim karakterlerini atar, kalan
  `xxx://` adreslerini "(adres)" yapar ve 8192 bayta keser.

Eski bir program `nonce` ve `kim` göndermez; site boş `nonce` ile cevap verir ve
program yalnız `anons` ile `ses_dene`'yi kabul eder.

İstek `tesis` (raporla aynı biçim ya da yalnız kimlik) taşıyabilir. Ana tesisten
gelmiyorsa (ya da kimliksiz bir program canlıyken) cevap `komutlar: []`,
`hizli: false`, `filo: {ana: false}` olur: kuyruktan hiçbir şey çekilmez,
gönderilen sonuçlar yine yazılır. `tesis` yoksa cevap bugünkü gibidir.

## Vercel'e kurulum (bir kez)

1. **Projeyi açın.** [vercel.com](https://vercel.com)'a GitHub hesabıyla girin:
   **Add New → Project → `RiosenBeq/bot` → Import**. Ayarlara dokunmadan
   **Deploy**'a basın (Framework Preset "Other" kalır, derleme adımı yoktur).
2. **Veri deposunu bağlayın.** Projede **Storage** sekmesi → **Create Database** →
   **Upstash** (Redis). Bölge olarak Avrupa'yı (Frankfurt) seçin ve bu projeye
   bağlayın. Bağlarken ortam **yalnız Production** olsun (Preview ve Development
   işaretli kalmasın); Vercel bağlantı ayarlarını projeye kendisi ekler.
3. **İki ayarı yazın.** **Settings → Environment Variables** - her ikisini de
   **yalnız Production** ortamına ekleyin:

   | Ad | Değer |
   |---|---|
   | `PANO_SIFRESI` | **Kurucu hesabının şifresi**, en az 10 karakter (öneri: 16). Geçiş sırasından sonra yalnız kurucu girişinde kullanılır |
   | `RAPOR_ANAHTARI` | En az 32 karakterlik rastgele anahtar. Pano sayfası, site kurulmamışken bir tane önerir |
   | `FABRIKA_ADRESI` | *(isteğe bağlı)* Fabrika ekranının VPN/Tailscale adresi, ör. `http://100.64.0.7:8080` |

   Dört ortam değişkeni de (`PANO_SIFRESI`, `RAPOR_ANAHTARI` ve Upstash'in iki
   değeri) yalnız Production'a bağlı kalmalı: önizleme (Preview) yayınından
   fabrikaya komut ve hesap değişikliği gönderilmez (aşağıda önizleme kilidi).
4. **Yeniden yayınlayın.** **Deployments** → son yayının menüsü → **Redeploy**.
   Ayarlar ancak yeniden yayından sonra geçerli olur.
5. **Bölgeyi seçin (önerilir).** **Settings → Functions → Region**: Frankfurt
   (`fra1`). İşlevler veri deposuna yakın çalışır.
6. **Panoyu açın:** `https://<projeniz>.vercel.app/pano`. Giriş ekranı gelmeli. Ayar
   eksikse sayfa neyin eksik olduğunu yazar. İlk girişte kullanıcı adı `kurucu`,
   şifresi `PANO_SIFRESI`'dir; sonra yukarıdaki **Geçiş sırası**'nı uygulayın.
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
  dakikada 3 MB kadar veri akar; ekrana 10 dakika dokunulmazsa durur.
- **Hesaplara geçişin ek yükü:** panoya giren her istek, rolü ve oturumu
  doğrulamak için hesap kaydını okuyan **bir `MGET` daha** yapar. Müdahale ya da
  Yönetim ekranı açıkken program komutları sormak için `/api/komut`'a birkaç
  saniyede bir uğrar (ekran kapanınca durur).
- **Bekçi:** her çağrı 2-4 komuttur; 5 dakikada bir çağrılırsa ayda yaklaşık
  35 bin. `BEKCI=acik` rapor başına komut eklemez: "haber yok" işareti raporun
  zaten yaptığı okumayla (aynı `MGET`) okunur; yalnız bir kesintiden sonraki ilk
  raporda bir `DEL` gider. Vercel Hobby en çok 12 işlev (`api/*.py`) kabul eder;
  site 10 kullanır.
- **Birden çok tesis:** tesis kimliği taşıyan rapor 3 yerine 10 komuttur (2
  istek); ana olmayan tesiste 5-6 komut (1 istek). 30 sn aralıkla ana tesis
  ayda yaklaşık 860 bin, öbür her tesis 430-520 bin komut. Ana olabilecek
  tesisin raporu (ANA_TESIS yazılı değilse her tesis) eski program denetimi
  için panonun son durumunu da okur: rapor başına bir rapor boyu veri. Birden
  çok tesiste kullandıkça öde planı gerekir.
- Ücretsiz plan (ayda 500 bin komut) günde birkaç kez bakmaya yeter. Pano bir
  ekranda sürekli açık kalacaksa ya da Kameralar sık açılacaksa kullandıkça öde
  planına geçip harcama sınırı koyun. Depoda en çok 60 fotoğraf durur (24 MB'tan
  az). Güncel sınırları Upstash'in fiyat sayfasında kontrol edin.

## Nasıl çalışır

```
fabrika programı ──(HTTPS POST, imzalı JSON)──> /api/rapor, /api/foto, /api/kare ──> Upstash Redis
fabrika programı ──(imzalı komut sorusu + nonce)──> /api/komut <──(imzalı cevap)── Upstash Redis
tarayıcı ──(kişisel hesapla giriş, oturum çerezi)──> /api/durum, /api/hesap, /api/mudahale, /api/foto, /api/kare <── Upstash Redis
```

| Dosya | İşi |
|---|---|
| `api/rapor.py` | Fabrikanın raporunu alır: imza ve zaman denetimi, alan süzme, kayıt |
| `api/giris.py`, `api/cikis.py` | Panoya kişisel hesapla giriş ve çıkış (oturum çerezi, kilitler) |
| `api/durum.py` | Panonun verisi; oturum ister ve rolü uygular (`?mudahale=1` operatör+, `?yonetim=1` yönetici, `?kare=1`: anlık görüntü istenir) |
| `api/hesap.py` | Hesaplar ve işlem kaydı: yönetici hesap açar / siler / rol verir, herkes kendi şifresini değiştirir (onay şifresiyle) |
| `api/foto.py` | Kanıt fotoğrafı: fabrikadan imzalı `POST`, panoya oturumlu `GET` |
| `api/kare.py` | Anlık görüntü: fabrikadan imzalı `POST`, panoya oturumlu `GET` |
| `api/mudahale.py` | Panodan komut (anons, hoparlör denemesi, olay inceleme, teşhis, yeniden başlatma, güncelleme); rol ve onay şifresi |
| `api/komut.py` | Fabrika programının komut yoklaması (imzalı istek + `nonce`, imzalı cevap) |
| `api/_pano.py` | Ortak çekirdek (adres değildir): imza, depo, hesap, rol, kilit, komut, rapor biçimi |
| `public/` | Sayfalar: `index.html`, `pano.html`, `pano.js`, `stil.css`, `404.html`; `demo.js` yalnız `/demo`'da örnek veri verir |
| `vercel.json` | Güvenlik başlıkları, `public/`'in yayınlanması, `/demo` yönlendirmesi |
| `yerel_sunucu.py` | Siteyi Vercel'siz, bu bilgisayarda denemek için |

Yalnız Python'un standart kütüphanesi ve sade HTML/CSS/JS kullanılır: kurulacak
paket, npm, derleme adımı yoktur. Her Vercel işlevi (`api/` altındaki adresler)
ayrı bir dosyadır; `_pano.py` adres değil, ortak parçadır. Yazı tipi (Inter) ve
logo fabrika ekranındakiyle aynıdır ve siteyle birlikte gelir (CDN yok).

Görünüm: bilgisayarda laffogato yönetim panelinin Innex düzeni (kenar çubuğu ve
sayfa kartı, sayı şeridi, tablo, rozetler), telefonda lafmobil'in mobil dili
(altta yüzen sekme çubuğu, en az 44 px dokunma alanı, çentik ve alt çizgi payı).
Simgeler Lucide'dendir ve sayfanın içindedir; lisanslar `public/LISANSLAR.md`.

## Güvenlik

- **Hesaplar ve roller:** Panoya ortak şifreyle değil kişiye özel hesapla
  girilir; rol (İzleyici, Operatör, Yönetici) her istekte kayıttan okunur.
  Yetkisi olmayan düğme gizlenir, istek yine rolle denetlenir. İzleyici
  bilgisayarın IP adreslerini ve bilgisayar adını görmez.
- **Şifre saklama:** Hesap şifreleri açık değil, hesap başına rastgele tuzla
  `scrypt` (yoksa güçlü PBKDF2) özetiyle saklanır; karşılaştırma sabit sürede
  yapılır. Kurucunun şifresi (`PANO_SIFRESI`) yalnız Vercel'dedir.
- **Onay şifresi:** Yeniden başlatma, güncelleme ve her hesap işi (ekleme, rol,
  yeni şifre, kapatma, silme) işi yapanın kendi şifresini ister; yanlış ya da
  eksikse iş yapılmaz ve kilit sayaçlarına girer.
- **Yalnız kurucu yöneticileri yönetir:** Bir yöneticiyi yönetici yapmak ya da
  düşürmek, yönetici hesabına yeni şifre vermek, kapatmak ya da silmek yalnız
  kurucuya açıktır. Çalınan bir yönetici hesabı kendine kalıcı yetki açamaz.
- **İmza ve nonce:** Her rapor ve her komut cevabı `RAPOR_ANAHTARI` ile
  HMAC-SHA256 imzalanır (başlıklar `X-Dalsan-Zaman`, `X-Dalsan-Imza`). İmza
  tutmayan ya da saati 5 dakikadan fazla kaymış istek reddedilir; gövde imzadan
  önce okunmaz. Komut cevabı programın o soruda gönderdiği `nonce`'u taşır: eski
  bir cevap yeniden oynatılamaz.
- **Giriş kilitleri:** Üç kilit şifre denetiminden önce okunur - adres başına
  5 yanlışta 5 dakika (IPv6'da /64 öneki), ad başına 15 dakikada 10 yanlışta
  15 dakika, bütün adreslerden 15 dakikada 100 yanlışta 15 dakika. Bilinmeyen
  adda da aynı maliyette sahte özet çalışır. Sayaçlarda adresin kendisi değil,
  geri çevrilemeyen özeti tutulur.
- **İşlem kaydı:** Her hesap işi, her komut ve her giriş / çıkış, kim yaptığıyla
  üç listede tutulur; yönetici Kullanıcılar ekranından görür. Rolü yetmeyen her
  deneme (ör. izleyicinin müdahale isteği) de "reddedildi" diye yazılır (hesap
  başına dakikada en çok 10 satır). Şifre asla kayda girmez.
- **Önizleme kilidi:** Vercel'in önizleme (Preview) yayınından komut ve hesap
  değişikliği yapılamaz; sayfada kalıcı önizleme bandı çıkar. Dört ortam
  değişkenini de yalnız Production'a bağlı tutun.
- **Güncelleme güven zinciri:** Siteyi ele geçiren biri fabrikaya kod
  GÖNDEREMEZ; yalnız GitHub'daki resmi DALSAN yayınının son sürümünü
  kurdurabilir. Güncelleme sabit adres ve etiketten, yalnız CI'ın yüklediği
  varlıktan, SHA-256 doğrulamasıyla iner; paket listesi değişen git güncellemesi
  uzaktan yapılmaz. Asıl kapı sitede değil programdadır (ayar, rol, diskteki
  ağır sınır, `nonce`).
- **Alan süzme:** Rapordaki alanlar tek tek tip ve uzunluk denetiminden geçer;
  bilinmeyen alan depoya yazılmaz. Görüntü yalnız kendi imzalı adresinden gelir:
  base64 sıkı çözülür, boyut sınırı aşılmaz, JPEG olmayan içerik reddedilir.
  Panoya `image/jpeg` ve `nosniff` ile, yalnız oturumla verilir.
- **Oturum:** Çerez (v2) `HttpOnly`, `Secure`, `SameSite=Strict`, 12 saat;
  imzası `PANO_SIFRESI` ve `RAPOR_ANAHTARI`'ndan türer, bu yüzden kurucu şifresi
  değişince bütün oturumlar düşer. Rol, hesap kimliği ve oturum sürümü her
  istekte kayıtla karşılaştırılır: rolü düşürülen, kapatılan ya da silinen
  hesabın oturumu anında biter.
- **Sayfa:** sıkı Content-Security-Policy (yalnız sitenin kendi dosyaları),
  çerçeve içine alınamaz, arama motorlarına kapalı (`noindex`, `robots.txt`).
  Veri sayfaya yalnız `textContent` ile yazılır (CSRF için `SameSite=Strict`,
  köken denetimi ve JSON zorunluluğu).
- **Saklama:** son durum ve kanıt fotoğrafları 7 gün (en çok 60 fotoğraf),
  anlık görüntü 2 dakika tutulur; rapor kesilirse hiçbiri süresiz kalmaz.

**Bir hesap ya da kurucu şifresi çalınırsa:** Vercel'de `PANO_SIFRESI`'ni
değiştirip Redeploy edin (bütün oturumlar düşer); fabrikada Uzaktan yönetim ve
Uzaktan müdahale'yi kapatın; gerekiyorsa `RAPOR_ANAHTARI`'nı iki tarafta
yenileyin.

## Sorun giderme

| Görülen | Sebep ve çözüm |
|---|---|
| Pano: "Site henüz kurulmadı" | Listedeki ayarları yazın, sonra Redeploy |
| Pano: "Fabrikadan henüz rapor gelmedi" | Fabrika programında Ayarlar → Uzak izleme panosu doldurulmadı ya da sistem yeniden başlatılmadı |
| Pano: "Kullanıcı adı ya da şifre yanlış" | İlk girişte ad `kurucu`, şifre `PANO_SIFRESI`; kendi hesabınızı yöneticiniz açar |
| Pano: "Oturumunuz kapandı" | Şifreniz / rolünüz değişti, hesabınız kapatıldı ya da kurucu şifresi değişti; yeniden giriş yapın |
| Pano: "ÖNİZLEME - fabrikaya komut ve hesap değişikliği gönderilmez" | Önizleme (Preview) adresindesiniz; Vercel'in ana (Production) adresini açın |
| Yönetim: düğme pasif, "Fabrika programı bu işi bilmiyor" | Fabrika programı eski; güncellendiğinde Yönetim işleri açılır (ilk güncelleme fabrikada elle yapılır) |
| Program: "İmza tutmadı" | Programdaki anahtar ile `RAPOR_ANAHTARI` aynı değil |
| Program: "saati yaklaşık ... saniye geri" | Fabrika bilgisayarının tarih ve saatinde "otomatik ayarla"yı açın |
| Program: "beklenmeyen bir cevap verdi (HTTP 401)" | Önizleme adresi yazılmış; Vercel'in ana (Production) adresini yazın |
| Program: "Siteye ulaşılamadı" | İnternet yok ya da şirket güvenlik duvarı `vercel.app` adreslerini engelliyor |
| Pano: "Veri deposuna ulaşılamadı" | Storage sekmesinde Upstash bağlantısını kontrol edin; Vercel → Logs |
| Kameralar: "Fabrika programı anlık görüntü göndermiyor" | Programın uzak pano bağlantısı eski; güncellenince kameralar görüntüsüyle çıkar |
| Kameralar: "Görüntü beklemede" | Ekrana 10 dakikadır dokunulmadı; Sürdür'e basın |
| Olaylar: "Fotoğraf alınamadı" | Fotoğraf sitede silinmiş (7 gün, en çok 60) ya da henüz gelmedi; asılları fabrikadaki bilgisayardadır |

### İnternet kesilirse

- **Fabrikadaki sistem etkilenmez.** Tespit, uyarı, anons ve kayıt internet
  istemez; yalnız bu siteye gönderim durur.
- **Pano:** gönderme aralığının 3 katı (varsayılan 90 sn) haber alamayınca
  kırmızıyla "haber yok" der ve son bilinen durumu gösterir.
- **Bağlantı gelince:** ilk rapor en geç bir aralıkta (varsayılan 30 sn) gelir.
  Sayılar kesintideki ihlaller dahil eksiksizdir; olay listesi son 20 olaydır.
  Son 20 ihlalin fotoğrafı rapor başına en çok 5 gelir; varsayılan aralıkla
  yaklaşık 2 dakikada tamamlanır.
- **Uzaktan anons:** kesintide panodan istenen anons, bağlantı 2 dakika içinde
  gelmezse düşer ve çalınmaz (DALSAN `docs/15-UZAKTAN-ERISIM.md` §4.4).

## Bu bilgisayarda denemek

```bash
python3 yerel_sunucu.py          # http://127.0.0.1:3000 - kurucu şifresi ve anahtar ekrana yazılır
```

Fabrika programında site adresi olarak `http://127.0.0.1:3000` yazılabilir (düz
http yalnız bu bilgisayar için kabul edilir). Yerel sunucu Upstash yerine bellek
kullanır; kapatınca her şey silinir. Yerel sunucuda `VERCEL_ENV` yoktur, bu
yüzden önizleme kilidi çalışmaz: komut ve hesap işleri açıktır.

Testler ve biçim denetimi:

```bash
python3 -m pip install pytest ruff
python3 -m pytest
ruff check . && ruff format --check .
```

Rapor ve komut biçimi iki depoda birlikte değişir: sitede `api/_pano.py`
(`RAPOR_SURUMU`, `rapor_temizle`), programda `backend/app/uzak_pano.py` ve
`uzak_mudahale.py`. İmzanın ve biçimin ortak örnekleri iki deponun
`tests/sozlesme/` klasöründe birebir aynıdır (sözleşme DALSAN
`docs/19-SITEDEN-YONETIM.md`).
