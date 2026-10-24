# NextGen Detector · Uzak izleme sitesi

DALSAN İSG Görüntü Analiz Sistemi'nin ([RiosenBeq/DALSAN](https://github.com/RiosenBeq/DALSAN))
Vercel'de duran sitesi. İki sayfası var:

| Adres | Ne |
|---|---|
| `/` | Tanıtım: sistemin ne yaptığı, nasıl çalıştığı, KVKK notu |
| `/pano` | Şifreli **uzak izleme panosu**: sistem çalışıyor mu, kameralar canlı mı, bugün kaç ihlal oldu, son olaylar |

Fabrikadaki program bu siteye düzenli aralıkla (varsayılan 30 sn) kısa, **imzalı**
bir durum özeti gönderir. Bağlantı yalnız fabrikadan dışarı doğrudur: fabrikada
port açılmaz, modeme dokunulmaz. Fabrikadan 90 saniye haber gelmezse pano
kırmızıyla "haber yok" der; program kapatılırken son bir "kapatıldı" raporu
gönderdiği için bilerek kapatmayı bağlantı kopmasından ayırır.

## Siteye ne gelir, ne gelmez

| Siteye gelir | Siteye HİÇ gelmez |
|---|---|
| Sistem çalışıyor mu, analiz, model, sistem şeridindeki sorunlar, boş disk | Kamera görüntüsü, video, kanıt fotoğrafı |
| Kameraların adı, bölümü, bağlantı durumu, kare hızı | Kamera ve hoparlör adresleri, kullanıcı adları, şifreler |
| Bugünkü ve dünkü ihlal, inceleme bekleyen, aktif kural, saatlik dağılım | Takip numarası, olayın ayrıntı kaydı, kural ayarları |
| Son 20 olayın adı, yeri, önemi, durumu ve zamanı | Sistem olayının serbest metni (yerine olayın adı gelir) |

**Canlı görüntü bu siteden geçmez.** Görüntüye uzaktan bakmak için fabrika
ağına VPN ya da Tailscale ile bağlanılır (DALSAN `docs/15-UZAKTAN-ERISIM.md` §4.1).
O adres `FABRIKA_ADRESI` olarak yazılırsa panoda "Fabrika ekranını aç" düğmesi çıkar.

> **KVKK:** Vercel ve Upstash'in sunucuları yurt dışındadır. Rapor görüntü taşımaz
> ama bir olayın zamanı, kamerası ve türü bir çalışanla dolaylı olarak
> ilişkilendirilebilir. Fabrika programında özelliği açmadan önce hukuk biriminin
> görüşünü alın (DALSAN `docs/18-KVKK.md`). Program tarafında özellik varsayılan
> olarak **kapalıdır**.

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
- **Upstash:** site az komut kullanır. Her rapor 1 istekte 2 komuttur (30 sn
  aralıkla günde yaklaşık 5.800), pano açıkken 15 saniyede bir okur. Ücretsiz
  planın güncel sınırını Upstash'in fiyat sayfasında kontrol edin.

## Nasıl çalışır

```
fabrika programı ──(HTTPS POST, imzalı JSON)──> /api/rapor ──> Upstash Redis
tarayıcı ──(şifreyle giriş, oturum çerezi)──> /api/durum <── Upstash Redis
```

| Dosya | İşi |
|---|---|
| `api/rapor.py` | Fabrikanın raporunu alır: imza ve zaman denetimi, alan süzme, kayıt |
| `api/giris.py`, `api/cikis.py` | Panoya giriş ve çıkış (oturum çerezi) |
| `api/durum.py` | Panonun verisi; oturum ister |
| `api/_pano.py` | Ortak çekirdek (adres değildir): imza, depo, kilit, rapor biçimi |
| `public/` | Sayfalar: `index.html`, `pano.html`, `pano.js`, `stil.css` |
| `vercel.json` | Güvenlik başlıkları, `public/`'in yayınlanması |
| `yerel_sunucu.py` | Siteyi Vercel'siz, bu bilgisayarda denemek için |

Yalnız Python'un standart kütüphanesi ve sade HTML/CSS/JS kullanılır: kurulacak
paket, npm, derleme adımı yoktur. Yazı tipi (Inter) ve logo fabrika ekranındakiyle
aynıdır ve siteyle birlikte gelir (CDN yok).

## Güvenlik

- **İmza:** her rapor `RAPOR_ANAHTARI` ile HMAC-SHA256 imzalanır (başlıklar
  `X-Dalsan-Zaman`, `X-Dalsan-Imza`). İmza tutmayan ya da saati 5 dakikadan fazla
  kaymış rapor reddedilir; gövde imzadan önce okunmaz.
- **Alan süzme:** rapordaki alanlar tek tek tip ve uzunluk denetiminden geçer;
  bilinmeyen alan depoya yazılmaz (kazayla eklenen bir fotoğraf bile siteye girmez).
- **Giriş:** şifre sabit sürede karşılaştırılır. Aynı adresten 5 yanlış denemede
  5 dakika, bütün adreslerden 15 dakikada 100 yanlış denemede 15 dakika kilit.
  Kilit sayacında IP adresinin kendisi değil, geri çevrilemeyen özeti tutulur.
- **Oturum:** çerez `HttpOnly`, `Secure`, `SameSite=Strict`, 12 saat. İmzası
  şifreden ve rapor anahtarından türer: şifre değişince bütün oturumlar düşer.
- **Sayfa:** sıkı Content-Security-Policy (yalnız sitenin kendi dosyaları), çerçeve
  içine alınamaz, arama motorlarına kapalı (`noindex`, `robots.txt`). Veri sayfaya
  yalnız `textContent` ile yazılır.
- **Saklama:** son durum 7 gün tutulur; rapor kesilirse olay adları süresiz kalmaz.

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
