"""Site denetiminde (08.11.2026) bulunanların regresyon testleri.

Her test bir bulguya karşılık gelir; bulgu düzeltilmeden önce kırmızıydı."""

import _pano
import pytest

KURUCU_SIFRESI = "kurucu-sifresi-123"


class Saat:
    """Elle ilerletilen saat: süreli anahtarların tam sınırını denemek için."""

    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _ayar(**ek) -> _pano.Ayar:
    return _pano.Ayar(
        pano_sifresi=KURUCU_SIFRESI,
        rapor_anahtari="r" * 40,
        redis_adresi="",
        redis_jetonu="",
        fabrika_adresi="",
        **ek,
    )


# ------------------------------------------------------------ giriş kilidi


def test_pay_geri_verilirken_suresi_dolan_sayac_suresiz_kalmaz(monkeypatch):
    """Pay ayrı istekte geri verilir. Sayacın süresi tam arada (scrypt sırasında)
    dolarsa eskiden DECR onu süresiz -1 kuruyordu; yanlışlar birikip genel kilit
    bütün girişleri süresiz kapatıyordu. Artık sayaç hep süreli kalır."""
    saat = Saat(1_800_000_000.0)
    depo = _pano.BellekDepo(saat)
    ayar = _ayar()
    gercek = _pano._sahte_dogrula

    def yavas(sifre):  # scrypt ve bir Upstash turu
        gercek(sifre)
        saat.t += 0.3

    monkeypatch.setattr(_pano, "_sahte_dogrula", yavas)
    t0 = saat.t
    with pytest.raises(_pano.PanoHatasi):
        _pano.giris_dene(depo, ayar, "10.0.0.1", "kurucu", "yanlis-sifre", saat.t)
    # Kurucunun doğru girişi genel ve ad penceresinin bittiği âna denk gelir
    saat.t = t0 + _pano.GENEL_KILIT_SURESI_SN - 0.1
    _pano.giris_dene(depo, ayar, "10.0.0.2", "kurucu", KURUCU_SIFRESI, saat.t)
    for anahtar in (_pano.GIRIS_GENEL_ANAHTARI, _pano._ad_kilit_anahtari("kurucu")):
        assert depo.komut("TTL", anahtar) > 0, anahtar
    # Seyrek yanlışlar artık birikmez: bir hafta sonra kurucu yine girer
    for i in range(_pano.GENEL_KILIT_DENEME + 10):
        saat.t += 1200
        with pytest.raises(_pano.PanoHatasi):
            _pano.giris_dene(depo, ayar, f"203.0.113.{i % 250}", f"bot{i}", "yanlis", saat.t)
    saat.t += 7 * 86400
    _pano.giris_dene(depo, ayar, "198.51.100.7", "kurucu", KURUCU_SIFRESI, saat.t)


def test_suresiz_kalmis_kilit_sayaci_ilk_reddde_sure_alir():
    """Eski bir yarıştan süresiz kalmış sayaç (canlıda olmuş olabilir) ilk 429'da
    süre alır; kilit en geç bir pencere sonra kendiliğinden kalkar."""
    saat = Saat(1_800_000_000.0)
    depo = _pano.BellekDepo(saat)
    ayar = _ayar()
    depo.komut("SET", _pano.GIRIS_GENEL_ANAHTARI, "150")
    assert depo.komut("TTL", _pano.GIRIS_GENEL_ANAHTARI) == -1
    with pytest.raises(_pano.PanoHatasi) as hata:
        _pano.giris_dene(depo, ayar, "10.0.0.3", "kurucu", KURUCU_SIFRESI, saat.t)
    assert (hata.value.kod, hata.value.hata) == (429, "genel_kilit")
    assert 0 < depo.komut("TTL", _pano.GIRIS_GENEL_ANAHTARI) <= _pano.GENEL_KILIT_SURESI_SN
    saat.t += _pano.GENEL_KILIT_SURESI_SN + 1
    _pano.giris_dene(depo, ayar, "10.0.0.3", "kurucu", KURUCU_SIFRESI, saat.t)


