"""Çekirdeğin kararları: imza, rapor biçimi, oturum, kilit, bağlantı durumu."""

import json

import _pano
import pytest

ANAHTAR = "k" * 40
SATIR_AYIRICI = chr(0x2028)  # Unicode satır ayırıcı
SIFRE = "dogru-sifre-123"


def _ayar(**degisen) -> _pano.Ayar:
    alanlar = {
        "pano_sifresi": SIFRE,
        "rapor_anahtari": ANAHTAR,
        "redis_adresi": "https://ornek.upstash.io",
        "redis_jetonu": "jeton",
        "fabrika_adresi": "",
    }
    alanlar.update(degisen)
    return _pano.Ayar(**alanlar)


class Saat:
    def __init__(self, simdi: float = 1_800_000_000.0) -> None:
        self.simdi = simdi

    def __call__(self) -> float:
        return self.simdi


def _rapor(**degisen) -> dict:
    rapor = {
        "surum": 1,
        "uretildi": "2026-10-24T10:00:00+03:00",
        "aralik_sn": 30,
        "program": {"ad": "NextGen Detector", "surum": "1.0"},
        "sistem": {"analiz": True, "hazir": True, "model": "hazir", "sorunlar": []},
        "kameralar": [{"ad": "Sevkiyat", "bolum": "Depo", "durum": "online"}],
        "sayilar": {"bugun_ihlal": 3, "bekleyen": 1},
        "saatlik": [0] * 24,
        "ogeler": [{"ad": "Baret yok", "sayi": 2}],
        "son_olaylar": [
            {"zaman": "2026-10-24T09:58:00Z", "tur": "ihlal", "baslik": "Baret yok", "onem": "high"}
        ],
    }
    rapor.update(degisen)
    return rapor


# ----------------------------------------------------------------------- imza


def test_dogru_imza_kabul_edilir():
    govde = b'{"surum": 1}'
    zaman = "1800000000"
    imza = _pano.imza_hesapla(ANAHTAR, zaman, govde)
    _pano.imza_dogrula(ANAHTAR, zaman, imza, govde, 1_800_000_010)


@pytest.mark.parametrize(
    ("zaman", "imza_anahtari", "govde_degisir", "beklenen"),
    [
        ("1800000000", "baska-anahtar" * 4, False, "imza_gecersiz"),
        ("1800000000", ANAHTAR, True, "imza_gecersiz"),
        ("1799999000", ANAHTAR, False, "saat_farki"),
        ("1800001000", ANAHTAR, False, "saat_farki"),
        ("18e8", ANAHTAR, False, "zaman"),
        ("²", ANAHTAR, False, "zaman"),
    ],
)
def test_bozuk_imza_reddedilir(zaman, imza_anahtari, govde_degisir, beklenen):
    govde = b'{"surum": 1}'
    imza = _pano.imza_hesapla(imza_anahtari, "1800000000", govde)
    gelen = govde + b" " if govde_degisir else govde
    with pytest.raises(_pano.PanoHatasi) as hata:
        _pano.imza_dogrula(ANAHTAR, zaman, imza, gelen, 1_800_000_000)
    assert hata.value.kod == 401
    assert hata.value.hata == beklenen


def test_imza_fabrika_programinin_imzasiyla_ayni():
    """Aynı deneme değeri fabrika programının testlerinde de vardır (DALSAN,
    tests/test_uzak_pano.py): iki taraftan biri imzayı değiştirirse ikisi de kırılır."""
    assert _pano.imza_hesapla("k" * 40, "1800000000", b'{"surum":1}') == (
        "sha256=77adb53d1783a0edd015dd5bd934d8d91ae7ce2dca40a96fc9fda846f7bc8feb"
    )


def test_imza_basligi_yoksa_reddedilir():
    with pytest.raises(_pano.PanoHatasi) as hata:
        _pano.imza_dogrula(ANAHTAR, None, None, b"{}", 1_800_000_000)
    assert hata.value.hata == "imza_yok"


