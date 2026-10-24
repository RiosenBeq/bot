/* Uzak izleme panosu.

   /api/durum'u 15 saniyede bir okur (sekme görünürken) ve ekranı çizer.
   Veri fabrikadan gelir: metinler textContent ile yazılır, innerHTML
   KULLANILMAZ. Saatler her zaman Türkiye saatiyle gösterilir; telefonun
   saat dilimi farklı olsa da. */
"use strict";

(function () {
  const TAZELEME_MS = 15000;
  const GORECELI_MS = 5000;
  // Sunucudaki kuralın aynısı (api/_pano.py GECIKME_KATSAYISI): rapor aralığının
  // bu katı kadar haber gelmezse bağlantı yok sayılır. Site de ulaşılamaz
  // olursa pano son veriden kendisi karar verir.
  const GECIKME_KATSAYISI = 3;
  const SAAT_DILIMI = "Europe/Istanbul";

  const KAMERA_DURUMLARI = {
    online: ["canlı", "basari"],
    connecting: ["yeniden bağlanıyor", "uyari"],
    offline: ["bağlantı yok", "tehlike"],
    pasif: ["pasif", ""],
  };
  const ONEM_SINIFLARI = { critical: "kritik", high: "tehlike", medium: "uyari", low: "" };

  const $ = (id) => document.getElementById(id);
  let sonVeri = null;
  let saatFarkiMs = 0; // sunucu saati - bu cihazın saati
  let istekSuruyor = false;
  let sonDuyuru = "";

  // ----------------------------------------------------------- yardımcılar

  function el(etiket, sinif, metin) {
    const oge = document.createElement(etiket);
    if (sinif) oge.className = sinif;
    if (metin !== undefined && metin !== null) oge.textContent = metin;
    return oge;
  }

  function hap(metin, sinif, nokta) {
    const oge = el("span", "hap" + (sinif ? " " + sinif : ""));
    if (nokta) oge.appendChild(el("span", "nokta"));
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

  function tarihSaatMetni(iso) {
    if (!iso) return "";
    const bugun = gunMetni(new Date(simdiMs()).toISOString());
    return gunMetni(iso) === bugun ? saatMetni(iso) : gunMetni(iso) + " " + saatMetni(iso);
  }

  /* Olay listesinin saat sütunu: bugünse yalnız saat; değilse üstte "dün" ya da
     "23.10", altta saat. Sütun dar: tam tarih başlığın üstüne taşardı. */
  function zamanOgesi(iso) {
    const oge = el("time", "saat");
    if (!iso) {
      oge.textContent = "-";
      return oge;
    }
    oge.dateTime = iso;
    const bugun = gunMetni(new Date(simdiMs()).toISOString());
    const dun = gunMetni(new Date(simdiMs() - 86400000).toISOString());
    const gun = gunMetni(iso);
    if (gun !== bugun) {
      // gunMetni "21.10.2026" verir; sütuna gün ve ay sığar ("21.10")
      oge.appendChild(el("span", "gun", gun === dun ? "dün" : gun.slice(0, 5)));
    }
    oge.appendChild(el("span", "", saatMetni(iso)));
    return oge;
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

  // ------------------------------------------------------------- görünüm

  function goster(bolum) {
    for (const ad of ["yukleniyor", "kurulum", "giris", "pano"]) {
      $(ad).hidden = ad !== bolum;
    }
    $("cikis").hidden = bolum !== "pano";
    $("baglanti-hapi").hidden = bolum !== "pano";
  }

  function siteUyarisi(metin) {
    const kutu = $("site-uyarisi");
    kutu.textContent = metin;
    kutu.hidden = !metin;
  }

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
      satir.appendChild(el("code", "", eksik.ad));
      satir.appendChild(document.createTextNode(": " + eksik.neden));
      liste.appendChild(satir);
    }
    if (!$("onerilen-anahtar").textContent) $("onerilen-anahtar").textContent = onerilenAnahtar();
    goster("kurulum");
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

  // --------------------------------------------------------------- çizim

  function durumBandiniCiz(veri) {
    const rapor = veri.rapor;
    const durum = baglantiDurumu(veri);
    const gecikme = gecikmeSn(veri);
    let sinif = "";
    let baslik = "";
    let alt = "";
    let hapMetni = "";
    let hapSinifi = "";

    if (durum === "hic") {
      baslik = "Fabrikadan henüz rapor gelmedi";
      alt =
        "Fabrika programında Ayarlar → Uzak izleme panosu bölümüne bu sitenin adresini ve " +
        "rapor anahtarını yazın, sonra sistemi yeniden başlatın.";
      hapMetni = "Rapor yok";
    } else if (durum === "kapandi") {
      baslik = "Fabrika programı kapatıldı";
      alt =
        "Program " + tarihSaatMetni(veri.son_rapor) + " saatinde kapatılırken son raporunu " +
        "gönderdi. Yeniden açılınca pano kendiliğinden güncellenir.";
      hapMetni = "Kapalı";
    } else if (durum === "yok") {
      sinif = "tehlike";
      baslik = "Fabrikadan " + sureMetni(gecikme) + " haber yok";
      alt =
        "Bilgisayar kapanmış, program durmuş ya da internet kesilmiş olabilir. " +
        (rapor ? "Aşağıdaki bilgiler son rapordan (" + tarihSaatMetni(veri.son_rapor) + ")." : "");
      hapMetni = "Bağlantı yok";
      hapSinifi = "tehlike";
    } else {
      const sistem = rapor.sistem;
      if (sistem.analiz === false) {
        sinif = "uyari";
        baslik = "Program açık ama analiz çalışmıyor";
      } else if (sistem.hazir === false || sistem.sorunlar.length) {
        sinif = "tehlike";
        baslik = "Sistem çalışıyor, dikkat gereken sorun var";
      } else {
        sinif = "basari";
        baslik = "Sistem çalışıyor";
      }
      alt = "Son rapor " + sureMetni(gecikme) + " önce geldi.";
      hapMetni = "Canlı";
      hapSinifi = "basari";
    }

    const bant = $("durum-bandi");
    bant.className = "durum-bandi" + (sinif ? " " + sinif : "");
    $("durum-baslik").textContent = baslik;
    $("durum-alt").textContent = alt;

    const ustHap = $("baglanti-hapi");
    ustHap.className = "hap" + (hapSinifi ? " " + hapSinifi : "");
    temizle(ustHap);
    ustHap.appendChild(el("span", "nokta"));
    ustHap.appendChild(document.createTextNode(hapMetni));

    duyur(baslik);
  }

  function sorunlariCiz(rapor) {
    const sorunlar = rapor ? rapor.sistem.sorunlar : [];
    const liste = $("sorun-listesi");
    temizle(liste);
    for (const metin of sorunlar) liste.appendChild(el("li", "", metin));
    $("sorunlar").hidden = sorunlar.length === 0;
  }

  function duneGore(bugun, dun) {
    if (dun === 0 && bugun === 0) return "dün de ihlal yoktu";
    if (dun === 0) return "dün ihlal yoktu";
    const fark = bugun - dun;
    if (fark === 0) return "dünkü ile aynı";
    return "düne göre " + (fark > 0 ? "+" : "-") + Math.abs(fark);
  }

  function sayilariCiz(rapor) {
    const s = rapor.sayilar;
    $("sayi-ihlal").textContent = sayiMetni(s.bugun_ihlal);
    $("alt-ihlal").textContent = duneGore(s.bugun_ihlal, s.dun_ihlal);

    $("sayi-bekleyen").textContent = sayiMetni(s.bekleyen);
    $("alt-bekleyen").textContent = s.bekleyen ? "fabrika ekranında incelenir" : "kuyruk boş";
    $("kutu-bekleyen").classList.toggle("dikkat", s.bekleyen > 0);

    $("sayi-kamera").textContent = s.kamera_canli + " / " + s.kamera_toplam;
    // Bilerek pasife alınmış kamera "görüntü vermiyor" sayılmaz
    const pasif = rapor.kameralar.filter((k) => k.durum === "pasif").length;
    const kopuk = rapor.kameralar.filter((k) => k.durum !== "pasif" && k.durum !== "online").length;
    let kameraNotu = "hepsi görüntü veriyor";
    if (s.kamera_toplam === 0) kameraNotu = "henüz kamera eklenmedi";
    else if (kopuk > 0) kameraNotu = kopuk + " kamera görüntü vermiyor";
    else if (pasif > 0) kameraNotu = pasif + " kamera pasif";
    $("alt-kamera").textContent = kameraNotu;
    $("kutu-kamera").classList.toggle("dikkat", kopuk > 0);

    $("sayi-kural").textContent = sayiMetni(s.aktif_kural);
    $("alt-kural").textContent = s.aktif_kural ? "" : "kural kurulmadan ihlal üretilmez";
    $("kutu-kural").classList.toggle("dikkat", s.aktif_kural === 0);
  }

  function kameralariCiz(rapor) {
    const liste = $("kameralar");
    temizle(liste);
    if (!rapor.kameralar.length) {
      liste.appendChild(el("li", "bos", "Henüz kamera eklenmedi."));
      return;
    }
    for (const k of rapor.kameralar) {
      const satir = el("li");
      const govde = el("div", "satir-govde");
      govde.appendChild(el("b", "", k.ad));
      const ayrinti = [];
      if (k.bolum) ayrinti.push(k.bolum);
      if (k.durum === "online" && k.islenen_fps !== null) {
        let hiz = "işlenen " + ondalik(k.islenen_fps);
        if (k.hedef_fps) hiz += " / " + ondalik(k.hedef_fps);
        ayrinti.push(hiz + " kare/sn");
      } else if (k.durum !== "pasif" && k.son_kare_yasi_sn !== null) {
        ayrinti.push("son görüntü " + sureMetni(k.son_kare_yasi_sn) + " önce");
      }
      if (ayrinti.length) govde.appendChild(el("span", "ikincil", ayrinti.join(" · ")));
      satir.appendChild(govde);

      const haplar = el("div", "haplar");
      const [ad, sinif] = KAMERA_DURUMLARI[k.durum] || KAMERA_DURUMLARI.offline;
      haplar.appendChild(hap(ad, sinif, k.durum === "online"));
      if (k.yavas) haplar.appendChild(hap("yavaş", "uyari"));
      satir.appendChild(haplar);
      liste.appendChild(satir);
    }
  }

  function olaylariCiz(rapor) {
    const liste = $("olaylar");
    temizle(liste);
    if (!rapor.son_olaylar.length) {
      liste.appendChild(el("li", "bos", "Henüz olay yok."));
      return;
    }
    for (const o of rapor.son_olaylar) {
      const satir = el("li", "olay-satiri");
      satir.appendChild(zamanOgesi(o.zaman));

      const govde = el("div", "satir-govde");
      govde.appendChild(el("b", "", o.baslik));
      if (o.yer) govde.appendChild(el("span", "ikincil", o.yer));
      satir.appendChild(govde);

      const haplar = el("div", "haplar");
      if (o.tur === "sistem") haplar.appendChild(hap("sistem", "bilgi"));
      else if (o.onem_adi) haplar.appendChild(hap(o.onem_adi, ONEM_SINIFLARI[o.onem] || ""));
      if (o.suruyor) haplar.appendChild(hap("sürüyor" + (o.sure ? " · " + o.sure : ""), "uyari"));
      if (o.durum_adi) haplar.appendChild(hap(o.durum_adi, ""));
      if (haplar.childNodes.length) satir.appendChild(haplar);
      liste.appendChild(satir);
    }
  }

  function saatligiCiz(veri) {
    const degerler = veri.rapor.saatlik;
    const kutu = $("saatlik");
    const etiketler = $("saat-etiketleri");
    temizle(kutu);
    temizle(etiketler);
    const enCok = Math.max(...degerler);
    const toplam = degerler.reduce((a, b) => a + b, 0);
    const simdikiSaat = Number(
      new Date(simdiMs()).toLocaleString("en-GB", { hour: "2-digit", hour12: false, timeZone: SAAT_DILIMI })
    ) % 24;
    degerler.forEach(function (n, saat) {
      const sutun = el("div", "sutun" + (saat === simdikiSaat ? " simdi" : ""));
      sutun.title = String(saat).padStart(2, "0") + ":00 · " + n + " ihlal";
      const dolgu = el("div", "dolgu");
      // CSP satır içi stile izin vermez; yükseklik CSSOM ile verilir
      dolgu.style.height = enCok ? Math.round((n / enCok) * 100) + "%" : "0";
      sutun.appendChild(dolgu);
      kutu.appendChild(sutun);
      etiketler.appendChild(el("span", "", saat % 6 === 0 ? String(saat).padStart(2, "0") : ""));
    });
    let ozet = "Bugün henüz ihlal yok.";
    if (toplam) {
      const tepe = degerler.indexOf(enCok);
      ozet =
        "Toplam " + sayiMetni(toplam) + " ihlal · en yoğun " + String(tepe).padStart(2, "0") +
        ":00 - " + String((tepe + 1) % 24).padStart(2, "0") + ":00 (" + enCok + ")";
    }
    $("saatlik-ozet").textContent = ozet;
    kutu.setAttribute("aria-label", "Bugün saat saat ihlal. " + ozet);
  }

  function ogeleriCiz(rapor) {
    const liste = $("ogeler");
    temizle(liste);
    if (!rapor.ogeler.length) {
      liste.appendChild(el("li", "bos", "Son 7 günde ihlal yok."));
      return;
    }
    const enCok = Math.max(...rapor.ogeler.map((o) => o.sayi));
    for (const o of rapor.ogeler) {
      const satir = el("li");
      const ust = el("div", "ust-satir");
      ust.appendChild(el("span", "", o.ad));
      ust.appendChild(el("b", "sayi", sayiMetni(o.sayi)));
      satir.appendChild(ust);
      const yol = el("div", "yol");
      const dolgu = el("div", "dolgu");
      dolgu.style.width = enCok ? Math.max(2, Math.round((o.sayi / enCok) * 100)) + "%" : "0";
      yol.appendChild(dolgu);
      satir.appendChild(yol);
      liste.appendChild(satir);
    }
  }

  function canliyiCiz(veri) {
    const baglanti = $("fabrika-baglantisi");
    if (veri.fabrika_adresi && /^https?:\/\//.test(veri.fabrika_adresi)) {
      baglanti.href = veri.fabrika_adresi;
      baglanti.hidden = false;
      $("canli-metni").textContent =
        "Canlı görüntü bu siteden geçmez; düğme doğrudan fabrikadaki bilgisayarın ekranını " +
        "açar. Yalnız fabrika ağına VPN ya da Tailscale ile bağlıyken çalışır ve fabrika " +
        "ekranının şifresini sorar.";
    } else {
      baglanti.hidden = true;
      $("canli-metni").textContent =
        "Canlı görüntü bu siteden geçmez (KVKK). Fabrika dışından izlemek için fabrika " +
        "bilgisayarına VPN ya da Tailscale ile bağlanılır. Bağlantı kurulunca adresi " +
        "Vercel'de FABRIKA_ADRESI olarak tanımlarsanız burada bir düğme çıkar.";
    }
  }

  function altNotuCiz(veri) {
    const r = veri.rapor;
    const parcalar = [];
    if (r && r.program.ad) parcalar.push(r.program.ad + (r.program.surum ? " " + r.program.surum : ""));
    if (r) parcalar.push("rapor aralığı " + r.aralik_sn + " sn");
    if (veri.son_rapor) parcalar.push("son rapor " + tarihSaatMetni(veri.son_rapor));
    $("alt-not").textContent = parcalar.join(" · ");
  }

  function panoyuCiz(veri) {
    durumBandiniCiz(veri);
    const rapor = veri.rapor;
    sorunlariCiz(rapor);
    const veriVar = Boolean(rapor);
    for (const kutu of document.querySelectorAll("#pano .sayilar, #pano .iki-sutun")) {
      kutu.hidden = !veriVar;
    }
    if (veriVar) {
      sayilariCiz(rapor);
      kameralariCiz(rapor);
      olaylariCiz(rapor);
      saatligiCiz(veri);
      ogeleriCiz(rapor);
    }
    canliyiCiz(veri);
    altNotuCiz(veri);
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
        goster("giris");
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
      goster("pano");
    } catch (hata) {
      hataGoster(
        "Siteye ulaşılamıyor. İnternet bağlantınızı kontrol edin; pano son bilinen durumu gösteriyor."
      );
    } finally {
      istekSuruyor = false;
    }
  }

  function hataGoster(metin) {
    if (sonVeri) {
      siteUyarisi(metin);
      durumBandiniCiz(sonVeri);
    } else {
      $("yukleniyor").textContent = metin;
      goster("yukleniyor");
    }
  }

  $("giris-formu").addEventListener("submit", async function (olay) {
    olay.preventDefault();
    const sifre = $("sifre").value;
    const hataKutusu = $("giris-hatasi");
    if (!sifre) {
      hataKutusu.textContent = "Şifreyi yazın.";
      return;
    }
    const dugme = $("giris-dugmesi");
    dugme.disabled = true;
    hataKutusu.textContent = "";
    try {
      const yanit = await fetch("/api/giris", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sifre: sifre }),
      });
      const veri = await yanit.json().catch(() => ({}));
      if (!yanit.ok) {
        hataKutusu.textContent = veri.mesaj || "Giriş yapılamadı (HTTP " + yanit.status + ").";
        return;
      }
      $("sifre").value = "";
      goster("yukleniyor");
      await yukle();
    } catch (hata) {
      hataKutusu.textContent = "Siteye ulaşılamıyor. İnternet bağlantınızı kontrol edin.";
    } finally {
      dugme.disabled = false;
    }
  });

  $("cikis").addEventListener("click", async function () {
    try {
      await fetch("/api/cikis", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
    } finally {
      sonVeri = null;
      goster("giris");
    }
  });

  // Görünmeyen sekme sunucuyu yormaz; sekmeye dönünce hemen tazelenir.
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") yukle();
  });
  // Giriş ekranında tazelenmez (yazılan şifre silinmesin); öbür her durumda
  // (pano, kurulum, ilk yüklemede ulaşılamayan site) tazelenir.
  setInterval(function () {
    if (document.visibilityState === "visible" && $("giris").hidden) yukle();
  }, TAZELEME_MS);
  // "12 saniye önce" ve bağlantı durumu istek arasında da ilerler
  setInterval(function () {
    if (sonVeri && !$("pano").hidden) durumBandiniCiz(sonVeri);
  }, GORECELI_MS);

  yukle();
})();
