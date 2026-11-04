/* Uzak izleme panosu (2. tasarım, Claude Design "Pano v2" ve "Giris v2").

   /api/durum'u 15 saniyede bir okur (sekme görünürken) ve ekranı çizer.
   Müdahale ekranı açıkken 5 saniyede bir okur ve `?mudahale=1` der: fabrika
   o zaman komutları sık sormaya başlar. Kameralar ekranı açıkken de 5
   saniyede bir okur ve `?kare=1` der: fabrika o zaman 10 saniyede bir anlık
   görüntü gönderir. Ekrana 10 dakika dokunulmazsa ikisi de bekler (açık
   unutulan bir ekran fabrikayı boşuna sorgulatmasın).
   Sekiz görünüm var; adres çubuğundaki #genel, #kameralar ... hangisinin
   açık olduğunu söyler, hem masaüstünün kenar çubuğu hem telefonun sekme
   çubuğu aynı bağlantılardır.

   Uyarı tek bileşendir (#durum-bandi): bağlantı yoksa kırmızı, program
   bilerek kapatıldıysa nötr, Genel bakışta kamera ya da sistem sorunu varsa
   turuncu. Her şey yolundaysa hiç çıkmaz; üst çubuktaki hap yeter.
   Gönderilen komut sağ altta (telefonda sekme çubuğunun üstünde) küçük bir
   bildirimle Sırada -> Fabrikada -> Yapıldı diye izlenir.

   Veri fabrikadan gelir: metinler textContent ile yazılır, innerHTML
   KULLANILMAZ. Görüntüler yalnız bu sitenin oturumlu adreslerinden gelir
   (/api/foto, /api/kare). Saatler her zaman Türkiye saatiyle gösterilir; telefonun
   saat dilimi farklı olsa da.

   Dört durum (lafmobil add-screen kuralı): yükleniyor, hata (site
   ulaşılamıyor: son bilinen veri bırakılır, üstte uyarı), boş (henüz rapor
   yok) ve veri. */
"use strict";