def test_saat_farki_mesaji_yonu_ve_cozumu_soyler():
    with pytest.raises(_pano.PanoHatasi) as hata:
        _pano.imza_dogrula(ANAHTAR, "1799999000", "sha256=x", b"{}", 1_800_000_000)
    assert "1000 saniye geri" in hata.value.mesaj
    assert "otomatik" in hata.value.mesaj


# --------------------------------------------------------------- rapor biçimi


def test_bilinmeyen_alanlar_depoya_girmez():
    """İleride biri rapora kazayla fotoğraf eklese bile siteye girmez."""
    rapor = _rapor(fotograf="data:image/jpeg;base64,AAAA")
    rapor["son_olaylar"][0]["foto"] = "AAAA"
    rapor["kameralar"][0]["rtsp"] = "rtsp://kullanici:sifre@10.0.0.5/akis"
    temiz = _pano.rapor_temizle(rapor)
    metin = json.dumps(temiz)
    assert "AAAA" not in metin and "rtsp" not in metin and "fotograf" not in metin


def test_metinler_kisaltilir_ve_tek_satira_iner():
    rapor = _rapor()
    rapor["son_olaylar"][0]["baslik"] = "satır\nenjeksiyonu" + SATIR_AYIRICI + "x" * 500
    temiz = _pano.rapor_temizle(rapor)
    baslik = temiz["son_olaylar"][0]["baslik"]
    assert "\n" not in baslik and SATIR_AYIRICI not in baslik
    assert len(baslik) <= 160


def test_yanlis_tipler_guvenli_degere_duser():
    rapor = _rapor(
        sistem="bozuk",
        kameralar=[{"ad": 5, "durum": "patladi", "okunan_fps": float("nan")}, "metin"],
        sayilar={"bugun_ihlal": "3", "bekleyen": True},
        saatlik=[1, 2],
        aralik_sn="30",
    )
    temiz = _pano.rapor_temizle(rapor)
    assert temiz["sistem"]["sorunlar"] == []
    assert temiz["kameralar"] == [
        {
            "id": None,
            "ad": "Adsız kamera",
            "bolum": "",
            "durum": "offline",
            "okunan_fps": None,
            "islenen_fps": None,
            "hedef_fps": None,
            "yavas": False,
            "son_kare_yasi_sn": None,
        }
    ]
    assert temiz["sayilar"]["bugun_ihlal"] == 0
    assert temiz["sayilar"]["bekleyen"] == 0
    assert temiz["saatlik"] == [0] * 24
    assert temiz["aralik_sn"] == 30


def test_uc_degerler_hata_vermez():
    """İmzalı ama tuhaf bir rapor 500 değil, güvenli değer üretir."""
    rapor = _rapor(sayilar={"bugun_ihlal": 10**400})
    rapor["kameralar"][0]["okunan_fps"] = 10**400
    rapor["son_olaylar"][0]["zaman"] = "0001-01-01T00:00:00+14:00"
    temiz = _pano.rapor_temizle(rapor)
    assert temiz["sayilar"]["bugun_ihlal"] == 10**7
    assert temiz["kameralar"][0]["okunan_fps"] is None
    assert temiz["son_olaylar"][0]["zaman"] == ""


def test_liste_uzunluklari_sinirlidir():
    rapor = _rapor(
        kameralar=[{"ad": f"K{i}"} for i in range(200)],
        son_olaylar=[{"baslik": "x"} for _ in range(200)],
    )
    temiz = _pano.rapor_temizle(rapor)
    assert len(temiz["kameralar"]) == 64
    assert len(temiz["son_olaylar"]) == 50