def test_bellek_deposu_ttl_redis_gibi():
    saat = Saat(1000.0)
    depo = _pano.BellekDepo(saat)
    assert depo.komut("TTL", "yok") == -2
    depo.komut("SET", "a", "1")
    assert depo.komut("TTL", "a") == -1
    depo.komut("SET", "b", "1", "EX", "60")
    assert depo.komut("TTL", "b") == 60
    saat.t += 61
    assert depo.komut("TTL", "b") == -2


# ------------------------------------------------------------ adres maskesi


@pytest.mark.parametrize(
    ("ham", "beklenen"),
    [
        (
            "Ulaşılamıyor (rtsp://admin:1234@10.0.0.5:554/akis). Yeniden deneniyor.",
            "Ulaşılamıyor (adres). Yeniden deneniyor.",
        ),
        ("Ulaşılamıyor: 192.168.1.20:554 yanıt yok", "Ulaşılamıyor: (adres) yanıt yok"),
        ("Kamera admin:12345@10.0.0.7 reddetti", "Kamera (adres) reddetti"),
        (r"Yazılamadı: C:\Users\isg\AppData\dalsan\kayit.db", "Yazılamadı: (dosya yolu)"),
        (r"Paylaşım \\NVR01\kayitlar yok", "Paylaşım (dosya yolu) yok"),
        ("Günlük /home/isg/dalsan/log.txt dolu.", "Günlük (dosya yolu) dolu."),
        ("Kanal hatası http://10.0.0.9/api, sonra.", "Kanal hatası (adres), sonra."),
        ("fe80::1%eth0 ve 2001:db8::8a2e:370:7334", "(adres) ve (adres)"),
        (
            "Kameraya ağ üzerinden ulaşılamıyor ((adres))",
            "Kameraya ağ üzerinden ulaşılamıyor (adres)",
        ),
        # Adres olmayanlar dokunulmadan kalır
        (
            "Saat 14:30:05 itibarıyla 3/5 kamera; sürüm v2.2.1 (08.11.2026) Tüm fabrika/Depo",
            "Saat 14:30:05 itibarıyla 3/5 kamera; sürüm v2.2.1 (08.11.2026) Tüm fabrika/Depo",
        ),
    ],
)
def test_adres_maskesi(ham, beklenen):
    assert _pano.adres_maskele(ham) == beklenen


def test_sistem_sorunlari_her_role_maskeli_gider():
    """sistem.sorunlar her role (izleyici dahil) gösterilir; eskiden maskelenmiyordu."""
    temiz = _pano.rapor_temizle(
        {"surum": 1, "sistem": {"sorunlar": ["Kamera 3: rtsp://admin:12345@10.0.0.5/x yok"]}}
    )
    assert temiz["sistem"]["sorunlar"] == ["Kamera 3: (adres) yok"]


def test_komut_sonucu_mesaji_maskeli_yazilir():
    from test_komut import YON, YONETIM_ACIK, _bul, _veri

    depo = _pano.BellekDepo()
    k = _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "teshis"}, 1000, YON)
    _pano.komutlari_teslim_et(depo, 1001)
    sonuc = {"id": k["id"], "durum": "hata", "mesaj": "Ulaşılamadı: 10.0.0.5:554"}
    _pano.sonuclari_yaz(depo, [sonuc], 1002)
    assert _bul(depo, 1003, k["id"])["mesaj"] == "Ulaşılamadı: (adres)"


# ------------------------------------------------------------ Tesisler ekranı yetkisi


def test_bilgisayar_yetkisi_olmayan_tesisler_ekraninda_bilgisayar_adi_gormez():
    """Kurucu bir role Tesisler ekranını verip veri.bilgisayar'ı vermezse çakışma
    uyarısı ve satırı bilgisayar adını taşımamalı."""
    import json

    from test_filo import T0, Saat, _ayar, _bilgisayarli, _kaydet

    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _ayar()
    _kaydet(depo, _bilgisayarli("gebze", "DALSAN-PC"), T0, ayar)
    saat.simdi = T0 + 15
    _kaydet(depo, _bilgisayarli("gebze", "ISG-PC-02"), saat.simdi, ayar)
    tam = _pano.filo_verisi(depo, ayar, saat.simdi)
    assert "DALSAN-PC" in json.dumps(tam, ensure_ascii=False)
    gizli = _pano.filo_verisi(depo, ayar, saat.simdi, bilgisayar_gorur=False)
    metin = json.dumps(gizli, ensure_ascii=False)
    assert "DALSAN-PC" not in metin and "ISG-PC-02" not in metin
    assert gizli["uyarilar"] == [_pano.TESIS_CAKISMA_ADSIZ_METNI.format(kimlik="gebze")]
    satir = next(s for s in gizli["tesisler"] if s["id"] == "gebze")
    assert satir["cakisma"]["adlar"] == [] and satir["cakisma"]["zaman"]