(function () {
  const TAZELEME_MS = 15000;
  const GORECELI_MS = 5000;
  const HIZLI_TAZELEME_MS = 5000; // Müdahale ve Kameralar ekranı açıkken
  const DINLEME_SURESI_MS = 10 * 60 * 1000;
  // Fabrika 10 saniyede bir gönderir; bundan eski kare soluk gösterilir
  // (kamera ya da bağlantı durmuş olabilir).
  const KARE_BAYAT_SN = 35;
  // Gelmeyen kanıt fotoğrafı bu süre geçmeden yeniden istenmez
  const FOTO_YENIDEN_MS = 2 * 60 * 1000;
  // Fabrika son soruyu bu kadar saniye önce sorduysa "dinliyor" denir
  // (fabrika 4 sn'de bir sorar; ağ gecikmesi payı).
  const DINLIYOR_SN = 12;
  // Sunucudaki kuralın aynısı (api/_pano.py GECIKME_KATSAYISI): rapor aralığının
  // bu katı kadar haber gelmezse bağlantı yok sayılır. Site de ulaşılamaz
  // olursa pano son veriden kendisi karar verir.
  const GECIKME_KATSAYISI = 3;
  const SAAT_DILIMI = "Europe/Istanbul";
  const GENEL_OLAY_SAYISI = 5;
  const MUDAHALE_LISTE_SAYISI = 5;
  const CIFT_DOKUNUS_MS = 4000;
  // Biten komutun bildirimi bu kadar sonra kapanır (üstündeyken beklenir)
  const BILDIRIM_KAPANIS_MS = 6000;
  const DAR_EKRAN = "(max-width: 1023.98px)";

  const GORUNUMLER = {
    genel: ["Genel bakış", ""],
    kameralar: ["Kameralar", "10 saniyede bir yenilenir"],
    olaylar: ["Olaylar", "Son 20 olay"],
    mudahale: ["Müdahale", "Uzaktan anons ve hoparlör"],
    yonetim: ["Yönetim", "Teşhis, yeniden başlatma, güncelleme"],
    kullanicilar: ["Kullanıcılar", "Hesaplar ve işlem kaydı"],
    tesisler: ["Tesisler", "Komut yalnız ana tesise gider"],
    sistem: ["Sistem", "Bağlantı, bilgisayar ve hesabınız"],
  };
  /* Yetki merdiveni ve hangi görünümün hangi rolü istediği (docs/19 §1).
     api/_pano.py'deki ROL_SIRASI ve GORUNUM_EN_AZ_ROL tablolarının AYNISIDIR;
     tests/test_yetki.py iki tarafı karşılaştırır: ekranı gizleyip ucu açık
     bırakmak (ya da tersi) iki tabloyu birden değiştirmeden olmaz.
     İzleyici yalnız izler. */
  const ROL_SIRASI = { izleyici: 0, operator: 1, yonetici: 2 };
  const GORUNUM_ROLU = {
    genel: "izleyici",
    kameralar: "izleyici",
    olaylar: "izleyici",
    sistem: "izleyici",
    mudahale: "operator",
    yonetim: "yonetici",
    kullanicilar: "yonetici",
    tesisler: "yonetici",
  };
  // Telefonda sekme değil, Sistem'den açılan görünümler (üstte geri düğmesi)
  const SISTEM_ALTI = ["yonetim", "kullanicilar", "tesisler"];
  const MUDAHALE_TURLERI = ["anons", "ses_dene", "olay_incele"];
  const YONETIM_TURLERI = ["teshis", "yeniden_baslat", "guncelle"];
  const INCELE_BEKLEME_MS = 3 * 60 * 1000; // sonuç bu süre gelmezse düğmeler geri gelir

  // Komutun türe göre durum etiketi ve rozet sınıfı (docs/19 §3.6, O10).
  const KOMUT_IKONU = {
    anons: "i-anons",
    ses_dene: "i-hoparlor",
    olay_incele: "i-inceleme",
    teshis: "i-teshis",
    yeniden_baslat: "i-guc",
    guncelle: "i-indir",
  };
  const ILETILDI_ETIKETI = {
    anons: "Çalınıyor",
    ses_dene: "Deneniyor",
    teshis: "Hazırlanıyor",
    olay_incele: "Fabrikada",
  };
  const SURUYOR_ETIKETI = { yeniden_baslat: "Yeniden başlatılıyor", guncelle: "Güncelleniyor" };
  const SINIF_TONU = { basari: "yesil", tehlike: "gul", uyari: "bal", bilgi: "mavi", "": "" };

  // Ekleme ve rol formundaki rol açıklamaları (docs/19 §1, O10).
  const ROL_ACIKLAMALARI = {
    izleyici: "İzleyici - durumu, olayları ve kamera görüntülerini görür; hiçbir şey değiştiremez.",
    operator:
      "Operatör - izleyiciye ek olarak hazır anons çaldırır, hoparlörü dener, olayları " +
      "İncelendi ya da Yanlış alarm diye işaretler.",
    yonetici:
      "Yönetici - operatöre ek olarak programı yeniden başlatır, günceller, teşhis alır, " +
      "hesapları ve işlem kaydını yönetir.",
  };
  const ROL_ADLARI = { izleyici: "İzleyici", operator: "Operatör", yonetici: "Yönetici" };
  // İşlem kaydındaki iş kodlarının ekrandaki adı (docs/19 §3.3).
  const IS_ADLARI = {
    hesap_ekle: "Hesap eklendi",
    rol_degistir: "Rol değişti",
    sifre_sifirla: "Yeni şifre verildi",
    hesap_kapat: "Giriş kapatıldı",
    hesap_ac: "Giriş açıldı",
    hesap_sil: "Hesap silindi",
    sifre_degistir: "Şifre değiştirildi",
    iki_adim_ac: "İki adımlı doğrulama açıldı",
    iki_adim_kapat: "İki adımlı doğrulama kapatıldı",
    iki_adim_sifirla: "İki adımlı doğrulama sıfırlandı",
    komut: "Komut gönderildi",
    komut_sonuc: "Komut sonucu",
    komut_dustu: "Komut düştü",
    giris: "Giriş",
    cikis: "Çıkış",
    komut_red: "Yetki reddi",
    giris_hatali: "Hatalı giriş",
  };
  const SONUC_ROZETI = {
    tamam: ["Tamam", "basari"],
    hata: ["Hata", "tehlike"],
    red: ["Reddedildi", "uyari"],
  };

  // Her ekranda görünen bantların metinleri (docs/19 §3.1, O10).
  const KURUCU_BANT =
    "Kurucu hesabıyla girdiniz. Bu hesap sitenin ortak şifresiyle açılır ve tam yetki verir; " +
    "işlem kaydında kim olduğunuz görünmez. Kullanıcılar ekranından herkese kendi hesabını " +
    "açın, sonra Vercel'de PANO_SIFRESI'ni değiştirin.";
  const KURUCU_HESABIM =
    "Kurucu hesabının şifresi burada değişmez: Vercel'de Settings > Environment Variables > " +
    "PANO_SIFRESI'ni değiştirip Redeploy edin. Bütün oturumlar kapanır.";
  const ONIZLEME_BANT = "ÖNİZLEME - fabrikaya komut ve hesap değişikliği gönderilmez.";
  const SIFRE_BANT =
    "Şifreniz yöneticiniz tarafından verildi. Sistem ekranından kendi şifrenizi " +
    "belirleyene kadar komut ve hesap işlemi yapamazsınız.";
  const KAMERA_DURUMLARI = {
    online: ["Canlı", "basari"],
    connecting: ["Bağlanıyor", "uyari"],
    offline: ["Bağlantı yok", "tehlike"],
    pasif: ["Pasif", ""],
  };
  const ONEM_ROZETI = { critical: "kritik", high: "tehlike", medium: "uyari", low: "" };
  const ONEM_KUTUSU = { critical: "gul", high: "gul", medium: "bal", low: "" };
  const OLAY_DURUMU = {
    new: ["Bekliyor", "uyari"],
    reviewed: ["İncelendi", ""],
    false_alarm: ["Yanlış alarm", ""],
  };
  const BAS_RENKLERI = ["", "yesil", "bal", "gul", "gri"];

  const $ = (id) => document.getElementById(id);
  // Yalnız /demo adresinde dolu (demo.js): resimler sunucudan değil tarayıcıda çizilir
  const DEMO = window.panoDemo || null;
  let sonVeri = null;
  let saatFarkiMs = 0; // sunucu saati - bu cihazın saati
  let istekSuruyor = false;
  let sonDuyuru = "";
  let kameraSuzgeci = "hepsi";
  let olayTuru = "hepsi";
  let yalnizBekleyen = false;
  let grafikDonemi = "bugun";
  let encokGrubu = "yer";
  let aktifGorunum = "genel";
  let sonEtkilesim = Date.now();
  let seciliMesaj = null;
  let seciliKanal = null; // "" = Tüm fabrika, "3" = kanal kimliği
  let mudahaleImzasi = "";
  let bekleyenKomutlar = []; // gönderildi, sunucudan henüz okunmadı
  const kareKutulari = new Map(); // kamera anahtarı -> anlık görüntü kutusu
  const fotoHatalari = new Map(); // olay kimliği -> fotoğrafın gelmediği an
  const fotoKucukleri = new Map(); // olay kimliği -> küçük fotoğraf (tazelemede yeniden inmesin)
  let acikKare = null; // büyütülmüş anlık görüntünün kamerası (canlı yenilenir)
  let oturum = null; // {ad, rol, rol_adi, kurucu, sifre_degismeli, iki_adim?} - /api/durum'dan
  let oturumDustu = false; // pano açıkken oturum düştü: giriş ekranı bunu söyler
  let ikiAdimKurulum = null; // {ad, sir, uri}: iki adımın kurulumu sürüyor (yalnız bu sekmede)
  let ikiAdimAsamasi = null; // null | "sifre" (açmak için şifre) | "kapat"
  let onizleme = false; // önizleme yayını mı
  let hesapVerisi = null; // GET /api/hesap (kullanıcılar + işlem kaydı)
  let hesapIstekSuruyor = false;
  let kullaniciBolumu = "hesaplar";
  let acikHesap = null; // işlem paneli açık hesabın adı
  let acikIslem = null; // açık paneldeki iş: rol | sifre | durum | iki_adim | sil
  const inceleKutulari = new Map(); // olay kimliği -> inceleme denetimi (tazelemede korunur)
  const inceleDurum = new Map(); // olay kimliği -> gönderildiği an (ms)
  const inceleGecti = new Set(); // sonucu 3 dakikada gelmeyen olay kimlikleri
  const bildirimler = []; // [{id, bitti: ms | 0, uzerinde}] - en yenisi sonda

  // ----------------------------------------------------------- yardımcılar

  function el(etiket, sinif, metin) {
    const oge = document.createElement(etiket);
    if (sinif) oge.className = sinif;
    if (metin !== undefined && metin !== null) oge.textContent = metin;
    return oge;
  }

  function simge(ad, sinif) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "simge" + (sinif ? " " + sinif : ""));
    svg.setAttribute("aria-hidden", "true");
    const kullan = document.createElementNS("http://www.w3.org/2000/svg", "use");
    kullan.setAttribute("href", "#" + ad);
    svg.appendChild(kullan);
    return svg;
  }

  function rozet(metin, sinif, noktali, nabiz) {
    const oge = el("span", "rozet" + (sinif ? " " + sinif : ""));
    if (noktali) oge.appendChild(el("span", "nokta" + (nabiz ? " nabiz" : "")));
    oge.appendChild(document.createTextNode(metin));
    return oge;
  }

  function ikonKutu(ad, ton) {
    const kutu = el("span", "ikon-kutu" + (ton ? " " + ton : ""));
    kutu.appendChild(simge(ad));
    return kutu;
  }

  function temizle(oge) {
    while (oge.firstChild) oge.removeChild(oge.firstChild);
  }

  function darEkran() {
    return window.matchMedia(DAR_EKRAN).matches;
  }

  function sayiMetni(n) {
    return new Intl.NumberFormat("tr-TR").format(n || 0);
  }

  function ondalik(n) {
    return n === null || n === undefined
      ? "-"
      : new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 1 }).format(n);
  }

  function simdiMs() {
    return Date.now() + saatFarkiMs;
  }

  function sureMetni(saniye) {
    const sn = Math.max(0, Math.round(saniye));
    if (sn < 60) return sn + " saniye";
    if (sn < 3600) return Math.floor(sn / 60) + " dakika";
    if (sn < 86400) return Math.floor(sn / 3600) + " saat";
    return Math.floor(sn / 86400) + " gün";
  }

  /* Hapta ve kutularda: "35 sn", "4 dk", "2 sa", "3 gün" */
  function kisaSure(saniye) {
    const sn = Math.max(0, Math.round(saniye));
    if (sn < 60) return sn + " sn";
    if (sn < 3600) return Math.floor(sn / 60) + " dk";
    if (sn < 86400) return Math.floor(sn / 3600) + " sa";
    return Math.floor(sn / 86400) + " gün";
  }

  /* "4 dakikadır", "30 saniyedir", "2 saattir", "3 gündür" */
  function sureDir(saniye) {
    const metin = sureMetni(saniye);
    const ek = { saniye: "dir", dakika: "dır", saat: "tir", "gün": "dür" }[metin.split(" ")[1]];
    return metin + ek;
  }

  function saatMetni(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleTimeString("tr-TR", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: SAAT_DILIMI,
    });
  }

  /* Saatin bulunma eki: "14:20'de", "14:30'da", "15:00'te". Ek, sayının
     okunuşundaki son kelimeye göre seçilir (yirmi -> de, otuz -> da). */
  function saatteMetni(saat) {
    const [s, d] = saat.split(":").map(Number);
    const sayi = d ? d : s;
    const birler = { 1: "de", 2: "de", 3: "te", 4: "te", 5: "te", 6: "da", 7: "de", 8: "de", 9: "da" };
    const onlar = { 0: "da", 1: "da", 2: "de", 3: "da", 4: "ta", 5: "de" };
    const ek = sayi % 10 ? birler[sayi % 10] : onlar[Math.floor(sayi / 10)];
    return saat + "'" + ek;
  }

  function gunMetni(iso) {
    return new Date(iso).toLocaleDateString("tr-TR", { timeZone: SAAT_DILIMI });
  }

  /* "bugün" boş, "dün", ya da "21.10" (gunMetni "21.10.2026" verir) */
  function gunEtiketi(iso) {
    const bugun = gunMetni(new Date(simdiMs()).toISOString());
    const dun = gunMetni(new Date(simdiMs() - 86400000).toISOString());
    const gun = gunMetni(iso);
    if (gun === bugun) return "";
    return gun === dun ? "dün" : gun.slice(0, 5);
  }

  function tarihSaatMetni(iso) {
    if (!iso) return "";
    const gun = gunEtiketi(iso);
    return gun ? gun + " " + saatMetni(iso) : saatMetni(iso);
  }

  /* Saat; bugünden eskiyse önünde gün ("dün 11:45"). `yalnizSaat`: gün
     zaten grubun başlığında yazıyor (Olaylar). */
  function zamanOgesi(iso, yalnizSaat) {
    const zaman = el("time");
    if (!iso) {
      zaman.textContent = "-";
      return zaman;
    }
    zaman.dateTime = iso;
    zaman.textContent = yalnizSaat ? saatMetni(iso) : tarihSaatMetni(iso);
    return zaman;
  }

  function basHarfler(ad) {
    return String(ad || "?").slice(0, 2).toLocaleUpperCase("tr-TR");
  }

  function buyukBasla(metin) {
    return metin ? metin.charAt(0).toLocaleUpperCase("tr-TR") + metin.slice(1) : "";
  }

  function gecikmeSn(veri) {
    if (!veri.son_rapor) return null;
    return (simdiMs() - Date.parse(veri.son_rapor)) / 1000;
  }

  /* Sunucunun söylediği bağlantı durumu, aradan geçen süreyle yeniden
     sınanır: site o arada ulaşılamaz olsa da pano kırmızıya döner. */
  function baglantiDurumu(veri) {
    if (veri.baglanti !== "canli") return veri.baglanti;
    const aralik = (veri.rapor && veri.rapor.aralik_sn) || 30;
    return gecikmeSn(veri) > aralik * GECIKME_KATSAYISI + 5 ? "yok" : "canli";
  }

  function canliMi() {
    return !!(sonVeri && sonVeri.rapor && baglantiDurumu(sonVeri) === "canli");
  }

  function duyur(metin) {
    if (metin === sonDuyuru) return;
    sonDuyuru = metin;
    $("duyuru").textContent = metin;
  }

  function fabrikaAdresi(veri) {
    const adres = veri && veri.fabrika_adresi;
    return adres && /^https?:\/\//.test(adres) ? adres : "";
  }

  /* Hap: "basari" | "tehlike" | "uyari" | "" sınıfı ve metni */
  function hapCiz(kimlik, metinKimlik, sinif, metin) {
    const hap = $(kimlik);
    hap.className = "hap" + (hap.classList.contains("kucuk") ? " kucuk" : "") + (sinif ? " " + sinif : "");
    $(metinKimlik).textContent = metin;
  }

  /* Çift dokunuş: ilk dokunuş sorar (düğme turuncu, altında 4 sn geri sayım),
     ikincisi gönderir. Soru 4 saniye sonra kendiliğinden kalkar. */
  function ciftDokunus(dugme, soru, kap) {
    if (dugme.classList.contains("onayla")) {
      onayiKaldir(dugme);
      return true;
    }
    for (const diger of document.querySelectorAll(".dugme.onayla")) onayiKaldir(diger);
    dugme.classList.add("onayla");
    dugme.dataset.etiket = dugme.dataset.etiket || dugme.lastChild.textContent;
    dugme.lastChild.textContent = soru;
    const cizgi = el("span", "geri-sayim");
    cizgi.setAttribute("aria-hidden", "true");
    (kap || dugme.parentNode).appendChild(cizgi);
    dugme._cizgi = cizgi;
    dugme._zaman = setTimeout(function () {
      onayiKaldir(dugme);
    }, CIFT_DOKUNUS_MS);
    return false;
  }

  function onayiKaldir(dugme) {
    clearTimeout(dugme._zaman);
    dugme.classList.remove("onayla");
    if (dugme.dataset.etiket) dugme.lastChild.textContent = dugme.dataset.etiket;
    if (dugme._cizgi) dugme._cizgi.remove();
    dugme._cizgi = null;
  }

  // ------------------------------------------------------------- ekranlar

  function tekEkranGoster(ad) {
    // Çıkış ve oturum düşmesi giriş ekranını buradan açar: yarım kalan iki adım
    // kurulumunun anahtarı unutulur, aynı sekmede giren başka kişi görmez.
    if (ad === "giris") ikiAdimKurulumuUnut();
    $("kabuk").hidden = true;
    $("tek-ekran").hidden = false;
    for (const kimlik of ["yukleniyor", "kurulum", "giris"]) $(kimlik).hidden = kimlik !== ad;
  }

  function ikiAdimKurulumuUnut() {
    ikiAdimKurulum = null;
    for (const kimlik of ["iki-adim-sir", "iki-adim-uri"]) $(kimlik).textContent = "";
  }

  /* Oturum düştü (401): giriş ekranı açılır, pano açıktıysa "süresi doldu" der. */
  function oturumuKapat() {
    oturumDustu = !!sonVeri;
    sonVeri = null;
    oturum = null;
    hesapVerisi = null;
    tekEkranGoster("giris");
    girisAdiminaDon();
    $("oturum-bandi").hidden = !oturumDustu;
  }

  function panoyuGoster() {
    $("tek-ekran").hidden = true;
    $("kabuk").hidden = false;
  }

  function siteUyarisi(metin) {
    const kutu = $("site-uyarisi");
    kutu.textContent = metin;
    kutu.hidden = !metin;
  }

  // ------------------------------------------------------- rol ve bantlar

  function rolu() {
    return oturum ? oturum.rol : "izleyici";
  }

  /* Rol merdiveni (api/_pano.py rol_yeterli_mi'nin aynısı): tanınmayan rol ve
     tanınmayan eşik yetmez. `rol` verilmezse oturumun rolü kullanılır. */
  function rolYeter(enAz, rol) {
    const esik = ROL_SIRASI[enAz];
    if (esik === undefined) return false;
    const sira = ROL_SIRASI[rol === undefined ? rolu() : rol];
    return sira !== undefined && sira >= esik;
  }

  function operatorMu() {
    return rolYeter("operator");
  }

  /* Menüdeki ve sekme çubuğundaki FABRİKA bağlantılarını role göre gösterir;
     yetkisi olmayan görünümden çıkar (docs/19 §1). */
  function rolUygula() {
    // Yalnız gezinme öğelerini (menü + sekme) gizle; görünüm kutularını
    // gorunumuUygula yönetir (data-gorunum görünüm div'inde de var). Hangi
    // öğenin gizleneceği GORUNUM_ROLU'ndan okunur: elle sayılan seçici listesi
    // yok, yeni bir ekran tabloya girince kendiliğinden doğru gizlenir.
    // (Yönetim, Kullanıcılar ve Tesisler'in telefon sekmesi yoktur; seçici boş
    // döner. Müdahale'nin hem kenar menüsü hem sekmesi vardır.)
    for (const ad of Object.keys(GORUNUM_ROLU)) {
      const yetkili = rolYeter(GORUNUM_ROLU[ad]);
      for (const oge of document.querySelectorAll(
        '.menu-ogesi[data-gorunum="' + ad + '"], .sekme[data-gorunum="' + ad + '"]'
      )) {
        oge.hidden = !yetkili;
      }
    }
    $("fabrika-grubu").hidden = !rolYeter("operator");
    $("fabrika-yonetim-karti").hidden = !rolYeter("yonetici");
    // Yetkisiz görünümdeysek (ör. rol düşürüldü) genel bakışa dön
    if (!gorunumYetkili(aktifGorunum) && location.hash.replace("#", "") !== "genel") {
      location.hash = "genel";
    }
  }

  function bantlariCiz() {
    const onizlemeBant = $("onizleme-bandi");
    onizlemeBant.hidden = !onizleme;
    if (onizleme) onizlemeBant.textContent = ONIZLEME_BANT;
    const kurucu = !!(oturum && oturum.kurucu);
    $("kurucu-bandi").hidden = !kurucu;
    if (kurucu) $("kurucu-bandi").textContent = KURUCU_BANT;
    const degismeli = !!(oturum && oturum.sifre_degismeli);
    $("sifre-bandi").hidden = !degismeli;
    if (degismeli) $("sifre-bandi").textContent = SIFRE_BANT;
  }

  // -------------------------------------------------------------- hesabım

  function hesabimCiz() {
    if (!oturum) return;
    const rolAdi = oturum.rol_adi || ROL_ADLARI[oturum.rol] || "";
    $("hesabim-ad").textContent = oturum.ad;
    $("hesabim-rol").textContent = rolAdi;
    $("hesabim-bas").textContent = basHarfler(oturum.ad);
    $("kenar-ad").textContent = oturum.ad;
    $("kenar-rol").textContent = rolAdi;
    $("kenar-bas").textContent = basHarfler(oturum.ad);
    const kurucu = oturum.kurucu;
    $("sifre-ac").hidden = kurucu || !$("hesabim-formu").hidden;
    if (kurucu) $("hesabim-formu").hidden = true;
    $("hesabim-kurucu").hidden = !kurucu;
    if (kurucu) $("hesabim-kurucu").textContent = KURUCU_HESABIM;
    ikiAdimCiz();
  }

  $("sifre-ac").addEventListener("click", function () {
    $("hesabim-sonuc").hidden = true;
    $("hesabim-hatasi").textContent = "";
    $("hesabim-formu").hidden = false;
    this.hidden = true;
    $("eski-sifre").focus();
  });

  $("sifre-vazgec").addEventListener("click", function () {
    $("hesabim-formu").hidden = true;
    $("eski-sifre").value = "";
    $("yeni-sifre").value = "";
    $("sifre-ac").hidden = false;
    $("sifre-ac").focus();
  });

  // ------------------------------------------------- iki adımlı doğrulama

  const IKI_ADIM_KURTARMA =
    "Telefonunuzu kaybederseniz yöneticiniz Kullanıcılar ekranından iki adımı sıfırlar; " +
    "sonra yalnız şifrenizle girer, isterseniz yeniden açarsınız.";
  const IKI_ADIM_KURTARMA_KURUCU =
    "Kurucu hesabında telefon kaybolursa Vercel'de PANO_SIFRESI'ni değiştirip Redeploy edin: " +
    "kurucunun iki adımlı doğrulaması kendiliğinden kapanır.";

  /* Durum (açık / kapalı), kurulum ya da kapatma formu. Sır yalnız kurulum
     sürerken ve yalnız textContent ile yazılır; tazelemede kutular korunur. */
  function ikiAdimCiz() {
    if (!oturum) return;
    const acik = oturum.iki_adim === true;
    // Anahtar yalnız kurulumu başlatan hesaba çizilir
    if (acik || (ikiAdimKurulum && ikiAdimKurulum.ad !== oturum.ad)) ikiAdimKurulumuUnut();
    if (acik && ikiAdimAsamasi === "sifre") ikiAdimAsamasi = null;
    if (!acik && ikiAdimAsamasi === "kapat") ikiAdimAsamasi = null;
    const durum = $("iki-adim-durumu");
    temizle(durum);
    durum.appendChild(acik ? rozet("Açık", "basari") : rozet("Kapalı", ""));
    const kurulum = !acik && !!ikiAdimKurulum;
    $("iki-adim-ac-formu").hidden = acik || kurulum || ikiAdimAsamasi !== "sifre";
    $("iki-adim-kurulum").hidden = !kurulum;
    $("iki-adim-kapat-formu").hidden = !acik || ikiAdimAsamasi !== "kapat";
    $("iki-adim-baslat").hidden = acik || kurulum || ikiAdimAsamasi === "sifre";
    $("iki-adim-kapat-ac").hidden = !acik || ikiAdimAsamasi === "kapat";
    const sir = ikiAdimKurulum ? ikiAdimKurulum.sir : "";
    if ($("iki-adim-sir").textContent !== sir) {
      $("iki-adim-sir").textContent = sir;
      $("iki-adim-uri").textContent = ikiAdimKurulum ? ikiAdimKurulum.uri : "";
      kopyaDugmesiniSifirla($("iki-adim-sir-kopyala"));
      kopyaDugmesiniSifirla($("iki-adim-uri-kopyala"));
    }
    $("iki-adim-notu").textContent = oturum.kurucu ? IKI_ADIM_KURTARMA_KURUCU : IKI_ADIM_KURTARMA;
    $("iki-adim-notu").hidden = !acik && !kurulum;
  }

  function kodMetni(deger) {
    return String(deger || "").replace(/\s+/g, "");
  }

  function kopyaDugmesiniSifirla(dugme) {
    dugme.querySelector("use").setAttribute("href", "#i-kopyala");
    dugme.lastChild.textContent = "Kopyala";
  }

  async function metniKopyala(kimlik, dugme) {
    try {
      await navigator.clipboard.writeText($(kimlik).textContent);
      dugme.querySelector("use").setAttribute("href", "#i-onay");
      dugme.lastChild.textContent = "Kopyalandı";
      setTimeout(function () {
        kopyaDugmesiniSifirla(dugme);
      }, 2000);
    } catch (hata) {
      // Pano izni yoksa metni seçili bırak: kullanıcı kendisi kopyalar
      const secim = window.getSelection();
      const aralik = document.createRange();
      aralik.selectNodeContents($(kimlik));
      secim.removeAllRanges();
      secim.addRange(aralik);
      dugme.lastChild.textContent = "Seçildi, kopyalayın";
    }
  }

  $("iki-adim-sir-kopyala").addEventListener("click", function () {
    metniKopyala("iki-adim-sir", this);
  });
  $("iki-adim-uri-kopyala").addEventListener("click", function () {
    metniKopyala("iki-adim-uri", this);
  });

  $("iki-adim-baslat").addEventListener("click", function () {
    ikiAdimAsamasi = "sifre";
    $("iki-adim-hatasi").textContent = "";
    ikiAdimCiz();
    $("iki-adim-ac-sifre").focus();
  });
  $("iki-adim-kapat-ac").addEventListener("click", function () {
    ikiAdimAsamasi = "kapat";
    $("iki-adim-hatasi").textContent = "";
    ikiAdimCiz();
    $("iki-adim-kapat-sifre").focus();
  });
  for (const kimlik of ["iki-adim-ac-vazgec", "iki-adim-kapat-vazgec"]) {
    $(kimlik).addEventListener("click", function () {
      ikiAdimAsamasi = null;
      $("iki-adim-hatasi").textContent = "";
      for (const girdi of ["iki-adim-ac-sifre", "iki-adim-kapat-sifre", "iki-adim-kapat-kodu"]) {
        $(girdi).value = "";
      }
      ikiAdimCiz();
    });
  }

  $("iki-adim-ac-formu").addEventListener("submit", async function (olay) {
    olay.preventDefault();
    $("iki-adim-hatasi").textContent = "";
    const sifre = $("iki-adim-ac-sifre").value;
    if (!sifre) {
      $("iki-adim-hatasi").textContent = "Açmak için şu anki şifrenizi yazın.";
      $("iki-adim-ac-sifre").focus();
      return;
    }
    const dugme = $("iki-adim-ac-dugmesi");
    dugme.disabled = true;
    try {
      const cevap = await hesapIslem({ eylem: "iki_adim_baslat", sifre: sifre });
      $("iki-adim-ac-sifre").value = "";
      ikiAdimAsamasi = null;
      ikiAdimKurulum = {
        ad: oturum.ad,
        sir: cevap.sir || "",
        uri: cevap.uri || "",
      };
      ikiAdimCiz();
      $("iki-adim-onay-kodu").focus();
    } catch (hata) {
      $("iki-adim-hatasi").textContent = hata.message;
    } finally {
      dugme.disabled = false;
    }
  });

  $("iki-adim-onay-formu").addEventListener("submit", async function (olay) {
    olay.preventDefault();
    $("iki-adim-hatasi").textContent = "";
    const kod = kodMetni($("iki-adim-onay-kodu").value);
    if (!/^[0-9]{6}$/.test(kod)) {
      $("iki-adim-hatasi").textContent = "Uygulamanın gösterdiği 6 haneli kodu yazın.";
      $("iki-adim-onay-kodu").focus();
      return;
    }
    const dugme = $("iki-adim-onay-dugmesi");
    dugme.disabled = true;
    try {
      await hesapIslem({ eylem: "iki_adim_onayla", kod: kod });
      ikiAdimKurulum = null;
      duyur("İki adımlı doğrulama açıldı.");
      await yukle();
    } catch (hata) {
      // Kurulum düştüyse (süre doldu ya da başka sekmede açıldı) başa dönülür
      if (hata.hata === "iki_adim_bekleyen_yok" || hata.hata === "iki_adim_acik") {
        ikiAdimKurulum = null;
        ikiAdimCiz();
      }
      $("iki-adim-hatasi").textContent = hata.message;
    } finally {
      $("iki-adim-onay-kodu").value = "";
      dugme.disabled = false;
    }
  });

  $("iki-adim-vazgec").addEventListener("click", function () {
    ikiAdimKurulum = null; // bekleyen sır sunucuda 10 dakikada kendiliğinden düşer
    $("iki-adim-hatasi").textContent = "";
    ikiAdimCiz();
  });

  $("iki-adim-kapat-formu").addEventListener("submit", async function (olay) {
    olay.preventDefault();
    $("iki-adim-hatasi").textContent = "";
    const sifre = $("iki-adim-kapat-sifre").value;
    const kod = kodMetni($("iki-adim-kapat-kodu").value);
    if (!sifre || !/^[0-9]{6}$/.test(kod)) {
      $("iki-adim-hatasi").textContent =
        "Kapatmak için şifrenizi ve uygulamanın gösterdiği 6 haneli kodu yazın.";
      return;
    }
    const dugme = $("iki-adim-kapat-dugmesi");
    dugme.disabled = true;
    try {
      await hesapIslem({ eylem: "iki_adim_kapat", sifre: sifre, kod: kod });
      $("iki-adim-kapat-sifre").value = "";
      ikiAdimAsamasi = null;
      duyur("İki adımlı doğrulama kapatıldı.");
      await yukle();
    } catch (hata) {
      $("iki-adim-hatasi").textContent = hata.message;
    } finally {
      $("iki-adim-kapat-kodu").value = "";
      dugme.disabled = false;
    }
  });

  $("hesabim-formu").addEventListener("submit", async function (olay) {
    olay.preventDefault();
    $("hesabim-hatasi").textContent = "";
    const eski = $("eski-sifre").value;
    const yeni = $("yeni-sifre").value;
    $("eski-sifre").toggleAttribute("aria-invalid", !eski);
    $("yeni-sifre").toggleAttribute("aria-invalid", !!eski && yeni.length < 10);
    if (!eski || !yeni) {
      $("hesabim-hatasi").textContent = "Şu anki ve yeni şifrenizi yazın.";
      $(!eski ? "eski-sifre" : "yeni-sifre").focus();
      return;
    }
    const dugme = $("hesabim-dugmesi");
    dugme.disabled = true;
    try {
      await hesapIslem({ eylem: "sifre_degistir", eski_sifre: eski, yeni_sifre: yeni });
      $("eski-sifre").value = "";
      $("yeni-sifre").value = "";
      $("hesabim-formu").hidden = true;
      $("sifre-ac").hidden = false;
      $("hesabim-sonuc").textContent = "Şifreniz değiştirildi.";
      $("hesabim-sonuc").hidden = false;
      duyur("Şifreniz değiştirildi.");
      await yukle();
    } catch (hata) {
      $("hesabim-hatasi").textContent = hata.message;
    } finally {
      dugme.disabled = false;
    }
  });

  // ------------------------------------------------------------ görünüm

  /* Adresteki görünüm; görünüm olmayan bir çapa (ör. "İçeriğe geç" -> #icerik)
     açık görünümü değiştirmez. */
  function gorunumAdi() {
    const ad = location.hash.replace("#", "");
    return Object.prototype.hasOwnProperty.call(GORUNUMLER, ad) ? ad : null;
  }

  /* Rolü bu görünüme yetiyor mu (docs/19 §1). Rol daha bilinmiyorsa (ilk
     yükleme) izin verilir; /api/durum gelince yetkisiz görünümden çıkılır. */
  function gorunumYetkili(ad) {
    const gereken = GORUNUM_ROLU[ad];
    if (!gereken || !oturum) return true;
    return rolYeter(gereken);
  }

  function bugunMetni() {
    return (
      "Bugün, " +
      new Date(simdiMs()).toLocaleDateString("tr-TR", { day: "numeric", month: "long", timeZone: SAAT_DILIMI })
    );
  }

  function gorunumuUygula() {
    let ad = gorunumAdi() || aktifGorunum;
    if (!gorunumYetkili(ad)) ad = "genel";
    aktifGorunum = ad;
    for (const kutu of document.querySelectorAll(".gorunum")) {
      kutu.hidden = kutu.dataset.gorunum !== ad;
    }
    for (const bag of document.querySelectorAll(".menu-ogesi[data-gorunum], .sekme, .hesap-bagi")) {
      // Telefonda Yönetim, Kullanıcılar ve Tesisler Sistem sekmesinin altındadır
      const etkin =
        bag.dataset.gorunum === ad ||
        (bag.classList.contains("sekme") && bag.dataset.gorunum === "sistem" && SISTEM_ALTI.includes(ad));
      if (etkin) bag.setAttribute("aria-current", "page");
      else bag.removeAttribute("aria-current");
    }
    const [baslik, aciklama] = GORUNUMLER[ad];
    $("gorunum-basligi").textContent = baslik;
    $("gorunum-aciklamasi").textContent = ad === "genel" ? bugunMetni() : aciklama;
    $("geri-dugmesi").hidden = !SISTEM_ALTI.includes(ad);
    document.title = baslik + " · Uzak izleme panosu";
    if (sonVeri) durumBandiniCiz(sonVeri);
  }

  function gorunumeGit(ad) {
    if (location.hash === "#" + ad) gorunumuUygula();
    else location.hash = ad;
  }

  window.addEventListener("hashchange", function () {
    if (!gorunumAdi()) return;
    gorunumuUygula();
    window.scrollTo(0, 0);
    const g = aktifGorunum;
    if ((g === "mudahale" || g === "kameralar" || g === "yonetim") && sonVeri) {
      sonEtkilesim = Date.now();
      if (g === "mudahale") mudahaleyiCiz(sonVeri);
      else if (g === "yonetim") yonetimiCiz(sonVeri);
      else kareleriCiz(sonVeri);
      yukle();
    }
    if (g === "olaylar" && sonVeri && sonVeri.rapor) olaylariCiz(sonVeri.rapor);
    if (g === "kullanicilar" && gorunumYetkili("kullanicilar")) hesaplariYukle();
    if (tesislerAcik()) {
      if (!sonVeri || !sonVeri.filo) tesisIskeleti();
      yukle();
    }
  });

  // ------------------------------------------------------------- kurulum

  function onerilenAnahtar() {
    const baytlar = new Uint8Array(24);
    crypto.getRandomValues(baytlar);
    let ikili = "";
    for (const b of baytlar) ikili += String.fromCharCode(b);
    return btoa(ikili).replace(/\+/g, "x").replace(/\//g, "y").replace(/=+$/, "");
  }

  function kurulumGoster(eksikler) {
    const sayi = ["", "bir", "iki", "üç", "dört"][eksikler.length] || String(eksikler.length);
    $("kurulum-alt").textContent =
      "Vercel'de " + (sayi ? sayi + " " : "") + "ayar eksik. Üç adımda biter.";
    $("kurulum-alt").title = eksikler.map((e) => e.ad + ": " + e.neden).join("\n");
    if (!$("onerilen-anahtar").textContent) $("onerilen-anahtar").textContent = onerilenAnahtar();
    tekEkranGoster("kurulum");
  }

  $("anahtar-kopyala").addEventListener("click", function () {
    metniKopyala("onerilen-anahtar", this);
  });

  // ------------------------------------------------- uyarı ve hap

  /* Üst çubuğun hapı ve Sistem kartındaki hap: Canlı 14:32 / Haber yok 4 dk /
     Kapalı 14:20. Telefonda yalnız kısa metin görünür. */
  function hapBilgisi(veri) {
    const durum = baglantiDurumu(veri);
    const gecikme = gecikmeSn(veri);
    if (durum === "canli") {
      const saat = saatMetni(veri.son_rapor);
      return { sinif: "basari", metin: "Canlı", saat: saat, kisa: saat };
    }
    if (durum === "yok") {
      const sure = gecikme === null ? "" : kisaSure(gecikme);
      return { sinif: "tehlike", metin: "Haber yok", saat: sure, kisa: sure || "Haber yok" };
    }
    if (durum === "kapandi") {
      return { sinif: "", metin: "Kapalı", saat: tarihSaatMetni(veri.son_rapor), kisa: "Kapalı" };
    }
    return { sinif: "", metin: "Rapor yok", saat: "", kisa: "Rapor yok" };
  }

  /* Tek uyarı. Bağlantı uyarısı her ekranda; kamera ve sistem sorunları
     yalnız Genel bakışta (orada sayılarla birlikte okunur). */
  function uyariBilgisi(veri) {
    const rapor = veri.rapor;
    const durum = baglantiDurumu(veri);
    const gecikme = gecikmeSn(veri);
    if (durum === "hic") {
      return {
        sinif: "",
        ikon: "i-bilgi",
        baslik: "Fabrikadan henüz rapor gelmedi",
        alt:
          "Fabrika programında Ayarlar → Uzak izleme panosu bölümüne bu sitenin adresini ve " +
          "rapor anahtarını yazın, sonra sistemi yeniden başlatın.",
      };
    }
    if (durum === "yok") {
      return {
        sinif: "tehlike",
        ikon: "i-kopuk",
        baslik: "Fabrikadan " + sureDir(gecikme || 0) + " haber yok",
        alt:
          (rapor ? "Gösterilen veriler " + tarihSaatMetni(veri.son_rapor) + " raporundan. " : "") +
          "Komutlar bağlantı gelene kadar gönderilemez.",
        liste: [
          "Fabrika bilgisayarı açık mı",
          "NextGen Detector programı çalışıyor mu",
          "İnternet bağlantısı var mı",
        ],
      };
    }
    if (durum === "kapandi") {
      const sebep = rapor && rapor.kapanis_sebebi;
      if (sebep === "guncelleme" || sebep === "yeniden_baslatma") {
        return {
          sinif: "",
          ikon: "i-yenile",
          baslik: sebep === "guncelleme" ? "Program güncelleniyor" : "Program yeniden başlatılıyor",
          alt: "Birkaç dakika kapalı kalabilir; açılınca pano kendiliğinden güncellenir.",
        };
      }
      const gun = gunEtiketi(veri.son_rapor);
      return {
        sinif: "",
        ikon: "i-saat",
        baslik: "Program " + (gun ? gun + " " : "") + saatteMetni(saatMetni(veri.son_rapor)) + " kapatıldı",
        alt: "Bilerek kapatıldı; yeniden açılınca pano kendiliğinden güncellenir.",
      };
    }
    if (aktifGorunum !== "genel" || !rapor) return null;

    // Canlı: Genel bakışta dikkat gereken sorunlar tek uyarıda
    const sistem = rapor.sistem;
    // Bağlantısı kopan kamera önce, yeniden bağlanan sonra yazılır
    const kopuklar = rapor.kameralar
      .filter((k) => k.durum !== "pasif" && k.durum !== "online")
      .sort((a, b) => (a.durum === "offline" ? 0 : 1) - (b.durum === "offline" ? 0 : 1));
    const liste = [...sistem.sorunlar];
    if (rapor.sayilar.aktif_kural === 0 && rapor.sayilar.kamera_toplam > 0) {
      liste.push("Aktif kural yok: kural kurulmadan ihlal üretilmez.");
    }
    if (sistem.analiz === false) {
      return {
        sinif: "tehlike",
        ikon: "i-uyari",
        baslik: "Program açık ama analiz çalışmıyor",
        alt: "Şu an ihlal yakalanmıyor; fabrikada sistemi başlatın.",
        liste: liste,
        eylem: kopuklar.length ? "kameralar" : "",
      };
    }
    if (kopuklar.length) {
      const parcalar = kopuklar.map(
        (k) => k.ad + " " + (KAMERA_DURUMLARI[k.durum] || KAMERA_DURUMLARI.offline)[0].toLocaleLowerCase("tr-TR")
      );
      return {
        sinif: "turuncu",
        ikon: "i-kamera",
        baslik: kopuklar.length + " kamera görüntü vermiyor",
        alt: parcalar.join(", ") + ". O alanlar şu an izlenmiyor.",
        // Aynı kameranın sistem şeridindeki sorunu başlıkta zaten söylendi
        liste: liste.filter((m) => !kopuklar.some((k) => m.includes(k.ad))),
        eylem: "kameralar",
      };
    }
    if (liste.length) {
      return {
        sinif: "turuncu",
        ikon: "i-uyari",
        baslik: liste.length === 1 ? "Dikkat gereken bir sorun var" : "Dikkat gereken " + liste.length + " sorun var",
        alt: "",
        liste: liste,
      };
    }
    return null;
  }

  function durumBandiniCiz(veri) {
    const hap = hapBilgisi(veri);
    for (const [kimlik, metin] of [
      ["baglanti-hapi", "hap-metni"],
      ["sistem-hapi", "sistem-hap-metni"],
    ]) {
      hapCiz(kimlik, metin, hap.sinif, hap.metin);
    }
    $("son-rapor").textContent = hap.saat;
    $("hap-kisa").textContent = hap.kisa;
    $("baglanti-hapi").setAttribute("aria-label", "Bağlantı: " + hap.metin + (hap.saat ? ", " + hap.saat : ""));

    const uyari = uyariBilgisi(veri);
    const bant = $("durum-bandi");
    bant.hidden = !uyari;
    if (!uyari) {
      duyur(baglantiDurumu(veri) === "canli" ? "Sistem çalışıyor" : hap.metin);
      return;
    }
    bant.className = "uyari-bandi" + (uyari.sinif ? " " + uyari.sinif : "");
    $("durum-simgesi").setAttribute("href", "#" + uyari.ikon);
    $("durum-baslik").textContent = uyari.baslik;
    $("durum-alt").textContent = uyari.alt;
    const liste = $("durum-listesi");
    temizle(liste);
    (uyari.liste || []).forEach(function (metin, i) {
      const satir = el("li");
      satir.appendChild(el("span", "no", String(i + 1)));
      satir.appendChild(el("span", "", metin));
      liste.appendChild(satir);
    });
    liste.hidden = !(uyari.liste && uyari.liste.length);
    $("durum-eylemi").hidden = !uyari.eylem;
    duyur(uyari.baslik);
  }

  $("durum-eylemi").addEventListener("click", function () {
    kameraSuzgeciSec("sorunlu");
  });

  // ------------------------------------------------------------- sayılar

  function degisimCiz(kimlik, fark, metin, etiket) {
    const kutu = $(kimlik);
    kutu.hidden = fark === 0;
    // Daha az ihlal iyi haber (yeşil), daha çok kötü haber (kırmızı)
    kutu.className = "degisim " + (fark > 0 ? "kotu" : "iyi");
    kutu.querySelector("use").setAttribute("href", fark > 0 ? "#i-yukari" : "#i-asagi");
    kutu.lastChild.textContent = metin;
    kutu.setAttribute("aria-label", etiket);
  }

  function haftalar(rapor) {
    if (rapor.gunluk) {
      return { bu: toplamAl(rapor.gunluk.slice(7)), gecen: toplamAl(rapor.gunluk.slice(0, 7)) };
    }
    if (rapor.yedi_gun && typeof rapor.yedi_gun.ihlal === "number") {
      return { bu: rapor.yedi_gun.ihlal, gecen: null };
    }
    return null;
  }

  function sayilariCiz(rapor) {
    const s = rapor.sayilar;
    $("k-ihlal").textContent = sayiMetni(s.bugun_ihlal);
    $("k-ihlal-ref").textContent =
      s.dun_ihlal === 0 ? (s.bugun_ihlal ? "dün ihlal yoktu" : "dün de ihlal yoktu") : "dün " + sayiMetni(s.dun_ihlal);
    const fark = s.bugun_ihlal - s.dun_ihlal;
    degisimCiz("k-ihlal-degisim", fark, String(Math.abs(fark)), "düne göre " + (fark > 0 ? fark + " fazla" : -fark + " az"));

    const hafta = haftalar(rapor);
    $("kpi-hafta").hidden = !hafta;
    $("kpi-hafta").parentNode.classList.toggle("uclu", !hafta);
    if (hafta) {
      $("k-hafta").textContent = sayiMetni(hafta.bu);
      if (hafta.gecen === null) {
        $("k-hafta-ref").textContent = "ihlal";
        $("k-hafta-degisim").hidden = true;
      } else {
        $("k-hafta-ref").textContent = "önceki 7 gün " + sayiMetni(hafta.gecen);
        const hf = hafta.bu - hafta.gecen;
        const oran = hafta.gecen ? "%" + Math.round((Math.abs(hf) / hafta.gecen) * 100) : String(Math.abs(hf));
        degisimCiz("k-hafta-degisim", hf, oran, "önceki haftaya göre " + (hf > 0 ? "arttı" : "azaldı"));
      }
    }

    $("k-bekleyen").textContent = sayiMetni(s.bekleyen);
    $("k-bekleyen").classList.toggle("dikkat", s.bekleyen > 0);
    $("k-bekleyen-ref").textContent = !s.bekleyen
      ? "kuyruk boş"
      : operatorMu()
        ? "incelemek için dokunun"
        : "fabrika ekranında incelenir";

    const pasif = rapor.kameralar.filter((k) => k.durum === "pasif").length;
    const kopuk = kopukKameraSayisi(rapor);
    $("k-kamera").textContent = s.kamera_canli + " / " + s.kamera_toplam;
    $("k-kamera").classList.toggle("dikkat", kopuk > 0);
    let not = "hepsi görüntü veriyor";
    if (s.kamera_toplam === 0) not = "henüz kamera eklenmedi";
    else if (kopuk > 0) not = kopuk + " kamera görüntü vermiyor";
    else if (pasif > 0) not = pasif + " kamera pasif";
    $("k-kamera-ref").textContent = not;

    for (const [kimlik, deger, ref] of [
      ["kpi-ihlal", "k-ihlal", "k-ihlal-ref"],
      ["kpi-hafta", "k-hafta", "k-hafta-ref"],
      ["kpi-bekleyen", "k-bekleyen", "k-bekleyen-ref"],
      ["kpi-kamera", "k-kamera", "k-kamera-ref"],
    ]) {
      const hucre = $(kimlik);
      hucre.setAttribute(
        "aria-label",
        hucre.querySelector(".kpi-etiket").textContent + ": " + $(deger).textContent + ", " + $(ref).textContent
      );
    }
  }

  $("kpi-ihlal").addEventListener("click", function () {
    olaySuzgeciSec("ihlal", false);
    gorunumeGit("olaylar");
  });
  $("kpi-hafta").addEventListener("click", function () {
    if (!sonVeri || !sonVeri.rapor || !sonVeri.rapor.gunluk) return;
    grafikDonemiSec("gun14");
    $("grafik").scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
  $("kpi-bekleyen").addEventListener("click", function () {
    olaySuzgeciSec("hepsi", true);
    gorunumeGit("olaylar");
  });
  $("kpi-kamera").addEventListener("click", function () {
    const kopuk = sonVeri && sonVeri.rapor ? kopukKameraSayisi(sonVeri.rapor) : 0;
    kameraSuzgeciSec(kopuk ? "sorunlu" : "hepsi");
    gorunumeGit("kameralar");
  });

  function kopukKameraSayisi(rapor) {
    return rapor.kameralar.filter((k) => k.durum !== "pasif" && k.durum !== "online").length;
  }

  function bekleyenOlaylar(rapor) {
    return rapor.son_olaylar.filter((o) => o.tur === "ihlal" && o.durum === "new");
  }

  /* Kenar çubuğu ve sekme çubuğundaki sayaçlar: yalnız iş bekleyen yerde. */
  function sayaclariCiz(rapor) {
    const kopuk = rapor ? kopukKameraSayisi(rapor) : 0;
    const bekleyen = rapor ? rapor.sayilar.bekleyen : 0;
    for (const sayac of document.querySelectorAll("[data-sayac]")) {
      const n = sayac.dataset.sayac === "kamera" ? kopuk : bekleyen;
      sayac.hidden = n === 0;
      sayac.textContent = n > 99 ? "99+" : String(n);
      sayac.classList.toggle("dikkat", sayac.dataset.sayac === "kamera" && n > 0);
    }
  }

  // --------------------------------------------------- grafik ve listeler

  function toplamAl(dizi) {
    return dizi.reduce((a, b) => a + b, 0);
  }

  function grafikDonemiSec(donem) {
    grafikDonemi = donem;
    for (const d of document.querySelectorAll("#grafik-segmenti button")) {
      d.setAttribute("aria-pressed", String(d.dataset.grafik === donem));
    }
    if (sonVeri && sonVeri.rapor) grafigiCiz(sonVeri.rapor);
  }

  for (const dugme of document.querySelectorAll("#grafik-segmenti button")) {
    dugme.addEventListener("click", function () {
      grafikDonemiSec(this.dataset.grafik);
    });
  }

  /* Tek grafik iki dönem: bugün saat saat (24 çubuk) ya da son 14 gün.
     Şimdiki saat / bugün mor-mavi geçişle; boş çubuk ince bir iz. */
  function grafigiCiz(rapor) {
    const gunlukVar = !!rapor.gunluk;
    $("grafik-segmenti").hidden = !gunlukVar;
    if (!gunlukVar) grafikDonemi = "bugun";
    const bugun = grafikDonemi === "bugun";
    const dar = darEkran();
    const kutu = $("grafik");
    const etiketler = $("grafik-etiketleri");
    const sinif = bugun ? "saatlik" : "gunluk";
    kutu.className = "grafik " + sinif;
    etiketler.className = "grafik-etiketleri " + sinif;
    temizle(kutu);
    temizle(etiketler);
    const degerler = bugun ? rapor.saatlik : rapor.gunluk;
    const enCok = Math.max(...degerler);
    const simdikiSaat =
      Number(
        new Date(simdiMs()).toLocaleString("en-GB", { hour: "2-digit", hour12: false, timeZone: SAAT_DILIMI })
      ) % 24;
    const simdi = bugun ? simdikiSaat : degerler.length - 1;
    degerler.forEach(function (n, i) {
      const sutun = el("div", "sutun-cubuk" + (n > 0 ? " dolu" : "") + (i === simdi ? " simdi" : ""));
      let etiket = "";
      if (bugun) {
        sutun.title = String(i).padStart(2, "0") + ":00 · " + n + " ihlal";
        if (i % 6 === 0) etiket = dar ? String(i) : String(i).padStart(2, "0");
      } else {
        const gun = new Date(simdiMs() - (degerler.length - 1 - i) * 86400000);
        sutun.title =
          gun.toLocaleDateString("tr-TR", { day: "numeric", month: "long", weekday: "long", timeZone: SAAT_DILIMI }) +
          " · " + n + " ihlal";
        if (!dar || (degerler.length - 1 - i) % 2 === 0) {
          etiket = gun.toLocaleDateString("tr-TR", { day: "numeric", timeZone: SAAT_DILIMI });
        }
      }
      const dolgu = el("div", "dolgu");
      // CSP satır içi stile izin vermez; yükseklik CSSOM ile verilir. Boş
      // sütun da ince bir iz bırakır: grafik dönemin tamamını gösterir.
      dolgu.style.height = enCok && n ? Math.max(6, Math.round((n / enCok) * 100)) + "%" : "3px";
      sutun.appendChild(dolgu);
      kutu.appendChild(sutun);
      etiketler.appendChild(el("span", i === simdi ? "simdi" : "", etiket));
    });
    let ozet;
    if (bugun) {
      const toplam = toplamAl(degerler);
      ozet = "Bugün henüz ihlal yok";
      if (toplam) {
        const tepe = degerler.indexOf(enCok);
        ozet = "Bugün " + sayiMetni(toplam) + " · en yoğun saat " + String(tepe).padStart(2, "0") + ":00 (" + enCok + ")";
      }
    } else {
      const bu = toplamAl(degerler.slice(7));
      const gecen = toplamAl(degerler.slice(0, 7));
      ozet =
        "Son 7 gün " + sayiMetni(bu) + ", önceki 7 gün " + sayiMetni(gecen) + " · günde ortalama " + ondalik(bu / 7);
    }
    $("grafik-ozet").textContent = ozet;
    kutu.setAttribute("aria-label", (bugun ? "Bugün saat saat ihlal. " : "Son 14 gün günlük ihlal. ") + ozet);
  }

  function olayDurumBilgisi(o) {
    if (OLAY_DURUMU[o.durum]) return OLAY_DURUMU[o.durum];
    return o.durum_adi ? [buyukBasla(o.durum_adi), ""] : null;
  }

  function olaySimgesi(o) {
    if (o.tur === "sistem") return ["i-sistem", "mavi"];
    return [o.onem === "critical" ? "i-siren" : "i-uyari", ONEM_KUTUSU[o.onem] || ""];
  }

  function genelOlaylariCiz(rapor) {
    const liste = $("genel-olaylar");
    temizle(liste);
    if (!rapor.son_olaylar.length) liste.appendChild(el("li", "bos-satir", "Henüz olay yok"));
    for (const o of rapor.son_olaylar.slice(0, GENEL_OLAY_SAYISI)) {
      const satir = el("li");
      const [ikon, ton] = olaySimgesi(o);
      satir.appendChild(ikonKutu(ikon, ton));
      const govde = el("div", "satir-govde");
      govde.appendChild(el("b", "", o.baslik));
      govde.appendChild(el("span", "kisa", o.yer || "Sistem"));
      satir.appendChild(govde);
      const sag = el("div", "satir-sag");
      sag.appendChild(zamanOgesi(o.zaman));
      const durum = o.tur === "sistem" ? ["Sistem", "bilgi"] : olayDurumBilgisi(o);
      if (durum) sag.appendChild(rozet(durum[0], durum[1]));
      satir.appendChild(sag);
      liste.appendChild(satir);
    }
  }

  function genelKameralariCiz(rapor) {
    const kameralar = rapor.kameralar;
    const serit = $("kamera-seridi");
    temizle(serit);
    const SERIT = { online: "", connecting: "baglaniyor", offline: "kopuk", pasif: "pasif" };
    for (const k of kameralar) {
      const parca = el("span", SERIT[k.durum] === undefined ? "kopuk" : SERIT[k.durum]);
      parca.title = k.ad + " · " + (KAMERA_DURUMLARI[k.durum] || KAMERA_DURUMLARI.offline)[0];
      serit.appendChild(parca);
    }
    serit.hidden = !kameralar.length;
    const s = rapor.sayilar;
    serit.setAttribute("aria-label", s.kamera_toplam + " kameradan " + s.kamera_canli + " tanesi canlı");
    const ozet = $("kamera-ozeti");
    temizle(ozet);
    if (kameralar.length) {
      ozet.appendChild(el("b", "", s.kamera_canli + " / " + s.kamera_toplam));
      ozet.appendChild(document.createTextNode(" kamera canlı"));
    }
    const liste = $("genel-kameralar");
    temizle(liste);
    const sorunlu = kameralar.filter((k) => k.durum !== "online" && k.durum !== "pasif");
    if (!kameralar.length) liste.appendChild(el("li", "bos-satir", "Henüz kamera eklenmedi"));
    else if (!sorunlu.length) liste.appendChild(el("li", "bos-satir", "Açık bütün kameralar görüntü veriyor"));
    for (const k of sorunlu) {
      const satir = el("li");
      const govde = el("div", "satir-govde");
      govde.appendChild(el("b", "", k.ad));
      const alt = [k.bolum];
      if (k.son_kare_yasi_sn !== null && k.son_kare_yasi_sn !== undefined) {
        alt.push("son görüntü " + kisaSure(k.son_kare_yasi_sn) + " önce");
      }
      govde.appendChild(el("span", "kucuk", alt.filter(Boolean).join(" · ")));
      satir.appendChild(govde);
      const [ad, sinif] = KAMERA_DURUMLARI[k.durum] || KAMERA_DURUMLARI.offline;
      satir.appendChild(rozet(ad, sinif, true));
      liste.appendChild(satir);
    }
  }

  for (const dugme of document.querySelectorAll("#encok-segmenti button")) {
    dugme.addEventListener("click", function () {
      encokGrubu = this.dataset.encok;
      for (const d of document.querySelectorAll("#encok-segmenti button")) {
        d.setAttribute("aria-pressed", String(d === this));
      }
      if (sonVeri && sonVeri.rapor) encokCiz(sonVeri.rapor);
    });
  }

  /* En çok ihlal: son 7 gün, kamera (yer) ya da tür başına; en büyüğe göre çubuk. */
  function encokCiz(rapor) {
    const yerVar = !!(rapor.yerler && rapor.yerler.length);
    $("encok-segmenti").hidden = !yerVar;
    const grup = yerVar ? encokGrubu : "tur";
    const ogeler = (grup === "yer" ? rapor.yerler : rapor.ogeler).filter((o) => o.sayi > 0).slice(0, 5);
    const liste = $("encok");
    temizle(liste);
    if (!ogeler.length) {
      liste.appendChild(el("li", "bos-satir", "Son 7 günde ihlal yok"));
      return;
    }
    const enCok = Math.max(...ogeler.map((o) => o.sayi));
    for (const o of ogeler) {
      const satir = el("li");
      const ust = el("div", "ust");
      ust.appendChild(el("span", "", o.ad));
      ust.appendChild(el("b", "", sayiMetni(o.sayi)));
      satir.appendChild(ust);
      const iz = el("span", "iz");
      const dolgu = el("i");
      dolgu.style.width = Math.max(3, Math.round((o.sayi / enCok) * 100)) + "%";
      iz.appendChild(dolgu);
      satir.appendChild(iz);
      liste.appendChild(satir);
    }
  }

  // ------------------------------------------------------- anlık görüntü

  function kareIzleniyor() {
    return aktifGorunum === "kameralar" && Date.now() - sonEtkilesim < DINLEME_SURESI_MS;
  }

  function kareAdresi(kimlik, zaman) {
    if (DEMO) return DEMO.kareAdresi(kimlik, zaman);
    return "/api/kare?kamera=" + kimlik + "&z=" + encodeURIComponent(zaman);
  }

  function kareYasi(zaman) {
    return zaman ? Math.max(0, (simdiMs() - Date.parse(zaman)) / 1000) : null;
  }

  function yasMetni(yas) {
    return yas < 3 ? "az önce" : kisaSure(yas) + " önce";
  }

  function kareAltMetni(veri, kimlikli, izleniyor, kareler) {
    if (baglantiDurumu(veri) !== "canli") return "Fabrikadan haber gelmediği için görüntü gelmiyor.";
    if (!kimlikli.length) {
      return (
        "Fabrika programı anlık görüntü göndermiyor. Programın uzak pano bağlantısı " +
        "güncellenince kameraların görüntüsü burada çıkar."
      );
    }
    if (!izleniyor) return "Görüntü beklemede: ekrana 10 dakikadır dokunulmadı.";
    if (!Object.keys(kareler).length) {
      return "Fabrika bir sonraki raporunda (en çok " + veri.rapor.aralik_sn + " saniye) göndermeye başlar.";
    }
    return "Görüntüye dokunun: büyür, kare hızları görünür. Akıcı görüntü için VPN ile fabrika ekranına bağlanın.";
  }

  function kameraAnahtari(k) {
    return k.id ? "id:" + k.id : "ad:" + k.ad;
  }

  /* Kutu kamera anahtarıyla bir kez kurulur ve yerinde güncellenir: resim
     yalnız yeni kare gelince yeniden istenir, eski kare yenisi inene kadar
     ekranda kalır (titremez). */
  function kareKutusu(k) {
    const kutu = { kamera: k, zaman: "" };
    kutu.dugme = el("button", "kare");
    kutu.dugme.type = "button";
    kutu.resim = el("img");
    kutu.resim.alt = "";
    kutu.resim.decoding = "async";
    kutu.resim.hidden = true;
    kutu.resim.addEventListener("load", function () {
      if (kutu.zaman) {
        kutu.resim.hidden = false;
        kutu.bos.hidden = true;
      }
    });
    kutu.resim.addEventListener("error", function () {
      // Kare istekle gösterim arasında silinmiş olabilir: bir sonraki kare bekler
      kutu.zaman = "";
      kutu.resim.hidden = true;
      kutu.bos.hidden = false;
      kutu.bosMetni.textContent = "Görüntü alınamadı";
    });
    kutu.bos = el("span", "kare-bos");
    kutu.bosSimge = simge("i-kamera");
    kutu.bos.appendChild(kutu.bosSimge);
    kutu.bosMetni = el("span");
    kutu.bos.appendChild(kutu.bosMetni);
    kutu.durum = el("span", "kare-durum");
    kutu.durum.appendChild(el("span", "nokta"));
    kutu.durumMetni = el("span");
    kutu.durum.appendChild(kutu.durumMetni);
    kutu.yavas = el("span", "kare-yavas", "Yavaş");
    const alt = el("span", "kare-alti");
    const adlar = el("span");
    kutu.ad = el("b");
    kutu.bolum = el("small");
    adlar.append(kutu.ad, kutu.bolum);
    kutu.yas = el("span", "kare-yasi");
    alt.append(adlar, kutu.yas);
    kutu.dugme.append(kutu.resim, kutu.bos, kutu.durum, kutu.yavas, alt);
    kutu.dugme.addEventListener("click", function () {
      acikKare = kameraAnahtari(kutu.kamera);
      fotoGoster(kutu.zaman ? kutu.resim.src : "", kutu.kamera.ad, kareAciklamasi(kutu), {
        bos: kutu.bosMetni.textContent,
        detay: kareDetayi(kutu.kamera),
      });
    });
    return kutu;
  }

  function kareDetayi(k) {
    const [durumAdi] = KAMERA_DURUMLARI[k.durum] || KAMERA_DURUMLARI.offline;
    const islenen =
      k.islenen_fps === null || k.islenen_fps === undefined
        ? "-"
        : ondalik(k.islenen_fps) + (k.hedef_fps ? " / " + ondalik(k.hedef_fps) : "") + " /sn";
    const okunan = k.okunan_fps === null || k.okunan_fps === undefined ? "-" : ondalik(k.okunan_fps) + " /sn";
    return [
      ["Durum", durumAdi + (k.yavas ? " · yavaş" : "")],
      ["İşlenen kare", islenen],
      ["Okunan kare", okunan],
    ];
  }

  function kareAciklamasi(kutu) {
    const yas = kutu.zaman ? kareYasi(kutu.zaman) : kutu.kamera.son_kare_yasi_sn;
    return [kutu.kamera.bolum, yas === null || yas === undefined ? "" : "görüntü " + yasMetni(yas)]
      .filter(Boolean)
      .join(" · ");
  }

  function kareBosMetni(veri, k, izleniyor) {
    if (baglantiDurumu(veri) !== "canli") return ["Fabrikadan haber yok", "i-kopuk"];
    if (k.durum === "pasif") return ["Kamera pasif", "i-kamera"];
    if (k.durum === "offline") return ["Kameradan görüntü gelmiyor", "i-kopuk"];
    if (k.durum === "connecting") return ["Yeniden bağlanıyor", "i-yenile"];
    if (!k.id) return ["Program görüntü göndermiyor", "i-kamera"];
    if (!izleniyor) return ["Görüntü beklemede", "i-saat"];
    return ["Görüntü bekleniyor", "i-kamera"];
  }

  function kareKutusunuGuncelle(veri, kutu, k, zaman, izleniyor) {
    kutu.kamera = k;
    kutu.ad.textContent = k.ad;
    kutu.bolum.textContent = k.bolum || "";
    const [durumAdi, durumSinifi] = KAMERA_DURUMLARI[k.durum] || KAMERA_DURUMLARI.offline;
    kutu.durum.className = "kare-durum" + (durumSinifi ? " " + durumSinifi : "");
    kutu.durumMetni.textContent = durumAdi;
    if (!zaman) {
      kutu.zaman = "";
      kutu.resim.hidden = true;
      kutu.resim.removeAttribute("src");
    } else if (zaman !== kutu.zaman) {
      kutu.zaman = zaman;
      kutu.resim.src = kareAdresi(k.id, zaman);
      if (acikKare === kameraAnahtari(k) && $("foto-penceresi").open) fotoResmi(kutu.resim.src, "");
    }
    const [bosMetin, bosSimge] = kareBosMetni(veri, k, izleniyor);
    kutu.bos.hidden = !!kutu.zaman && !kutu.resim.hidden;
    kutu.bosMetni.textContent = bosMetin;
    kutu.bosSimge.firstChild.setAttribute("href", "#" + bosSimge);
    kutu.yavas.hidden = !(k.yavas && k.durum === "online");
    const yas = kutu.zaman ? kareYasi(kutu.zaman) : k.durum !== "pasif" ? k.son_kare_yasi_sn : null;
    const bayat = yas !== null && yas !== undefined && yas > KARE_BAYAT_SN;
    kutu.dugme.classList.toggle("bayat", bayat && !!kutu.zaman);
    kutu.yas.textContent = yas === null || yas === undefined ? "" : yasMetni(yas);
    kutu.dugme.setAttribute(
      "aria-label",
      k.ad + ", " + durumAdi + (kutu.zaman ? ", büyütmek için dokunun" : ", " + bosMetin)
    );
    if (acikKare === kameraAnahtari(k) && $("foto-penceresi").open) {
      $("foto-alt").textContent = kareAciklamasi(kutu);
      fotoDetayiCiz(kareDetayi(k));
    }
  }

  function kameraSuz(k) {
    if (kameraSuzgeci === "canli") return k.durum === "online";
    if (kameraSuzgeci === "sorunlu") return k.durum !== "online" && k.durum !== "pasif";
    return true;
  }

  function kameraSuzgeciSec(suzgec) {
    kameraSuzgeci = suzgec;
    for (const cip of document.querySelectorAll("#kamera-cipleri .cip")) {
      cip.setAttribute("aria-pressed", String(cip.dataset.suzgec === suzgec));
    }
    if (sonVeri) kareleriCiz(sonVeri);
  }

  for (const cip of document.querySelectorAll("#kamera-cipleri .cip")) {
    cip.addEventListener("click", function () {
      kameraSuzgeciSec(this.dataset.suzgec);
    });
  }

  function kareleriCiz(veri) {
    const rapor = veri.rapor;
    const kameralar = rapor ? rapor.kameralar : [];
    // Pasif kamera görüntü vermez; kimliği olmayan kamerayı eski program gönderir
    const kimlikli = kameralar.filter((k) => k.id && k.durum !== "pasif");
    const izleniyor = kareIzleniyor();
    // Görüntü yalnız ?kare=1 ile gelen cevapta vardır; öbür cevapta kutular bekler
    const kareler = (izleniyor && veri.kareler) || {};
    $("kare-alt").textContent = rapor
      ? kareAltMetni(veri, kimlikli, izleniyor, kareler)
      : "Fabrikadan ilk rapor gelince kameralar burada görünür.";
    $("kare-surdur").hidden = izleniyor || !kimlikli.length || baglantiDurumu(veri) !== "canli";

    const sayilar = {
      hepsi: kameralar.length,
      canli: kameralar.filter((k) => k.durum === "online").length,
      sorunlu: rapor ? kopukKameraSayisi(rapor) : 0,
    };
    for (const sayac of document.querySelectorAll("[data-cip]")) {
      sayac.textContent = String(sayilar[sayac.dataset.cip]);
    }

    const izgara = $("kare-izgarasi");
    const gorunenler = new Set();
    for (const k of kameralar) {
      const anahtar = kameraAnahtari(k);
      let kutu = kareKutulari.get(anahtar);
      if (!kutu) {
        kutu = kareKutusu(k);
        kareKutulari.set(anahtar, kutu);
      }
      gorunenler.add(anahtar);
      // Rapordaki sırayla dizilir; öğe yerinde kalır, yalnız sırası düzelir
      izgara.appendChild(kutu.dugme);
      kareKutusunuGuncelle(veri, kutu, k, k.id ? kareler[String(k.id)] || "" : "", izleniyor);
      kutu.dugme.hidden = !kameraSuz(k);
    }
    for (const [anahtar, kutu] of kareKutulari) {
      if (!gorunenler.has(anahtar)) {
        kutu.dugme.remove();
        kareKutulari.delete(anahtar);
      }
    }
    const gorunen = kameralar.filter(kameraSuz).length;
    $("kamera-bos").hidden = gorunen > 0;
    $("kamera-bos-baslik").textContent = kameralar.length ? "Bu süzgeçte kamera yok" : "Henüz kamera eklenmedi";
  }

  $("kare-surdur").addEventListener("click", function () {
    sonEtkilesim = Date.now();
    if (sonVeri) kareleriCiz(sonVeri);
    yukle();
  });

  // -------------------------------------------------- fotoğraf penceresi

  function fotoResmi(adres, bos) {
    const resim = $("foto-buyuk");
    if (adres) resim.src = adres;
    else resim.removeAttribute("src");
    resim.hidden = !adres;
    $("foto-bos").textContent = bos || "";
    $("foto-bos").hidden = !!adres;
  }

  function fotoDetayiCiz(detay) {
    const liste = $("foto-detay");
    temizle(liste);
    for (const [ad, deger] of detay || []) {
      const satir = el("div");
      satir.appendChild(el("dt", "", ad));
      satir.appendChild(el("dd", "", deger));
      liste.appendChild(satir);
    }
    liste.hidden = !(detay && detay.length);
  }

  function fotoGoster(adres, baslik, aciklama, ek) {
    fotoResmi(adres, ek && ek.bos);
    $("foto-buyuk").alt = baslik;
    $("foto-baslik").textContent = baslik;
    $("foto-alt").textContent = aciklama;
    fotoDetayiCiz(ek && ek.detay);
    const pencere = $("foto-penceresi");
    if (!pencere.open) pencere.showModal();
  }

  $("foto-kapat").addEventListener("click", function () {
    $("foto-penceresi").close();
  });
  // Karartılmış zemine dokununca kapanır (pencerenin içi tamamen dolu)
  $("foto-penceresi").addEventListener("click", function (olay) {
    if (olay.target === this) this.close();
  });
  $("foto-penceresi").addEventListener("close", function () {
    acikKare = null;
    $("foto-buyuk").removeAttribute("src");
  });

  // -------------------------------------------------------------- olaylar

  function olaySuzgeciSec(tur, bekleyen) {
    olayTuru = tur;
    yalnizBekleyen = bekleyen;
    for (const d of document.querySelectorAll("#olay-segmenti button")) {
      d.setAttribute("aria-pressed", String(d.dataset.tur === tur));
    }
    $("bekleyen-cipi").setAttribute("aria-pressed", String(bekleyen));
    if (sonVeri && sonVeri.rapor) olaylariCiz(sonVeri.rapor);
  }

  for (const dugme of document.querySelectorAll("#olay-segmenti button")) {
    dugme.addEventListener("click", function () {
      olaySuzgeciSec(this.dataset.tur, yalnizBekleyen);
    });
  }
  $("bekleyen-cipi").addEventListener("click", function () {
    olaySuzgeciSec(olayTuru, !yalnizBekleyen);
  });

  function olayAciklamasi(o) {
    return [o.yer, tarihSaatMetni(o.zaman)].filter(Boolean).join(" · ");
  }

  function fotoAc(o) {
    acikKare = null;
    fotoGoster(DEMO ? DEMO.fotoAdresi(o.id) : "/api/foto?olay=" + o.id, o.baslik, olayAciklamasi(o));
  }

  function olaySatiri(o) {
    const satir = el("li", "olay-satiri");
    const sistem = o.tur === "sistem";
    const [ikon, ton] = olaySimgesi(o);
    satir.appendChild(ikonKutu(ikon, ton));

    const govde = el("div", "olay-govde");
    const ust = el("div", "olay-ust");
    ust.appendChild(el("b", "", o.baslik));
    if (!sistem && o.onem_adi) ust.appendChild(rozet(o.onem_adi, ONEM_ROZETI[o.onem] || ""));
    if (o.suruyor && o.durum === "new") {
      ust.appendChild(rozet("Sürüyor" + (o.sure ? " · " + o.sure : ""), "uyari", true, true));
    }
    govde.appendChild(ust);
    govde.appendChild(el("span", "", o.yer || "Sistem"));
    if (o.ayrinti) govde.appendChild(el("span", "", o.ayrinti));
    satir.appendChild(govde);

    const sag = el("div", "olay-sag");
    sag.appendChild(zamanOgesi(o.zaman, true));
    const durum = sistem ? null : olayDurumBilgisi(o);
    if (durum) sag.appendChild(rozet(durum[0], durum[1]));
    const fotoVar = o.foto && o.id;
    if (fotoVar) sag.appendChild(fotoKucuk(o));
    satir.appendChild(sag);

    // Telefonda fotoğraf düğmesi ve inceleme düğmeleri satırın altında, tam genişlikte
    const alti = el("div", "olay-alti");
    if (fotoVar && !fotoHatasiTaze(o.id)) {
      const dugme = el("button", "foto-dugmesi yalniz-mobil");
      dugme.type = "button";
      dugme.appendChild(simge("i-foto"));
      dugme.appendChild(document.createTextNode("Kanıt fotoğrafı"));
      dugme.addEventListener("click", function () {
        fotoAc(o);
      });
      alti.appendChild(dugme);
    }
    if (inceleGosterilsin(o)) alti.appendChild(inceleKontrolu(o));
    satir.appendChild(alti);
    return satir;
  }

  function fotoHatasiTaze(kimlik) {
    const hata = fotoHatalari.get(kimlik);
    return !!hata && Date.now() - hata < FOTO_YENIDEN_MS;
  }

  /* Kanıt fotoğrafının küçüğü; dokununca büyür. Liste her tazelemede yeniden
     kurulur ama küçük fotoğraf aynı öğedir (yeni satıra taşınır): resim
     yeniden inmez, ekran titremez. Gelmeyen fotoğraf FOTO_YENIDEN_MS
     geçmeden yeniden istenmez. */
  function fotoKucuk(o) {
    const hazir = fotoKucukleri.get(o.id);
    if (hazir) return hazir;
    if (fotoHatasiTaze(o.id)) return el("span", "foto-yok", "Fotoğraf alınamadı");
    const adres = DEMO ? DEMO.fotoAdresi(o.id) : "/api/foto?olay=" + o.id;
    const dugme = el("button", "olay-foto");
    dugme.type = "button";
    dugme.setAttribute("aria-label", "Kanıt fotoğrafını büyüt: " + o.baslik);
    const resim = el("img");
    resim.alt = "";
    resim.width = 160;
    resim.height = 90;
    resim.loading = "lazy";
    resim.addEventListener("error", function () {
      fotoHatalari.set(o.id, Date.now());
      fotoKucukleri.delete(o.id);
      dugme.replaceWith(el("span", "foto-yok", "Fotoğraf alınamadı"));
    });
    resim.src = adres;
    dugme.appendChild(resim);
    dugme.addEventListener("click", function () {
      fotoAc(o);
    });
    fotoKucukleri.set(o.id, dugme);
    return dugme;
  }

  /* İnceleme düğmeleri yalnız son raporda durumu "new" olan ihlal satırında,
     yalnız operatör/yönetici hesaplarında ve bağlantı canlıyken çıkar
     (docs/19 §3.5, §3.9). */
  function inceleGosterilsin(o) {
    return o.tur === "ihlal" && o.id && o.durum === "new" && operatorMu() && canliMi();
  }

  /* Gönderilen işaretin durumu ve çift dokunuş hali tazelemede silinmesin diye
     denetim öğesi fotoKucukleri gibi önbelleğe alınır (olaylariCiz yeniden kurar). */
  function inceleKontrolu(o) {
    const anahtar = String(o.id);
    const gonderim = inceleDurum.get(anahtar);
    if (gonderim !== undefined && simdiMs() - gonderim > INCELE_BEKLEME_MS) {
      inceleDurum.delete(anahtar);
      inceleGecti.add(anahtar); // sonuç gelmedi: düğmeler geri gelir
      inceleKutulari.delete(anahtar);
    }
    let kutu = inceleKutulari.get(anahtar);
    if (kutu) return kutu;
    kutu = inceleKutusuKur(o);
    inceleKutulari.set(anahtar, kutu);
    return kutu;
  }

  function inceleKutusuKur(o) {
    const anahtar = String(o.id);
    if (inceleDurum.has(anahtar)) {
      const kutu = el("span", "incele-durum");
      kutu.setAttribute("role", "status");
      kutu.appendChild(simge("i-tamam"));
      kutu.appendChild(el("span", "", "Fabrikaya gönderildi"));
      return kutu;
    }
    const kutu = el("div", "incele-kutusu");
    if (inceleGecti.has(anahtar)) {
      kutu.appendChild(el("p", "incele-not", "Sonuç gelmedi; Müdahale ekranındaki son müdahalelere bakın."));
    }
    const satir = el("div", "incele-satiri");
    satir.appendChild(inceleDugmesi(o, "reviewed", "İncelendi", "i-onay", kutu));
    satir.appendChild(inceleDugmesi(o, "false_alarm", "Yanlış alarm", "i-kapat", kutu));
    kutu.appendChild(satir);
    kutu.appendChild(el("p", "hata incele-hatasi"));
    return kutu;
  }

  /* Çift dokunuş: ilk dokunuş sorar, ikincisi gönderir (cepte yanlış işaret
     olmasın). Soru 4 saniye sonra kendiliğinden kalkar. */
  function inceleDugmesi(o, karar, etiket, ikon, kutu) {
    const dugme = el("button", "dugme ikincil");
    dugme.type = "button";
    dugme.appendChild(simge(ikon));
    dugme.appendChild(el("span", "", etiket));
    dugme.addEventListener("click", function () {
      if (ciftDokunus(dugme, "Emin misiniz?", kutu)) inceleGonder(o, karar, dugme);
    });
    return dugme;
  }

  async function inceleGonder(o, karar, dugme) {
    const kutu = dugme.closest(".incele-kutusu");
    const hata = kutu.querySelector(".incele-hatasi");
    if (hata) hata.textContent = "";
    for (const d of kutu.querySelectorAll("button")) d.disabled = true;
    try {
      await mudahaleGonder({ tur: "olay_incele", olay_id: o.id, karar: karar });
      inceleDurum.set(String(o.id), simdiMs());
      inceleGecti.delete(String(o.id));
      inceleKutulari.delete(String(o.id));
      if (sonVeri && sonVeri.rapor) olaylariCiz(sonVeri.rapor);
      setTimeout(yukle, 1500);
    } catch (e) {
      for (const d of kutu.querySelectorAll("button")) d.disabled = false;
      if (hata) hata.textContent = e.message;
    }
  }

  function olayGunu(o) {
    if (!o.zaman) return "Tarihsiz";
    const gun = gunEtiketi(o.zaman);
    if (!gun) return "Bugün";
    return gun === "dün" ? "Dün" : gunMetni(o.zaman);
  }

  function olaylariCiz(rapor) {
    genelOlaylariCiz(rapor);
    const bekleyen = bekleyenOlaylar(rapor).length;
    $("bekleyen-sayisi").textContent = String(bekleyen);
    const kap = $("olay-gruplari");
    temizle(kap);
    const gorunen = rapor.son_olaylar.filter(
      (o) =>
        (olayTuru === "hepsi" || o.tur === olayTuru) &&
        (!yalnizBekleyen || (o.tur === "ihlal" && o.durum === "new"))
    );
    // Olaylar güne göre gruplanır: Bugün, Dün, 21.10.2026 ...
    const gruplar = [];
    for (const o of gorunen) {
      const gun = olayGunu(o);
      let grup = gruplar[gruplar.length - 1];
      if (!grup || grup.gun !== gun) {
        grup = { gun: gun, olaylar: [] };
        gruplar.push(grup);
      }
      grup.olaylar.push(o);
    }
    for (const grup of gruplar) {
      const bolum = el("section", "olay-grubu");
      bolum.setAttribute("aria-label", grup.gun);
      bolum.appendChild(el("h2", "", grup.gun + " · " + grup.olaylar.length + " olay"));
      const liste = el("ul");
      for (const o of grup.olaylar) liste.appendChild(olaySatiri(o));
      bolum.appendChild(liste);
      kap.appendChild(bolum);
    }
    $("olay-bos").hidden = gorunen.length > 0;
    $("olay-bos-baslik").textContent = yalnizBekleyen ? "İnceleme bekleyen ihlal yok" : "Bu türde olay yok";
    $("olay-bos-metni").textContent = yalnizBekleyen ? "Hepsi işaretlendi." : "Son 20 olayın içinde.";
    // Listeden düşen ya da artık "new" olmayan olayın önbelleği unutulur
    for (const [anahtar, dugme] of fotoKucukleri) {
      if (!dugme.isConnected) fotoKucukleri.delete(anahtar);
    }
    for (const [anahtar, kutu] of inceleKutulari) {
      if (!kutu.isConnected) inceleKutulari.delete(anahtar);
    }
  }

  // ------------------------------------------------------- bilgisayar

  function bilgisayariCiz(rapor) {
    const b = rapor && rapor.bilgisayar;
    $("bilgisayar-yok").hidden = !!b;
    $("bilgisayar-ac").hidden = !b;
    if (!b) $("bilgisayar-bilgisi").hidden = true;
    $("bilgisayar-alt").textContent = b
      ? [b.ad, b.bilgisayar_adi, b.isletim_sistemi].filter(Boolean).join(" · ")
      : "Programın çalıştığı makine";
    const liste = $("bilgisayar-bilgisi");
    temizle(liste);
    if (!b) return;
    const bos = rapor.sistem.bos_disk_gb;
    const satirlar = [
      ["IP adresi", (b.ip || []).join(", ")],
      ["İşlemci", b.islemci + (b.islemci && b.cekirdek ? " · " + b.cekirdek + " çekirdek" : "")],
      ["Bellek", b.bellek_gb ? ondalik(b.bellek_gb) + " GB" : ""],
      ["Ekran kartı", b.ekran_karti],
      ["Tespit", b.cikarim],
      [
        "Disk",
        b.disk_toplam_gb
          ? (bos !== null ? ondalik(bos) + " GB boş / " : "") + ondalik(b.disk_toplam_gb) + " GB"
          : "",
      ],
      [
        "Kurulum",
        [b.kurulum_turu, b.kurulum_tarihi ? gunMetni(b.kurulum_tarihi) : ""].filter(Boolean).join(" · "),
      ],
      ["Açık", b.acilis ? sureDir((simdiMs() - Date.parse(b.acilis)) / 1000) : ""],
    ];
    for (const [ad, deger] of satirlar) {
      if (!deger) continue;
      const satir = el("div");
      satir.appendChild(el("dt", "", ad));
      satir.appendChild(el("dd", "", deger));
      liste.appendChild(satir);
    }
  }

  $("bilgisayar-ac").addEventListener("click", function () {
    const acik = this.getAttribute("aria-expanded") !== "true";
    this.setAttribute("aria-expanded", String(acik));
    $("bilgisayar-ac-metni").textContent = acik ? "Gizle" : "Ayrıntılar";
    $("bilgisayar-bilgisi").hidden = !acik;
  });

  // ------------------------------------------------------------- müdahale

  function dinleniyor() {
    return aktifGorunum === "mudahale" && Date.now() - sonEtkilesim < DINLEME_SURESI_MS;
  }

  /* Müdahalenin şu an yapılıp yapılamayacağı ve neden. `kisa` kartın
     başlığındaki hapta, `alt` (varsa) hapın altındaki satırda yazılır. */
  function mudahaleHali(veri) {
    const rapor = veri.rapor;
    const m = rapor && rapor.mudahale;
    if (!rapor || baglantiDurumu(veri) !== "canli") {
      // Neden ekranın üstündeki uyarıda yazar; burada tekrar edilmez
      return { acik: false, sinif: "tehlike", kisa: "Bağlantı yok", alt: "" };
    }
    if (!m || !m.acik) {
      return {
        acik: false,
        sinif: "",
        kisa: "Müdahale kapalı",
        alt:
          "Fabrikadaki bilgisayarda Ayarlar → Uzak izleme panosu → Uzaktan müdahale'yi " +
          "\"Açık\" yapıp sistemi yeniden başlatın. Kapalıyken pano yalnız izler.",
      };
    }
    if (rapor.sistem.analiz === false) {
      return {
        acik: false,
        sinif: "uyari",
        kisa: "Analiz çalışmıyor",
        alt: "Anons ve deneme sesi analizin kuyruğundan çalar; önce fabrikada sistemi başlatın.",
      };
    }
    if (!m.kanallar.length) {
      return {
        acik: false,
        sinif: "uyari",
        kisa: "Ses kanalı yok",
        alt: "Fabrikada Anons ekranında açık bir hoparlör kanalı olmadan anons çalınamaz.",
      };
    }
    if (!dinleniyor()) {
      return {
        acik: true,
        bekliyor: true,
        sinif: "",
        kisa: "Dinleme beklemede",
        alt: "Ekrana 10 dakikadır dokunulmadı. Fabrikanın komutları sık sorması için sürdürün.",
      };
    }
    const yas = veri.mudahale ? veri.mudahale.yoklama_yasi_sn : null;
    if (yas !== null && yas !== undefined && yas <= DINLIYOR_SN) {
      return { acik: true, sinif: "basari", kisa: "Fabrika dinliyor", alt: "" };
    }
    return {
      acik: true,
      sinif: "uyari",
      kisa: "Birazdan dinler",
      alt:
        "Bu ekran açıkken fabrika bir sonraki raporunda (en çok " + rapor.aralik_sn +
        " saniye) sık sormaya başlar. Komutu şimdi gönderebilirsiniz; sırada bekler.",
    };
  }

  /* "Nerede çalsın" çipleri: Tüm fabrika (fabrikada bölümsüz bir kanal varsa)
     ve bölümü olan her kanal. */
  function kanalCipleri(kanallar) {
    const cipler = [];
    if (kanallar.some((k) => !k.bolum)) cipler.push({ deger: "", ad: "Tüm fabrika" });
    const bolumler = kanallar.filter((k) => k.bolum).map((k) => k.bolum);
    for (const k of kanallar) {
      if (!k.bolum) continue;
      // Aynı bölümde iki kanal varsa kanalın adı yazılır
      const ad = bolumler.filter((b) => b === k.bolum).length > 1 ? k.ad : k.bolum;
      cipler.push({ deger: String(k.id), ad: ad, kanal: k });
    }
    return cipler;
  }

  function kanalCipiniSec(deger) {
    seciliKanal = deger;
    for (const cip of document.querySelectorAll("#kanal-cipleri .cip")) {
      cip.setAttribute("aria-pressed", String(cip.dataset.kanal === deger));
    }
    anonsOnayiniKapat();
  }

  function secenekleriCiz(m) {
    const mesajlar = (m && m.mesajlar) || [];
    const kanallar = (m && m.kanallar) || [];
    // Liste değişmediyse yeniden kurulmaz: seçim ve odak kaybolmasın
    const imza = JSON.stringify([mesajlar, kanallar]);
    if (imza === mudahaleImzasi) return;
    mudahaleImzasi = imza;

    const kutu = $("mesaj-secenekleri");
    temizle(kutu);
    if (!mesajlar.some((ms) => ms.id === seciliMesaj)) seciliMesaj = null;
    if (!mesajlar.length) {
      kutu.appendChild(el("p", "ikincil-metin", "Fabrikada açık bir anons mesajı yok."));
    }
    for (const ms of mesajlar) {
      const secim = el("label", "secim");
      const girdi = el("input");
      girdi.type = "radio";
      girdi.name = "mesaj";
      girdi.value = String(ms.id);
      girdi.checked = ms.id === seciliMesaj;
      girdi.addEventListener("change", function () {
        seciliMesaj = ms.id;
        $("anons-hatasi").textContent = "";
        anonsOnayiniKapat();
      });
      secim.appendChild(girdi);
      secim.appendChild(el("span", "", ms.metin));
      kutu.appendChild(secim);
    }

    const cipKutusu = $("kanal-cipleri");
    temizle(cipKutusu);
    const cipler = kanalCipleri(kanallar);
    if (!cipler.some((c) => c.deger === seciliKanal)) seciliKanal = cipler.length ? cipler[0].deger : null;
    for (const c of cipler) {
      const cip = el("button", "cip", c.ad);
      cip.type = "button";
      cip.dataset.kanal = c.deger;
      cip.setAttribute("aria-pressed", String(c.deger === seciliKanal));
      if (c.kanal) cip.title = c.kanal.ad;
      cip.addEventListener("click", function () {
        kanalCipiniSec(c.deger);
      });
      cipKutusu.appendChild(cip);
    }

    const liste = $("kanal-listesi");
    temizle(liste);
    if (!kanallar.length) liste.appendChild(el("li", "bos-satir", "Açık ses kanalı yok; fabrikada Anons ekranından eklenir"));
    for (const k of kanallar) {
      const satir = el("li");
      satir.appendChild(ikonKutu("i-hoparlor", "koyu"));
      const govde = el("div", "satir-govde");
      govde.appendChild(el("b", "ince", k.ad));
      govde.appendChild(el("span", "kucuk", k.bolum || "Bütün bölümler"));
      satir.appendChild(govde);
      const kap = el("div", "deneme-kutusu");
      const dugme = el("button", "dugme ikincil");
      dugme.type = "button";
      dugme.appendChild(el("span", "", "Dene"));
      dugme.dataset.kanal = String(k.id);
      dugme.addEventListener("click", denemeTiklandi);
      kap.appendChild(dugme);
      satir.appendChild(kap);
      liste.appendChild(satir);
    }
  }

  /* Komutun ekranda görünen durum etiketi ve rozet sınıfı (docs/19 §3.6, O10):
     iletildi ve suruyor türe göre adlandırılır. */
  function komutDurumBilgisi(k) {
    const d = k.durum;
    if (d === "bekliyor") return ["Sırada", "uyari"];
    if (d === "iletildi") return [ILETILDI_ETIKETI[k.tur] || "Fabrikada", "bilgi"];
    if (d === "suruyor") return [SURUYOR_ETIKETI[k.tur] || "Sürüyor", "bilgi"];
    if (d === "yapildi") return ["Yapıldı", "basari"];
    if (d === "suresi_doldu") return ["Süresi doldu", ""];
    if (d === "sonuc_yok") return ["Sonuç gelmedi", "uyari"];
    return ["Yapılamadı", "tehlike"];
  }

  function komutSuruyor(k) {
    return k.durum === "bekliyor" || k.durum === "iletildi" || k.durum === "suruyor";
  }

  /* Müdahale ve Yönetim geçmişinin satırı; yönetimde kim yaptı ve teşhis
     metni de yazılır. */
  function komutSatiri(k, yonetim) {
    const satir = el("li", yonetim ? "alt-alta" : "");
    const ust = yonetim ? el("div", "satir-ust") : satir;
    const [etiket, sinif] = komutDurumBilgisi(k);
    ust.appendChild(ikonKutu(KOMUT_IKONU[k.tur] || "i-anons", SINIF_TONU[sinif] || ""));
    const govde = el("div", "satir-govde");
    govde.appendChild(el("b", "", k.ozet));
    const alt = [];
    if (yonetim && k.kim && k.kim.ad) {
      alt.push(k.kim.ad);
    }
    if (k.mesaj) alt.push(k.mesaj);
    if (alt.length) govde.appendChild(el("span", "kucuk", alt.join(" · ")));
    ust.appendChild(govde);
    const sag = el("div", "satir-sag");
    sag.appendChild(zamanOgesi(k.olusturuldu));
    sag.appendChild(rozet(etiket, sinif, true, komutSuruyor(k)));
    ust.appendChild(sag);
    if (yonetim) {
      satir.appendChild(ust);
      if (k.ek) {
        const det = el("details", "teshis-ek");
        det.appendChild(el("summary", "", "Teşhis metnini göster"));
        const pre = el("pre", "teshis-metni");
        pre.textContent = k.ek; // fabrikadan gelen metin: yalnız textContent
        det.appendChild(pre);
        satir.appendChild(det);
      }
    }
    return satir;
  }

  /* Gönderilip henüz sunucudan okunmayan komutları da gösterir ve bekleyen
     listesini sunucu kimliği görünce temizler (iki ekran da buradan okur). */
  function birlesikKomutlar(veri, turler) {
    const sunucudan = (veri.mudahale && veri.mudahale.komutlar) || [];
    const bilinen = new Set(sunucudan.map((k) => k.id));
    bekleyenKomutlar = bekleyenKomutlar.filter((k) => !bilinen.has(k.id));
    return [...bekleyenKomutlar, ...sunucudan].filter((k) => turler.includes(k.tur));
  }

  function komutlariCiz(veri) {
    const komutlar = birlesikKomutlar(veri, MUDAHALE_TURLERI);
    const liste = $("komut-listesi");
    temizle(liste);
    if (!komutlar.length) liste.appendChild(el("li", "bos-satir", "Henüz müdahale yok; gönderdiğiniz anons burada görünür"));
    for (const k of komutlar.slice(0, MUDAHALE_LISTE_SAYISI)) liste.appendChild(komutSatiri(k, false));
  }

  function mudahaleyiCiz(veri) {
    const hal = mudahaleHali(veri);
    hapCiz("dinleme-hapi", "dinleme-metni", hal.sinif, hal.kisa);
    $("mudahale-alt").textContent = hal.alt;
    $("mudahale-durumu").hidden = !hal.alt;
    $("dinlemeyi-surdur").hidden = !hal.bekliyor;
    secenekleriCiz(veri.rapor && veri.rapor.mudahale);
    const kilitli = !hal.acik;
    for (const oge of document.querySelectorAll(
      "#anons-formu input, #anons-formu button, #kanal-listesi button"
    )) {
      oge.disabled = kilitli;
    }
    if (kilitli) anonsOnayiniKapat();
    komutlariCiz(veri);
  }

  function anonsOnayiniKapat() {
    $("anons-onayi").hidden = true;
    $("anons-alt").hidden = false;
  }

  async function mudahaleGonder(istek) {
    const yanit = await fetch("/api/mudahale", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(istek),
    });
    const veri = await yanit.json().catch(() => ({}));
    if (yanit.status === 401) {
      oturumuKapat();
      throw new Error("Oturumun süresi doldu; yeniden giriş yapın.");
    }
    if (!yanit.ok) throw new Error(veri.mesaj || "Gönderilemedi (HTTP " + yanit.status + ").");
    bekleyenKomutlar.unshift(veri.komut);
    bildirimEkle(veri.komut.id);
    if (sonVeri) {
      komutlariCiz(sonVeri);
      yonetimKomutlariCiz(sonVeri);
    }
    duyur("Komut gönderildi: " + veri.komut.ozet);
    return veri.komut;
  }

  function anonsYeri() {
    if (seciliKanal === "" || seciliKanal === null) return "bütün fabrikada";
    const cip = document.querySelector('#kanal-cipleri .cip[data-kanal="' + seciliKanal + '"]');
    return (cip ? cip.textContent.toLocaleLowerCase("tr-TR") : "seçilen") + " hoparlöründen";
  }

  $("anons-dugmesi").addEventListener("click", function () {
    $("anons-hatasi").textContent = "";
    const mesajlar = (sonVeri && sonVeri.rapor && sonVeri.rapor.mudahale.mesajlar) || [];
    const mesaj = mesajlar.find((m) => m.id === seciliMesaj);
    if (!mesaj) {
      $("anons-hatasi").textContent = "Önce çalınacak mesajı seçin.";
      return;
    }
    if (seciliKanal === null) {
      $("anons-hatasi").textContent = "Nerede çalacağını seçin.";
      return;
    }
    $("anons-onay-metni").textContent = "“" + mesaj.metin + "” " + anonsYeri() + " çalınsın mı?";
    $("anons-onayi").hidden = false;
    $("anons-alt").hidden = true;
    $("anons-gonder").focus();
  });

  $("anons-vazgec").addEventListener("click", function () {
    anonsOnayiniKapat();
    $("anons-dugmesi").focus();
  });

  $("anons-formu").addEventListener("submit", async function (olay) {
    olay.preventDefault();
    if ($("anons-onayi").hidden) return; // Enter ile onaysız gönderilmez
    const dugme = $("anons-gonder");
    dugme.disabled = true;
    try {
      const kanal = seciliKanal;
      await mudahaleGonder({ tur: "anons", mesaj_id: seciliMesaj, kanal_id: kanal === "" ? null : Number(kanal) });
      anonsOnayiniKapat();
      setTimeout(yukle, 1500);
    } catch (hata) {
      anonsOnayiniKapat();
      $("anons-hatasi").textContent = hata.message;
    } finally {
      dugme.disabled = false;
    }
  });

  /* Deneme iki dokunuşla gider: ilki sorar, ikincisi gönderir (cepte yanlışlıkla
     dokunulup fabrikada ses çıkmasın). Soru 4 saniye sonra kendiliğinden kalkar. */
  async function denemeTiklandi() {
    const dugme = this;
    $("deneme-hatasi").textContent = "";
    if (!ciftDokunus(dugme, "Çalınsın mı?")) return;
    dugme.disabled = true;
    try {
      await mudahaleGonder({ tur: "ses_dene", kanal_id: Number(dugme.dataset.kanal) });
      setTimeout(yukle, 1500);
    } catch (hata) {
      $("deneme-hatasi").textContent = hata.message;
    } finally {
      dugme.disabled = false;
    }
  }

  $("dinlemeyi-surdur").addEventListener("click", function () {
    sonEtkilesim = Date.now();
    if (sonVeri) mudahaleyiCiz(sonVeri);
    yukle();
  });

  for (const tur of ["pointerdown", "keydown"]) {
    document.addEventListener(tur, function () {
      const bekliyordu = !dinleniyor() && !yonetimDinliyor() && !kareIzleniyor();
      sonEtkilesim = Date.now();
      // Bekleyen Müdahale, Yönetim ya da Kameralar ekranı dokununca hemen canlanır
      if (bekliyordu && (dinleniyor() || yonetimDinliyor() || kareIzleniyor()) && $("giris").hidden) {
        yukle();
      }
    });
  }

  // ---------------------------------------------------------- bildirimler

  function bildirimEkle(kimlik) {
    if (bildirimler.some((b) => b.id === kimlik)) return;
    bildirimler.push({ id: kimlik, bitti: 0, uzerinde: false });
    bildirimleriCiz();
  }

  function bildirimKapat(kimlik) {
    const sira = bildirimler.findIndex((b) => b.id === kimlik);
    if (sira >= 0) bildirimler.splice(sira, 1);
    bildirimleriCiz();
  }

  function tumKomutlar() {
    if (!sonVeri) return bekleyenKomutlar;
    return birlesikKomutlar(sonVeri, MUDAHALE_TURLERI.concat(YONETIM_TURLERI));
  }

  /* Komut bildirimi: simge (sürerken döner), "Anons · Tüm fabrika · Çalınıyor",
     mesaj ve üç adımlı ilerleme çizgisi. Biten komut 6 sn sonra kapanır;
     yapılamayan komut kullanıcı kapatana kadar kalır. */
  function bildirimleriCiz() {
    const komutlar = tumKomutlar();
    const simdi = Date.now();
    for (let i = bildirimler.length - 1; i >= 0; i--) {
      const b = bildirimler[i];
      const k = komutlar.find((x) => x.id === b.id);
      if (!k) continue;
      if (!komutSuruyor(k) && !b.bitti) b.bitti = simdi;
      const hatali = k.durum === "hata" || k.durum === "sonuc_yok";
      if (b.bitti && !hatali && !b.uzerinde && simdi - b.bitti > BILDIRIM_KAPANIS_MS) bildirimler.splice(i, 1);
    }
    const gorunen = bildirimler.slice(darEkran() ? -1 : -2);
    const fazla = bildirimler.length - gorunen.length;
    $("bildirim-fazla").hidden = fazla <= 0;
    $("bildirim-fazla").textContent = "+" + fazla + " komut daha";
    const liste = $("bildirim-listesi");
    temizle(liste);
    for (const b of gorunen) {
      const k = komutlar.find((x) => x.id === b.id);
      if (!k) continue;
      liste.appendChild(bildirimKarti(k, b));
    }
  }

  function bildirimKarti(k, b) {
    const [etiket, sinif] = komutDurumBilgisi(k);
    const suruyor = komutSuruyor(k);
    const kart = el("div", "bildirim");
    kart.setAttribute("role", "status");
    kart.addEventListener("mouseenter", function () {
      b.uzerinde = true;
    });
    kart.addEventListener("mouseleave", function () {
      b.uzerinde = false;
      if (b.bitti) b.bitti = Date.now() - BILDIRIM_KAPANIS_MS + 2000; // 2 sn sonra kapanır
    });
    const ikon = suruyor
      ? "i-yukleniyor"
      : k.durum === "yapildi"
        ? "i-onay"
        : k.durum === "suresi_doldu"
          ? "i-saat"
          : "i-hata";
    const kutu = ikonKutu(ikon, SINIF_TONU[sinif] || "");
    if (suruyor) kutu.firstChild.classList.add("donus");
    kart.appendChild(kutu);
    const govde = el("div", "bildirim-govde");
    govde.appendChild(el("b", "", k.ozet + " · " + etiket));
    govde.appendChild(el("span", "", k.mesaj || saatMetni(k.olusturuldu)));
    const adim = k.durum === "bekliyor" ? 1 : suruyor ? 2 : 3;
    const ton = suruyor ? "" : k.durum === "yapildi" ? "basari" : k.durum === "suresi_doldu" ? "notr" : "tehlike";
    const cizgi = el("div", "adimlar-cizgisi" + (ton ? " " + ton : ""));
    cizgi.setAttribute("aria-hidden", "true");
    for (let i = 1; i <= 3; i++) cizgi.appendChild(el("i", i <= adim ? "gecti" : ""));
    govde.appendChild(cizgi);
    kart.appendChild(govde);
    const kapat = el("button", "ikon-dugme");
    kapat.type = "button";
    kapat.setAttribute("aria-label", "Bildirimi kapat");
    kapat.appendChild(simge("i-kapat"));
    kapat.addEventListener("click", function () {
      bildirimKapat(k.id);
    });
    kart.appendChild(kapat);
    return kart;
  }

  $("bildirim-fazla").addEventListener("click", function () {
    gorunumeGit(gorunumYetkili("mudahale") ? "mudahale" : "genel");
  });

  // ---------------------------------------------------------------- yönetim

  function yonetimDinliyor() {
    return aktifGorunum === "yonetim" && Date.now() - sonEtkilesim < DINLEME_SURESI_MS;
  }

  /* Açık (bitmemiş) bir ağır komut (yeniden başlatma / güncelleme) var mı. */
  function acikAgirKomut(veri) {
    const komutlar = (veri.mudahale && veri.mudahale.komutlar) || [];
    return (
      komutlar.find(
        (k) =>
          (k.tur === "yeniden_baslat" || k.tur === "guncelle") &&
          (k.durum === "bekliyor" || k.durum === "iletildi" || k.durum === "suruyor")
      ) || null
    );
  }

  /* Yönetim hali: yönetim açık mı, fabrika dinliyor mu, açık ağır komut var mı
     (docs/19 §3.8, O10). Ağır iş sürerken "haber yok" yerine "sürüyor" der. */
  function yonetimHali(veri) {
    const rapor = veri.rapor;
    const y = rapor && rapor.yonetim;
    const durum = baglantiDurumu(veri);
    const agir = acikAgirKomut(veri);
    if (durum !== "canli") {
      let sebep = durum === "kapandi" && rapor ? rapor.kapanis_sebebi : "";
      if (!sebep && agir) sebep = agir.tur === "guncelle" ? "guncelleme" : "yeniden_baslatma";
      if (sebep === "guncelleme" || sebep === "yeniden_baslatma") {
        const ad = sebep === "guncelleme" ? "Güncelleme" : "Yeniden başlatma";
        const sinir = sebep === "guncelleme" ? 600 : 300;
        const gecikme = gecikmeSn(veri);
        if (durum === "kapandi" && gecikme !== null && gecikme > sinir) {
          return {
            acik: false,
            sinif: "tehlike",
            kisa: "Program açılmadı",
            alt: ad + "den sonra program kendiliğinden açılmadı; fabrikadaki bilgisayara bakılmalı.",
          };
        }
        return {
          acik: false,
          agir: true,
          sinif: "uyari",
          kisa: sebep === "guncelleme" ? "Güncelleme sürüyor" : "Yeniden başlatılıyor",
          alt: "Program birkaç dakika kapalı kalabilir.",
        };
      }
      return {
        acik: false,
        sinif: "tehlike",
        kisa: "Bağlantı yok",
        alt: "Kapalı bir program siteden açılamaz; fabrikada bilgisayarı ve Kontrol Paneli'ni kontrol edin.",
      };
    }
    if (!y || !y.acik) {
      return {
        acik: false,
        sinif: "",
        kisa: "Yönetim kapalı",
        alt:
          "Fabrikadaki bilgisayarda Ayarlar → Uzak izleme panosu → Uzaktan yönetim'i " +
          '"Açık" yapıp sistemi yeniden başlatın.',
      };
    }
    if (agir) {
      return {
        acik: true,
        agir: true,
        sinif: "uyari",
        kisa: agir.tur === "guncelle" ? "Güncelleme sürüyor" : "Yeniden başlatılıyor",
        alt: "",
      };
    }
    if (!yonetimDinliyor()) {
      return {
        acik: true,
        bekliyor: true,
        sinif: "",
        kisa: "Dinleme beklemede",
        alt: "Ekrana 10 dakikadır dokunulmadı. Fabrikanın komutları sık sorması için sürdürün.",
      };
    }
    const yas = veri.mudahale ? veri.mudahale.yoklama_yasi_sn : null;
    if (yas !== null && yas !== undefined && yas <= DINLIYOR_SN) {
      return { acik: true, sinif: "basari", kisa: "Fabrika dinliyor", alt: "" };
    }
    return {
      acik: true,
      sinif: "uyari",
      kisa: "Birazdan dinler",
      alt:
        "Bu ekran açıkken fabrika bir sonraki raporunda sık sormaya başlar. İşlemi şimdi " +
        "gönderebilirsiniz; sırada bekler.",
    };
  }

  const KURULUM_ADLARI = { paket: "Paket (Windows)", git: "Kaynak (git)", diger: "Diğer" };

  function yonetimProgramCiz(rapor) {
    const p = (rapor && rapor.program) || {};
    const yapi = p.yapi || {};
    const y = rapor && rapor.yonetim;
    $("program-adi").textContent = rapor ? (p.ad || "Program") + (p.surum ? " " + p.surum : "") : "Program";
    const meta = [];
    if (yapi.commit) meta.push("Yapı " + yapi.commit.slice(0, 7));
    if (yapi.tarih) meta.push(gunMetni(yapi.tarih));
    if (y && y.kurulum) meta.push(KURULUM_ADLARI[y.kurulum] || y.kurulum);
    $("yonetim-program").textContent = rapor
      ? meta.join(" · ") || "Yapı bilgisi gönderilmiyor"
      : "Fabrikadan henüz rapor gelmedi";
  }

  function yonetimSebep(acik, y, tur, kapi) {
    if (!acik || !y) return "";
    if (!(y.isler || []).includes(tur)) return "Fabrika programı bu işi bilmiyor; programı güncelleyin.";
    if (kapi && !kapi.mumkun) return kapi.sebep || "Şu an yapılamıyor.";
    return "";
  }

  function sebepGoster(kimlik, metin) {
    $(kimlik).textContent = metin;
    $(kimlik).hidden = !metin;
  }

  function yonetimKomutlariCiz(veri) {
    const komutlar = birlesikKomutlar(veri, YONETIM_TURLERI);
    const liste = $("yonetim-komutlar");
    temizle(liste);
    if (!komutlar.length) {
      liste.appendChild(el("li", "bos-satir", "Henüz işlem yok; teşhis, yeniden başlatma ve güncelleme burada görünür"));
    }
    for (const k of komutlar) liste.appendChild(komutSatiri(k, true));
  }

  function yonetimiCiz(veri) {
    const hal = yonetimHali(veri);
    hapCiz("yonetim-hapi", "yonetim-hap-metni", hal.sinif, hal.kisa);
    $("yonetim-alt").textContent = hal.alt;
    $("yonetim-durumu").hidden = !hal.alt;
    $("yonetim-surdur").hidden = !hal.bekliyor;
    yonetimProgramCiz(veri.rapor);
    const y = veri.rapor && veri.rapor.yonetim;
    const acik = !!(hal.acik && y && y.acik);
    const teshisVar = acik && (y.isler || []).includes("teshis");
    const yrb = y && y.yeniden_baslatma;
    const gnc = y && y.guncelleme;
    const yenidenVar = acik && !hal.agir && (y.isler || []).includes("yeniden_baslat") && yrb && yrb.mumkun;
    const guncelleVar = acik && !hal.agir && (y.isler || []).includes("guncelle") && gnc && gnc.mumkun;
    $("teshis-dugmesi").disabled = !teshisVar;
    $("yeniden-dugmesi").disabled = !yenidenVar;
    $("guncelle-dugmesi").disabled = !guncelleVar;
    sebepGoster("yeniden-sebep", hal.agir ? "" : yonetimSebep(acik, y, "yeniden_baslat", yrb));
    sebepGoster("guncelle-sebep", hal.agir ? "" : yonetimSebep(acik, y, "guncelle", gnc));
    $("islem-notu").hidden = !hal.agir;
    if (!yenidenVar) yenidenOnayiniKapat();
    if (!guncelleVar) guncelleOnayiniKapat();
    yonetimKomutlariCiz(veri);
  }

  function yenidenOnayiniKapat() {
    $("yeniden-onayi").hidden = true;
    $("yeniden-dugmesi").hidden = false;
    $("yeniden-sifre").value = "";
    $("yeniden-sifre").removeAttribute("aria-invalid");
  }
  function guncelleOnayiniKapat() {
    $("guncelle-onayi").hidden = true;
    $("guncelle-dugmesi").hidden = false;
    $("guncelle-sifre").value = "";
    $("guncelle-sifre").removeAttribute("aria-invalid");
  }

  $("yonetim-surdur").addEventListener("click", function () {
    sonEtkilesim = Date.now();
    if (sonVeri) yonetimiCiz(sonVeri);
    yukle();
  });

  $("teshis-dugmesi").addEventListener("click", async function () {
    $("teshis-hatasi").textContent = "";
    this.disabled = true;
    try {
      await mudahaleGonder({ tur: "teshis" });
      setTimeout(yukle, 1500);
    } catch (hata) {
      $("teshis-hatasi").textContent = hata.message;
    } finally {
      this.disabled = false;
    }
  });

  /* Ağır işler: düğme kartın içinde onay formunu açar, formda şifre istenir
     (docs/19 §3.9). Form açıkken düğme gizlenir. */
  function agirOnay(ac, kapat, sifreKimlik, hataKimlik, tur) {
    ac.addEventListener("click", function () {
      guncelleOnayiniKapat();
      yenidenOnayiniKapat();
      $(hataKimlik).textContent = "";
      kapat.onayi.hidden = false;
      ac.hidden = true;
      $(sifreKimlik).focus();
    });
    kapat.vazgec.addEventListener("click", function () {
      kapat.onayi.hidden = true;
      ac.hidden = false;
      $(sifreKimlik).value = "";
      ac.focus();
    });
    async function gonder() {
      $(hataKimlik).textContent = "";
      const sifre = $(sifreKimlik).value;
      $(sifreKimlik).toggleAttribute("aria-invalid", !sifre);
      if (!sifre) {
        $(hataKimlik).textContent = "Onaylamak için şifrenizi yazın.";
        $(sifreKimlik).focus();
        return;
      }
      kapat.gonder.disabled = true;
      try {
        await mudahaleGonder({ tur: tur, sifre: sifre });
        kapat.onayi.hidden = true;
        ac.hidden = false;
        $(sifreKimlik).value = "";
        setTimeout(yukle, 1500);
      } catch (hata) {
        $(hataKimlik).textContent = hata.message;
      } finally {
        kapat.gonder.disabled = false;
      }
    }
    kapat.gonder.addEventListener("click", gonder);
    $(sifreKimlik).addEventListener("keydown", function (olay) {
      if (olay.key === "Enter") {
        olay.preventDefault();
        gonder();
      }
    });
  }
  agirOnay(
    $("yeniden-dugmesi"),
    { onayi: $("yeniden-onayi"), vazgec: $("yeniden-vazgec"), gonder: $("yeniden-gonder") },
    "yeniden-sifre",
    "yeniden-hatasi",
    "yeniden_baslat"
  );
  agirOnay(
    $("guncelle-dugmesi"),
    { onayi: $("guncelle-onayi"), vazgec: $("guncelle-vazgec"), gonder: $("guncelle-gonder") },
    "guncelle-sifre",
    "guncelle-hatasi",
    "guncelle"
  );

  // -------------------------------------------------------------- kullanıcılar

  async function hesapIslem(govde) {
    const yanit = await fetch("/api/hesap", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(govde),
    });
    const veri = await yanit.json().catch(() => ({}));
    if (yanit.status === 401) {
      oturumuKapat();
      throw new Error("Oturumun süresi doldu; yeniden giriş yapın.");
    }
    if (!yanit.ok) {
      const hata = new Error(veri.mesaj || "İşlem yapılamadı (HTTP " + yanit.status + ").");
      hata.hata = veri.hata || "";
      throw hata;
    }
    return veri;
  }

  function iskeletSatirlari(liste, adet) {
    temizle(liste);
    for (let i = 0; i < adet; i++) {
      const satir = el("li", "iskelet-satiri");
      satir.setAttribute("aria-hidden", "true");
      satir.appendChild(el("span", "iskelet-yuvarlak"));
      const govde = el("div");
      govde.append(el("span", "iskelet genis"), el("span", "iskelet dar"));
      satir.appendChild(govde);
      liste.appendChild(satir);
    }
  }

  async function hesaplariYukle() {
    if (hesapIstekSuruyor) return;
    hesapIstekSuruyor = true;
    if (!hesapVerisi) {
      iskeletSatirlari($("kullanici-listesi"), 4);
      iskeletSatirlari($("kayit-tablosu"), 4);
    }
    try {
      const yanit = await fetch("/api/hesap", { credentials: "same-origin", cache: "no-store" });
      const veri = await yanit.json().catch(() => ({}));
      if (yanit.status === 401) {
        oturumuKapat();
        return;
      }
      if (!yanit.ok) {
        $("kullanicilar-hatasi").textContent = veri.mesaj || "Yüklenemedi (HTTP " + yanit.status + ").";
        return;
      }
      hesapVerisi = veri;
      $("kullanicilar-hatasi").textContent = "";
      kullanicilariCiz(veri);
    } catch (hata) {
      $("kullanicilar-hatasi").textContent = "Siteye ulaşılamıyor.";
    } finally {
      hesapIstekSuruyor = false;
    }
  }

  function yonetilebilir(k) {
    return !k.kurucu && rolYeter("yonetici") && oturum && k.ad !== oturum.ad;
  }

  function kullaniciSonucu(metin) {
    $("kullanici-sonuc-metni").textContent = metin;
    $("kullanici-sonucu").hidden = !metin;
    if (metin) duyur(metin);
  }

  /* Satırın "⋯" paneli: iş düğmeleri; dokunulan iş panelin altında kendi küçük
     formunu açar (rol seçimi, yeni şifre ...). Her işte kendi şifreniz sorulur. */
  function kullaniciIslemleri(k) {
    const panel = el("div", "islem-paneli");
    const dugmeler = el("div", "dugmeler");
    const isler = [
      ["rol", "Rolü değiştir"],
      ["sifre", "Yeni şifre ver"],
      ["durum", k.acik ? "Girişi kapat" : "Girişi aç"],
    ];
    // İki adımı sıfırla: telefonunu kaybeden yalnız şifresiyle girer (yalnız açıkken)
    if (k.iki_adim) isler.push(["iki_adim", "2 adımı sıfırla"]);
    isler.push(["sil", "Hesabı sil"]);
    for (const [is, ad] of isler) {
      const dugme = el("button", "dugme " + (is === "sil" ? "tehlike" : "ikincil") + (acikIslem === is ? " secili" : ""), ad);
      dugme.type = "button";
      dugme.setAttribute("aria-pressed", String(acikIslem === is));
      dugme.addEventListener("click", function () {
        acikIslem = acikIslem === is ? null : is;
        kullanicilariCiz(hesapVerisi);
        const ilk = document.querySelector("#kullanici-listesi .islem-formu select, #kullanici-listesi .islem-formu input");
        if (ilk) ilk.focus();
      });
      dugmeler.appendChild(dugme);
    }
    panel.appendChild(dugmeler);
    if (acikIslem) panel.appendChild(islemFormu(acikIslem));
    return panel;

    // Seçilen işin küçük formu: gerekirse rol ya da yeni şifre, her zaman kendi şifreniz
    function islemFormu(is) {
      const form = el("form", "islem-formu");
      form.noValidate = true;
      const hata = el("p", "hata tam-satir");
      hata.setAttribute("role", "alert");
      const alanlar = [];

      function alan(etiket, girdi) {
        const kap = el("div", "alan");
        const kimlik = "islem-" + is + "-" + alanlar.length;
        girdi.id = kimlik;
        const lbl = el("label", "", etiket);
        lbl.htmlFor = kimlik;
        kap.append(lbl, girdi);
        alanlar.push(girdi);
        form.appendChild(kap);
        return girdi;
      }

      let rolSecici = null;
      let yeniSifre = null;
      if (is === "rol") {
        rolSecici = el("select", "secici");
        for (const deger of Object.keys(ROL_SIRASI)) {
          const o = el("option", "", ROL_ADLARI[deger]);
          o.value = deger;
          if (deger === k.rol) o.selected = true;
          rolSecici.appendChild(o);
        }
        alan("Yeni rol", rolSecici);
      }
      if (is === "sifre") {
        yeniSifre = el("input");
        yeniSifre.type = "text";
        yeniSifre.placeholder = "En az 10 karakter";
        yeniSifre.maxLength = 200;
        yeniSifre.autocapitalize = "none";
        yeniSifre.spellcheck = false;
        alan("Yeni şifre", yeniSifre);
      }
      const onaySifre = el("input");
      onaySifre.type = "password";
      onaySifre.autocomplete = "current-password";
      onaySifre.maxLength = 200;
      alan("Kendi şifreniz", onaySifre);

      const GONDER = {
        rol: ["Kaydet", "birincil"],
        sifre: ["Yeni şifreyi ver", "birincil"],
        durum: [k.acik ? "Girişi kapat" : "Girişi aç", "birincil"],
        iki_adim: ["Sıfırla", "birincil"],
        sil: ["Evet, sil", "tehlike"],
      };
      const gonder = el("button", "dugme " + GONDER[is][1], GONDER[is][0]);
      gonder.type = "submit";
      form.appendChild(gonder);
      form.appendChild(hata);
      if (is === "sil") form.appendChild(el("p", "not", k.ad + " hesabı kalıcı olarak silinir."));
      if (is === "iki_adim") form.appendChild(el("p", "not", k.ad + " bundan sonra yalnız şifresiyle girer."));

      form.addEventListener("submit", function (olay) {
        olay.preventDefault();
        hata.textContent = "";
        if (!onaySifre.value) {
          hata.textContent = "Onaylamak için kendi şifrenizi yazın.";
          onaySifre.setAttribute("aria-invalid", "true");
          onaySifre.focus();
          return;
        }
        let govde;
        let sonuc;
        if (is === "rol") {
          govde = { eylem: "rol", ad: k.ad, rol: rolSecici.value, sifre: onaySifre.value };
          sonuc = k.ad + " artık " + ROL_ADLARI[rolSecici.value] + ".";
        } else if (is === "sifre") {
          govde = { eylem: "sifre_sifirla", ad: k.ad, yeni_sifre: yeniSifre.value, sifre: onaySifre.value };
          sonuc = k.ad + " için yeni şifre verildi. Şifreyi kişiye kendiniz iletin.";
        } else if (is === "durum") {
          govde = { eylem: k.acik ? "kapat" : "ac", ad: k.ad, sifre: onaySifre.value };
          sonuc = k.ad + (k.acik ? " için giriş kapatıldı." : " için giriş açıldı.");
        } else if (is === "iki_adim") {
          govde = { eylem: "iki_adim_sifirla", ad: k.ad, sifre: onaySifre.value };
          sonuc = k.ad + " için iki adımlı doğrulama sıfırlandı.";
        } else {
          govde = { eylem: "sil", ad: k.ad, sifre: onaySifre.value };
          sonuc = k.ad + " silindi.";
        }
        gonder.disabled = true;
        hesapIslem(govde)
          .then(function () {
            acikHesap = null;
            acikIslem = null;
            kullaniciSonucu(sonuc);
            return hesaplariYukle();
          })
          .catch(function (e) {
            gonder.disabled = false;
            hata.textContent = e.message;
          });
      });
      return form;
    }
  }

  function kullaniciSatiri(k) {
    const satir = el("li", "alt-alta");
    const ust = el("div", "satir-ust");
    const bas = el("span", "bas orta" + (BAS_RENKLERI[k.ad.length % 5] ? " " + BAS_RENKLERI[k.ad.length % 5] : ""), basHarfler(k.ad));
    bas.setAttribute("aria-hidden", "true");
    ust.appendChild(bas);
    const govde = el("div", "satir-govde");
    govde.appendChild(el("b", "", k.ad));
    let alt = "";
    if (k.kurucu) alt = "Ortak şifreyle açılır";
    else if (k.son_giris) {
      const gun = gunEtiketi(k.son_giris);
      alt = "Son giriş " + (gun && gun !== "dün" ? gun : tarihSaatMetni(k.son_giris));
    }
    else alt = "Hiç giriş yapmadı";
    govde.appendChild(el("span", "kucuk", alt));
    ust.appendChild(govde);
    const rozetler = el("div", "rozetler hesap-rozetleri");
    if (k.kurucu) rozetler.appendChild(rozet("Kurucu", "mor"));
    rozetler.appendChild(rozet(k.rol_adi || ROL_ADLARI[k.rol] || "", k.rol === "yonetici" ? "bilgi" : ""));
    if (!k.acik && !k.kurucu) rozetler.appendChild(rozet("Girişi kapalı", "tehlike"));
    if (k.sifre_degismeli) rozetler.appendChild(rozet("Şifre bekliyor", "uyari"));
    if (k.iki_adim) rozetler.appendChild(rozet("2 adım", "basari"));
    ust.appendChild(rozetler);
    const acik = acikHesap === k.ad;
    if (yonetilebilir(k)) {
      const dugme = el("button", "ikon-dugme");
      dugme.type = "button";
      dugme.setAttribute("aria-label", k.ad + ": işlemler");
      dugme.setAttribute("aria-expanded", String(acik));
      const ikon = simge("i-daha");
      ikon.style.strokeWidth = "2.6";
      dugme.appendChild(ikon);
      dugme.addEventListener("click", function () {
        acikHesap = acik ? null : k.ad;
        acikIslem = null;
        kullanicilariCiz(hesapVerisi);
      });
      ust.appendChild(dugme);
    }
    satir.appendChild(ust);
    if (acik && yonetilebilir(k)) satir.appendChild(kullaniciIslemleri(k));
    return satir;
  }

  function kayitTablosu(kayit) {
    const liste = $("kayit-tablosu");
    temizle(liste);
    if (!kayit.length) {
      liste.appendChild(el("li", "bos-satir", "Henüz işlem kaydı yok"));
      return;
    }
    for (const r of kayit) {
      const satir = el("li");
      satir.appendChild(el("span", "kayit-zamani", tarihSaatMetni(r.zaman) || "-"));
      const govde = el("div", "satir-govde");
      govde.appendChild(el("b", "ince", IS_ADLARI[r.is] || r.is || "-"));
      const kim = (r.kim || "-") + (r.rol_adi ? " (" + r.rol_adi + ")" : "");
      govde.appendChild(el("span", "kucuk", r.ozet ? kim + " · " + r.ozet : kim));
      satir.appendChild(govde);
      const [sad, ssinif] = SONUC_ROZETI[r.sonuc] || ["", ""];
      if (sad) satir.appendChild(rozet(sad, ssinif));
      liste.appendChild(satir);
    }
  }

  function kullanicilariCiz(veri) {
    if (!veri) return;
    const kullanicilar = veri.kullanicilar || [];
    if (acikHesap && !kullanicilar.some((k) => k.ad === acikHesap)) {
      acikHesap = null;
      acikIslem = null;
    }
    const liste = $("kullanici-listesi");
    temizle(liste);
    if (!kullanicilar.length) liste.appendChild(el("li", "bos-satir", "Henüz hesap yok"));
    for (const k of kullanicilar) liste.appendChild(kullaniciSatiri(k));
    $("hesaplar-bolumu").setAttribute("aria-label", "Hesaplar: " + kullanicilar.length + " hesap (kurucu dahil)");
    kayitTablosu(veri.kayit || []);
  }

  for (const dugme of document.querySelectorAll("#kullanici-segmenti button")) {
    dugme.addEventListener("click", function () {
      kullaniciBolumu = this.dataset.bolum;
      for (const d of document.querySelectorAll("#kullanici-segmenti button")) {
        d.setAttribute("aria-pressed", String(d === this));
      }
      $("hesaplar-bolumu").hidden = kullaniciBolumu !== "hesaplar";
      $("kayit-bolumu").hidden = kullaniciBolumu !== "kayit";
    });
  }

  $("ekle-ac").addEventListener("click", function () {
    kullaniciSonucu("");
    $("ekle-karti").hidden = false;
    this.hidden = true;
    $("yeni-ad").focus();
  });

  function ekleKartiniKapat() {
    $("ekle-karti").hidden = true;
    $("ekle-ac").hidden = false;
    for (const kimlik of ["yeni-ad", "yeni-ilk-sifre", "yeni-onay-sifresi"]) {
      $(kimlik).value = "";
      $(kimlik).removeAttribute("aria-invalid");
    }
    for (const kimlik of ["yeni-ad-hatasi", "yeni-ilk-hatasi", "yeni-onay-hatasi", "kullanici-ekle-hatasi"]) {
      $(kimlik).textContent = "";
    }
  }
  $("ekle-kapat").addEventListener("click", function () {
    ekleKartiniKapat();
    $("ekle-ac").focus();
  });

  function yeniRolAciklama() {
    $("yeni-rol-aciklama").textContent = ROL_ACIKLAMALARI[$("yeni-rol").value] || "";
  }
  $("yeni-rol").addEventListener("change", yeniRolAciklama);

  // Alanın hatası yazınca silinir
  for (const [girdi, hata] of [
    ["yeni-ad", "yeni-ad-hatasi"],
    ["yeni-ilk-sifre", "yeni-ilk-hatasi"],
    ["yeni-onay-sifresi", "yeni-onay-hatasi"],
  ]) {
    $(girdi).addEventListener("input", function () {
      $(hata).textContent = "";
      this.removeAttribute("aria-invalid");
    });
  }

  $("kullanici-formu").addEventListener("submit", async function (olay) {
    olay.preventDefault();
    $("kullanici-ekle-hatasi").textContent = "";
    const ad = $("yeni-ad").value.trim();
    const ilk = $("yeni-ilk-sifre").value;
    const onay = $("yeni-onay-sifresi").value;
    const hatalar = [
      ["yeni-ad", "yeni-ad-hatasi", !ad ? "Kullanıcı adı gerekir." : /\s/.test(ad) ? "Boşluk olmaz; nokta ya da alt çizgi kullanın." : ""],
      ["yeni-ilk-sifre", "yeni-ilk-hatasi", ilk.length < 10 ? "En az 10 karakter." : ""],
      ["yeni-onay-sifresi", "yeni-onay-hatasi", !onay ? "Kendi şifrenizi yazın." : ""],
    ];
    let ilkHatali = null;
    for (const [girdi, kutu, metin] of hatalar) {
      $(kutu).textContent = metin;
      $(girdi).toggleAttribute("aria-invalid", !!metin);
      if (metin && !ilkHatali) ilkHatali = girdi;
    }
    if (ilkHatali) {
      $(ilkHatali).focus();
      return;
    }
    const dugme = $("kullanici-ekle-dugmesi");
    dugme.disabled = true;
    dugme.setAttribute("aria-busy", "true");
    $("kullanici-ekle-metni").textContent = "Açılıyor…";
    try {
      await hesapIslem({ eylem: "ekle", ad: ad, rol: $("yeni-rol").value, ilk_sifre: ilk, sifre: onay });
      ekleKartiniKapat();
      kullaniciSonucu(ad + " eklendi. İlk şifreyi kişiye kendiniz iletin.");
      await hesaplariYukle();
    } catch (hata) {
      $("kullanici-ekle-hatasi").textContent = hata.message;
    } finally {
      dugme.disabled = false;
      dugme.removeAttribute("aria-busy");
      $("kullanici-ekle-metni").textContent = "Hesabı aç";
    }
  });

  // -------------------------------------------------------------- tesisler

  /* Tesisler ekranı açık mı: filo verisi (/api/durum?filo=1) yalnız o zaman
     istenir (docs/20 §4). */
  function tesislerAcik() {
    return aktifGorunum === "tesisler" && gorunumYetkili("tesisler");
  }

  const TESIS_ROZETI = {
    canli: ["Canlı", "basari"],
    yok: ["Haber yok", "tehlike"],
    kapandi: ["Kapandı", ""],
    hic: ["Rapor gelmedi", ""],
  };

  function tesisIskeleti() {
    const kap = $("tesis-listesi");
    if (kap.childNodes.length) return;
    for (let i = 0; i < 2; i++) {
      const kart = el("section", "kart tesis-karti");
      kart.setAttribute("aria-hidden", "true");
      kart.append(el("span", "iskelet genis"), el("span", "iskelet dar"), el("span", "iskelet dar"));
      kap.appendChild(kart);
    }
  }

  /* Tesis kartı: ad, kimlik, bağlantı, bugünkü ihlal, son rapor. Aynı kimlik
     iki bilgisayardan geliyorsa (kopyalanan .env) uyarı yalnız bu kartta. */
  function tesisSatiri(t) {
    const kart = el("section", "kart tesis-karti");
    kart.setAttribute("aria-label", t.ad || t.id || "Fabrika");
    const ust = el("div", "tesis-ust");
    const adlar = el("div");
    adlar.appendChild(el("h2", "", t.ad || t.id || "Fabrika"));
    if (t.id) adlar.appendChild(el("code", "", t.id));
    ust.appendChild(adlar);
    const [ad, sinif] = TESIS_ROZETI[t.baglanti] || ["Bilinmiyor", ""];
    const hap = el("span", "hap kucuk" + (sinif ? " " + sinif : ""));
    hap.appendChild(el("span", "nokta"));
    hap.appendChild(el("span", "", ad));
    ust.appendChild(hap);
    kart.appendChild(ust);
    const sayilar = el("dl", "tesis-sayilari");
    const ihlal = el("div");
    ihlal.append(el("dt", "", "Bugün ihlal"), el("dd", "", sayiMetni(t.bugun_ihlal)));
    const son = el("div");
    son.append(
      el("dt", "", "Son rapor"),
      el("dd", "kucuk", t.son_rapor ? kisaSure(t.gecikme_sn || 0) + " önce" : "henüz yok")
    );
    sayilar.append(ihlal, son);
    kart.appendChild(sayilar);
    if (t.cakisma) {
      const kutu = el("p", "cakisma-kutusu");
      kutu.appendChild(simge("i-uyari"));
      // Adlar "kurulum · bilgisayar" biçimindedir; ayırt eden bilgisayar adıdır
      const bilgisayarlar = (t.cakisma.adlar || []).filter(Boolean).map((a) => a.split(" · ").pop());
      kutu.appendChild(
        el(
          "span",
          "",
          "Aynı kimlik iki bilgisayardan geliyor" +
            (bilgisayarlar.length ? ": " + bilgisayarlar.join(" ve ") : "") +
            ". Birine farklı UZAK_PANO_TESIS_ID yazın."
        )
      );
      kart.appendChild(kutu);
    }
    kart.appendChild(t.ana ? rozet("Ana tesis · komut alır", "bilgi") : rozet("Yalnız izleme", ""));
    return kart;
  }

  function tesisleriCiz(filo) {
    const tesisler = filo.tesisler || [];
    // Sunucunun uyarıları (kimliksiz program canlı, ANA_TESIS geçersiz): düz metin.
    // Kimlik çakışması ilgili tesisin kartında yazdığı için burada tekrarlanmaz.
    const uyarilar = (filo.uyarilar || []).filter((m) => !m.startsWith("Aynı tesis kimliği"));
    $("tesis-uyarisi").textContent = uyarilar.join(" ");
    $("tesis-uyarisi").hidden = !uyarilar.length;
    if (!tesisler.some((t) => t.ana) && filo.ana_tesis) {
      uyarilar.push("Ana tesis (" + filo.ana_tesis + ") henüz rapor göndermedi.");
      $("tesis-uyarisi").textContent = uyarilar.join(" ");
      $("tesis-uyarisi").hidden = false;
    }
    const kap = $("tesis-listesi");
    temizle(kap);
    if (!tesisler.length) {
      const bos = el("div", "bos-kutu");
      bos.appendChild(simge("i-tesis"));
      bos.appendChild(el("b", "", "Henüz tesis yok"));
      bos.appendChild(el("span", "", "Fabrikadan ilk rapor gelince görünür."));
      kap.appendChild(bos);
    }
    for (const t of tesisler) kap.appendChild(tesisSatiri(t));
  }

  // ---------------------------------------------------------------- sistem

  /* Bu ayın çalışma oranı (raporun isteğe bağlı calisma alanı): tek satır,
     Türkçe ondalık virgül; ör. "Bu ay çalışma: %99,6 (kameralar %98,9; ...)". */
  function calismaMetni(c) {
    const yuzde = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    return (
      "Bu ay çalışma: %" +
      yuzde.format(c.sistem_yuzde) +
      " (kameralar %" +
      yuzde.format(c.kamera_yuzde) +
      "; " +
      new Intl.NumberFormat("tr-TR").format(c.olculen_saat) +
      " saat ölçüldü)"
    );
  }

  function sistemiCiz(veri) {
    const r = veri.rapor;
    const yuzde = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    const satirlar = [["Son rapor", veri.son_rapor ? tarihSaatMetni(veri.son_rapor) : "-", ""]];
    if (r) {
      satirlar.push(["Rapor aralığı", r.aralik_sn + " sn", ""]);
      // Bu ayın çalışma oranı yalnız program gönderiyorsa; ayrıntısı üstüne gelince
      if (r.calisma) satirlar.push(["Bu ay çalışma", "%" + yuzde.format(r.calisma.sistem_yuzde), calismaMetni(r.calisma)]);
      satirlar.push(["Boş disk", r.sistem.bos_disk_gb === null ? "-" : Math.round(r.sistem.bos_disk_gb) + " GB", ""]);
    }
    const liste = $("sistem-bilgisi");
    temizle(liste);
    for (const [ad, deger, ayrinti] of satirlar) {
      const satir = el("div");
      if (ayrinti) satir.title = ayrinti;
      satir.appendChild(el("dt", "", ad));
      satir.appendChild(el("dd", "", deger));
      liste.appendChild(satir);
    }

    const adres = fabrikaAdresi(veri);
    const bag = $("fabrika-dugmesi");
    bag.hidden = !adres;
    if (adres) bag.href = adres;
  }

  // ------------------------------------------------------------ hepsi

  function panoyuCiz(veri) {
    rolUygula();
    bantlariCiz();
    hesabimCiz();
    gorunumuUygula();
    const rapor = veri.rapor;
    sayaclariCiz(rapor);
    for (const kutu of document.querySelectorAll(".veri")) kutu.hidden = !rapor;
    bilgisayariCiz(rapor);
    if (rapor) {
      sayilariCiz(rapor);
      grafigiCiz(rapor);
      genelKameralariCiz(rapor);
      encokCiz(rapor);
      olaylariCiz(rapor);
    } else {
      temizle($("olay-gruplari"));
      $("olay-bos").hidden = false;
      $("olay-bos-baslik").textContent = "Henüz rapor yok";
      $("olay-bos-metni").textContent = "Fabrikadan ilk rapor gelince görünür.";
    }
    kareleriCiz(veri);
    sistemiCiz(veri);
    mudahaleyiCiz(veri);
    if (rolYeter("yonetici")) yonetimiCiz(veri);
    if (veri.filo) tesisleriCiz(veri.filo);
    bildirimleriCiz();
  }

  // ----------------------------------------------------------- sunucu

  async function yukle() {
    if (istekSuruyor) return;
    istekSuruyor = true;
    const yenile = $("yenile");
    yenile.classList.add("donuyor");
    try {
      const adres = dinleniyor()
        ? "/api/durum?mudahale=1"
        : yonetimDinliyor()
          ? "/api/durum?yonetim=1"
          : kareIzleniyor()
            ? "/api/durum?kare=1"
            : tesislerAcik()
              ? "/api/durum?filo=1"
              : "/api/durum";
      const yanit = await fetch(adres, { credentials: "same-origin", cache: "no-store" });
      const veri = await yanit.json().catch(() => ({}));
      if (yanit.status === 401) {
        oturumuKapat();
        $("ad").focus();
        return;
      }
      if (yanit.status === 503 && veri.hata === "kurulum_eksik") {
        kurulumGoster(veri.eksikler || []);
        return;
      }
      if (!yanit.ok) {
        hataGoster(veri.mesaj || "Site hata verdi (HTTP " + yanit.status + ").");
        return;
      }
      saatFarkiMs = Date.parse(veri.sunucu_zamani) - Date.now();
      sonVeri = veri;
      oturum = veri.oturum || null;
      onizleme = !!veri.onizleme;
      oturumDustu = false;
      siteUyarisi("");
      panoyuCiz(veri);
      panoyuGoster();
      // Kullanıcılar ekranı açık ve henüz yüklenmediyse hesapları getir
      if (aktifGorunum === "kullanicilar" && gorunumYetkili("kullanicilar") && !hesapVerisi) {
        hesaplariYukle();
      }
    } catch (hata) {
      hataGoster(
        "Siteye ulaşılamıyor. İnternet bağlantınızı kontrol edin; pano son bilinen durumu gösteriyor."
      );
    } finally {
      istekSuruyor = false;
      // Dönüş en az bir tur sürsün: hızlı cevapta da yenilendiği görülsün
      setTimeout(function () {
        if (!istekSuruyor) yenile.classList.remove("donuyor");
      }, 700);
    }
  }

  /* Hata durumu: veri varsa bırakılır (bayat veri, üstte uyarı); yoksa
     yükleme ekranı hatayı söyler ve tazeleme denemeye devam eder. */
  function hataGoster(metin) {
    if (sonVeri) {
      siteUyarisi(metin);
      durumBandiniCiz(sonVeri);
    } else {
      $("yukleniyor-baslik").textContent = "Siteye ulaşılamıyor";
      $("yukleniyor-metni").textContent = metin;
      tekEkranGoster("yukleniyor");
    }
  }

  // ---------------------------------------------------------------- giriş

  // Hata iletisi ve kutuların kırmızı kenarı birlikte yazılır, birlikte silinir.
  // `alanlar`: kırmızı kenarlı kutular (varsayılan ad ve şifre; kod hatasında kod).
  function girisHatasi(metin, alanlar) {
    const hatali = metin ? alanlar || ["ad", "sifre"] : [];
    $("giris-hatasi").textContent = metin;
    $("giris-hata-kutusu").hidden = !metin;
    for (const kimlik of ["ad", "sifre", "giris-kod"]) {
      if (hatali.includes(kimlik)) $(kimlik).setAttribute("aria-invalid", "true");
      else $(kimlik).removeAttribute("aria-invalid");
    }
    $("kod-haneleri").classList.toggle("hatali", hatali.includes("giris-kod"));
  }
  for (const kimlik of ["ad", "sifre", "giris-kod"]) {
    $(kimlik).addEventListener("input", function () {
      if ($(kimlik).hasAttribute("aria-invalid")) girisHatasi("");
    });
  }

  $("sifre-goster").addEventListener("click", function () {
    const goster = $("sifre").type === "password";
    $("sifre").type = goster ? "text" : "password";
    this.setAttribute("aria-pressed", String(goster));
    this.setAttribute("aria-label", goster ? "Şifreyi gizle" : "Şifreyi göster");
    this.querySelector("use").setAttribute("href", goster ? "#i-goz-kapali" : "#i-goz");
  });

  /* Altı kutu: girilen haneler kutulara yazılır, sıradaki kutu yanıp söner.
     Asıl girdi kutuların üstünde görünmez durur (telefonda kod klavyenin
     üstünde önerilir: autocomplete="one-time-code"). */
  function kodKutulariniCiz() {
    const girdi = $("giris-kod");
    const haneler = girdi.value.split("");
    const odakta = document.activeElement === girdi;
    const kutular = $("kod-haneleri").children;
    for (let i = 0; i < kutular.length; i++) {
      kutular[i].textContent = haneler[i] || "";
      kutular[i].classList.toggle("dolu", !!haneler[i]);
      kutular[i].classList.toggle("etkin", odakta && i === Math.min(haneler.length, 5));
    }
  }
  $("giris-kod").addEventListener("input", function () {
    const temiz = this.value.replace(/\D/g, "").slice(0, 6);
    if (temiz !== this.value) this.value = temiz;
    kodKutulariniCiz();
  });
  $("giris-kod").addEventListener("focus", kodKutulariniCiz);
  $("giris-kod").addEventListener("blur", kodKutulariniCiz);

  function girisDugmesi(metin, bekliyor) {
    const dugme = $("giris-dugmesi");
    dugme.disabled = !!bekliyor;
    if (bekliyor) dugme.setAttribute("aria-busy", "true");
    else dugme.removeAttribute("aria-busy");
    $("giris-dugme-metni").textContent = metin;
  }

  function kodAdimi() {
    return !$("giris-kod-alani").hidden;
  }

  /* İki adımlı doğrulama açık hesapta sunucu "iki_adim_gerekli" der: kod adımı
     açılır, aynı ad ve şifre kodla yeniden gönderilir. */
  function kodAlaniGoster(goster) {
    $("giris-kod-alani").hidden = !goster;
    $("giris-sifre-adimi").hidden = goster;
    $("giris-notu").hidden = goster;
    $("kod-notu").hidden = !goster;
    $("kod-hesap").textContent = $("ad").value.trim();
    girisDugmesi(goster ? "Doğrula ve gir" : "Giriş yap", false);
    if (!goster) $("giris-kod").value = "";
    kodKutulariniCiz();
  }

  function girisAdiminaDon() {
    kodAlaniGoster(false);
    girisHatasi("");
  }

  $("kod-geri").addEventListener("click", function () {
    girisAdiminaDon();
    $("sifre").focus();
  });

  $("giris-formu").addEventListener("submit", async function (olay) {
    olay.preventDefault();
    const ad = $("ad").value.trim();
    const sifre = $("sifre").value;
    if (!ad || !sifre) {
      girisHatasi("Kullanıcı adı ve şifre gerekir.", [!ad ? "ad" : null, !sifre ? "sifre" : null].filter(Boolean));
      if (kodAdimi()) kodAlaniGoster(false);
      $(!ad ? "ad" : "sifre").focus();
      return;
    }
    const kodAcik = kodAdimi();
    const kod = kodAcik ? $("giris-kod").value.replace(/\s+/g, "") : "";
    if (kodAcik && kod.length !== 6) {
      girisHatasi("Kodun 6 hanesini de yazın.", ["giris-kod"]);
      $("giris-kod").focus();
      return;
    }
    girisHatasi("");
    girisDugmesi(kodAcik ? "Doğrulanıyor…" : "Giriş yapılıyor…", true);
    try {
      const govde = { ad: ad, sifre: sifre };
      if (kod) govde.kod = kod;
      const yanit = await fetch("/api/giris", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(govde),
      });
      const veri = await yanit.json().catch(() => ({}));
      if (!yanit.ok) {
        if (veri.hata === "iki_adim_gerekli") {
          // Şifre doğru; kod isteniyor (hata değil): kod adımı açılır
          kodAlaniGoster(true);
          $("giris-kod").focus();
          return;
        }
        if (veri.hata === "kod_yanlis") {
          $("giris-kod").value = "";
          girisDugmesi("Doğrula ve gir", false);
          girisHatasi(veri.mesaj || "Doğrulama kodu yanlış ya da süresi geçti.", ["giris-kod"]);
          $("giris-kod").focus();
          return;
        }
        kodAlaniGoster(false);
        $("sifre").value = "";
        girisHatasi(veri.mesaj || "Giriş yapılamadı (HTTP " + yanit.status + ").");
        $("sifre").focus();
        return;
      }
      $("sifre").value = "";
      kodAlaniGoster(false);
      $("oturum-bandi").hidden = true;
      $("yukleniyor-baslik").textContent = "Pano açılıyor…";
      $("yukleniyor-metni").textContent = "Fabrikadan gelen son durum okunuyor.";
      tekEkranGoster("yukleniyor");
      await yukle();
    } catch (hata) {
      girisDugmesi(kodAcik ? "Doğrula ve gir" : "Giriş yap", false);
      girisHatasi("Siteye ulaşılamıyor. İnternet bağlantınızı kontrol edin.");
    }
  });

  for (const dugme of document.querySelectorAll("[data-cikis]")) {
    dugme.addEventListener("click", async function () {
      try {
        await fetch("/api/cikis", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
      } finally {
        sonVeri = null;
        oturum = null;
        hesapVerisi = null;
        oturumDustu = false;
        $("oturum-bandi").hidden = true;
        tekEkranGoster("giris");
        girisAdiminaDon();
      }
    });
  }

  $("yenile").addEventListener("click", function () {
    yukle();
    if (aktifGorunum === "kullanicilar" && gorunumYetkili("kullanicilar")) hesaplariYukle();
  });

  // Görünmeyen sekme sunucuyu yormaz; sekmeye dönünce hemen tazelenir.
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && $("giris").hidden) yukle();
  });
  // Giriş ekranında tazelenmez (yazılan şifre silinmesin); öbür her durumda
  // (pano, kurulum, ilk yüklemede ulaşılamayan site) tazelenir. Müdahale
  // ekranı dinlerken daha sık: komutun sonucu birkaç saniyede görünsün.
  // Kameralar ekranında da: yeni kare birkaç saniyede görünsün.
  let sonTazeleme = 0;
  setInterval(function () {
    if (document.visibilityState !== "visible" || !$("giris").hidden) return;
    const aralik =
      dinleniyor() || yonetimDinliyor() || kareIzleniyor() || bildirimler.length ? HIZLI_TAZELEME_MS : TAZELEME_MS;
    if (Date.now() - sonTazeleme >= aralik - 250) {
      sonTazeleme = Date.now();
      yukle();
    }
  }, HIZLI_TAZELEME_MS);
  // "12 saniye önce", bağlantı durumu ve bildirimlerin kapanışı istek arasında da ilerler
  setInterval(function () {
    if (sonVeri && !$("kabuk").hidden) {
      durumBandiniCiz(sonVeri);
      if (bildirimler.length) bildirimleriCiz();
    }
  }, GORECELI_MS);
  // Telefon ile masaüstü arasında geçince grafik etiketleri ve bildirim sayısı yeniden çizilir
  window.matchMedia(DAR_EKRAN).addEventListener("change", function () {
    if (sonVeri && sonVeri.rapor) grafigiCiz(sonVeri.rapor);
    bildirimleriCiz();
  });

  yeniRolAciklama();
  gorunumuUygula();
  yukle();
})();