def test_zaman_utcye_cevrilir_saat_dilimsiz_damga_atilir():
    rapor = _rapor()
    rapor["son_olaylar"] = [
        {"zaman": "2026-10-24T12:58:00+03:00"},
        {"zaman": "2026-10-24T12:58:00"},
    ]
    temiz = _pano.rapor_temizle(rapor)
    assert temiz["son_olaylar"][0]["zaman"] == "2026-10-24T09:58:00+00:00"
    assert temiz["son_olaylar"][1]["zaman"] == ""


def test_baska_surum_reddedilir():
    with pytest.raises(_pano.PanoHatasi) as hata:
        _pano.rapor_temizle(_rapor(surum=2))
    assert hata.value.hata == "surum"
    with pytest.raises(_pano.PanoHatasi):
        _pano.rapor_temizle(["liste"])


# -------------------------------------------------------- bağlantı durumu


def test_hic_rapor_gelmediyse_hic():
    depo = _pano.BellekDepo(Saat())
    veri = _pano.pano_verisi(depo, _ayar(), 1_800_000_000)
    assert veri["baglanti"] == "hic"
    assert veri["rapor"] is None and veri["son_rapor"] is None


def test_taze_rapor_canli_gec_rapor_yok():
    saat = Saat()
    depo = _pano.BellekDepo(saat)
    _pano.rapor_kaydet(depo, _pano.rapor_temizle(_rapor()), saat.simdi)
    assert _pano.pano_verisi(depo, _ayar(), saat.simdi + 60)["baglanti"] == "canli"
    # 30 sn aralıkta üç rapor kaçınca (ve 5 sn pay) bağlantı yok sayılır
    veri = _pano.pano_verisi(depo, _ayar(), saat.simdi + 96)
    assert veri["baglanti"] == "yok"
    assert veri["gecikme_sn"] == 96
    assert veri["rapor"]["sayilar"]["bugun_ihlal"] == 3


def test_kapanis_raporu_kapandi_der():
    saat = Saat()
    depo = _pano.BellekDepo(saat)
    _pano.rapor_kaydet(depo, _pano.rapor_temizle(_rapor(kapanis=True)), saat.simdi)
    assert _pano.pano_verisi(depo, _ayar(), saat.simdi + 5)["baglanti"] == "kapandi"


def test_eski_durum_silinir_son_rapor_zamani_kalir():
    saat = Saat()
    depo = _pano.BellekDepo(saat)
    _pano.rapor_kaydet(depo, _pano.rapor_temizle(_rapor()), saat.simdi)
    saat.simdi += _pano.DURUM_SAKLAMA_SN + 1
    veri = _pano.pano_verisi(depo, _ayar(), saat.simdi)
    assert veri["baglanti"] == "yok"
    assert veri["rapor"] is None
    assert veri["son_rapor"] is not None


# ---------------------------------------------------------------- oturum


def test_kurucu_cerezi_dogrulanir_suresi_dolunca_kapanir():
    ayar = _ayar()
    depo = _pano.BellekDepo()
    deger = _pano.cerez_uret(ayar, "kurucu", "kurucu", 0, 1_800_000_000)
    oturum = _pano.oturum_coz(depo, ayar, deger, 1_800_000_000)
    assert oturum.ad == "kurucu" and oturum.rol == "yonetici" and oturum.kurucu
    with pytest.raises(_pano.PanoHatasi) as hata:
        _pano.oturum_coz(depo, ayar, deger, 1_800_000_000 + _pano.OTURUM_SURESI_SN)
    assert hata.value.hata == "oturum_kapandi"


