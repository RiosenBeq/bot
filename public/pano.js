/* Uzak izleme panosu.

   /api/durum'u 15 saniyede bir okur (sekme görünürken) ve ekranı çizer.
   Müdahale ekranı açıkken 5 saniyede bir okur ve `?mudahale=1` der: fabrika
   o zaman komutları sık sormaya başlar. Kameralar ekranı açıkken de 5
   saniyede bir okur ve `?kare=1` der: fabrika o zaman 10 saniyede bir anlık
   görüntü gönderir. Ekrana 10 dakika dokunulmazsa ikisi de bekler (açık
   unutulan bir ekran fabrikayı boşuna sorgulatmasın).
   Beş görünüm var (Genel bakış, Kameralar, Olaylar, Müdahale, Sistem); adres
   çubuğundaki #genel, #kameralar ... hangisinin açık olduğunu söyler, hem
   masaüstünün kenar çubuğu hem telefonun sekme çubuğu aynı bağlantılardır.

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
  const GENEL_OLAY_SAYISI = 6;

  const GORUNUMLER = {
    genel: ["Genel bakış", "Fabrikadan gelen son durum"],
    kameralar: ["Kameralar", "Anlık görüntü, bağlantı durumu ve kare hızı"],
    olaylar: ["Olaylar", "Son 20 olay, en yenisi üstte"],
    mudahale: ["Müdahale", "Fabrikada uzaktan anons ve hoparlör denemesi"],
    sistem: ["Sistem", "Program, bağlantı ve canlı görüntü"],
  };
  // [rozet, rozet sınıfı, sonuç yokken açıklama]
  const KOMUT_DURUMLARI = {
    bekliyor: ["Sırada", "uyari", "Fabrikanın almasını bekliyor"],
    iletildi: ["Fabrikada", "bilgi", "Çalınıyor"],
    yapildi: ["Yapıldı", "basari", ""],
    hata: ["Yapılamadı", "tehlike", ""],
    suresi_doldu: ["Süresi doldu", "", ""],
    sonuc_yok: ["Sonuç gelmedi", "uyari", ""],
  };
  const KAMERA_DURUMLARI = {
    online: ["Canlı", "basari"],
    connecting: ["Yeniden bağlanıyor", "uyari"],
    offline: ["Bağlantı yok", "tehlike"],
    pasif: ["Pasif", ""],
  };
  const ONEM_ROZETI = { critical: "kritik", high: "tehlike", medium: "uyari", low: "" };
  const ONEM_KUTUSU = { critical: "gul", high: "gul", medium: "bal", low: "gri" };

  const $ = (id) => document.getElementById(id);
  let sonVeri = null;
  let saatFarkiMs = 0; // sunucu saati - bu cihazın saati
  let istekSuruyor = false;
  let sonDuyuru = "";
  let kameraSuzgeci = "hepsi";
  let olayTuru = "hepsi";
  let aktifGorunum = "genel";
  let sonEtkilesim = Date.now();
  let seciliMesaj = null;
  let mudahaleImzasi = "";
  let bekleyenKomutlar = []; // gönderildi, sunucudan henüz okunmadı
  let kurulumMetni = ""; // "Gebze fabrikası · ISG-PC-01": Genel bakışın alt başlığı
  let kareImzasi = ""; // ızgaradaki kameralar; değişmedikçe ızgara yeniden kurulmaz
  const kareKutulari = new Map(); // kamera kimliği -> anlık görüntü kutusu
  const fotoHatalari = new Map(); // olay kimliği -> fotoğrafın gelmediği an
  const fotoKucukleri = new Map(); // "genel:123" -> küçük fotoğraf (tazelemede yeniden inmesin)
  let acikKare = null; // büyütülmüş anlık görüntünün kamerası (canlı yenilenir)

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

  function temizle(oge) {
    while (oge.firstChild) oge.removeChild(oge.firstChild);
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

  function saatMetni(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleTimeString("tr-TR", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: SAAT_DILIMI,
    });
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

  function duyur(metin) {
    if (metin === sonDuyuru) return;
    sonDuyuru = metin;
    $("duyuru").textContent = metin;
  }

  function fabrikaAdresi(veri) {
    const adres = veri && veri.fabrika_adresi;
    return adres && /^https?:\/\//.test(adres) ? adres : "";
  }

  // ------------------------------------------------------------- ekranlar

  function tekEkranGoster(ad) {
    $("kabuk").hidden = true;
    $("tek-ekran").hidden = false;
    for (const kimlik of ["yukleniyor", "kurulum", "giris"]) $(kimlik).hidden = kimlik !== ad;
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

  // ------------------------------------------------------------ görünüm

  /* Adresteki görünüm; görünüm olmayan bir çapa (ör. "İçeriğe geç" -> #icerik)
     açık görünümü değiştirmez. */
  function gorunumAdi() {
    const ad = location.hash.replace("#", "");
    return Object.prototype.hasOwnProperty.call(GORUNUMLER, ad) ? ad : null;
  }

  function gorunumuUygula() {
    const ad = gorunumAdi() || aktifGorunum;
    aktifGorunum = ad;
    for (const kutu of document.querySelectorAll(".gorunum")) {
      kutu.hidden = kutu.dataset.gorunum !== ad;
    }
    for (const bag of document.querySelectorAll(".menu-ogesi[data-gorunum], .sekme")) {
      if (bag.dataset.gorunum === ad) bag.setAttribute("aria-current", "page");
      else bag.removeAttribute("aria-current");
    }
    const [baslik, aciklama] = GORUNUMLER[ad];
    $("gorunum-basligi").textContent = baslik;
    $("gorunum-aciklamasi").textContent = ad === "genel" && kurulumMetni ? kurulumMetni : aciklama;
    // Müdahale ekranı bağlantıyı kendi bandında söyler; iki bant üst üste binmesin
    $("durum-bandi").hidden = ad === "mudahale";
    $("yol-adi").textContent = baslik;
    document.title = baslik + " · Uzak izleme panosu";
  }

  window.addEventListener("hashchange", function () {
    if (!gorunumAdi()) return;
    gorunumuUygula();
    window.scrollTo(0, 0);
    if ((aktifGorunum === "mudahale" || aktifGorunum === "kameralar") && sonVeri) {
      sonEtkilesim = Date.now();
      if (aktifGorunum === "mudahale") mudahaleyiCiz(sonVeri);
      else kareleriCiz(sonVeri);
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
    const liste = $("eksik-listesi");
    temizle(liste);
    for (const eksik of eksikler) {
      const satir = el("li");
      const govde = el("div", "satir-govde");
      govde.appendChild(el("b", "", eksik.ad));
      satir.appendChild(govde);
      const rozetler = el("div", "rozetler");
      rozetler.appendChild(rozet(eksik.neden, "tehlike"));
      satir.appendChild(rozetler);
      liste.appendChild(satir);
    }
    if (!$("onerilen-anahtar").textContent) $("onerilen-anahtar").textContent = onerilenAnahtar();
    tekEkranGoster("kurulum");
  }

  $("anahtar-kopyala").addEventListener("click", async function () {
    const metin = $("onerilen-anahtar").textContent;
    try {
      await navigator.clipboard.writeText(metin);
      this.textContent = "Kopyalandı";
    } catch (hata) {
      // Pano izni yoksa metni seçili bırak: kullanıcı kendisi kopyalar
      const secim = window.getSelection();
      const aralik = document.createRange();
      aralik.selectNodeContents($("onerilen-anahtar"));
      secim.removeAllRanges();
      secim.addRange(aralik);
      this.textContent = "Seçildi, kopyalayın";
    }
  });

  // ------------------------------------------------- durum bandı ve hap

  function durumBandiniCiz(veri) {
    const rapor = veri.rapor;
    const durum = baglantiDurumu(veri);
    const gecikme = gecikmeSn(veri);
    let sinif = "";
    let ikon = "i-sistem";
    let baslik = "";
    let alt = "";
    let hap = rozet("Rapor yok", "", true);

    if (durum === "hic") {
      baslik = "Fabrikadan henüz rapor gelmedi";
      alt =
        "Fabrika programında Ayarlar → Uzak izleme panosu bölümüne bu sitenin adresini ve " +
        "rapor anahtarını yazın, sonra sistemi yeniden başlatın.";
    } else if (durum === "kapandi") {
      ikon = "i-saat";
      baslik = "Fabrika programı kapatıldı";
      alt =
        "Program " + tarihSaatMetni(veri.son_rapor) + " saatinde kapatılırken son raporunu " +
        "gönderdi. Yeniden açılınca pano kendiliğinden güncellenir.";
      hap = rozet("Kapalı", "", true);
    } else if (durum === "yok") {
      sinif = "tehlike";
      ikon = "i-kopuk";
      baslik = "Fabrikadan " + sureMetni(gecikme) + " haber yok";
      alt =
        "Bilgisayar kapanmış, program durmuş ya da internet kesilmiş olabilir." +
        (rapor ? " Aşağıdaki bilgiler son rapordan (" + tarihSaatMetni(veri.son_rapor) + ")." : "");
      hap = rozet("Bağlantı yok", "tehlike", true);
    } else {
      const sistem = rapor.sistem;
      if (sistem.analiz === false) {
        sinif = "uyari";
        ikon = "i-uyari";
        baslik = "Program açık ama analiz çalışmıyor";
      } else if (sistem.hazir === false || sistem.sorunlar.length) {
        sinif = "tehlike";
        ikon = "i-uyari";
        baslik = "Sistem çalışıyor, dikkat gereken sorun var";
      } else {
        sinif = "basari";
        ikon = "i-tamam";
        baslik = "Sistem çalışıyor";
      }
      alt = "Son rapor " + sureMetni(gecikme) + " önce geldi.";
      hap = rozet("Canlı", "basari", true, true);
    }

    $("durum-bandi").className = "durum-bandi" + (sinif ? " " + sinif : "");
    $("durum-simgesi").setAttribute("href", "#" + ikon);
    $("durum-baslik").textContent = baslik;
    $("durum-alt").textContent = alt;
    const eski = $("baglanti-hapi");
    hap.id = "baglanti-hapi";
    eski.replaceWith(hap);
    $("son-rapor").textContent = veri.son_rapor ? "son rapor " + tarihSaatMetni(veri.son_rapor) : "";
    duyur(baslik);
  }

  // ------------------------------------------------------------- sayılar

  function duneGore(bugun, dun) {
    if (dun === 0 && bugun === 0) return "dün de ihlal yoktu";
    if (dun === 0) return "dün ihlal yoktu";
    return "dün " + sayiMetni(dun);
  }

  function sayilariCiz(rapor) {
    const s = rapor.sayilar;
    $("k-ihlal").textContent = sayiMetni(s.bugun_ihlal);
    $("k-ihlal-ref").textContent = duneGore(s.bugun_ihlal, s.dun_ihlal);
    const degisim = $("k-ihlal-degisim");
    const fark = s.bugun_ihlal - s.dun_ihlal;
    degisim.hidden = s.dun_ihlal === 0 && s.bugun_ihlal === 0;
    // Daha az ihlal iyi haber (yeşil), daha çok kötü haber (kırmızı)
    degisim.className = "degisim " + (fark > 0 ? "kotu" : fark < 0 ? "iyi" : "notr");
    degisim.textContent = fark > 0 ? "▲ " + fark : fark < 0 ? "▼ " + Math.abs(fark) : "=";
    degisim.setAttribute("aria-label", fark === 0 ? "dünkü ile aynı" : "düne göre " + fark);

    $("k-bekleyen").textContent = sayiMetni(s.bekleyen);
    $("k-bekleyen").classList.toggle("dikkat", s.bekleyen > 0);
    const y = rapor.yedi_gun;
    $("k-bekleyen-ref").textContent =
      y && y.ihlal
        ? "son 7 günde inceleme oranı %" + Math.round((y.incelenen / y.ihlal) * 100)
        : s.bekleyen
          ? "fabrika ekranında incelenir"
          : "kuyruk boş";

    const pasif = rapor.kameralar.filter((k) => k.durum === "pasif").length;
    const kopuk = kopukKameraSayisi(rapor);
    $("k-kamera").textContent = s.kamera_canli + " / " + s.kamera_toplam;
    $("k-kamera").classList.toggle("dikkat", kopuk > 0);
    let not = "hepsi görüntü veriyor";
    if (s.kamera_toplam === 0) not = "henüz kamera eklenmedi";
    else if (kopuk > 0) not = kopuk + " kamera görüntü vermiyor";
    else if (pasif > 0) not = pasif + " kamera pasif";
    $("k-kamera-ref").textContent = not;

    $("k-kural").textContent = sayiMetni(s.aktif_kural);
    $("k-kural").classList.toggle("dikkat", s.aktif_kural === 0);
    $("k-kural-ref").textContent = s.aktif_kural ? "uyarı üreten kural" : "kural kurulmadan ihlal üretilmez";
  }

  function kopukKameraSayisi(rapor) {
    return rapor.kameralar.filter((k) => k.durum !== "pasif" && k.durum !== "online").length;
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

  function sorunlariCiz(rapor) {
    const sorunlar = rapor ? rapor.sistem.sorunlar : [];
    const liste = $("sorun-listesi");
    temizle(liste);
    for (const metin of sorunlar) {
      const satir = el("li");
      satir.appendChild(simge("i-uyari"));
      satir.appendChild(el("span", "", metin));
      liste.appendChild(satir);
    }
    $("sorunlar").hidden = sorunlar.length === 0;
  }

  // ------------------------------------------------------------ kameralar

  function kameraAyrintisi(k) {
    if (k.durum === "online" && k.islenen_fps !== null) {
      return "işlenen " + ondalik(k.islenen_fps) + (k.hedef_fps ? " / " + ondalik(k.hedef_fps) : "") + " kare/sn";
    }
    if (k.durum !== "pasif" && k.son_kare_yasi_sn !== null) {
      return "son görüntü " + sureMetni(k.son_kare_yasi_sn) + " önce";
    }
    return "";
  }

  function kameraRozetleri(k) {
    const kutu = el("div", "rozetler");
    const [ad, sinif] = KAMERA_DURUMLARI[k.durum] || KAMERA_DURUMLARI.offline;
    kutu.appendChild(rozet(ad, sinif, true));
    if (k.yavas) kutu.appendChild(rozet("Yavaş", "uyari"));
    return kutu;
  }

  function kameraSatiri(k, ayrintili) {
    const satir = el("li");
    const govde = el("div", "satir-govde");
    govde.appendChild(el("b", "", k.ad));
    const parcalar = [];
    if (k.bolum) parcalar.push(k.bolum);
    if (ayrintili) {
      const ayrinti = kameraAyrintisi(k);
      if (ayrinti) parcalar.push(ayrinti);
    }
    if (parcalar.length) govde.appendChild(el("span", "", parcalar.join(" · ")));
    satir.appendChild(govde);
    satir.appendChild(kameraRozetleri(k));
    return satir;
  }

  function bosDurum(baslik, metin) {
    const kutu = el("li", "bos");
    kutu.appendChild(simge("i-genel", "buyuk"));
    kutu.appendChild(el("b", "", baslik));
    if (metin) kutu.appendChild(el("span", "", metin));
    return kutu;
  }

  function kameraSuz(k) {
    if (kameraSuzgeci === "canli") return k.durum === "online";
    if (kameraSuzgeci === "sorunlu") return k.durum !== "online" && k.durum !== "pasif";
    if (kameraSuzgeci === "pasif") return k.durum === "pasif";
    return true;
  }

  function kameralariCiz(rapor) {
    const kameralar = rapor.kameralar;
    // Genel bakış: sorunlu olanlar önde, en çok 5
    const genel = $("genel-kameralar");
    temizle(genel);
    const sira = { offline: 0, connecting: 1, online: 2, pasif: 3 };
    const sirali = [...kameralar].sort((a, b) => (sira[a.durum] ?? 0) - (sira[b.durum] ?? 0));
    if (!kameralar.length) genel.appendChild(bosDurum("Henüz kamera eklenmedi", ""));
    for (const k of sirali.slice(0, 5)) genel.appendChild(kameraSatiri(k, false));

    // Süzgeç çiplerinin sayıları
    const sayilar = {
      hepsi: kameralar.length,
      canli: kameralar.filter((k) => k.durum === "online").length,
      sorunlu: kopukKameraSayisi(rapor),
      pasif: kameralar.filter((k) => k.durum === "pasif").length,
    };
    for (const sayac of document.querySelectorAll("[data-cip]")) {
      sayac.textContent = String(sayilar[sayac.dataset.cip]);
    }

    const gorunen = kameralar.filter(kameraSuz);
    const liste = $("kamera-listesi");
    const tablo = $("kamera-tablosu");
    temizle(liste);
    temizle(tablo);
    if (!gorunen.length) {
      liste.appendChild(bosDurum("Bu süzgeçte kamera yok", ""));
      const satir = el("tr");
      const hucre = el("td", "", "Bu süzgeçte kamera yok.");
      hucre.colSpan = 5;
      satir.appendChild(hucre);
      tablo.appendChild(satir);
    }
    for (const k of gorunen) {
      liste.appendChild(kameraSatiri(k, true));

      const satir = el("tr");
      const ad = el("td");
      ad.appendChild(el("b", "", k.ad));
      if (k.bolum) ad.appendChild(el("span", "alt", k.bolum));
      satir.appendChild(ad);
      const durum = el("td");
      durum.appendChild(kameraRozetleri(k));
      satir.appendChild(durum);
      const islenen = k.islenen_fps === null ? "-" : ondalik(k.islenen_fps) + (k.hedef_fps ? " / " + ondalik(k.hedef_fps) : "");
      satir.appendChild(el("td", "sag sayi", islenen));
      satir.appendChild(el("td", "sag sayi", ondalik(k.okunan_fps)));
      satir.appendChild(
        el("td", "sag sayi", k.son_kare_yasi_sn === null ? "-" : sureMetni(k.son_kare_yasi_sn) + " önce")
      );
      tablo.appendChild(satir);
    }
  }

  // ------------------------------------------------------- anlık görüntü

  function kareIzleniyor() {
    return aktifGorunum === "kameralar" && Date.now() - sonEtkilesim < DINLEME_SURESI_MS;
  }

  function kareAdresi(kimlik, zaman) {
    return "/api/kare?kamera=" + kimlik + "&z=" + encodeURIComponent(zaman);
  }

  function kareYasi(zaman) {
    return zaman ? Math.max(0, (simdiMs() - Date.parse(zaman)) / 1000) : null;
  }

  function yasMetni(yas) {
    return yas < 3 ? "az önce" : sureMetni(yas) + " önce";
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
    return "10 saniyede bir yenilenir; yalnız bu ekran açıkken gelir.";
  }

  /* Kutu kamera kimliğiyle bir kez kurulur ve yerinde güncellenir: resim
     yalnız yeni kare gelince yeniden istenir, eski kare yenisi inene kadar
     ekranda kalır (titremez). */
  function kareKutusu(k) {
    const kutu = { kamera: k, zaman: "" };
    kutu.figur = el("figure", "kare");
    kutu.dugme = el("button", "kare-resim");
    kutu.dugme.type = "button";
    kutu.resim = el("img");
    kutu.resim.alt = "";
    kutu.resim.decoding = "async";
    kutu.resim.hidden = true;
    kutu.resim.addEventListener("load", function () {
      if (kutu.zaman) kutu.resim.hidden = false;
    });
    kutu.resim.addEventListener("error", function () {
      // Kare istekle gösterim arasında silinmiş olabilir: bir sonraki kare bekler
      kutu.zaman = "";
      kutu.resim.hidden = true;
      kutu.bos.hidden = false;
      kutu.bosMetni.textContent = "Görüntü alınamadı";
      kutu.dugme.disabled = true;
    });
    kutu.bos = el("span", "kare-bos");
    kutu.bos.appendChild(simge("i-kamera", "buyuk"));
    kutu.bosMetni = el("span");
    kutu.bos.appendChild(kutu.bosMetni);
    kutu.rozetYeri = el("span", "kare-rozet");
    kutu.dugme.append(kutu.resim, kutu.bos, kutu.rozetYeri);
    const yazi = el("figcaption");
    kutu.ad = el("b");
    kutu.alt = el("span");
    yazi.append(kutu.ad, kutu.alt);
    kutu.figur.append(kutu.dugme, yazi);
    kutu.dugme.addEventListener("click", function () {
      if (!kutu.zaman) return;
      acikKare = kutu.kamera.id;
      fotoGoster(kutu.resim.src, kutu.kamera.ad, kareAciklamasi(kutu));
    });
    return kutu;
  }

  function kareAciklamasi(kutu) {
    const yas = kareYasi(kutu.zaman);
    return [kutu.kamera.bolum, yas === null ? "" : "görüntü " + yasMetni(yas)]
      .filter(Boolean)
      .join(" · ");
  }

  function kareBosMetni(veri, k, izleniyor) {
    if (baglantiDurumu(veri) !== "canli") return "Fabrikadan haber yok";
    if (!izleniyor) return "Görüntü beklemede";
    if (k.durum === "offline") return "Kameradan görüntü gelmiyor";
    if (k.durum === "connecting") return "Kamera yeniden bağlanıyor";
    return "Görüntü bekleniyor";
  }

  function kareKutusunuGuncelle(veri, kutu, k, zaman, izleniyor) {
    kutu.kamera = k;
    kutu.ad.textContent = k.ad;
    const [durumAdi, durumSinifi] = KAMERA_DURUMLARI[k.durum] || KAMERA_DURUMLARI.offline;
    temizle(kutu.rozetYeri);
    kutu.rozetYeri.appendChild(rozet(durumAdi, durumSinifi, true));
    if (!zaman) {
      kutu.zaman = "";
      kutu.resim.hidden = true;
      kutu.resim.removeAttribute("src");
    } else if (zaman !== kutu.zaman) {
      kutu.zaman = zaman;
      kutu.resim.src = kareAdresi(k.id, zaman);
      if (acikKare === k.id && $("foto-penceresi").open) $("foto-buyuk").src = kutu.resim.src;
    }
    kutu.bos.hidden = !!kutu.zaman;
    kutu.bosMetni.textContent = kareBosMetni(veri, k, izleniyor);
    const yas = kareYasi(kutu.zaman);
    kutu.figur.classList.toggle("bayat", yas !== null && yas > KARE_BAYAT_SN);
    kutu.alt.textContent = [k.bolum, yas === null ? "" : yasMetni(yas)].filter(Boolean).join(" · ");
    kutu.dugme.disabled = !kutu.zaman;
    kutu.dugme.setAttribute("aria-label", k.ad + ", " + durumAdi + (kutu.zaman ? ": görüntüyü büyüt" : ""));
    if (acikKare === k.id && $("foto-penceresi").open) $("foto-alt").textContent = kareAciklamasi(kutu);
  }

  function kareleriCiz(veri) {
    const rapor = veri.rapor;
    const bolum = $("kare-bolumu");
    bolum.hidden = !rapor || !rapor.kameralar.length;
    if (bolum.hidden) return;
    // Pasif kamera görüntü vermez; kimliği olmayan kamerayı eski program gönderir
    const kimlikli = rapor.kameralar.filter((k) => k.id && k.durum !== "pasif");
    const izleniyor = kareIzleniyor();
    // Görüntü yalnız ?kare=1 ile gelen cevapta vardır; öbür cevapta kutular bekler
    const kareler = (izleniyor && veri.kareler) || {};
    $("kare-alt").textContent = kareAltMetni(veri, kimlikli, izleniyor, kareler);
    $("kare-surdur").hidden = izleniyor || !kimlikli.length || baglantiDurumu(veri) !== "canli";

    const imza = kimlikli.map((k) => k.id).join(",");
    if (imza !== kareImzasi) {
      kareImzasi = imza;
      temizle($("kare-izgarasi"));
      kareKutulari.clear();
      for (const k of kimlikli) {
        const kutu = kareKutusu(k);
        kareKutulari.set(k.id, kutu);
        $("kare-izgarasi").appendChild(kutu.figur);
      }
    }
    $("kare-izgarasi").hidden = !kimlikli.length;
    for (const k of kimlikli) {
      kareKutusunuGuncelle(veri, kareKutulari.get(k.id), k, kareler[String(k.id)] || "", izleniyor);
    }
  }

  $("kare-surdur").addEventListener("click", function () {
    sonEtkilesim = Date.now();
    if (sonVeri) kareleriCiz(sonVeri);
    yukle();
  });

  // -------------------------------------------------- fotoğraf penceresi

  function fotoGoster(adres, baslik, aciklama) {
    $("foto-buyuk").src = adres;
    $("foto-buyuk").alt = baslik;
    $("foto-baslik").textContent = baslik;
    $("foto-alt").textContent = aciklama;
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

  for (const cip of document.querySelectorAll("#kamera-cipleri .cip")) {
    cip.addEventListener("click", function () {
      kameraSuzgeci = this.dataset.suzgec;
      for (const diger of document.querySelectorAll("#kamera-cipleri .cip")) {
        diger.setAttribute("aria-pressed", String(diger === this));
      }
      if (sonVeri && sonVeri.rapor) kameralariCiz(sonVeri.rapor);
    });
  }

  // -------------------------------------------------------------- olaylar

  function olaySatiri(o, liste) {
    const satir = el("li");
    const sistem = o.tur === "sistem";
    const kutu = el("span", "ikon-kutu " + (sistem ? "" : ONEM_KUTUSU[o.onem] || "gri"));
    kutu.appendChild(simge(sistem ? "i-sistem" : o.onem === "critical" ? "i-siren" : "i-uyari"));
    satir.appendChild(kutu);

    const govde = el("div", "cizelge-govde");
    govde.appendChild(el("b", "", o.baslik));
    if (o.yer) govde.appendChild(el("span", "", o.yer));
    if (o.ayrinti) govde.appendChild(el("span", "olay-ayrinti", o.ayrinti));
    const rozetler = el("div", "rozetler");
    if (sistem) rozetler.appendChild(rozet("Sistem", "bilgi"));
    else if (o.onem_adi) rozetler.appendChild(rozet(o.onem_adi, ONEM_ROZETI[o.onem] || ""));
    if (o.suruyor) rozetler.appendChild(rozet("Sürüyor" + (o.sure ? " · " + o.sure : ""), "uyari"));
    if (o.durum_adi) rozetler.appendChild(rozet(o.durum_adi, ""));
    if (rozetler.childNodes.length) govde.appendChild(rozetler);
    if (o.foto && o.id) govde.appendChild(fotoKucuk(o, liste));
    satir.appendChild(govde);

    const zaman = el("time", "cizelge-zaman");
    if (o.zaman) {
      zaman.dateTime = o.zaman;
      zaman.appendChild(el("b", "", saatMetni(o.zaman)));
      const gun = gunEtiketi(o.zaman);
      if (gun) zaman.appendChild(el("span", "", gun));
    } else {
      zaman.textContent = "-";
    }
    satir.appendChild(zaman);
    return satir;
  }

  /* Kanıt fotoğrafının küçüğü; dokununca büyür. Liste her tazelemede yeniden
     kurulur ama küçük fotoğraf aynı öğedir (yeni satıra taşınır): resim
     yeniden inmez, ekran titremez. Gelmeyen fotoğraf FOTO_YENIDEN_MS
     geçmeden yeniden istenmez. */
  function fotoKucuk(o, liste) {
    const anahtar = liste + ":" + o.id;
    const hazir = fotoKucukleri.get(anahtar);
    if (hazir) return hazir;
    const hata = fotoHatalari.get(o.id);
    if (hata && Date.now() - hata < FOTO_YENIDEN_MS) return el("span", "foto-yok", "Fotoğraf alınamadı");
    const adres = "/api/foto?olay=" + o.id;
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
      fotoKucukleri.delete(anahtar);
      dugme.replaceWith(el("span", "foto-yok", "Fotoğraf alınamadı"));
    });
    resim.src = adres;
    dugme.appendChild(resim);
    dugme.addEventListener("click", function () {
      acikKare = null;
      fotoGoster(adres, o.baslik, [o.yer, tarihSaatMetni(o.zaman)].filter(Boolean).join(" · "));
    });
    fotoKucukleri.set(anahtar, dugme);
    return dugme;
  }

  function olaylariCiz(rapor) {
    const genel = $("genel-olaylar");
    temizle(genel);
    if (!rapor.son_olaylar.length) genel.appendChild(bosDurum("Henüz olay yok", ""));
    for (const o of rapor.son_olaylar.slice(0, GENEL_OLAY_SAYISI)) genel.appendChild(olaySatiri(o, "genel"));

    const liste = $("olay-cizelgesi");
    temizle(liste);
    const gorunen = rapor.son_olaylar.filter((o) => olayTuru === "hepsi" || o.tur === olayTuru);
    if (!gorunen.length) liste.appendChild(bosDurum("Bu türde olay yok", "Son 20 olayın içinde"));
    for (const o of gorunen) liste.appendChild(olaySatiri(o, "olaylar"));
    // Listeden düşen olayın küçük fotoğrafı unutulur
    for (const [anahtar, dugme] of fotoKucukleri) {
      if (!dugme.isConnected) fotoKucukleri.delete(anahtar);
    }
  }

  for (const dugme of document.querySelectorAll("#olay-segmenti button")) {
    dugme.addEventListener("click", function () {
      olayTuru = this.dataset.tur;
      for (const diger of document.querySelectorAll("#olay-segmenti button")) {
        diger.setAttribute("aria-pressed", String(diger === this));
      }
      if (sonVeri && sonVeri.rapor) olaylariCiz(sonVeri.rapor);
    });
  }

  // --------------------------------------------------- grafik ve lejant

  function saatligiCiz(rapor) {
    const degerler = rapor.saatlik;
    const kutu = $("saatlik");
    const etiketler = $("saat-etiketleri");
    temizle(kutu);
    temizle(etiketler);
    const enCok = Math.max(...degerler);
    const toplam = degerler.reduce((a, b) => a + b, 0);
    const simdikiSaat =
      Number(
        new Date(simdiMs()).toLocaleString("en-GB", { hour: "2-digit", hour12: false, timeZone: SAAT_DILIMI })
      ) % 24;
    degerler.forEach(function (n, saat) {
      const sutun = el("div", "sutun" + (n > 0 ? " dolu" : "") + (saat === simdikiSaat ? " simdi" : ""));
      sutun.title = String(saat).padStart(2, "0") + ":00 · " + n + " ihlal";
      const dolgu = el("div", "dolgu");
      // CSP satır içi stile izin vermez; yükseklik CSSOM ile verilir. Boş
      // saat de ince bir iz bırakır: grafik günün tamamını gösterir.
      dolgu.style.height = enCok && n ? Math.max(6, Math.round((n / enCok) * 100)) + "%" : "4px";
      sutun.appendChild(dolgu);
      kutu.appendChild(sutun);
      etiketler.appendChild(el("span", "", saat % 6 === 0 ? String(saat).padStart(2, "0") : ""));
    });
    let ozet = "Bugün henüz ihlal yok";
    if (toplam) {
      const tepe = degerler.indexOf(enCok);
      ozet =
        "Toplam " + sayiMetni(toplam) + " · en yoğun " + String(tepe).padStart(2, "0") + ":00 - " +
        String((tepe + 1) % 24).padStart(2, "0") + ":00 (" + enCok + ")";
    }
    $("saatlik-ozet").textContent = ozet;
    kutu.setAttribute("aria-label", "Bugün saat saat ihlal. " + ozet);
  }

  function ogeleriCiz(rapor) {
    const liste = $("ogeler");
    temizle(liste);
    if (!rapor.ogeler.length) {
      liste.appendChild(bosDurum("Son 7 günde ihlal yok", ""));
      return;
    }
    lejantCiz(liste, rapor.ogeler, (o) => o.ad);
  }

  // ------------------------------------------------------- yönetici özeti

  function toplamAl(dizi) {
    return dizi.reduce((a, b) => a + b, 0);
  }

  function yerAdi(yer) {
    return yer.ad + (yer.bolum ? " (" + yer.bolum + ")" : "");
  }

  /* Patronun tek bakışta okuyacağı cümleler: önce sorun, sonra bugün, eğilim,
     en çok ihlal görülen yer, inceleme ve kameralar. Hepsi rapordaki sayıdan
     kurulur; tahmin ya da puan yoktur. */
  function ozetCumleleri(rapor) {
    const s = rapor.sayilar;
    const satirlar = [];
    if (rapor.sistem.analiz === false) {
      satirlar.push(["i-uyari", "gul", "Program açık ama analiz çalışmıyor: şu an ihlal yakalanmıyor."]);
    }
    const fark = s.bugun_ihlal - s.dun_ihlal;
    let bugun =
      s.bugun_ihlal === 0 ? "Bugün henüz ihlal yakalanmadı" : "Bugün " + sayiMetni(s.bugun_ihlal) + " ihlal yakalandı";
    if (s.bugun_ihlal || s.dun_ihlal) {
      bugun += fark < 0 ? ", dünden " + -fark + " az." : fark > 0 ? ", dünden " + fark + " fazla." : ", dünle aynı.";
    } else {
      bugun += ".";
    }
    satirlar.push(["i-siren", fark > 0 ? "gul" : "yesil", bugun]);
    if (rapor.gunluk) {
      const bu = toplamAl(rapor.gunluk.slice(7));
      const gecen = toplamAl(rapor.gunluk.slice(0, 7));
      let metin = "Son 7 günde " + sayiMetni(bu) + " ihlal";
      if (gecen === 0) metin += bu ? "; önceki 7 günde hiç yoktu." : ".";
      else if (bu === gecen) metin += ", önceki 7 günle aynı.";
      else metin += "; önceki 7 güne göre %" + Math.round((Math.abs(bu - gecen) / gecen) * 100) + (bu < gecen ? " azaldı." : " arttı.");
      satirlar.push(["i-rapor", bu > gecen ? "gul" : "yesil", metin]);
    }
    const yer = rapor.yerler && rapor.yerler[0];
    const tur = rapor.ogeler[0];
    if (yer && yer.sayi > 0) {
      satirlar.push([
        "i-kamera",
        "bal",
        "En çok ihlal " + yerAdi(yer) + " kamerasında: " + sayiMetni(yer.sayi) + " (son 7 gün)" +
          (tur ? "; en sık tür " + tur.ad.toLocaleLowerCase("tr") + "." : "."),
      ]);
    } else if (tur) {
      satirlar.push(["i-uyari", "bal", "Son 7 günün en sık ihlali: " + tur.ad.toLocaleLowerCase("tr") + "."]);
    }
    satirlar.push(
      s.bekleyen > 0
        ? ["i-inceleme", "bal", sayiMetni(s.bekleyen) + " ihlal fabrikada incelenmeyi bekliyor."]
        : ["i-tamam", "yesil", "İncelenmeyi bekleyen ihlal yok."]
    );
    const kopuk = kopukKameraSayisi(rapor);
    if (s.kamera_toplam === 0) satirlar.push(["i-kamera", "gri", "Henüz kamera eklenmedi."]);
    else if (kopuk) satirlar.push(["i-kopuk", "gul", kopuk + " kamera görüntü vermiyor; o alanlar şu an izlenmiyor."]);
    else satirlar.push(["i-tamam", "yesil", "Açık bütün kameralar görüntü veriyor."]);
    return satirlar;
  }

  function ozetiCiz(rapor) {
    const liste = $("ozet-listesi");
    temizle(liste);
    for (const [ikon, ton, metin] of ozetCumleleri(rapor)) {
      const satir = el("li");
      const kutu = el("span", "ikon-kutu " + ton);
      kutu.appendChild(simge(ikon));
      satir.appendChild(kutu);
      satir.appendChild(el("span", "", metin));
      liste.appendChild(satir);
    }
  }

  function gunlukCiz(rapor) {
    const kart = $("gunluk-kart");
    kart.hidden = !rapor.gunluk;
    if (!rapor.gunluk) return;
    const g = rapor.gunluk;
    const kutu = $("gunluk");
    const etiketler = $("gun-etiketleri");
    temizle(kutu);
    temizle(etiketler);
    const enCok = Math.max(...g);
    g.forEach(function (n, i) {
      const gun = new Date(simdiMs() - (13 - i) * 86400000);
      const tarih = gun.toLocaleDateString("tr-TR", { day: "numeric", month: "long", weekday: "long", timeZone: SAAT_DILIMI });
      const sutun = el("div", "sutun" + (n > 0 ? " dolu" : "") + (i === 13 ? " simdi" : ""));
      sutun.title = tarih + " · " + n + " ihlal";
      const dolgu = el("div", "dolgu");
      dolgu.style.height = enCok && n ? Math.max(6, Math.round((n / enCok) * 100)) + "%" : "4px";
      sutun.appendChild(dolgu);
      kutu.appendChild(sutun);
      const etiket = el("span", i === 13 ? "bugun" : "", gun.toLocaleDateString("tr-TR", { day: "numeric", timeZone: SAAT_DILIMI }));
      etiketler.appendChild(etiket);
    });
    const bu = toplamAl(g.slice(7));
    const gecen = toplamAl(g.slice(0, 7));
    $("gunluk-ozet").textContent =
      "Son 7 gün " + sayiMetni(bu) + ", önceki 7 gün " + sayiMetni(gecen) + " ihlal · günde ortalama " + ondalik(bu / 7);
    const degisim = $("hafta-degisim");
    const fark = bu - gecen;
    degisim.className = "degisim " + (fark > 0 ? "kotu" : fark < 0 ? "iyi" : "notr");
    degisim.textContent =
      fark === 0 ? "=" : (fark > 0 ? "▲ " : "▼ ") + (gecen ? "%" + Math.round((Math.abs(fark) / gecen) * 100) : Math.abs(fark));
    degisim.setAttribute("aria-label", fark === 0 ? "önceki haftayla aynı" : "önceki haftaya göre " + (fark > 0 ? "arttı" : "azaldı"));
    kutu.setAttribute("aria-label", "Son 14 gün günlük ihlal sayıları. " + $("gunluk-ozet").textContent);
    const y = rapor.yedi_gun;
    $("inceleme-ozeti").textContent =
      y && y.ihlal
        ? "Son 7 günde inceleme oranı %" + Math.round((y.incelenen / y.ihlal) * 100) +
          (y.yanlis_alarm ? " · yanlış alarm " + sayiMetni(y.yanlis_alarm) : " · yanlış alarm yok")
        : "";
  }

  /* İhlal türleri ve yerler aynı çizimle: ad, sayı ve en büyüğe göre çubuk. */
  function lejantCiz(liste, ogeler, adAl) {
    temizle(liste);
    const enCok = Math.max(...ogeler.map((o) => o.sayi));
    for (const o of ogeler) {
      const satir = el("li");
      const ust = el("div", "ust");
      ust.appendChild(el("span", "centik"));
      ust.appendChild(el("span", "", adAl(o)));
      ust.appendChild(el("b", "", sayiMetni(o.sayi)));
      satir.appendChild(ust);
      const iz = el("span", "iz");
      const dolgu = el("i");
      dolgu.style.width = enCok ? Math.max(3, Math.round((o.sayi / enCok) * 100)) + "%" : "0";
      iz.appendChild(dolgu);
      satir.appendChild(iz);
      liste.appendChild(satir);
    }
  }

  function yerleriCiz(rapor) {
    const yerler = (rapor.yerler || []).filter((y) => y.sayi > 0);
    $("yerler-kart").hidden = !rapor.yerler || !rapor.yerler.length;
    if (yerler.length) lejantCiz($("yerler"), yerler, yerAdi);
    else {
      temizle($("yerler"));
      $("yerler").appendChild(bosDurum("Son 7 günde ihlal yok", ""));
    }
  }

  function bilgisayariCiz(rapor) {
    const b = rapor && rapor.bilgisayar;
    $("bilgisayar-yok").hidden = !!b;
    const liste = $("bilgisayar-bilgisi");
    temizle(liste);
    kurulumMetni = b ? [b.ad, b.bilgisayar_adi].filter(Boolean).join(" · ") : "";
    if (!b) return;
    const bos = rapor.sistem.bos_disk_gb;
    const satirlar = [
      ["Kurulum", b.ad],
      ["Bilgisayar adı", b.bilgisayar_adi],
      ["IP adresi", (b.ip || []).join(", ")],
      ["İşletim sistemi", b.isletim_sistemi],
      ["İşlemci", b.islemci + (b.islemci && b.cekirdek ? " · " + b.cekirdek + " çekirdek" : "")],
      ["Bellek", b.bellek_gb ? ondalik(b.bellek_gb) + " GB" : ""],
      ["Ekran kartı", b.ekran_karti],
      ["Tespit nerede çalışıyor", b.cikarim],
      [
        "Disk",
        b.disk_toplam_gb
          ? (bos !== null ? ondalik(bos) + " GB boş / " : "") + ondalik(b.disk_toplam_gb) + " GB"
          : "",
      ],
      ["Kurulum türü", b.kurulum_turu],
      ["Kurulum tarihi", b.kurulum_tarihi ? gunMetni(b.kurulum_tarihi) : ""],
      ["Bilgisayar açık", b.acilis ? sureMetni((simdiMs() - Date.parse(b.acilis)) / 1000) : ""],
    ];
    for (const [ad, deger] of satirlar) {
      if (!deger) continue;
      const satir = el("div");
      satir.appendChild(el("dt", "", ad));
      satir.appendChild(el("dd", "", deger));
      liste.appendChild(satir);
    }
  }

  // ------------------------------------------------------------- müdahale

  function dinleniyor() {
    return aktifGorunum === "mudahale" && Date.now() - sonEtkilesim < DINLEME_SURESI_MS;
  }

  function kanalAdi(kanal) {
    return kanal.ad + (kanal.bolum ? " (" + kanal.bolum + ")" : " (Tüm fabrika)");
  }

  /* Müdahalenin şu an yapılıp yapılamayacağı ve neden. */
  function mudahaleHali(veri) {
    const rapor = veri.rapor;
    const m = rapor && rapor.mudahale;
    if (!rapor || baglantiDurumu(veri) !== "canli") {
      return {
        acik: false,
        sinif: "tehlike",
        ikon: "i-kopuk",
        baslik: "Fabrikadan haber gelmiyor",
        alt: "Fabrika programı çalışmıyor ya da internete bağlı değil; müdahale gönderilemez.",
      };
    }
    if (!m || !m.acik) {
      return {
        acik: false,
        sinif: "",
        ikon: "i-kilit",
        baslik: "Uzaktan müdahale kapalı",
        alt:
          "Fabrikadaki bilgisayarda Ayarlar → Uzak izleme panosu → Uzaktan müdahale'yi " +
          "\"Açık\" yapıp sistemi yeniden başlatın. Kapalıyken pano yalnız izler.",
      };
    }
    if (rapor.sistem.analiz === false) {
      return {
        acik: false,
        sinif: "uyari",
        ikon: "i-uyari",
        baslik: "Analiz çalışmıyor",
        alt: "Anons ve deneme sesi analizin kuyruğundan çalar; önce fabrikada sistemi başlatın.",
      };
    }
    if (!m.kanallar.length) {
      return {
        acik: false,
        sinif: "uyari",
        ikon: "i-anons",
        baslik: "Açık ses kanalı yok",
        alt: "Fabrikada Anons ekranında açık bir hoparlör kanalı olmadan anons çalınamaz.",
      };
    }
    if (!dinleniyor()) {
      return {
        acik: true,
        bekliyor: true,
        sinif: "",
        ikon: "i-saat",
        baslik: "Dinleme beklemede",
        alt: "Ekrana 10 dakikadır dokunulmadı. Fabrikanın komutları sık sorması için sürdürün.",
      };
    }
    const yas = veri.mudahale ? veri.mudahale.yoklama_yasi_sn : null;
    if (yas !== null && yas !== undefined && yas <= DINLIYOR_SN) {
      return {
        acik: true,
        sinif: "basari",
        ikon: "i-tamam",
        baslik: "Fabrika komutları dinliyor",
        alt: "Son soru " + sureMetni(yas) + " önce. Gönderdiğiniz komut birkaç saniyede çalar.",
      };
    }
    return {
      acik: true,
      sinif: "uyari",
      ikon: "i-saat",
      baslik: "Fabrika birazdan dinlemeye başlar",
      alt:
        "Bu ekran açıkken fabrika bir sonraki raporunda (en çok " + rapor.aralik_sn +
        " saniye) sık sormaya başlar. Komutu şimdi gönderebilirsiniz; sırada bekler.",
    };
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
        anonsOnayiniKapat();
      });
      secim.appendChild(girdi);
      secim.appendChild(el("span", "", ms.metin));
      kutu.appendChild(secim);
    }

    const secici = $("anons-kanali");
    const onceki = secici.value;
    temizle(secici);
    if (kanallar.some((k) => !k.bolum)) {
      const tum = el("option", "", "Tüm fabrika kanalları");
      tum.value = "";
      secici.appendChild(tum);
    }
    for (const k of kanallar) {
      const secenek = el("option", "", kanalAdi(k));
      secenek.value = String(k.id);
      secici.appendChild(secenek);
    }
    if ([...secici.options].some((o) => o.value === onceki)) secici.value = onceki;

    const liste = $("kanal-listesi");
    temizle(liste);
    if (!kanallar.length) liste.appendChild(bosDurum("Açık ses kanalı yok", "Fabrikada Anons ekranından eklenir"));
    for (const k of kanallar) {
      const satir = el("li");
      const govde = el("div", "satir-govde");
      govde.appendChild(el("b", "", k.ad));
      govde.appendChild(el("span", "", k.bolum || "Tüm fabrika"));
      satir.appendChild(govde);
      const dugme = el("button", "dugme ikincil", "Dene");
      dugme.type = "button";
      dugme.dataset.kanal = String(k.id);
      dugme.addEventListener("click", denemeTiklandi);
      satir.appendChild(dugme);
      liste.appendChild(satir);
    }
  }

  function komutSatiri(k) {
    const satir = el("li");
    const [ad, sinif, varsayilan] = KOMUT_DURUMLARI[k.durum] || KOMUT_DURUMLARI.hata;
    const kutu = el("span", "ikon-kutu " + ({ basari: "yesil", tehlike: "gul", uyari: "bal" }[sinif] || "gri"));
    kutu.appendChild(simge(k.tur === "ses_dene" ? "i-sistem" : "i-anons"));
    satir.appendChild(kutu);
    const govde = el("div", "cizelge-govde");
    govde.appendChild(el("b", "", k.ozet));
    const aciklama = k.mesaj || varsayilan;
    if (aciklama) govde.appendChild(el("span", "", aciklama));
    const rozetler = el("div", "rozetler");
    const suruyor = k.durum === "bekliyor" || k.durum === "iletildi";
    rozetler.appendChild(rozet(ad, sinif, true, suruyor));
    govde.appendChild(rozetler);
    satir.appendChild(govde);
    const zaman = el("time", "cizelge-zaman");
    zaman.dateTime = k.olusturuldu;
    zaman.appendChild(el("b", "", saatMetni(k.olusturuldu)));
    const gun = gunEtiketi(k.olusturuldu);
    if (gun) zaman.appendChild(el("span", "", gun));
    satir.appendChild(zaman);
    return satir;
  }

  function komutlariCiz(veri) {
    const sunucudan = (veri.mudahale && veri.mudahale.komutlar) || [];
    // Gönderilip henüz sunucudan okunmayan komut da görünür
    const bilinen = new Set(sunucudan.map((k) => k.id));
    bekleyenKomutlar = bekleyenKomutlar.filter((k) => !bilinen.has(k.id));
    const komutlar = [...bekleyenKomutlar, ...sunucudan];
    const liste = $("komut-listesi");
    temizle(liste);
    if (!komutlar.length) liste.appendChild(bosDurum("Henüz müdahale yok", "Gönderdiğiniz anons burada görünür"));
    for (const k of komutlar) liste.appendChild(komutSatiri(k));
  }

  function mudahaleyiCiz(veri) {
    const hal = mudahaleHali(veri);
    $("mudahale-durumu").className = "durum-bandi" + (hal.sinif ? " " + hal.sinif : "");
    $("mudahale-simgesi").setAttribute("href", "#" + hal.ikon);
    $("mudahale-baslik").textContent = hal.baslik;
    $("mudahale-alt").textContent = hal.alt;
    $("dinlemeyi-surdur").hidden = !hal.bekliyor;
    secenekleriCiz(veri.rapor && veri.rapor.mudahale);
    const kilitli = !hal.acik;
    for (const oge of document.querySelectorAll(
      "#anons-formu input, #anons-formu select, #anons-formu button, #kanal-listesi button"
    )) {
      oge.disabled = kilitli;
    }
    if (kilitli) anonsOnayiniKapat();
    komutlariCiz(veri);
  }

  function anonsOnayiniKapat() {
    $("anons-onayi").hidden = true;
    $("anons-dugmesi").hidden = false;
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
      sonVeri = null;
      tekEkranGoster("giris");
      throw new Error("Oturumun süresi doldu; yeniden giriş yapın.");
    }
    if (!yanit.ok) throw new Error(veri.mesaj || "Gönderilemedi (HTTP " + yanit.status + ").");
    bekleyenKomutlar.unshift(veri.komut);
    if (sonVeri) komutlariCiz(sonVeri);
    duyur("Komut gönderildi: " + veri.komut.ozet);
    return veri.komut;
  }

  $("anons-dugmesi").addEventListener("click", function () {
    $("anons-hatasi").textContent = "";
    const mesajlar = (sonVeri && sonVeri.rapor && sonVeri.rapor.mudahale.mesajlar) || [];
    const mesaj = mesajlar.find((m) => m.id === seciliMesaj);
    if (!mesaj) {
      $("anons-hatasi").textContent = "Önce çalınacak mesajı seçin.";
      return;
    }
    const secici = $("anons-kanali");
    const yer = secici.value === "" ? "Tüm fabrika kanallarından" : secici.selectedOptions[0].textContent + " kanalından";
    $("anons-onay-metni").textContent = "“" + mesaj.metin + "” " + yer + " çalınsın mı?";
    $("anons-onayi").hidden = false;
    this.hidden = true;
    $("anons-gonder").focus();
  });

  $("anons-vazgec").addEventListener("click", function () {
    anonsOnayiniKapat();
    $("anons-dugmesi").focus();
  });

  $("anons-kanali").addEventListener("change", anonsOnayiniKapat);

  $("anons-formu").addEventListener("submit", async function (olay) {
    olay.preventDefault();
    const dugme = $("anons-gonder");
    dugme.disabled = true;
    try {
      const kanal = $("anons-kanali").value;
      await mudahaleGonder({ tur: "anons", mesaj_id: seciliMesaj, kanal_id: kanal === "" ? null : Number(kanal) });
      anonsOnayiniKapat();
      setTimeout(yukle, 1500);
    } catch (hata) {
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
    if (!dugme.classList.contains("onayla")) {
      for (const diger of document.querySelectorAll("#kanal-listesi .onayla")) {
        diger.classList.remove("onayla");
        diger.textContent = "Dene";
      }
      dugme.classList.add("onayla");
      dugme.textContent = "Çalınsın mı?";
      setTimeout(function () {
        if (dugme.classList.contains("onayla")) {
          dugme.classList.remove("onayla");
          dugme.textContent = "Dene";
        }
      }, 4000);
      return;
    }
    dugme.classList.remove("onayla");
    dugme.textContent = "Dene";
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
      const bekliyordu = !dinleniyor() && !kareIzleniyor();
      sonEtkilesim = Date.now();
      // Bekleyen Müdahale ya da Kameralar ekranı dokununca hemen canlanır
      if (bekliyordu && (dinleniyor() || kareIzleniyor()) && $("giris").hidden) yukle();
    });
  }

  // ---------------------------------------------------------------- sistem

  function evetHayir(deger) {
    return deger === true ? "Evet" : deger === false ? "Hayır" : "Bilinmiyor";
  }

  function sistemiCiz(veri) {
    const r = veri.rapor;
    const satirlar = [
      ["Bağlantı", { canli: "Canlı", yok: "Haber yok", kapandi: "Program kapatıldı", hic: "Rapor gelmedi" }[baglantiDurumu(veri)]],
      ["Son rapor", veri.son_rapor ? tarihSaatMetni(veri.son_rapor) : "-"],
    ];
    if (r) {
      satirlar.push(
        ["Rapor aralığı", r.aralik_sn + " saniye"],
        ["Program", (r.program.ad || "-") + (r.program.surum ? " " + r.program.surum : "")],
        ["Analiz çalışıyor", evetHayir(r.sistem.analiz)],
        ["Uyarı hazır", evetHayir(r.sistem.hazir)],
        ["Sesli uyarı kanalı", evetHayir(r.sistem.uyari_garantisi)],
        ["Boş disk", r.sistem.bos_disk_gb === null ? "-" : ondalik(r.sistem.bos_disk_gb) + " GB"],
        ["Çalışma süresi", r.sistem.calisma_suresi_sn ? sureMetni(r.sistem.calisma_suresi_sn) : "-"]
      );
    }
    const liste = $("sistem-bilgisi");
    temizle(liste);
    for (const [ad, deger] of satirlar) {
      const satir = el("div");
      satir.appendChild(el("dt", "", ad));
      satir.appendChild(el("dd", "", deger));
      liste.appendChild(satir);
    }

    const adres = fabrikaAdresi(veri);
    for (const kimlik of ["fabrika-baglantisi", "fabrika-dugmesi", "kenar-fabrika"]) {
      const bag = $(kimlik);
      bag.hidden = !adres;
      if (adres) bag.href = adres;
    }
    $("canli-metni").textContent = adres
      ? "Kameraların 10 saniyede bir yenilenen görüntüsü Kameralar ekranındadır. Akıcı " +
        "canlı görüntü için düğme doğrudan fabrikadaki bilgisayarın ekranını açar; yalnız " +
        "fabrika ağına VPN ya da Tailscale ile bağlıyken çalışır ve fabrika ekranının " +
        "şifresini sorar."
      : "Kameraların 10 saniyede bir yenilenen görüntüsü Kameralar ekranındadır. Akıcı " +
        "canlı görüntü için fabrika bilgisayarına VPN ya da Tailscale ile bağlanılır; " +
        "adresi Vercel'de FABRIKA_ADRESI olarak tanımlarsanız burada bir düğme çıkar.";
  }

  // ------------------------------------------------------------ hepsi

  function panoyuCiz(veri) {
    durumBandiniCiz(veri);
    const rapor = veri.rapor;
    sorunlariCiz(rapor);
    sayaclariCiz(rapor);
    for (const kutu of document.querySelectorAll(".veri")) kutu.hidden = !rapor;
    bilgisayariCiz(rapor);
    if (rapor) {
      ozetiCiz(rapor);
      gunlukCiz(rapor);
      yerleriCiz(rapor);
      sayilariCiz(rapor);
      kameralariCiz(rapor);
      olaylariCiz(rapor);
      kareleriCiz(veri);
      saatligiCiz(rapor);
      ogeleriCiz(rapor);
    } else {
      for (const kimlik of ["kamera-listesi", "kamera-tablosu", "olay-cizelgesi"]) temizle($(kimlik));
      $("kare-bolumu").hidden = true;
      $("kamera-listesi").appendChild(bosDurum("Henüz rapor yok", "Fabrikadan ilk rapor gelince görünür"));
      $("olay-cizelgesi").appendChild(bosDurum("Henüz rapor yok", "Fabrikadan ilk rapor gelince görünür"));
    }
    sistemiCiz(veri);
    mudahaleyiCiz(veri);
    if (aktifGorunum === "genel") {
      $("gorunum-aciklamasi").textContent = kurulumMetni || GORUNUMLER.genel[1];
    }
  }

  // ----------------------------------------------------------- sunucu

  async function yukle() {
    if (istekSuruyor) return;
    istekSuruyor = true;
    try {
      const adres = dinleniyor()
        ? "/api/durum?mudahale=1"
        : kareIzleniyor()
          ? "/api/durum?kare=1"
          : "/api/durum";
      const yanit = await fetch(adres, { credentials: "same-origin", cache: "no-store" });
      const veri = await yanit.json().catch(() => ({}));
      if (yanit.status === 401) {
        sonVeri = null;
        tekEkranGoster("giris");
        $("sifre").focus();
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
      siteUyarisi("");
      panoyuCiz(veri);
      panoyuGoster();
    } catch (hata) {
      hataGoster(
        "Siteye ulaşılamıyor. İnternet bağlantınızı kontrol edin; pano son bilinen durumu gösteriyor."
      );
    } finally {
      istekSuruyor = false;
    }
  }

  /* Hata durumu: veri varsa bırakılır (bayat veri, üstte uyarı); yoksa
     yükleme kartı hatayı söyler ve tazeleme denemeye devam eder. */
  function hataGoster(metin) {
    if (sonVeri) {
      siteUyarisi(metin);
      durumBandiniCiz(sonVeri);
    } else {
      $("yukleniyor-metni").textContent = metin;
      tekEkranGoster("yukleniyor");
    }
  }

  // Hata iletisi ve şifre kutusunun kırmızı kenarı birlikte yazılır, birlikte silinir.
  function girisHatasi(metin) {
    $("giris-hatasi").textContent = metin;
    if (metin) $("sifre").setAttribute("aria-invalid", "true");
    else $("sifre").removeAttribute("aria-invalid");
  }
  $("sifre").addEventListener("input", function () {
    if ($("sifre").hasAttribute("aria-invalid")) girisHatasi("");
  });

  $("giris-formu").addEventListener("submit", async function (olay) {
    olay.preventDefault();
    const sifre = $("sifre").value;
    if (!sifre) {
      girisHatasi("Şifreyi yazın.");
      return;
    }
    const dugme = $("giris-dugmesi");
    dugme.disabled = true;
    girisHatasi("");
    try {
      const yanit = await fetch("/api/giris", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sifre: sifre }),
      });
      const veri = await yanit.json().catch(() => ({}));
      if (!yanit.ok) {
        girisHatasi(veri.mesaj || "Giriş yapılamadı (HTTP " + yanit.status + ").");
        return;
      }
      $("sifre").value = "";
      $("yukleniyor-metni").textContent = "Yükleniyor...";
      tekEkranGoster("yukleniyor");
      await yukle();
    } catch (hata) {
      girisHatasi("Siteye ulaşılamıyor. İnternet bağlantınızı kontrol edin.");
    } finally {
      dugme.disabled = false;
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
        tekEkranGoster("giris");
      }
    });
  }

  $("yenile").addEventListener("click", function () {
    yukle();
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
    const aralik = dinleniyor() || kareIzleniyor() ? HIZLI_TAZELEME_MS : TAZELEME_MS;
    if (Date.now() - sonTazeleme >= aralik - 250) {
      sonTazeleme = Date.now();
      yukle();
    }
  }, HIZLI_TAZELEME_MS);
  // "12 saniye önce" ve bağlantı durumu istek arasında da ilerler
  setInterval(function () {
    if (sonVeri && !$("kabuk").hidden) durumBandiniCiz(sonVeri);
  }, GORECELI_MS);

  gorunumuUygula();
  yukle();
})();
