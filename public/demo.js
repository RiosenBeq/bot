/* Demo: /demo adresi panoyu örnek verilerle açar (tasarımı denetlemek için).

   Yalnız /demo adresinde çalışır; /pano'da hiçbir şey yapmaz. Panonun
   /api/... istekleri burada karşılanır: siteye ve fabrikaya HİÇBİR istek
   gitmez, giriş istenmez, hiçbir şey kaydedilmez (sayfa yenilenince her şey
   başa döner). Biçim sunucununkiyle aynıdır (api/_pano.py: pano_verisi,
   mudahale_verisi, hesap_verisi, filo_verisi); pano.js aynı kodla çizer.

   Kanıt fotoğrafı ve anlık görüntü sunucudan gelmez: tarayıcıda çizilir
   (canvas -> data: adresi; güvenlik başlığı img-src 'self' data: izin verir).
   pano.js resim adresini window.panoDemo'dan alır.

   Üstteki demo bandından rol (İzleyici / Operatör / Yönetici) ve bağlantı
   durumu (canlı / haber yok / kapatıldı) değiştirilir. Anons, hoparlör
   denemesi, olay inceleme, teşhis, yeniden başlatma ve güncelleme birkaç
   saniyede "Sırada -> Fabrikada -> Yapıldı" diye ilerler; hesap işleri
   kullanıcı listesini ve işlem kaydını değiştirir. Onay şifresi olarak her
   şey kabul edilir. */
"use strict";