def test_sahte_bozuk_ve_eski_bicimli_cerez_gecersiz():
    ayar = _ayar()
    depo = _pano.BellekDepo()
    deger = _pano.cerez_uret(ayar, "kurucu", "kurucu", 0, 1_800_000_000)
    _, _, _, bitis, imza = _pano._cerez_coz(deger)
    # Bitiş değiştirilince imza tutmaz: giriş gerekli
    with pytest.raises(_pano.PanoHatasi) as h1:
        _pano.oturum_coz(depo, ayar, f"v2.kurucu.kurucu.0.{bitis + 9999}.{imza}", 1_800_000_000)
    assert h1.value.hata == "giris_gerekli"
    # Eski (v2 olmayan) biçim, boş ve bozuk çerez
    for bozuk in (f"{bitis}.{imza}", "", "²²²²²²²²²²", "v2.kurucu.kurucu.0.x.y"):
        with pytest.raises(_pano.PanoHatasi):
            _pano.oturum_coz(depo, ayar, bozuk, 1_800_000_000)
    # Kurucu şifresi değişince açık oturumlar düşer (imza anahtarı değişir)
    with pytest.raises(_pano.PanoHatasi):
        _pano.oturum_coz(depo, _ayar(pano_sifresi="yeni-sifre-456"), deger, 1_800_000_000)


# ----------------------------------------------------------------- kilit


def test_bes_yanlis_denemede_adres_kilitlenir_dogru_sifre_de_reddedilir():
    saat = Saat()
    depo = _pano.BellekDepo(saat)
    ayar = _ayar()
    for _ in range(_pano.KILIT_DENEME):
        with pytest.raises(_pano.PanoHatasi) as hata:
            _pano.giris_dene(depo, ayar, "1.2.3.4", "kurucu", "yanlis", saat.simdi)
        assert hata.value.kod == 401
    with pytest.raises(_pano.PanoHatasi) as hata:
        _pano.giris_dene(depo, ayar, "1.2.3.4", "kurucu", SIFRE, saat.simdi)
    assert hata.value.kod == 429
    # Başka adres etkilenmez
    _pano.giris_dene(depo, ayar, "5.6.7.8", "kurucu", SIFRE, saat.simdi)
    # Süre dolunca kilit açılır (ad sayacı 5<10 olduğundan engel değil)
    saat.simdi += _pano.KILIT_SURESI_SN + 1
    _pano.giris_dene(depo, ayar, "1.2.3.4", "kurucu", SIFRE, saat.simdi)


def test_ayni_anda_gelen_denemeler_kilidi_asamaz(monkeypatch):
    """Paralel deneme: eskiden üç sayaç şifreden önce yalnız OKUNUYOR, yanlış
    girişten sonra artırılıyordu; aynı anda gelen 30 denemenin hepsi eski sayıyı
    görüp şifre denetimine giriyordu (5 sınırında 30 deneme; iki adım kodu da
    böyle tahmin edilebilirdi; inceleme 02.11.2026). Sayaçlar artık şifreden
    ÖNCE atomik olarak ayrılır: en çok KILIT_DENEME deneme şifreye ulaşır."""
    import threading
    import time as gercek_saat

    depo = _pano.BellekDepo()
    ayar = _ayar()
    denenen = []
    kilit = threading.Lock()

    def yavas_sahte(sifre):  # şifre denetimi sürerken öbür istekler gelsin
        with kilit:
            denenen.append(sifre)
        gercek_saat.sleep(0.2)

    monkeypatch.setattr(_pano, "_sahte_dogrula", yavas_sahte)
    baslangic = threading.Barrier(30)
    sonuclar = []

    def dene():
        baslangic.wait()
        try:
            _pano.giris_dene(depo, ayar, "1.2.3.4", "bilinmeyen.kisi", "yanlis", 1_800_000_000)
        except _pano.PanoHatasi as hata:
            with kilit:
                sonuclar.append(hata.kod)

    isler = [threading.Thread(target=dene) for _ in range(30)]
    for is_ in isler:
        is_.start()
    for is_ in isler:
        is_.join(timeout=30)
    assert len(denenen) <= _pano.KILIT_DENEME, len(denenen)
    assert sonuclar.count(401) == len(denenen) and sonuclar.count(429) == 30 - len(denenen)
    # Kilit süresince doğru şifre de reddedilir; reddedilen deneme sayacı büyütmez
    with pytest.raises(_pano.PanoHatasi) as hata:
        _pano.giris_dene(depo, ayar, "1.2.3.4", "kurucu", SIFRE, 1_800_000_000)
    assert hata.value.kod == 429
    adres_sayisi = depo.komut("GET", _pano._adres_anahtari("1.2.3.4"))
    assert int(adres_sayisi) == _pano.KILIT_DENEME