# ------------------------------------------------------------ girdi


def test_kullanici_adi_turkce_harfle_yazilsa_da_ayni_hesaba_gider():
    assert _pano.ad_duzelt("İsmail") == "ismail"
    assert _pano.ad_duzelt("  ŞEF.Ümit ") == "sef.umit"
    assert _pano.ad_duzelt(None) == ""


class _SahteIstek:
    def __init__(self, cerez: str) -> None:
        self.headers = {"Cookie": cerez}


@pytest.mark.parametrize(
    "baslik",
    [
        "pano_oturum=v2.abc",
        'tercih={"tema":"koyu"}; pano_oturum=v2.abc',
        "bozuk deger=1 2; pano_oturum=v2.abc; diger=x",
        'pano_oturum="v2.abc"',
    ],
)
def test_bozuk_komsu_cerez_oturumu_gizlemez(baslik):
    assert _pano.Isleyici.cerez_al(_SahteIstek(baslik), _pano.CEREZ_ADI) == "v2.abc"


def test_cerez_yoksa_bos():
    assert _pano.Isleyici.cerez_al(_SahteIstek("pano_oturumx=1; a=b"), _pano.CEREZ_ADI) == ""
    assert _pano.Isleyici.cerez_al(_SahteIstek(""), _pano.CEREZ_ADI) == ""


# ------------------------------------------------------------ bekçi e-postası


def test_bekci_butun_alicilara_tek_smtp_oturumunda_gonderir(monkeypatch):
    """Eskiden her alıcıya ayrı bağlantı ve giriş açılıyordu. Artık bağlantı ve
    giriş bir kez; bozuk bir alıcı (ret) oturumu bozmaz, öbürleri yine gider."""
    import smtplib

    olaylar = []

    class SMTP:
        def __init__(self, sunucu, port, context=None, timeout=None):
            olaylar.append("ac")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            olaylar.append("kapat")

        def starttls(self, context=None):
            olaylar.append("starttls")

        def login(self, kullanici, sifre):
            olaylar.append("login")

        def send_message(self, mesaj):
            if mesaj["To"].startswith("ret@"):
                raise smtplib.SMTPRecipientsRefused({mesaj["To"]: (550, b"yok")})
            olaylar.append("gonder " + mesaj["To"])

    monkeypatch.setattr(_pano.smtplib, "SMTP", SMTP)
    ayar = _ayar(smtp_sunucu="smtp.ornek.com", smtp_kullanici="pano@ornek.com", smtp_sifresi="s")
    alicilar = ("a@ornek.com", "ret@ornek.com", "b@ornek.com")
    sayi = _pano.bekci_uyari_gonder(ayar, alicilar, "Konu", "Metin")
    assert sayi == 2
    assert olaylar == [
        "ac",
        "starttls",
        "login",
        "gonder a@ornek.com",
        "gonder b@ornek.com",
        "kapat",
    ]


# ------------------------------------------------------------ hesap kilidi


def test_hesap_kilidi_yalniz_kendi_kilidini_birakir():
    """İşi kilidin ömrünü aşan istek, o arada kilidi alan başka bir isteğin
    kilidini silmemeli (eskiden koşulsuz DEL vardı)."""
    saat = Saat(1000.0)
    depo = _pano.BellekDepo(saat)
    anahtar = _pano.KULLANICI_KILIT_ONEKI + "ali"
    with _pano._hesap_kilidi(depo, "ali"):
        assert depo.komut("GET", anahtar)
        saat.t += _pano.HESAP_KILIT_SURESI_SN + 1  # bu istek uzadı, kilidin süresi doldu
        depo.komut("SET", anahtar, "baska-istek", "EX", "20", "NX")  # başka istek aldı
    assert depo.komut("GET", anahtar) == "baska-istek"
    depo.komut("DEL", anahtar)
    with _pano._hesap_kilidi(depo, "ali"):
        pass
    assert depo.komut("GET", anahtar) is None  # olağan durumda kilit bırakılır