(function () {
  if (location.pathname.replace(/\/+$/, "") !== "/demo") return;

  const SN = 1000;
  const DK = 60 * SN;
  const SA = 60 * DK;
  const SAAT_DILIMI = "Europe/Istanbul";
  const ACILIS = Date.now();

  const ROL_ADLARI = { izleyici: "İzleyici", operator: "Operatör", yonetici: "Yönetici" };
  /* Rol yetkileri (api/_pano.py YETKILER / VARSAYILAN_YETKILER / KILITLI_YETKILER'in
     aynısı, docs/19 §1): demo da gerçek pano gibi yetkiden gider, böylece rol
     değiştirince menüler aynı kuralla açılıp kapanır. Demoda değiştirilebilir:
     değişiklik yalnız bu sekmede yaşar. */
  const YETKILER = [
    "ekran.mudahale",
    "komut.anons",
    "komut.ses_dene",
    "komut.olay_incele",
    "veri.bilgisayar",
    "ekran.yonetim",
    "komut.teshis",
    "komut.yeniden_baslat",
    "komut.guncelle",
    "ekran.tesisler",
    "ekran.kullanicilar",
    "hesap.yonet",
  ];
  const YETKI_ADLARI = {
    "ekran.mudahale": "Müdahale ekranını görme",
    "komut.anons": "Hazır anons çaldırma",
    "komut.ses_dene": "Hoparlör denemesi",
    "komut.olay_incele": "Olayı İncelendi / Yanlış alarm işaretleme",
    "veri.bilgisayar": "Bilgisayarın IP adresi, adı ve fabrika adresi",
    "ekran.yonetim": "Yönetim ekranını görme",
    "komut.teshis": "Teşhis alma",
    "komut.yeniden_baslat": "Programı yeniden başlatma",
    "komut.guncelle": "Programı güncelleme",
    "ekran.tesisler": "Tesisler ekranını görme",
    "ekran.kullanicilar": "Kullanıcılar ve işlem kaydını görme",
    "hesap.yonet": "Hesap açma, rol, şifre, kapatma, silme",
  };
  const YETKI_GRUPLARI = [
    ["Müdahale", ["ekran.mudahale", "komut.anons", "komut.ses_dene", "komut.olay_incele"]],
    ["Bilgi", ["veri.bilgisayar", "ekran.tesisler"]],
    ["Yönetim", ["ekran.yonetim", "komut.teshis", "komut.yeniden_baslat", "komut.guncelle"]],
    ["Hesaplar", ["ekran.kullanicilar", "hesap.yonet"]],
  ];
  const KILITLI_YETKILER = ["ekran.kullanicilar", "hesap.yonet"];
  const VARSAYILAN_YETKILER = {
    izleyici: [],
    operator: ["ekran.mudahale", "komut.anons", "komut.ses_dene", "komut.olay_incele", "veri.bilgisayar"],
    yonetici: [...YETKILER],
  };
  /* Demoda ayarlanmış tanım (rol -> yetki listesi); başlangıçta varsayılan */
  const rolYetkileri = {
    izleyici: [...VARSAYILAN_YETKILER.izleyici],
    operator: [...VARSAYILAN_YETKILER.operator],
    yonetici: [...VARSAYILAN_YETKILER.yonetici],
  };

  /* Kilitli yetkiler yalnız yöneticide olur, yöneticiden alınamaz (sunucunun
     yetki_kumesi_duzelt'i) */
  function yetkiKumesiDuzelt(liste, rol) {
    if (!Array.isArray(liste)) return [...VARSAYILAN_YETKILER[rol]];
    const kume = new Set(liste.filter((y) => YETKILER.includes(y) && !KILITLI_YETKILER.includes(y)));
    if (rol === "yonetici") for (const y of KILITLI_YETKILER) kume.add(y);
    return YETKILER.filter((y) => kume.has(y));
  }

  function yetkiliMi(yetki) {
    return rolYetkileri[durum.rol].includes(yetki);
  }

  function yetkiGorunumu() {
    return {
      gruplar: YETKI_GRUPLARI.map(([ad, yetkiler]) => ({
        ad: ad,
        yetkiler: yetkiler.map((y) => ({ id: y, ad: YETKI_ADLARI[y] })),
      })),
      kilitli: [...KILITLI_YETKILER],
      roller: Object.keys(ROL_ADLARI).map((rol) => ({
        id: rol,
        ad: ROL_ADLARI[rol],
        yetkiler: [...rolYetkileri[rol]],
        varsayilan: [...VARSAYILAN_YETKILER[rol]],
      })),
    };
  }
  // Demo bandından seçilen role göre kim giriş yapmış görünür
  const ROL_HESABI = { izleyici: "fabrika.muduru", operator: "vardiya.amiri", yonetici: "isg.uzmani" };

  const durum = {
    girisli: true,
    rol: "yonetici",
    ad: "isg.uzmani",
    baglanti: "canli", // canli | yok | kapandi
    baglantiDegisti: ACILIS,
  };

  // ------------------------------------------------------------ yardımcılar

  function iso(ms) {
    return new Date(ms).toISOString().replace(/\.\d{3}Z$/, "+00:00");
  }

  function turkiyeSaati(ms) {
    return Number(
      new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hourCycle: "h23", timeZone: SAAT_DILIMI }).format(
        new Date(ms),
      ),
    );
  }

  function turkiyeGunu(ms) {
    return new Date(ms).toLocaleDateString("tr-TR", { timeZone: SAAT_DILIMI });
  }

  function onaltilik(uzunluk) {
    const baytlar = new Uint8Array(uzunluk / 2);
    crypto.getRandomValues(baytlar);
    return Array.from(baytlar, (b) => b.toString(16).padStart(2, "0")).join("");
  }

  // Her kameranın ve fotoğrafın çizimi hep aynı olsun diye tohumlu rastgele
  function tohumlu(tohum) {
    let t = tohum >>> 0;
    return function () {
      t = (t + 0x6d2b79f5) >>> 0;
      let r = Math.imul(t ^ (t >>> 15), 1 | t);
      r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
      return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
    };
  }

  function paylastir(toplam, oranlar) {
    const paylar = oranlar.map((o) => Math.floor(toplam * o));
    paylar[0] += toplam - paylar.reduce((a, b) => a + b, 0);
    return paylar;
  }

  // ------------------------------------------------------------ fabrika

  const KAMERALAR = [
    {
      id: 1,
      ad: "Üretim Hattı 1",
      bolum: "Üretim",
      durum: "online",
      okunan_fps: 15,
      islenen_fps: 15,
      hedef_fps: 15,
      yavas: false,
    },
    {
      id: 2,
      ad: "Üretim Hattı 2",
      bolum: "Üretim",
      durum: "online",
      okunan_fps: 14.8,
      islenen_fps: 14.6,
      hedef_fps: 15,
      yavas: false,
    },
    {
      id: 3,
      ad: "Depo Girişi",
      bolum: "Depo",
      durum: "online",
      okunan_fps: 12,
      islenen_fps: 10,
      hedef_fps: 10,
      yavas: false,
    },
    {
      id: 4,
      ad: "Forklift Koridoru",
      bolum: "Depo",
      durum: "online",
      okunan_fps: 15,
      islenen_fps: 8.7,
      hedef_fps: 15,
      yavas: true,
    },
    {
      id: 5,
      ad: "Yükleme Rampası",
      bolum: "Sevkiyat",
      durum: "connecting",
      okunan_fps: 0,
      islenen_fps: 0,
      hedef_fps: 10,
      yavas: false,
    },
    {
      id: 6,
      ad: "Kazan Dairesi",
      bolum: "Bakım",
      durum: "offline",
      okunan_fps: null,
      islenen_fps: null,
      hedef_fps: 10,
      yavas: false,
    },
  ];
  const KAMERA = Object.fromEntries(KAMERALAR.map((k) => [k.ad, k]));

  const ONEM_ADLARI = { critical: "Kritik", high: "Yüksek", medium: "Orta", low: "Düşük" };
  const DURUM_ADLARI = { new: "yeni", reviewed: "incelendi", false_alarm: "yanlış alarm" };

  // [kaç dakika önce, tür, başlık, kamera ya da yer, önem, durum, süre, ayrıntı]
  const OLAY_TASLAKLARI = [
    [2, "ihlal", "Baret yok", "Üretim Hattı 1", "high", "new", "1 dk 40 sn"],
    [9, "ihlal", "Yasak bölge", "Forklift Koridoru", "critical", "new", "14 sn"],
    [
      18,
      "sistem",
      "Kamera yeniden bağlanıyor",
      "Yükleme Rampası",
      "",
      "",
      "",
      "Kameradan 30 saniyedir görüntü gelmiyor; yeniden bağlanılıyor.",
    ],
    [26, "ihlal", "Yelek yok", "Depo Girişi", "medium", "new", "22 sn"],
    [
      41,
      "sistem",
      "Uzaktan anons",
      "Tüm fabrika",
      "",
      "",
      "",
      "Uzak izleme panosundan anons: “Lütfen baret takınız” - Tüm fabrika. Hoparlör: çalındı.",
    ],
    [47, "ihlal", "Baret yok", "Üretim Hattı 2", "high", "reviewed", "9 sn"],
    [63, "ihlal", "Forklift yakınlığı", "Forklift Koridoru", "critical", "reviewed", "6 sn"],
    [85, "ihlal", "Eldiven yok", "Üretim Hattı 1", "low", "false_alarm", "5 sn"],
    [110, "ihlal", "Yelek yok", "Yükleme Rampası", "medium", "new", "31 sn"],
    [140, "ihlal", "Baret yok", "Depo Girişi", "high", "reviewed", "12 sn"],
    [
      175,
      "sistem",
      "Kamera bağlantısı koptu",
      "Kazan Dairesi",
      "",
      "",
      "",
      "Kameraya ağ üzerinden ulaşılamıyor ((adres)). Program 30 saniyede bir yeniden deniyor.",
    ],
    [210, "ihlal", "Yasak bölge", "Kazan Dairesi", "critical", "reviewed", "40 sn"],
    [260, "ihlal", "Baret yok", "Üretim Hattı 1", "high", "reviewed", "7 sn"],
    [320, "ihlal", "Yelek yok", "Forklift Koridoru", "medium", "false_alarm", "4 sn"],
    [
      400,
      "sistem",
      "Program başlatıldı",
      "",
      "",
      "",
      "",
      "NextGen Detector v2.2 Keskin Göz açıldı; 6 kameranın 5'i bağlandı.",
    ],
    [520, "ihlal", "Baret yok", "Yükleme Rampası", "high", "reviewed", "18 sn"],
    [700, "ihlal", "Forklift yakınlığı", "Forklift Koridoru", "critical", "reviewed", "3 sn"],
    [900, "ihlal", "Eldiven yok", "Üretim Hattı 2", "low", "reviewed", "11 sn"],
    [1150, "ihlal", "Yelek yok", "Depo Girişi", "medium", "reviewed", "26 sn"],
    [1400, "ihlal", "Baret yok", "Üretim Hattı 2", "high", "reviewed", "15 sn"],
  ];

  const olaylar = OLAY_TASLAKLARI.map(function (t, sira) {
    const [dk, tur, baslik, yerAdi, onem, olayDurumu, sure, ayrinti] = t;
    const kamera = KAMERA[yerAdi];
    return {
      id: 4821 - sira,
      // Son iki ihlalin fotoğrafı sitede yok (en çok 60 fotoğraf tutulur)
      foto: tur === "ihlal" && sira < 17,
      ayrinti: ayrinti || "",
      zamanMs: ACILIS - dk * DK,
      tur: tur,
      baslik: baslik,
      yer: kamera ? kamera.ad + " · " + kamera.bolum : yerAdi,
      kamera: kamera ? kamera.id : 0,
      onem: onem,
      onem_adi: ONEM_ADLARI[onem] || "",
      durum: tur === "ihlal" ? olayDurumu : "",
      durum_adi: DURUM_ADLARI[olayDurumu] || "",
      suruyor: sira === 0,
      sure: sure,
    };
  });

  const MESAJLAR = [
    { id: 1, metin: "Lütfen baret takınız" },
    { id: 2, metin: "Lütfen reflektif yelek giyiniz" },
    { id: 3, metin: "Forklift alanına yaya girişi yasaktır" },
    { id: 4, metin: "Vardiya değişimi: lütfen çalışma alanınızı toparlayınız" },
    { id: 5, metin: "Tatbikat başlıyor, toplanma alanına gidiniz" },
  ];
  const KANALLAR = [
    { id: 1, ad: "Tüm fabrika hoparlörü", bolum: "" },
    { id: 2, ad: "Üretim hoparlörü", bolum: "Üretim" },
    { id: 3, ad: "Depo hoparlörü", bolum: "Depo" },
    { id: 4, ad: "Sevkiyat hoparlörü", bolum: "Sevkiyat" },
  ];
  const ONCEKI_GUNLER = [14, 11, 17, 9, 6, 13, 15, 12, 10, 16, 8, 11, 13]; // en eskisi başta, sonuncusu dün
  // Saat başına olağan ihlal (vardiya saatlerinde çok, gece yok)
  const SAAT_AGIRLIGI = [0, 0, 0, 0, 0, 0, 1, 2, 2, 1, 1, 1, 0, 1, 2, 1, 1, 1, 0, 1, 0, 0, 0, 0];

  function saatlik(simdi) {
    const saat = turkiyeSaati(simdi);
    const bugun = turkiyeGunu(simdi);
    const dizi = SAAT_AGIRLIGI.map((n, s) => (s < saat ? n : 0));
    for (const o of olaylar) {
      if (o.tur === "ihlal" && turkiyeGunu(o.zamanMs) === bugun) dizi[turkiyeSaati(o.zamanMs)] += 1;
    }
    return dizi;
  }

  function teshisMetni(simdi) {
    const satirlar = KAMERALAR.map(function (k) {
      const fps = k.okunan_fps === null ? "-" : [k.okunan_fps, k.islenen_fps, k.hedef_fps].join(" / ");
      return "  " + k.ad + " - " + k.durum + " - " + fps + " kare/sn";
    });
    return [
      "Program: NextGen Detector v2.2 Keskin Göz",
      "Yapı: 3f9c2ab71e04 (çalıştırma 123)",
      "Kurulum: Windows uygulaması",
      "Çalışma süresi: " + Math.floor((simdi - ACILIS + 400 * DK) / SA) + " sa",
      "Analiz: çalışıyor, model hazır, uyarı garantisi var",
      "Kameralar:",
      ...satirlar,
      "Disk: 182,4 GB boş / 476,9 GB",
      "Son günlük satırları:",
      iso(simdi - 18 * DK) + " WARNING kamera: Yükleme Rampası yeniden bağlanıyor",
      iso(simdi - 175 * DK) + " WARNING kamera: Kameraya ağ üzerinden ulaşılamıyor ((adres))",
    ].join("\n");
  }

  // --------------------------------------------------------------- komutlar

  // Sunucudaki kayıt gibi: durum zamanla ilerler (ilerlet)
  const komutlar = [];

  function komutEkle(tur, ozet, kim, rol, dkOnce, sonDurum, mesaj, ek) {
    komutlar.push({
      id: onaltilik(16),
      tur: tur,
      ozet: ozet,
      kim: { ad: kim, rol: rol, rol_adi: ROL_ADLARI[rol] },
      olusturulduMs: ACILIS - dkOnce * DK,
      durum: sonDurum,
      mesaj: mesaj,
      ek: ek || "",
      bitti: true,
    });
  }
  komutEkle(
    "anons",
    "Anons: “Lütfen baret takınız” · Tüm fabrika",
    "vardiya.amiri",
    "operator",
    41,
    "yapildi",
    "Tüm fabrika: çalındı.",
  );
  komutEkle(
    "olay_incele",
    "İnceleme: “Baret yok” · Üretim Hattı 2 · Üretim → İncelendi",
    "vardiya.amiri",
    "operator",
    44,
    "yapildi",
    "Olay 4816 incelendi olarak işaretlendi.",
  );
  komutEkle(
    "ses_dene",
    "Hoparlör denemesi · Depo hoparlörü (Depo)",
    "isg.uzmani",
    "yonetici",
    190,
    "yapildi",
    "Depo hoparlörü: deneme sesi çalındı.",
  );
  komutEkle(
    "anons",
    "Anons: “Forklift alanına yaya girişi yasaktır” · Sevkiyat hoparlörü (Sevkiyat)",
    "vardiya.amiri",
    "operator",
    300,
    "hata",
    "Sevkiyat hoparlörüne ulaşılamadı; anons çalınmadı.",
  );
  komutEkle(
    "teshis",
    "Teşhis",
    "isg.uzmani",
    "yonetici",
    360,
    "yapildi",
    "Teşhis hazır.",
    teshisMetni(ACILIS - 360 * DK),
  );
  komutEkle(
    "guncelle",
    "Güncelleme",
    "isg.uzmani",
    "yonetici",
    410,
    "yapildi",
    "v2.2 Keskin Göz kuruldu; program yeniden açıldı.",
  );
  komutEkle(
    "yeniden_baslat",
    "Yeniden başlatma",
    "isg.uzmani",
    "yonetici",
    1500,
    "suresi_doldu",
    "Fabrika komutu 2 dakika içinde almadı; yapılmadı.",
  );
  komutlar.sort((a, b) => b.olusturulduMs - a.olusturulduMs);

  const AGIR = ["yeniden_baslat", "guncelle"];
  const YONETIM = ["teshis", "yeniden_baslat", "guncelle"];
  const MUDAHALE = ["anons", "ses_dene", "olay_incele"];

  /* Yeni komutun yolu: Sırada (2,5 sn) -> Fabrikada (2,5 sn) -> Yapıldı.
     Yeniden başlatma ve güncelleme arada "sürüyor" der ve program bir süre
     kapanır (panoda "Fabrika programı kapatıldı"). */
  function ilerlet(simdi) {
    for (const k of komutlar) {
      if (k.bitti) continue;
      const yas = simdi - k.olusturulduMs;
      const agir = AGIR.includes(k.tur);
      if (yas < 2500) {
        k.durum = "bekliyor";
      } else if (yas < 5000) {
        k.durum = "iletildi";
        k.mesaj = "";
      } else if (agir && yas < 25000) {
        k.durum = "suruyor";
        k.mesaj =
          k.tur === "guncelle"
            ? "Kontrol Paneli'ne iletildi; güncelleme hazırlanıyor."
            : "Program yeniden başlatılıyor; kameralar birazdan yeniden izlenir.";
      } else {
        k.durum = "yapildi";
        k.mesaj = k.sonucMesaji;
        k.bitti = true;
        if (k.tur === "teshis") k.ek = teshisMetni(simdi);
        if (k.tur === "olay_incele") {
          const olay = olaylar.find((o) => o.id === k.olayId);
          if (olay) {
            olay.durum = k.karar;
            olay.durum_adi = DURUM_ADLARI[k.karar];
          }
        }
      }
    }
  }

  // Ağır iş sürerken program kapanıp açılır (yeniden başlatma, güncelleme)
  function agirKapanis(simdi) {
    const k = komutlar.find(
      (k) =>
        AGIR.includes(k.tur) &&
        !k.bitti &&
        simdi - k.olusturulduMs >= 8000 &&
        simdi - k.olusturulduMs < 22000,
    );
    return k
      ? { sebep: k.tur === "guncelle" ? "guncelleme" : "yeniden_baslatma", an: k.olusturulduMs + 8000 }
      : null;
  }

  function komutGorunumu(k, ekGoster) {
    const gorunum = {
      id: k.id,
      tur: k.tur,
      ozet: k.ozet,
      kim: k.kim,
      olusturuldu: iso(k.olusturulduMs),
      durum: k.durum,
      mesaj: k.mesaj,
    };
    if (ekGoster && k.ek) gorunum.ek = k.ek;
    return gorunum;
  }

  // --------------------------------------------------------------- hesaplar

  const kullanicilar = [
    {
      ad: "isg.uzmani",
      rol: "yonetici",
      acik: true,
      sifre_degismeli: false,
      olusturulduMs: ACILIS - 9 * 24 * SA,
      sonGirisMs: ACILIS - 2 * DK,
    },
    {
      ad: "vardiya.amiri",
      rol: "operator",
      acik: true,
      sifre_degismeli: false,
      iki_adim: true,
      olusturulduMs: ACILIS - 9 * 24 * SA,
      sonGirisMs: ACILIS - 48 * DK,
    },
    {
      ad: "uretim.sefi",
      rol: "operator",
      acik: true,
      sifre_degismeli: false,
      olusturulduMs: ACILIS - 8 * 24 * SA,
      sonGirisMs: ACILIS - 26 * SA,
    },
    {
      ad: "fabrika.muduru",
      rol: "izleyici",
      acik: true,
      sifre_degismeli: false,
      olusturulduMs: ACILIS - 8 * 24 * SA,
      sonGirisMs: ACILIS - 3 * SA,
    },
    {
      ad: "bakim.ekibi",
      rol: "operator",
      acik: true,
      sifre_degismeli: true,
      olusturulduMs: ACILIS - 2 * 24 * SA,
      sonGirisMs: null,
    },
    {
      ad: "stajyer",
      rol: "izleyici",
      acik: false,
      sifre_degismeli: false,
      olusturulduMs: ACILIS - 30 * 24 * SA,
      sonGirisMs: ACILIS - 12 * 24 * SA,
    },
  ];

  const kayit = [];
  function kayitYaz(ms, kim, rol, is, ozet, sonuc) {
    kayit.push({ zMs: ms, kim: kim, rol: rol, is: is, ozet: ozet, sonuc: sonuc });
  }
  kayitYaz(ACILIS - 2 * DK, "isg.uzmani", "yonetici", "giris", "", "tamam");
  kayitYaz(
    ACILIS - 41 * DK,
    "vardiya.amiri",
    "operator",
    "komut",
    "Anons: “Lütfen baret takınız” · Tüm fabrika",
    "tamam",
  );
  kayitYaz(
    ACILIS - 44 * DK,
    "vardiya.amiri",
    "operator",
    "komut",
    "İnceleme: “Baret yok” · Üretim Hattı 2 · Üretim → İncelendi",
    "tamam",
  );
  kayitYaz(ACILIS - 48 * DK, "vardiya.amiri", "operator", "giris", "", "tamam");
  kayitYaz(ACILIS - 52 * DK, "vardiya.amiri", "operator", "giris_hatali", "", "hata");
  kayitYaz(ACILIS - 3 * SA, "fabrika.muduru", "izleyici", "giris", "", "tamam");
  kayitYaz(
    ACILIS - 3 * SA - 4 * DK,
    "fabrika.muduru",
    "izleyici",
    "komut_red",
    "Yetki yetmedi: anons",
    "red",
  );
  kayitYaz(
    ACILIS - 190 * DK,
    "isg.uzmani",
    "yonetici",
    "komut",
    "Hoparlör denemesi · Depo hoparlörü (Depo)",
    "tamam",
  );
  kayitYaz(
    ACILIS - 300 * DK,
    "vardiya.amiri",
    "operator",
    "komut",
    "Anons: “Forklift alanına yaya girişi yasaktır” · Sevkiyat hoparlörü (Sevkiyat)",
    "tamam",
  );
  kayitYaz(ACILIS - 359 * DK, "fabrika", "", "komut_sonuc", "Teşhis", "tamam");
  kayitYaz(ACILIS - 360 * DK, "isg.uzmani", "yonetici", "komut", "Teşhis", "tamam");
  kayitYaz(ACILIS - 402 * DK, "fabrika", "", "komut_sonuc", "Güncelleme", "tamam");
  kayitYaz(ACILIS - 410 * DK, "isg.uzmani", "yonetici", "komut", "Güncelleme", "tamam");
  kayitYaz(ACILIS - 2 * 24 * SA, "isg.uzmani", "yonetici", "hesap_ekle", "bakim.ekibi (Operatör)", "tamam");
  kayitYaz(ACILIS - 2 * 24 * SA - 5 * DK, "isg.uzmani", "yonetici", "hesap_kapat", "stajyer", "tamam");
  kayitYaz(
    ACILIS - 3 * 24 * SA,
    "isg.uzmani",
    "yonetici",
    "rol_degistir",
    "uretim.sefi -> Operatör",
    "tamam",
  );
  kayitYaz(ACILIS - 9 * 24 * SA, "isg.uzmani", "yonetici", "sifre_degistir", "", "tamam");
  kayitYaz(
    ACILIS - 9 * 24 * SA - 10 * DK,
    "kurucu",
    "yonetici",
    "hesap_ekle",
    "isg.uzmani (Yönetici)",
    "tamam",
  );

  function hesapVerisi() {
    const kurucu = {
      ad: "kurucu",
      rol: "yonetici",
      rol_adi: "Yönetici",
      acik: true,
      kurucu: true,
      sifre_degismeli: false,
      olusturuldu: null,
      son_giris: null,
    };
    const satirlar = kullanicilar.map((k) => ({
      ad: k.ad,
      rol: k.rol,
      rol_adi: ROL_ADLARI[k.rol],
      acik: k.acik,
      kurucu: false,
      sifre_degismeli: k.sifre_degismeli,
      olusturuldu: k.olusturulduMs ? iso(k.olusturulduMs) : null,
      son_giris: k.sonGirisMs ? iso(k.sonGirisMs) : null,
      ...(k.iki_adim ? { iki_adim: true } : {}),
    }));
    const liste = kayit
      .slice()
      .sort((a, b) => b.zMs - a.zMs)
      .map((r) => ({
        z: Math.floor(r.zMs / SN),
        zaman: iso(r.zMs),
        kim: r.kim,
        rol: r.rol,
        rol_adi: ROL_ADLARI[r.rol] || "",
        is: r.is,
        ozet: r.ozet,
        sonuc: r.sonuc,
      }));
    return { kullanicilar: [kurucu, ...satirlar], kayit: liste, yetki: yetkiGorunumu() };
  }

  // ----------------------------------------------------------------- rapor

  function rapor(simdi, kapanis) {
    const saatler = saatlik(simdi);
    const bugun = saatler.reduce((a, b) => a + b, 0);
    const gunluk = [...ONCEKI_GUNLER, bugun];
    const yediGun = gunluk.slice(-7).reduce((a, b) => a + b, 0);
    const yerPayi = paylastir(yediGun, [0.28, 0.24, 0.17, 0.14, 0.11, 0.06]);
    const yerSirasi = [
      "Forklift Koridoru",
      "Üretim Hattı 1",
      "Depo Girişi",
      "Üretim Hattı 2",
      "Yükleme Rampası",
      "Kazan Dairesi",
    ];
    const ogePayi = paylastir(yediGun, [0.36, 0.24, 0.16, 0.14, 0.1]);
    const ogeAdlari = ["Baret yok", "Yelek yok", "Yasak bölge", "Forklift yakınlığı", "Eldiven yok"];
    const canli = KAMERALAR.filter((k) => k.durum === "online").length;
    return {
      surum: 1,
      uretildi: iso(simdi),
      aralik_sn: 30,
      kapanis: !!kapanis,
      kapanis_sebebi: kapanis ? kapanis.sebep : "",
      program: {
        ad: "NextGen Detector",
        surum: "v2.2 Keskin Göz",
        yapi: {
          commit: "3f9c2ab71e04d5c86b2a90f1e7d4c3b2a1908f7e",
          tarih: iso(ACILIS - 2 * 24 * SA),
          calistirma: 123,
        },
      },
      sistem: {
        analiz: true,
        hazir: true,
        model: "hazir",
        uyari_garantisi: true,
        sorunlar: ["Kazan Dairesi kamerasından görüntü gelmiyor."],
        bos_disk_gb: 182.4,
        calisma_suresi_sn: Math.floor((simdi - ACILIS) / SN) + 400 * 60,
      },
      kameralar: KAMERALAR.map((k) => ({
        id: k.id,
        ad: k.ad,
        bolum: k.bolum,
        durum: k.durum,
        okunan_fps: k.okunan_fps,
        islenen_fps: k.islenen_fps,
        hedef_fps: k.hedef_fps,
        yavas: k.yavas,
        son_kare_yasi_sn:
          k.durum === "online"
            ? 0
            : k.durum === "connecting"
              ? 35
              : Math.floor((simdi - ACILIS) / SN) + 175 * 60,
      })),
      sayilar: {
        bugun_ihlal: bugun,
        dun_ihlal: ONCEKI_GUNLER[ONCEKI_GUNLER.length - 1],
        bekleyen: olaylar.filter((o) => o.tur === "ihlal" && o.durum === "new").length,
        aktif_kural: 5,
        kamera_toplam: KAMERALAR.length,
        kamera_canli: canli,
      },
      saatlik: saatler,
      ogeler: ogeAdlari.map((ad, i) => ({ ad: ad, sayi: ogePayi[i] })),
      son_olaylar: olaylar.map((o) => ({
        id: o.id,
        foto: o.foto,
        ayrinti: o.ayrinti,
        zaman: iso(o.zamanMs),
        tur: o.tur,
        baslik: o.baslik,
        yer: o.yer,
        onem: o.onem,
        onem_adi: o.onem_adi,
        durum_adi: o.durum_adi,
        durum: o.durum,
        suruyor: o.suruyor,
        sure: o.sure,
      })),
      mudahale: {
        acik: true,
        isler: ["anons", "ses_dene", "olay_incele"],
        mesajlar: MESAJLAR,
        kanallar: KANALLAR,
      },
      gunluk: gunluk,
      yedi_gun: {
        ihlal: yediGun,
        incelenen: Math.round(yediGun * 0.78),
        yanlis_alarm: Math.round(yediGun * 0.09),
      },
      yerler: yerSirasi.map((ad, i) => ({ ad: ad, bolum: KAMERA[ad].bolum, sayi: yerPayi[i] })),
      bilgisayar: {
        ad: "Örnek fabrika",
        bilgisayar_adi: "ISG-PC-01",
        isletim_sistemi: "Windows 11 Pro",
        islemci: "Intel Core i7-12700",
        cekirdek: 12,
        bellek_gb: 32,
        ekran_karti: "NVIDIA GeForce RTX 3060",
        cikarim: "Ekran kartı (DirectML)",
        disk_toplam_gb: 476.9,
        kurulum_turu: "Windows uygulaması",
        kurulum_tarihi: iso(ACILIS - 12 * 24 * SA),
        acilis: iso(ACILIS - 2 * 24 * SA - 3 * SA),
        ip: ["192.168.1.20"],
      },
      yonetim: {
        acik: true,
        isler: ["teshis", "yeniden_baslat", "guncelle"],
        kurulum: "paket",
        yeniden_baslatma: { mumkun: true, sebep: "" },
        guncelleme: { mumkun: true, sebep: "" },
      },
      // Bu ayın çalışma oranı (isteğe bağlı alan): ayın başından bu yana ölçülen saat
      calisma: {
        ay: new Date(simdi).toISOString().slice(0, 7),
        sistem_yuzde: 99.6,
        kamera_yuzde: 98.9,
        olculen_saat: Math.min(744, Math.max(1, Math.floor((simdi - ayBasi(simdi)) / SA))),
      },
    };
  }

  function ayBasi(ms) {
    const an = new Date(ms);
    return Date.UTC(an.getUTCFullYear(), an.getUTCMonth(), 1);
  }

  /* pano_verisi + durum(): bağlantı, rol süzgeci, ?mudahale=1 / ?yonetim=1 /
     ?kare=1 ekleri. Bağlantı demo bandından seçilir. */
  function panoVerisi(simdi, sorgu) {
    ilerlet(simdi);
    const kapanis = agirKapanis(simdi);
    let baglanti = durum.baglanti;
    let sonRapor;
    let kapanisBilgisi = null;
    if (baglanti === "canli" && kapanis) {
      baglanti = "kapandi";
      sonRapor = kapanis.an;
      kapanisBilgisi = kapanis;
    } else if (baglanti === "canli") {
      sonRapor = simdi - ((simdi - ACILIS) % (30 * SN)); // 30 saniyede bir rapor
    } else if (baglanti === "yok") {
      sonRapor = durum.baglantiDegisti - 4 * DK;
    } else {
      sonRapor = durum.baglantiDegisti - 3 * DK;
      kapanisBilgisi = { sebep: "" };
    }
    const r = rapor(sonRapor, kapanisBilgisi);
    const veri = {
      baglanti: baglanti,
      son_rapor: iso(sonRapor),
      gecikme_sn: Math.max(0, Math.round((simdi - sonRapor) / SN)),
      sunucu_zamani: iso(simdi),
      rapor: r,
      fabrika_adresi: "",
      oturum: {
        ad: durum.ad,
        rol: durum.rol,
        rol_adi: ROL_ADLARI[durum.rol],
        kurucu: false,
        sifre_degismeli: false,
        ...(oturumHesabi() && oturumHesabi().iki_adim ? { iki_adim: true } : {}),
        yetkiler: [...rolYetkileri[durum.rol]],
      },
      onizleme: false,
    };
    // Rol süzgeci api/_pano.py durum() ile aynı (docs/19 §1)
    const yoneticiMi = yetkiliMi("ekran.yonetim");
    const mudahaleciMi = yetkiliMi("ekran.mudahale");
    if (!yoneticiMi) delete r.yonetim;
    if (!yetkiliMi("veri.bilgisayar")) {
      delete r.bilgisayar.ip;
      delete r.bilgisayar.bilgisayar_adi;
      // İzleyici hazır anons metinlerini ve hoparlör kanallarını görmez; blok
      // biçimi aynı kalır, listeler boşalır (en az yetki). Sabit diziler
      // paylaşıldığı için yeni nesne kurulur.
      r.mudahale = { ...r.mudahale, mesajlar: [], kanallar: [] };
    }
    const mudahaleIster = sorgu.get("mudahale") === "1" && mudahaleciMi;
    const yonetimIster = sorgu.get("yonetim") === "1" && yoneticiMi;
    if (mudahaleIster || yonetimIster) {
      const gorunur = [...MUDAHALE, ...YONETIM].filter((t) => yetkiliMi("komut." + t));
      const yoklama = veri.baglanti === "canli" ? simdi - 2 * SN : null;
      veri.mudahale = {
        komutlar: komutlar
          .filter((k) => gorunur.includes(k.tur))
          .slice(0, 20)
          .map((k) => komutGorunumu(k, yoneticiMi)),
        son_yoklama: yoklama ? iso(yoklama) : null,
        yoklama_yasi_sn: yoklama ? 2 : null,
      };
    }
    if (sorgu.get("kare") === "1") {
      veri.kareler = {};
      if (veri.baglanti === "canli") {
        for (const k of KAMERALAR) {
          if (k.durum !== "online") continue;
          // Fabrika 10 saniyede bir gönderir; kameralar biraz kaydırılmış
          const an = simdi - 1500 - k.id * 700;
          veri.kareler[String(k.id)] = iso(an - (an % (10 * SN)));
        }
      }
    }
    // Tesisler ekranı (yalnız yönetici; filo_verisi): ana tesis bu panonun
    // fabrikası, öbür ikisi yalnız izlenir (biri canlı, biri haber vermiyor)
    if (sorgu.get("filo") === "1" && yetkiliMi("ekran.tesisler")) {
      const paketlemeSon = ACILIS - 135 * DK;
      veri.filo = {
        ana_tesis: "merkez",
        uyarilar: [
          "Aynı tesis kimliği iki bilgisayardan geliyor: lojistik (Lojistik deposu · DEPO-PC, " +
            "Lojistik deposu · DEPO-PC-2). Her bilgisayara farklı UZAK_PANO_TESIS_ID yazın.",
        ],
        tesisler: [
          {
            id: "merkez",
            ad: r.bilgisayar.ad,
            baglanti: veri.baglanti,
            son_rapor: veri.son_rapor,
            gecikme_sn: veri.gecikme_sn,
            bugun_ihlal: r.sayilar.bugun_ihlal,
            ana: true,
          },
          {
            id: "lojistik",
            ad: "Lojistik deposu",
            baglanti: "canli",
            son_rapor: iso(simdi - 12 * SN),
            gecikme_sn: 12,
            bugun_ihlal: 4,
            ana: false,
            // Aynı kimlik iki bilgisayardan geliyor (kopyalanan .env örneği)
            cakisma: {
              adlar: ["Lojistik deposu · DEPO-PC", "Lojistik deposu · DEPO-PC-2"],
              zaman: iso(simdi - 12 * SN),
            },
          },
          {
            id: "paketleme",
            ad: "Paketleme tesisi",
            baglanti: "yok",
            son_rapor: iso(paketlemeSon),
            gecikme_sn: Math.round((simdi - paketlemeSon) / SN),
            bugun_ihlal: 7,
            ana: false,
          },
        ],
      };
    }
    return veri;
  }

  // ----------------------------------------------------------- uç noktalar

  class DemoHatasi extends Error {
    constructor(kod, hata, mesaj) {
      super(mesaj);
      this.kod = kod;
      this.hata = hata;
    }
  }

  /* api/_pano.py ROL_SIRASI'nın aynısı; tanınmayan rol -1 (hiçbir eşiği geçmez). */
  function rolSirasi(rol) {
    const sira = { izleyici: 0, operator: 1, yonetici: 2 }[rol];
    return sira === undefined ? -1 : sira;
  }

  function komutKaydet(simdi, tur, ozet, sonucMesaji, ek) {
    const k = {
      id: onaltilik(16),
      tur: tur,
      ozet: ozet,
      kim: { ad: durum.ad, rol: durum.rol, rol_adi: ROL_ADLARI[durum.rol] },
      olusturulduMs: simdi,
      durum: "bekliyor",
      mesaj: "",
      ek: "",
      bitti: false,
      sonucMesaji: sonucMesaji,
      ...ek,
    };
    komutlar.unshift(k);
    kayitYaz(simdi, durum.ad, durum.rol, "komut", ozet, "tamam");
    return k;
  }

  function mudahaleIstegi(govde, simdi) {
    // Kaba kapı: hiç komut yetkisi yoksa gövde okunmadan 403 (sunucunun sırası)
    if (![...MUDAHALE, ...YONETIM].some((t) => yetkiliMi("komut." + t))) {
      throw new DemoHatasi(403, "yetki", "Bu iş için yetkiniz yok.");
    }
    const tur = govde.tur;
    if (![...MUDAHALE, ...YONETIM].includes(tur)) throw new DemoHatasi(400, "tur", "Bilinmeyen müdahale.");
    if (!yetkiliMi("komut." + tur)) {
      kayitYaz(simdi, durum.ad, durum.rol, "komut_red", "Yetki yetmedi: " + tur, "red");
      throw new DemoHatasi(403, "yetki", "Bu iş için yetkiniz yok.");
    }
    if (AGIR.includes(tur) && !govde.sifre) {
      throw new DemoHatasi(400, "onay_sifresi", "Şifreniz yanlış; işlem yapılmadı.");
    }
    if (panoVerisi(simdi, new URLSearchParams()).baglanti !== "canli") {
      throw new DemoHatasi(
        409,
        "fabrika_bagli_degil",
        "Fabrika programından şu an haber gelmiyor; komut gönderilemez.",
      );
    }
    let k;
    if (tur === "anons" || tur === "ses_dene") {
      let yer;
      let kanalAdi;
      if (govde.kanal_id === null || govde.kanal_id === undefined) {
        if (tur !== "anons")
          throw new DemoHatasi(400, "kanal", "Bu ses kanalı fabrikada yok; sayfayı yenileyin.");
        yer = "Tüm fabrika";
        kanalAdi = "Tüm fabrika";
      } else {
        const kanal = KANALLAR.find((x) => x.id === govde.kanal_id);
        if (!kanal) throw new DemoHatasi(400, "kanal", "Bu ses kanalı fabrikada yok; sayfayı yenileyin.");
        yer = kanal.ad + (kanal.bolum ? " (" + kanal.bolum + ")" : "");
        kanalAdi = kanal.ad;
      }
      if (tur === "anons") {
        const mesaj = MESAJLAR.find((m) => m.id === govde.mesaj_id);
        if (!mesaj) throw new DemoHatasi(400, "mesaj", "Bu anons mesajı fabrikada yok; sayfayı yenileyin.");
        k = komutKaydet(simdi, tur, "Anons: “" + mesaj.metin + "” · " + yer, kanalAdi + ": çalındı.");
      } else {
        k = komutKaydet(simdi, tur, "Hoparlör denemesi · " + yer, kanalAdi + ": deneme sesi çalındı.");
      }
    } else if (tur === "olay_incele") {
      const olay = olaylar.find((o) => o.id === govde.olay_id);
      if (!olay || olay.tur !== "ihlal") {
        throw new DemoHatasi(
          400,
          "olay",
          "Bu olay fabrikanın son raporunda yok ya da ihlal değil; sayfayı yenileyin.",
        );
      }
      if (olay.durum !== "new")
        throw new DemoHatasi(
          409,
          "olay_incelenmis",
          "Bu olay fabrikada zaten incelenmiş; sayfayı yenileyin.",
        );
      const karar = govde.karar === "false_alarm" ? "false_alarm" : "reviewed";
      const kararAdi = karar === "reviewed" ? "İncelendi" : "Yanlış alarm";
      k = komutKaydet(
        simdi,
        tur,
        "İnceleme: “" + olay.baslik + "” · " + olay.yer + " → " + kararAdi,
        "Olay " + olay.id + " " + kararAdi.toLocaleLowerCase("tr-TR") + " olarak işaretlendi.",
        { olayId: olay.id, karar: karar },
      );
    } else if (tur === "teshis") {
      k = komutKaydet(simdi, tur, "Teşhis", "Teşhis hazır.");
    } else {
      if (komutlar.some((x) => AGIR.includes(x.tur) && !x.bitti)) {
        throw new DemoHatasi(409, "agir_suruyor", "Önceki güncelleme ya da yeniden başlatma henüz bitmedi.");
      }
      k =
        tur === "guncelle"
          ? komutKaydet(
              simdi,
              tur,
              "Güncelleme",
              "Program zaten son sürümde (v2.2 Keskin Göz); yeniden açıldı.",
            )
          : komutKaydet(simdi, tur, "Yeniden başlatma", "Program yeniden başlatıldı; kameralar izleniyor.");
    }
    return { tamam: true, komut: komutGorunumu(k, durum.rol === "yonetici") };
  }

  function yeniSifreDogrula(yeni, ad) {
    if (typeof yeni !== "string" || yeni.length < 10)
      throw new DemoHatasi(400, "sifre_kisa", "Şifre en az 10 karakter olmalı.");
    if (yeni === ad) throw new DemoHatasi(400, "sifre_ad_ayni", "Şifre kullanıcı adıyla aynı olamaz.");
  }

  function oturumHesabi() {
    return kullanicilar.find((k) => k.ad === durum.ad) || null;
  }

  function demoSir() {
    const harfler = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
    const baytlar = new Uint8Array(32);
    crypto.getRandomValues(baytlar);
    return Array.from(baytlar, (b) => harfler[b % 32]).join("");
  }

  /* Kendi iki adımı (her rol): baslat şifreyle sır verir, onayla 6 haneli
     herhangi bir kodu kabul eder (demo), kapat şifre ve kod ister. */
  function ikiAdimIstegi(govde, simdi) {
    const hesap = oturumHesabi();
    const eylem = govde.eylem;
    if (!hesap) throw new DemoHatasi(400, "eylem", "Bu demoda bu hesabın iki adımı yok.");
    const kodGecerli = /^[0-9]{6}$/.test(String(govde.kod || "").replace(/\s+/g, ""));
    if (eylem === "iki_adim_baslat") {
      if (!govde.sifre) throw new DemoHatasi(400, "onay_sifresi", "Şifreniz yanlış; işlem yapılmadı.");
      if (hesap.iki_adim) {
        throw new DemoHatasi(409, "iki_adim_acik", "İki adımlı doğrulama zaten açık; yeni telefon için önce kapatın.");
      }
      const sir = demoSir();
      hesap.bekleyenSir = sir;
      return {
        tamam: true,
        sir: sir,
        uri: "otpauth://totp/DALSAN:" + hesap.ad + "?secret=" + sir + "&issuer=DALSAN",
        sure_sn: 600,
      };
    }
    if (eylem === "iki_adim_onayla") {
      if (!hesap.bekleyenSir) {
        throw new DemoHatasi(
          400,
          "iki_adim_bekleyen_yok",
          "Kurulum bulunamadı ya da 10 dakikası doldu; İki adımlı doğrulama bölümünden yeniden başlatın.",
        );
      }
      if (!kodGecerli) throw new DemoHatasi(400, "kod_yanlis", "Doğrulama kodu yanlış ya da süresi geçti.");
      hesap.bekleyenSir = null;
      hesap.iki_adim = true;
      kayitYaz(simdi, durum.ad, durum.rol, "iki_adim_ac", "", "tamam");
      return { tamam: true };
    }
    if (!hesap.iki_adim) throw new DemoHatasi(409, "iki_adim_kapali", "İki adımlı doğrulama zaten kapalı.");
    if (!govde.sifre) throw new DemoHatasi(400, "onay_sifresi", "Şifreniz yanlış; işlem yapılmadı.");
    if (!kodGecerli) throw new DemoHatasi(400, "kod_yanlis", "Doğrulama kodu yanlış; işlem yapılmadı.");
    hesap.iki_adim = false;
    kayitYaz(simdi, durum.ad, durum.rol, "iki_adim_kapat", "", "tamam");
    return { tamam: true };
  }

  function hesapIstegi(govde, simdi) {
    const eylem = govde.eylem;
    if (["iki_adim_baslat", "iki_adim_onayla", "iki_adim_kapat"].includes(eylem)) {
      return ikiAdimIstegi(govde, simdi);
    }
    if (eylem === "sifre_degistir") {
      if (!govde.eski_sifre)
        throw new DemoHatasi(400, "eski_sifre", "Eski şifreniz yanlış; işlem yapılmadı.");
      yeniSifreDogrula(govde.yeni_sifre, durum.ad);
      kayitYaz(simdi, durum.ad, durum.rol, "sifre_degistir", "", "tamam");
      return { tamam: true };
    }
    // Rol yetkilerinin tanımı: demoda kurucu yok, yönetici değiştirebilir
    // (gerçek sitede yalnız kurucu; docs/19 §1)
    if (eylem === "rol_yetkileri") {
      if (!yetkiliMi("hesap.yonet")) {
        kayitYaz(simdi, durum.ad, durum.rol, "komut_red", "Yalnız kurucu: rol_yetkileri", "red");
        throw new DemoHatasi(403, "yalniz_kurucu", "Rol yetkilerini yalnız kurucu hesabı değiştirebilir.");
      }
      const gelen = govde.yetkiler;
      if (!gelen || typeof gelen !== "object" || !Object.keys(gelen).length) {
        throw new DemoHatasi(400, "yetkiler", "Değiştirilecek rol yetkisi gelmedi.");
      }
      if (!govde.sifre) throw new DemoHatasi(400, "onay_sifresi", "Şifreniz yanlış; işlem yapılmadı.");
      let degisti = false;
      for (const rol of Object.keys(ROL_ADLARI)) {
        if (!(rol in gelen)) continue;
        const yeni = yetkiKumesiDuzelt(gelen[rol], rol);
        if (yeni.join("|") !== rolYetkileri[rol].join("|")) degisti = true;
        rolYetkileri[rol] = yeni;
      }
      if (degisti) {
        kayitYaz(simdi, durum.ad, durum.rol, "rol_yetkileri", "Yetkiler güncellendi", "tamam");
      }
      return { tamam: true, degisti: degisti, yetki: yetkiGorunumu() };
    }
    if (!yetkiliMi("hesap.yonet")) {
      kayitYaz(simdi, durum.ad, durum.rol, "komut_red", "Yetki yetmedi: " + eylem, "red");
      throw new DemoHatasi(403, "yetki", "Bu iş için yönetici yetkisi gerekir.");
    }
    if (!["ekle", "rol", "sifre_sifirla", "kapat", "ac", "sil", "iki_adim_sifirla"].includes(eylem)) {
      throw new DemoHatasi(400, "eylem", "Bilinmeyen işlem.");
    }
    const ad = String(govde.ad || "")
      .trim()
      .toLocaleLowerCase("tr-TR");
    const hedef = kullanicilar.find((k) => k.ad === ad) || null;
    const yeniRol = ["izleyici", "operator", "yonetici"].includes(govde.rol) ? govde.rol : "";
    const yoneticiIsi =
      (eylem === "ekle" && yeniRol === "yonetici") ||
      (eylem === "rol" && (yeniRol === "yonetici" || (hedef && hedef.rol === "yonetici"))) ||
      (["sifre_sifirla", "kapat", "ac", "sil", "iki_adim_sifirla"].includes(eylem) &&
        hedef &&
        hedef.rol === "yonetici");
    if (ad === "kurucu") throw new DemoHatasi(400, "kurucu", "Kurucu hesabı buradan değiştirilemez.");
    if (["rol", "kapat", "sil", "iki_adim_sifirla"].includes(eylem) && ad === durum.ad) {
      throw new DemoHatasi(400, "kendi_hesabi", "Kendi hesabınızın bu ayarını buradan değiştiremezsiniz.");
    }
    if (yoneticiIsi) {
      kayitYaz(simdi, durum.ad, durum.rol, "komut_red", "Yalnız kurucu: " + eylem, "red");
      throw new DemoHatasi(403, "yalniz_kurucu", "Yönetici hesaplarını yalnız kurucu hesabı değiştirebilir.");
    }
    if (!govde.sifre) throw new DemoHatasi(400, "onay_sifresi", "Şifreniz yanlış; işlem yapılmadı.");
    if (eylem === "ekle") {
      if (!/^[a-z0-9][a-z0-9._-]{2,31}$/.test(ad)) {
        throw new DemoHatasi(
          400,
          "ad_gecersiz",
          "Kullanıcı adı 3-32 karakter; küçük harf, rakam, nokta, tire ve alt çizgi.",
        );
      }
      if (["kurucu", "fabrika", "sistem", "site"].includes(ad)) {
        throw new DemoHatasi(400, "ad_ayrilmis", "Bu ad sistemde kullanılıyor; başka bir ad seçin.");
      }
      if (!yeniRol) throw new DemoHatasi(400, "rol", "Rol seçilmedi.");
      yeniSifreDogrula(govde.ilk_sifre, ad);
      if (hedef) throw new DemoHatasi(409, "ad_alinmis", "Bu kullanıcı adı zaten var.");
      kullanicilar.push({
        ad: ad,
        rol: yeniRol,
        acik: true,
        sifre_degismeli: true,
        olusturulduMs: simdi,
        sonGirisMs: null,
      });
      kayitYaz(simdi, durum.ad, durum.rol, "hesap_ekle", ad + " (" + ROL_ADLARI[yeniRol] + ")", "tamam");
      return { tamam: true, ad: ad };
    }
    if (!hedef) throw new DemoHatasi(404, "hesap_yok", "Böyle bir hesap yok.");
    let is;
    let ozet = ad;
    if (eylem === "rol") {
      if (!yeniRol) throw new DemoHatasi(400, "rol", "Rol seçilmedi.");
      hedef.rol = yeniRol;
      is = "rol_degistir";
      ozet = ad + " -> " + ROL_ADLARI[yeniRol];
    } else if (eylem === "sifre_sifirla") {
      yeniSifreDogrula(govde.yeni_sifre, ad);
      hedef.sifre_degismeli = true;
      is = "sifre_sifirla";
    } else if (eylem === "kapat" || eylem === "ac") {
      hedef.acik = eylem === "ac";
      is = eylem === "ac" ? "hesap_ac" : "hesap_kapat";
    } else if (eylem === "iki_adim_sifirla") {
      if (!hedef.iki_adim) {
        throw new DemoHatasi(409, "iki_adim_kapali", "Bu hesapta iki adımlı doğrulama zaten kapalı.");
      }
      hedef.iki_adim = false;
      is = "iki_adim_sifirla";
    } else {
      kullanicilar.splice(kullanicilar.indexOf(hedef), 1);
      is = "hesap_sil";
    }
    kayitYaz(simdi, durum.ad, durum.rol, is, ozet, "tamam");
    return { tamam: true };
  }

  function giris(govde, simdi) {
    const ad = String(govde.ad || "")
      .trim()
      .toLocaleLowerCase("tr-TR");
    if (!ad || !govde.sifre) throw new DemoHatasi(400, "giris_eksik", "Kullanıcı adı ve şifre gerekir.");
    const hesap = kullanicilar.find((k) => k.ad === ad);
    if (hesap && hesap.iki_adim && !/^[0-9]{6}$/.test(String(govde.kod || "").replace(/\s+/g, ""))) {
      throw new DemoHatasi(
        401,
        govde.kod ? "kod_yanlis" : "iki_adim_gerekli",
        govde.kod
          ? "Doğrulama kodu yanlış ya da süresi geçti; uygulamadaki güncel kodu yazın."
          : "Telefonunuzdaki doğrulama uygulamasının gösterdiği 6 haneli kodu yazın.",
      );
    }
    durum.rol = hesap ? hesap.rol : "yonetici";
    durum.ad = hesap ? hesap.ad : ROL_HESABI[durum.rol];
    durum.girisli = true;
    kayitYaz(simdi, durum.ad, durum.rol, "giris", "", "tamam");
    secicileriEsle();
    return { tamam: true };
  }

  function yanit(kod, govde) {
    return new Response(JSON.stringify(govde), {
      status: kod,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  }

  function bekle(ms) {
    return new Promise((coz) => setTimeout(coz, ms));
  }

  const gercekFetch = window.fetch.bind(window);

  window.fetch = async function (adres, secenekler) {
    const url = new URL(typeof adres === "string" ? adres : adres.url, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) {
      return gercekFetch(adres, secenekler);
    }
    await bekle(90 + Math.random() * 120); // ağ gibi kısa bir gecikme
    const yontem = ((secenekler && secenekler.method) || "GET").toUpperCase();
    let govde = {};
    if (secenekler && typeof secenekler.body === "string") {
      try {
        govde = JSON.parse(secenekler.body) || {};
      } catch (hata) {
        govde = {};
      }
    }
    const simdi = Date.now();
    const yol = url.pathname.slice("/api/".length);
    try {
      if (yol === "giris" && yontem === "POST") return yanit(200, giris(govde, simdi));
      if (yol === "cikis" && yontem === "POST") {
        durum.girisli = false;
        kayitYaz(simdi, durum.ad, "", "cikis", "", "tamam");
        return yanit(200, { tamam: true });
      }
      if (!durum.girisli) throw new DemoHatasi(401, "giris_gerekli", "Panoyu görmek için giriş yapın.");
      if (yol === "durum") return yanit(200, panoVerisi(simdi, url.searchParams));
      if (yol === "mudahale" && yontem === "POST") return yanit(200, mudahaleIstegi(govde, simdi));
      if (yol === "hesap" && yontem === "POST") return yanit(200, hesapIstegi(govde, simdi));
      if (yol === "hesap") {
        if (!yetkiliMi("ekran.kullanicilar"))
          throw new DemoHatasi(403, "yetki", "Bu sayfa için yönetici yetkisi gerekir.");
        return yanit(200, hesapVerisi());
      }
      throw new DemoHatasi(404, "yok", "Böyle bir adres yok.");
    } catch (hata) {
      if (hata instanceof DemoHatasi) return yanit(hata.kod, { hata: hata.hata, mesaj: hata.message });
      throw hata;
    }
  };

  // ------------------------------------------------------ çizilen görüntü

  const SAHNE_TONLARI = {
    1: ["#5b6470", "#3b4048", "#8a8f96"],
    2: ["#56606b", "#383d44", "#858b93"],
    3: ["#66625a", "#46423b", "#9a958b"],
    4: ["#5c5f55", "#3e4038", "#8e9184"],
    5: ["#5a6066", "#3a3f44", "#8c9298"],
    6: ["#5d5550", "#3f3833", "#8f8580"],
  };

  function kisi(g, x, y, olcek, baretli, yelekli, renk) {
    const o = olcek;
    g.fillStyle = "#2b2f36";
    g.fillRect(x - 7 * o, y - 30 * o, 5 * o, 30 * o); // bacaklar
    g.fillRect(x + 2 * o, y - 30 * o, 5 * o, 30 * o);
    g.fillStyle = renk;
    g.fillRect(x - 10 * o, y - 62 * o, 20 * o, 34 * o); // gövde
    if (yelekli) {
      g.fillStyle = "#f59e0b";
      g.fillRect(x - 10 * o, y - 62 * o, 20 * o, 30 * o);
      g.fillStyle = "#f3f4f6";
      g.fillRect(x - 10 * o, y - 48 * o, 20 * o, 3 * o);
      g.fillRect(x - 10 * o, y - 40 * o, 20 * o, 3 * o);
    }
    g.fillStyle = "#d6a786";
    g.beginPath();
    g.arc(x, y - 70 * o, 7 * o, 0, Math.PI * 2); // baş
    g.fill();
    if (baretli) {
      g.fillStyle = "#facc15";
      g.beginPath();
      g.arc(x, y - 72 * o, 8 * o, Math.PI, 0);
      g.fill();
      g.fillRect(x - 10 * o, y - 73 * o, 20 * o, 2.5 * o);
    } else {
      g.fillStyle = "#3a2a20";
      g.beginPath();
      g.arc(x, y - 73 * o, 7 * o, Math.PI, 0);
      g.fill();
    }
    return { x: x - 14 * o, y: y - 84 * o, w: 28 * o, h: 86 * o };
  }

  function forklift(g, x, y, o) {
    g.fillStyle = "#ea8a0c";
    g.fillRect(x, y - 34 * o, 46 * o, 24 * o);
    g.fillStyle = "#1f2937";
    g.fillRect(x + 8 * o, y - 58 * o, 3 * o, 24 * o);
    g.fillRect(x + 32 * o, y - 58 * o, 3 * o, 24 * o);
    g.fillRect(x + 8 * o, y - 58 * o, 27 * o, 3 * o);
    g.fillRect(x - 16 * o, y - 60 * o, 4 * o, 56 * o); // direk
    g.fillRect(x - 30 * o, y - 8 * o, 18 * o, 3 * o); // çatal
    g.beginPath();
    g.arc(x + 10 * o, y - 6 * o, 7 * o, 0, Math.PI * 2);
    g.arc(x + 38 * o, y - 6 * o, 7 * o, 0, Math.PI * 2);
    g.fill();
    return { x: x - 32 * o, y: y - 62 * o, w: 86 * o, h: 64 * o };
  }

  function kutuCiz(g, k, renk, etiket) {
    g.strokeStyle = renk;
    g.lineWidth = 2.5;
    g.strokeRect(k.x, k.y, k.w, k.h);
    g.font = "600 13px Inter, system-ui, sans-serif";
    const genislik = g.measureText(etiket).width + 10;
    g.fillStyle = renk;
    g.fillRect(k.x - 1.25, k.y - 19, genislik, 19);
    g.fillStyle = "#ffffff";
    g.fillText(etiket, k.x + 4, k.y - 5);
  }

  /* Kamera sahnesi: arka duvar, raflar, zemin, sarı yaya yolu ve insanlar.
     ihlal verilirse ilgili kişi kırmızı çerçeveyle işaretlenir. */
  function sahne(kameraId, adMetni, zamanMs, ihlal) {
    const G = 640;
    const Y = 360;
    const tuval = document.createElement("canvas");
    tuval.width = G;
    tuval.height = Y;
    const g = tuval.getContext("2d");
    const r = tohumlu(kameraId * 7919 + (ihlal ? ihlal.id : 0));
    const [duvar, zemin, acik] = SAHNE_TONLARI[kameraId] || SAHNE_TONLARI[1];
    const ufuk = Y * 0.42;

    let renk = g.createLinearGradient(0, 0, 0, ufuk);
    renk.addColorStop(0, duvar);
    renk.addColorStop(1, acik);
    g.fillStyle = renk;
    g.fillRect(0, 0, G, ufuk);
    renk = g.createLinearGradient(0, ufuk, 0, Y);
    renk.addColorStop(0, acik);
    renk.addColorStop(1, zemin);
    g.fillStyle = renk;
    g.fillRect(0, ufuk, G, Y - ufuk);

    // Tavan lambaları
    g.fillStyle = "rgba(255,255,240,0.55)";
    for (let i = 0; i < 4; i++) g.fillRect(70 + i * 150, 18, 70, 6);

    // Raflar ve koliler
    for (let i = 0; i < 5; i++) {
      const x = 20 + i * 128 + r() * 10;
      g.fillStyle = "#2f3a4a";
      g.fillRect(x, ufuk - 120, 100, 120);
      for (let kat = 0; kat < 3; kat++) {
        g.fillStyle = "#e5e7eb";
        g.fillRect(x, ufuk - 120 + kat * 40 + 36, 100, 4);
        for (let k = 0; k < 4; k++) {
          if (r() < 0.25) continue;
          g.fillStyle = ["#b8875a", "#a47449", "#c99b6b"][Math.floor(r() * 3)];
          g.fillRect(x + 4 + k * 24, ufuk - 120 + kat * 40 + 12, 20, 24);
        }
      }
    }

    // Zemin çizgileri (perspektif) ve sarı yaya yolu
    g.strokeStyle = "rgba(255,255,255,0.08)";
    g.lineWidth = 1;
    for (let i = -6; i <= 12; i++) {
      g.beginPath();
      g.moveTo(G / 2 + i * 12, ufuk);
      g.lineTo(G / 2 + i * 110, Y);
      g.stroke();
    }
    g.fillStyle = "#eab308";
    g.beginPath();
    g.moveTo(G * 0.18, Y);
    g.lineTo(G * 0.44, ufuk);
    g.lineTo(G * 0.46, ufuk);
    g.lineTo(G * 0.24, Y);
    g.fill();
    g.beginPath();
    g.moveTo(G * 0.76, Y);
    g.lineTo(G * 0.56, ufuk);
    g.lineTo(G * 0.58, ufuk);
    g.lineTo(G * 0.82, Y);
    g.fill();

    // Yasak bölge: kırmızı taralı alan
    if (ihlal && ihlal.baslik === "Yasak bölge") {
      g.fillStyle = "rgba(220,38,38,0.22)";
      g.fillRect(G * 0.56, Y * 0.62, G * 0.4, Y * 0.36);
      g.strokeStyle = "rgba(220,38,38,0.85)";
      g.setLineDash([8, 6]);
      g.strokeRect(G * 0.56, Y * 0.62, G * 0.4, Y * 0.36);
      g.setLineDash([]);
    }

    // İnsanlar (anlık görüntüde zamanla yürür) ve forklift
    const adim = (zamanMs / 10000) % 12;
    const kisiler = [];
    const sayi = 2 + Math.floor(r() * 2);
    for (let i = 0; i < sayi; i++) {
      const x = ((80 + i * 190 + r() * 60 + adim * (i % 2 ? -14 : 18)) % (G - 80)) + 40;
      const y = ufuk + 70 + r() * (Y - ufuk - 80);
      const o = 0.75 + ((y - ufuk) / (Y - ufuk)) * 0.75;
      kisiler.push({ x: x, y: y, o: o, renk: ["#1e3a8a", "#334155", "#3f6212"][i % 3] });
    }
    kisiler.sort((a, b) => a.y - b.y);
    const forkliftVar = kameraId === 4 || (ihlal && ihlal.baslik === "Forklift yakınlığı");
    let forkliftKutusu = null;
    if (forkliftVar) {
      // Forklift yakınlığı dışındaki ihlalde forklift kenarda durur (etiketler çakışmasın)
      const yakin = ihlal && ihlal.baslik === "Forklift yakınlığı";
      forkliftKutusu = forklift(g, ihlal && !yakin ? 110 : 360 + ((adim * 9) % 120), Y - 40, 1.4);
      kutuCiz(g, forkliftKutusu, "rgba(59,130,246,0.95)", "Forklift");
    }

    const hedef = ihlal ? kisiler.length - 1 : -1; // ihlali yapan en öndeki kişi
    kisiler.forEach(function (k, i) {
      const baret = !(i === hedef && ihlal.baslik === "Baret yok");
      const yelek = !(i === hedef && ihlal.baslik === "Yelek yok");
      if (i === hedef && ihlal.baslik === "Yasak bölge") k.x = G * 0.74;
      if (i === hedef && ihlal.baslik === "Forklift yakınlığı" && forkliftKutusu) k.x = forkliftKutusu.x - 20;
      const kutu = kisi(g, k.x, k.y, k.o, baret, yelek, k.renk);
      if (i === hedef) kutuCiz(g, kutu, "#dc2626", ihlal.baslik + " · %" + (86 + Math.floor(r() * 12)));
      else kutuCiz(g, kutu, "rgba(34,197,94,0.9)", "Kişi");
    });

    // Kamera ekranı yazısı: ad, kayıt noktası, Türkiye saati
    g.fillStyle = "rgba(0,0,0,0.45)";
    g.fillRect(0, 0, G, 30);
    g.font = "600 14px Inter, system-ui, sans-serif";
    g.fillStyle = "#ffffff";
    g.fillText("KAM-0" + kameraId + " · " + adMetni, 12, 20);
    const saat = new Date(zamanMs).toLocaleString("tr-TR", { timeZone: SAAT_DILIMI });
    const genislik = g.measureText(saat).width;
    g.fillText(saat, G - genislik - 12, 20);
    g.fillStyle = "#ef4444";
    g.beginPath();
    g.arc(G - genislik - 24, 15, 4.5, 0, Math.PI * 2);
    g.fill();
    g.font = "600 11px Inter, system-ui, sans-serif";
    g.fillStyle = "rgba(255,255,255,0.75)";
    g.fillText("DEMO GÖRÜNTÜ", 12, Y - 12);

    return tuval.toDataURL("image/jpeg", 0.85);
  }

  const resimler = new Map();

  window.panoDemo = {
    kareAdresi: function (kimlik, zaman) {
      const anahtar = "kare:" + kimlik + ":" + zaman;
      if (!resimler.has(anahtar)) {
        const k = KAMERALAR.find((x) => String(x.id) === String(kimlik)) || KAMERALAR[0];
        resimler.set(anahtar, sahne(k.id, k.ad, Date.parse(zaman) || Date.now(), null));
      }
      return resimler.get(anahtar);
    },
    fotoAdresi: function (olayId) {
      const anahtar = "foto:" + olayId;
      if (!resimler.has(anahtar)) {
        const o = olaylar.find((x) => x.id === olayId);
        if (!o) return "";
        const k = KAMERALAR.find((x) => x.id === o.kamera) || KAMERALAR[0];
        resimler.set(anahtar, sahne(k.id, k.ad, o.zamanMs, o));
      }
      return resimler.get(anahtar);
    },
  };

  // ------------------------------------------------------------ demo bandı

  let rolSecici = null;

  function secicileriEsle() {
    if (rolSecici) rolSecici.value = durum.rol;
  }

  function secici(etiket, secenekler, deger, degisti) {
    const kap = document.createElement("label");
    kap.className = "demo-secim";
    kap.appendChild(document.createTextNode(etiket));
    const s = document.createElement("select");
    s.className = "secici";
    for (const [d, metin] of secenekler) {
      const o = document.createElement("option");
      o.value = d;
      o.textContent = metin;
      s.appendChild(o);
    }
    s.value = deger;
    s.addEventListener("change", function () {
      degisti(s.value);
      // pano.js'in Yenile düğmesi: veriyi (ve açıksa hesapları) yeniden okur
      const yenile = document.getElementById("yenile");
      if (yenile) yenile.click();
    });
    kap.appendChild(s);
    return { kap: kap, secici: s };
  }

  function bantKur() {
    const yer = document.getElementById("onizleme-bandi");
    if (!yer) return;
    const bant = document.createElement("div");
    bant.className = "pano-bandi demo-bandi";
    bant.setAttribute("role", "region");
    bant.setAttribute("aria-label", "Demo");
    const metin = document.createElement("p");
    const b = document.createElement("b");
    b.textContent = "DEMO";
    metin.append(
      b,
      document.createTextNode(
        " · Örnek verilerle çalışır; fabrikaya bağlı değildir, hiçbir komut gitmez. Yenileyince başa döner.",
      ),
    );
    const secimler = document.createElement("div");
    secimler.className = "demo-secimler";
    const rol = secici(
      "Rol",
      [
        ["yonetici", "Yönetici"],
        ["operator", "Operatör"],
        ["izleyici", "İzleyici"],
      ],
      durum.rol,
      function (deger) {
        durum.rol = deger;
        durum.ad = ROL_HESABI[deger];
      },
    );
    rolSecici = rol.secici;
    const baglanti = secici(
      "Bağlantı",
      [
        ["canli", "Canlı"],
        ["yok", "Haber yok"],
        ["kapandi", "Kapatıldı"],
      ],
      durum.baglanti,
      function (deger) {
        durum.baglanti = deger;
        durum.baglantiDegisti = Date.now();
      },
    );
    secimler.append(rol.kap, baglanti.kap);
    bant.append(metin, secimler);
    yer.before(bant);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bantKur);
  else bantKur();
})();