def test_basarili_giris_ve_kod_istegi_sayaca_yazilmaz():
    """Başarılı girişin ayırdığı pay geri verilir: hatasız giriş sayaçları
    büyütmez, önceki yanlışlar silinmez (süresi dolar)."""
    depo = _pano.BellekDepo()
    ayar = _ayar()
    with pytest.raises(_pano.PanoHatasi):
        _pano.giris_dene(depo, ayar, "1.2.3.4", "kurucu", "yanlis", 1_800_000_000)
    for _ in range(3):
        _pano.giris_dene(depo, ayar, "1.2.3.4", "kurucu", SIFRE, 1_800_000_000)
    assert depo.komut("GET", _pano._adres_anahtari("1.2.3.4")) == "1"
    assert depo.komut("GET", _pano._ad_kilit_anahtari("kurucu")) == "1"
    assert depo.komut("GET", _pano.GIRIS_GENEL_ANAHTARI) == "1"


def test_genel_kilit_cok_adresten_gelen_denemeyi_durdurur():
    saat = Saat()
    depo = _pano.BellekDepo(saat)
    ayar = _ayar()
    # Her deneme ayrı ad ve ayrı adres: yalnız genel sayaç dolsun (ad kilidi değil)
    for i in range(_pano.GENEL_KILIT_DENEME):
        with pytest.raises(_pano.PanoHatasi):
            _pano.giris_dene(
                depo, ayar, f"10.0.{i // 250}.{i % 250}", f"kisi{i}", "yanlis", saat.simdi
            )
    with pytest.raises(_pano.PanoHatasi) as hata:
        _pano.giris_dene(depo, ayar, "9.9.9.9", "kurucu", SIFRE, saat.simdi)
    assert hata.value.hata == "genel_kilit"


def test_ad_kilidi_ayni_adla_cok_denemeyi_durdurur():
    saat = Saat()
    depo = _pano.BellekDepo(saat)
    ayar = _ayar()
    # Aynı ad, hep farklı adres: adres kilidi değil, ad kilidi devreye girer
    for i in range(_pano.AD_KILIT_DENEME):
        with pytest.raises(_pano.PanoHatasi):
            _pano.giris_dene(depo, ayar, f"10.1.{i}.{i}", "ahmet.yilmaz", "yanlis", saat.simdi)
    with pytest.raises(_pano.PanoHatasi) as hata:
        _pano.giris_dene(depo, ayar, "7.7.7.7", "ahmet.yilmaz", SIFRE, saat.simdi)
    assert hata.value.hata == "ad_kilitli"


def test_ipv6_ayni_64_tek_sayacta_sayilir():
    saat = Saat()
    depo = _pano.BellekDepo(saat)
    ayar = _ayar()
    # Aynı /64'ten dört farklı adres: beşinci yanlış denemede kilit
    for son in range(_pano.KILIT_DENEME):
        with pytest.raises(_pano.PanoHatasi) as hata:
            _pano.giris_dene(
                depo, ayar, f"2a02:e0:1234:5678::{son + 1}", "kurucu", "yanlis", saat.simdi
            )
        assert hata.value.kod == 401
    with pytest.raises(_pano.PanoHatasi) as hata:
        _pano.giris_dene(depo, ayar, "2a02:e0:1234:5678::ff", "kurucu", SIFRE, saat.simdi)
    assert hata.value.hata == "kilitli"