# ------------------------------------------------------------ raporun günü


def test_dunden_kalan_rapor_bugun_diye_isaretlenmez():
    """Program cuma 18:02'de kapatıldı, pazartesi 09:00'da bakılıyor: sayılar
    cumanın. Pano raporun gününü ve bugüne ait olmadığını bilmeli."""
    from datetime import datetime

    cuma = datetime(2026, 11, 6, 18, 2, tzinfo=_pano.TURKIYE_SAATI).timestamp()
    pazartesi = datetime(2026, 11, 9, 9, 0, tzinfo=_pano.TURKIYE_SAATI).timestamp()
    depo = _pano.BellekDepo(lambda: pazartesi)
    ayar = _ayar()
    rapor = _pano.rapor_temizle({"surum": 1, "kapanis": True, "sayilar": {"bugun_ihlal": 23}})
    _pano.rapor_kaydet(depo, rapor, cuma, ayar)
    veri = _pano.pano_verisi(depo, ayar, pazartesi)
    assert veri["rapor_gunu"] == "2026-11-06"
    assert veri["bugun_gecerli"] is False
    ayni_gun = _pano.pano_verisi(depo, ayar, cuma + 3600)
    assert ayni_gun["bugun_gecerli"] is True
    # Türkiye gece yarısı (UTC 21:00) gün değiştirir
    gece = datetime(2026, 11, 6, 23, 59, 50, tzinfo=_pano.TURKIYE_SAATI).timestamp()
    _pano.rapor_kaydet(depo, rapor, gece, ayar)
    assert _pano.pano_verisi(depo, ayar, gece + 20)["bugun_gecerli"] is False


def test_hic_rapor_yoksa_gun_bos():
    depo = _pano.BellekDepo()
    veri = _pano.pano_verisi(depo, _ayar(), 1_800_000_000)
    assert veri["rapor_gunu"] is None and veri["bugun_gecerli"] is False


# ------------------------------------------------------------ ayrı oturum anahtarı


def test_oturum_anahtari_istege_bagli_ve_cerez_imzasina_katilir():
    from dataclasses import replace

    duz = _ayar()
    ayri = replace(duz, oturum_anahtari="o" * 40)
    cerez = _pano.cerez_uret(duz, "ali", "1234567890abcdef", 1, 1_800_000_000)
    imza = cerez.rsplit(".", 1)[1]
    # Ayar yokken imza bugünküyle aynı (açık oturumlar düşmez)
    assert imza == _pano._cerez_imzasi(duz, "ali", "1234567890abcdef", 1, int(cerez.split(".")[4]))
    assert imza != _pano._cerez_imzasi(ayri, "ali", "1234567890abcdef", 1, int(cerez.split(".")[4]))
    # Kurucu şifresi değişince yine bütün oturumlar düşer
    assert _pano._cerez_anahtari(ayri) != _pano._cerez_anahtari(
        replace(ayri, pano_sifresi="baska-kurucu-sifresi")
    )
    # Kurucunun iki adım izi ayardan etkilenmez (iki adım sessizce kapanmasın)
    assert _pano._kurucu_parmagi(duz) == _pano._kurucu_parmagi(ayri)


def test_kisa_oturum_anahtari_yok_sayilir():
    taban = {"PANO_SIFRESI": "k" * 16, "RAPOR_ANAHTARI": "r" * 40}
    assert _pano.ayar_oku({**taban, "OTURUM_ANAHTARI": "kisa"}).oturum_anahtari == ""
    assert (
        _pano.ayar_oku({**taban, "OTURUM_ANAHTARI": " " + "x" * 32 + " "}).oturum_anahtari
        == "x" * 32
    )
    assert "x" * 32 not in repr(_pano.ayar_oku({**taban, "OTURUM_ANAHTARI": "x" * 32}))
