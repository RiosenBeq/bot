/* Uzak izleme panosu.

   /api/durum'u 15 saniyede bir okur (sekme görünürken) ve ekranı çizer.
   Dört görünüm var (Genel bakış, Kameralar, Olaylar, Sistem); adres
   çubuğundaki #genel, #kameralar ... hangisinin açık olduğunu söyler, hem
   masaüstünün kenar çubuğu hem telefonun sekme çubuğu aynı bağlantılardır.

   Veri fabrikadan gelir: metinler textContent ile yazılır, innerHTML
   KULLANILMAZ. Saatler her zaman Türkiye saatiyle gösterilir; telefonun
   saat dilimi farklı olsa da.

   Dört durum (lafmobil add-screen kuralı): yükleniyor, hata (site
   ulaşılamıyor: son bilinen veri bırakılır, üstte uyarı), boş (henüz rapor
   yok) ve veri. */
"use strict";

(function () {
  const TAZELEME_MS = 15000;
  const GORECELI_MS = 5000;
  // Sunucudaki kuralın aynısı (api/_pano.py GECIKME_KATSAYISI): rapor aralığının
  // bu katı kadar haber gelmezse bağlantı yok sayılır. Site de ulaşılamaz
  // olursa pano son veriden kendisi karar verir.
  const GECIKME_KATSAYISI = 3;
  const SAAT_DILIMI = "Europe/Istanbul";
  const GENEL_OLAY_SAYISI = 6;

  const GORUNUMLER = {
    genel: ["Genel bakış", "Fabrikadan gelen son durum"],
    kameralar: ["Kameralar", "Bağlantı durumu ve kare hızı"],
    olaylar: ["Olaylar", "Son 20 olay, en yenisi üstte"],
    sistem: ["Sistem", "Program, bağlantı ve canlı görüntü"],
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
    $("gorunum-aciklamasi").textContent = aciklama;
    $("yol-adi").textContent = baslik;
    document.title = baslik + " · Uzak izleme panosu";
  }

  window.addEventListener("hashchange", function () {
    if (!gorunumAdi()) return;
    gorunumuUygula();
    window.scrollTo(0, 0);
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
    $("k-bekleyen-ref").textContent = s.bekleyen ? "fabrika ekranında incelenir" : "kuyruk boş";

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

  function olaySatiri(o) {
    const satir = el("li");
    const sistem = o.tur === "sistem";
    const kutu = el("span", "ikon-kutu " + (sistem ? "" : ONEM_KUTUSU[o.onem] || "gri"));
    kutu.appendChild(simge(sistem ? "i-sistem" : o.onem === "critical" ? "i-siren" : "i-uyari"));
    satir.appendChild(kutu);

    const govde = el("div", "cizelge-govde");
    govde.appendChild(el("b", "", o.baslik));
    if (o.yer) govde.appendChild(el("span", "", o.yer));
    const rozetler = el("div", "rozetler");
    if (sistem) rozetler.appendChild(rozet("Sistem", "bilgi"));
    else if (o.onem_adi) rozetler.appendChild(rozet(o.onem_adi, ONEM_ROZETI[o.onem] || ""));
    if (o.suruyor) rozetler.appendChild(rozet("Sürüyor" + (o.sure ? " · " + o.sure : ""), "uyari"));
    if (o.durum_adi) rozetler.appendChild(rozet(o.durum_adi, ""));
    if (rozetler.childNodes.length) govde.appendChild(rozetler);
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

  function olaylariCiz(rapor) {
    const genel = $("genel-olaylar");
    temizle(genel);
    if (!rapor.son_olaylar.length) genel.appendChild(bosDurum("Henüz olay yok", ""));
    for (const o of rapor.son_olaylar.slice(0, GENEL_OLAY_SAYISI)) genel.appendChild(olaySatiri(o));

    const liste = $("olay-cizelgesi");
    temizle(liste);
    const gorunen = rapor.son_olaylar.filter((o) => olayTuru === "hepsi" || o.tur === olayTuru);
    if (!gorunen.length) liste.appendChild(bosDurum("Bu türde olay yok", "Son 20 olayın içinde"));
    for (const o of gorunen) liste.appendChild(olaySatiri(o));
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
    const enCok = Math.max(...rapor.ogeler.map((o) => o.sayi));
    for (const o of rapor.ogeler) {
      const satir = el("li");
      const ust = el("div", "ust");
      ust.appendChild(el("span", "centik"));
      ust.appendChild(el("span", "", o.ad));
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
      ? "Canlı görüntü bu siteden geçmez; düğme doğrudan fabrikadaki bilgisayarın ekranını " +
        "açar. Yalnız fabrika ağına VPN ya da Tailscale ile bağlıyken çalışır ve fabrika " +
        "ekranının şifresini sorar."
      : "Canlı görüntü bu siteden geçmez (KVKK). Fabrika dışından izlemek için fabrika " +
        "bilgisayarına VPN ya da Tailscale ile bağlanılır. Bağlantı kurulunca adresi " +
        "Vercel'de FABRIKA_ADRESI olarak tanımlarsanız burada bir düğme çıkar.";
  }

  // ------------------------------------------------------------ hepsi

  function panoyuCiz(veri) {
    durumBandiniCiz(veri);
    const rapor = veri.rapor;
    sorunlariCiz(rapor);
    sayaclariCiz(rapor);
    for (const kutu of document.querySelectorAll(".veri")) kutu.hidden = !rapor;
    if (rapor) {
      sayilariCiz(rapor);
      kameralariCiz(rapor);
      olaylariCiz(rapor);
      saatligiCiz(rapor);
      ogeleriCiz(rapor);
    } else {
      for (const kimlik of ["kamera-listesi", "kamera-tablosu", "olay-cizelgesi"]) temizle($(kimlik));
      $("kamera-listesi").appendChild(bosDurum("Henüz rapor yok", "Fabrikadan ilk rapor gelince görünür"));
      $("olay-cizelgesi").appendChild(bosDurum("Henüz rapor yok", "Fabrikadan ilk rapor gelince görünür"));
    }
    sistemiCiz(veri);
  }

  // ----------------------------------------------------------- sunucu

  async function yukle() {
    if (istekSuruyor) return;
    istekSuruyor = true;
    try {
      const yanit = await fetch("/api/durum", { credentials: "same-origin", cache: "no-store" });
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
  // (pano, kurulum, ilk yüklemede ulaşılamayan site) tazelenir.
  setInterval(function () {
    if (document.visibilityState === "visible" && $("giris").hidden) yukle();
  }, TAZELEME_MS);
  // "12 saniye önce" ve bağlantı durumu istek arasında da ilerler
  setInterval(function () {
    if (sonVeri && !$("kabuk").hidden) durumBandiniCiz(sonVeri);
  }, GORECELI_MS);

  gorunumuUygula();
  yukle();
})();