def test_bilinmeyen_ad_ve_kurucu_ilk_denemede_de_tek_ozet_calistirir(monkeypatch):
    """Var olmayan ad ve kurucu da bir hesap kadar özet çalıştırır (docs/19 §3.2).
    Sahte kayıt ilk denemede kuruluyordu: yeni bir işlevin (Vercel'de soğuk
    başlangıç) ilk bilinmeyen ad denemesi iki özet çalıştırıp ölçülebilir biçimde
    yavaşlıyor, adın olmadığını sızdırıyordu. Artık her deneme tek özet."""
    sayi = {"ozet": 0}
    scrypt, pbkdf2 = _pano.hashlib.scrypt, _pano.hashlib.pbkdf2_hmac

    def sayan(gercek):
        def ozet(*arg, **ad):
            sayi["ozet"] += 1
            return gercek(*arg, **ad)

        return ozet

    depo = _pano.BellekDepo(Saat())
    hesap = {
        "ad": "ali",
        "hesap_kimligi": "1234567890abcdef",
        "rol": "operator",
        "acik": True,
        "sifre": _pano.sifre_ozetle("ali-sifresi-1"),
        "oturum_surumu": 1,
    }
    depo.komut("SET", _pano.KULLANICI_ONEKI + "ali", json.dumps(hesap))
    monkeypatch.setattr(_pano.hashlib, "scrypt", sayan(scrypt))
    monkeypatch.setattr(_pano.hashlib, "pbkdf2_hmac", sayan(pbkdf2))
    denemeler = [("hayalet", True), ("hayalet", False), ("kurucu", True), ("ali", True)]
    for sira, (ad, yeni_islev) in enumerate(denemeler):
        if yeni_islev:  # sahte kayıt henüz kurulmamış (yeni işlev)
            monkeypatch.setattr(_pano, "_SAHTE_KAYIT", None)
        sayi["ozet"] = 0
        with pytest.raises(_pano.PanoHatasi):
            _pano.giris_dene(depo, _ayar(), f"10.9.0.{sira}", ad, "yanlis-sifre", 1_800_000_000)
        assert sayi["ozet"] == 1, (ad, yeni_islev)


def test_kilit_sayaci_ip_adresini_acik_yazmaz():
    depo = _pano.BellekDepo(Saat())
    with pytest.raises(_pano.PanoHatasi):
        _pano.giris_dene(depo, _ayar(), "192.168.77.88", "kurucu", "yanlis", 1_800_000_000)
    assert not any("192.168.77.88" in anahtar for anahtar in depo._veri)


# ---------------------------------------------------------------- kurulum


def test_eksik_ayarlar_listelenir_sirlar_yazilmaz():
    eksik = _pano.eksikler(_ayar(pano_sifresi="kisa", rapor_anahtari="", redis_adresi=""))
    adlar = [e["ad"] for e in eksik]
    assert adlar == ["PANO_SIFRESI", "RAPOR_ANAHTARI", "Upstash Redis"]
    assert "kisa" not in json.dumps(eksik)
    assert _pano.eksikler(_ayar()) == []


def test_upstash_iki_ad_bicimini_de_okur():
    yeni = _pano.ayar_oku({"UPSTASH_REDIS_REST_URL": "https://a", "UPSTASH_REDIS_REST_TOKEN": "t"})
    eski = _pano.ayar_oku({"KV_REST_API_URL": "https://b", "KV_REST_API_TOKEN": "u"})
    assert (yeni.redis_adresi, yeni.redis_jetonu) == ("https://a", "t")
    assert (eski.redis_adresi, eski.redis_jetonu) == ("https://b", "u")


@pytest.mark.parametrize(
    ("ham", "beklenen"),
    [
        ("http://100.64.1.2:8080", "http://100.64.1.2:8080"),
        ("https://isg.dalsan.local", "https://isg.dalsan.local"),
        ("javascript:alert(1)", ""),
        ("http://a b", ""),
        ("", ""),
    ],
)
def test_fabrika_adresi_yalniz_http(ham, beklenen):
    assert _pano.ayar_oku({"FABRIKA_ADRESI": ham}).fabrika_adresi == beklenen
