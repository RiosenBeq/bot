"""Uzaktan müdahale: panodan komut, fabrikanın imzalı yoklaması ve sonuç.

Önce çekirdek işlevler sahte saatle (süre aşımı, bir kez teslim), sonra gerçek
HTTP ile bütün akış: giriş -> komut -> fabrika alır -> sonucu bildirir.
"""

import json
import time

import _pano
import pytest
from test_uctan_uca import ANAHTAR, RAPOR, _cerez, _giris, _istek, _rapor_gonder, site  # noqa: F401

MUDAHALE = {
    "acik": True,
    "mesajlar": [{"id": 3, "metin": "Lütfen baret takınız"}, {"id": 5, "metin": "Sahayı boşaltın"}],
    "kanallar": [
        {"id": 1, "ad": "Genel anons", "bolum": ""},
        {"id": 2, "ad": "Sevkiyat hoparlörü", "bolum": "Sevkiyat"},
    ],
}


def _veri(acik=True, baglanti="canli", kanallar=None):
    mudahale = {**MUDAHALE, "acik": acik}
    if kanallar is not None:
        mudahale["kanallar"] = kanallar
    return {"baglanti": baglanti, "rapor": {"mudahale": mudahale}}


# ------------------------------------------------------------- bellek deposu


def test_bellek_deposu_liste_komutlari_redis_gibi():
    depo = _pano.BellekDepo()
    assert depo.komut("RPUSH", "l", "a", "b") == 2
    assert depo.komut("LPUSH", "l", "x", "y") == 4  # LPUSH x y: y başa geçer
    assert depo.komut("LRANGE", "l", "0", "-1") == ["y", "x", "a", "b"]
    assert depo.komut("LRANGE", "l", "1", "2") == ["x", "a"]
    assert depo.komut("LPOP", "l", "3") == ["y", "x", "a"]
    assert depo.komut("LPOP", "l") == "b"
    assert depo.komut("LPOP", "l", "2") is None  # boş liste silinir
    assert depo.komut("LLEN", "l") == 0
    depo.komut("RPUSH", "k", "1", "2", "3", "4")
    assert depo.komut("LTRIM", "k", "0", "1") == "OK"
    assert depo.komut("LRANGE", "k", "0", "-1") == ["1", "2"]
    with pytest.raises(_pano.DepoHatasi, match="WRONGTYPE"):
        depo.komut("GET", "k")
    with pytest.raises(_pano.DepoHatasi, match="unknown command"):
        depo.komut("FLUSHALL")


def test_bellek_deposu_sureleri_uygular():
    simdi = [1000.0]
    depo = _pano.BellekDepo(lambda: simdi[0])
    depo.boru_hatti([["SET", "a", "1", "EX", "10"], ["RPUSH", "l", "x"], ["EXPIRE", "l", "5"]])
    assert depo.komut("SET", "a", "2", "NX") is None
    simdi[0] += 6
    assert depo.komut("LLEN", "l") == 0
    assert depo.al_coklu(["a"]) == ["1"]
    simdi[0] += 5
    assert depo.al_coklu(["a"]) == [None]
    assert depo.komut("DEL", "a", "yok") == 0


# ------------------------------------------------------------ rapor biçimi


def test_mudahale_alani_suzulur_ve_adres_tasimaz():
    ham = {
        **RAPOR,
        "mudahale": {
            "acik": "evet",  # yalnız gerçek true açık sayılır
            "mesajlar": [
                {"id": 1, "metin": "Baret\ntakınız", "ses_dosyasi": "veri/sesler/a.wav"},
                {"id": True, "metin": "bool kimlik"},
                {"id": "2", "metin": "dize kimlik"},
            ],
            "kanallar": [{"id": 4, "ad": "Kapı", "bolum": "Giriş", "adres": "http://10.0.0.9/ses"}],
            "sifre": "gizli",
        },
    }
    temiz = _pano.rapor_temizle(ham)["mudahale"]
    assert temiz == {
        "acik": False,
        "mesajlar": [{"id": 1, "metin": "Baret takınız"}],
        "kanallar": [{"id": 4, "ad": "Kapı", "bolum": "Giriş"}],
    }
    # Eski fabrika programı alanı hiç göndermez: kapalı sayılır
    assert _pano.rapor_temizle(RAPOR)["mudahale"] == {"acik": False, "mesajlar": [], "kanallar": []}


# ------------------------------------------------------------ çekirdek akış


def test_komut_kuyruga_girer_bir_kez_teslim_edilir_sonucu_yazilir():
    depo = _pano.BellekDepo()
    komut = _pano.komut_olustur(depo, _veri(), {"tur": "anons", "mesaj_id": 3}, 1000)
    assert komut["durum"] == "bekliyor"
    assert komut["ozet"] == "Anons: “Lütfen baret takınız” · Tüm fabrika"

    teslim, hizli = _pano.komutlari_teslim_et(depo, 1010)
    assert hizli is True  # komut işareti ve izleyen işareti
    assert teslim == [
        {
            "id": komut["id"],
            "tur": "anons",
            "kanal_id": None,
            "mesaj_id": 3,
            "son_gecerlilik": 1000 + _pano.KOMUT_GECERLILIK_SN,
            "kalan_sn": _pano.KOMUT_GECERLILIK_SN - 10,
        }
    ]
    # İkinci yoklamada aynı komut gelmez (fabrika yeniden başlasa da anons tekrarlanmaz)
    assert _pano.komutlari_teslim_et(depo, 1012)[0] == []
    gorunum = _pano.mudahale_verisi(depo, 1015, izliyor=False)
    assert gorunum["komutlar"][0]["durum"] == "iletildi"
    assert gorunum["yoklama_yasi_sn"] == 3

    _pano.sonuclari_yaz(
        depo, [{"id": komut["id"], "durum": "yapildi", "mesaj": "Genel anons: çalındı"}], 1020
    )
    son = _pano.mudahale_verisi(depo, 1021, izliyor=False)["komutlar"][0]
    assert (son["durum"], son["mesaj"]) == ("yapildi", "Genel anons: çalındı")
    # Bitmiş komut yeniden açılmaz
    _pano.sonuclari_yaz(depo, [{"id": komut["id"], "durum": "hata", "mesaj": "x"}], 1030)
    assert _pano.mudahale_verisi(depo, 1031, izliyor=False)["komutlar"][0]["durum"] == "yapildi"


def test_suresi_dolan_komut_fabrikaya_gitmez():
    depo = _pano.BellekDepo(lambda: 1000.0)
    komut = _pano.komut_olustur(depo, _veri(), {"tur": "ses_dene", "kanal_id": 2}, 1000)
    assert komut["ozet"] == "Hoparlör denemesi · Sevkiyat hoparlörü (Sevkiyat)"
    gec = 1000 + _pano.KOMUT_GECERLILIK_SN
    # Fabrika sormadan önce de panoda "süresi doldu" görünür
    assert _pano.mudahale_verisi(depo, gec, izliyor=False)["komutlar"][0]["durum"] == (
        "suresi_doldu"
    )
    teslim, _ = _pano.komutlari_teslim_et(depo, gec)
    assert teslim == []
    gorunum = _pano.mudahale_verisi(depo, gec + 1, izliyor=False)["komutlar"][0]
    assert gorunum["durum"] == "suresi_doldu"
    assert gorunum["mesaj"] == _pano.SURESI_DOLDU_METNI


def test_iletilip_sonucu_gelmeyen_komut_adlandirilir():
    depo = _pano.BellekDepo(lambda: 1000.0)
    _pano.komut_olustur(depo, _veri(), {"tur": "anons", "mesaj_id": 5, "kanal_id": 2}, 1000)
    _pano.komutlari_teslim_et(depo, 1001)
    gec = 1001 + _pano.SONUC_BEKLEME_SN + 1
    assert _pano.mudahale_verisi(depo, gec, izliyor=False)["komutlar"][0]["durum"] == "sonuc_yok"


@pytest.mark.parametrize(
    ("veri", "istek", "kod", "hata"),
    [
        (_veri(acik=False), {"tur": "anons", "mesaj_id": 3}, 409, "mudahale_kapali"),
        (_veri(baglanti="yok"), {"tur": "anons", "mesaj_id": 3}, 409, "fabrika_bagli_degil"),
        (_veri(), {"tur": "kapat"}, 400, "tur"),
        (_veri(), {"tur": "anons", "mesaj_id": 99}, 400, "mesaj"),
        (_veri(), {"tur": "anons", "mesaj_id": "3"}, 400, "mesaj"),
        (_veri(), {"tur": "anons", "mesaj_id": 3, "kanal_id": 9}, 400, "kanal"),
        (_veri(), {"tur": "ses_dene"}, 400, "kanal"),
        (
            _veri(kanallar=[{"id": 2, "ad": "Sevkiyat", "bolum": "Sevkiyat"}]),
            {"tur": "anons", "mesaj_id": 3},
            400,
            "tum_fabrika_yok",
        ),
    ],
)
def test_gecersiz_komut_reddedilir_ve_kuyruga_girmez(veri, istek, kod, hata):
    depo = _pano.BellekDepo()
    with pytest.raises(_pano.PanoHatasi) as bilgi:
        _pano.komut_olustur(depo, veri, istek, 1000)
    assert (bilgi.value.kod, bilgi.value.hata) == (kod, hata)
    assert depo.komut("LLEN", _pano.KOMUT_SIRA_ANAHTARI) == 0


def test_komut_siniri():
    depo = _pano.BellekDepo(lambda: 1000.0)
    for _ in range(_pano.KOMUT_SINIRI):
        _pano.komut_olustur(depo, _veri(), {"tur": "anons", "mesaj_id": 3}, 1000)
    with pytest.raises(_pano.PanoHatasi) as bilgi:
        _pano.komut_olustur(depo, _veri(), {"tur": "anons", "mesaj_id": 3}, 1000)
    assert bilgi.value.kod == 429
    assert depo.komut("LLEN", _pano.KOMUT_SIRA_ANAHTARI) == _pano.KOMUT_SINIRI


def test_bozuk_sonuc_ve_yabanci_kimlik_yok_sayilir():
    depo = _pano.BellekDepo()
    _pano.sonuclari_yaz(
        depo,
        [
            "metin",
            {"id": "../../anahtar", "durum": "yapildi"},
            {"id": "0123456789abcdef", "durum": "silindi"},
            {"id": "0123456789abcdef", "durum": "yapildi"},  # böyle bir komut yok
        ],
        1000,
    )
    assert depo.komut("MGET", _pano.KOMUT_KAYIT_ONEKI + "0123456789abcdef") == [None]


# --------------------------------------------------------------- HTTP akışı


def _fabrika_yoklar(adres, sonuclar=(), anahtar=ANAHTAR):
    govde = json.dumps({"surum": 1, "sonuclar": list(sonuclar)}).encode()
    zaman = str(int(time.time()))
    return _istek(
        f"{adres}/api/komut",
        "POST",
        govde,
        {
            "Content-Type": "application/json",
            _pano.ZAMAN_BASLIGI: zaman,
            _pano.IMZA_BASLIGI: _pano.imza_hesapla(anahtar, zaman, govde),
        },
    )


def _mudahale_iste(adres, cerez, govde, koken=None):
    basliklar = {"Content-Type": "application/json", "Cookie": cerez}
    if koken:
        basliklar["Origin"] = koken
    return _istek(f"{adres}/api/mudahale", "POST", json.dumps(govde).encode(), basliklar)


def test_panodan_fabrikaya_anons_akisi(site):  # noqa: F811
    kod, _, govde = _rapor_gonder(site, {**RAPOR, "mudahale": MUDAHALE})
    assert kod == 200
    assert json.loads(govde)["komut"] == {"hizli": False}  # ekran kapalı, komut yok

    cerez = _cerez(_giris(site)[1])
    kod, _, govde = _istek(f"{site}/api/durum?mudahale=1", basliklar={"Cookie": cerez})
    assert kod == 200
    assert json.loads(govde)["mudahale"]["komutlar"] == []
    # Müdahale ekranı açıldı: fabrikanın bir sonraki raporu "sık sor" cevabı alır
    assert json.loads(_rapor_gonder(site, {**RAPOR, "mudahale": MUDAHALE})[2])["komut"] == {
        "hizli": True
    }

    kod, _, govde = _mudahale_iste(site, cerez, {"tur": "anons", "mesaj_id": 3}, site)
    assert kod == 200, govde
    komut = json.loads(govde)["komut"]

    kod, basliklar, govde = _fabrika_yoklar(site)
    assert kod == 200
    # Cevap imzalı: fabrika imzası tutmayan cevaptaki komutu yürütmez
    zaman = basliklar[_pano.ZAMAN_BASLIGI]
    _pano.imza_dogrula(ANAHTAR, zaman, basliklar[_pano.IMZA_BASLIGI], govde, time.time())
    cevap = json.loads(govde)
    assert [k["id"] for k in cevap["komutlar"]] == [komut["id"]]
    assert cevap["komutlar"][0]["mesaj_id"] == 3
    assert cevap["hizli"] is True

    sonuc = {"id": komut["id"], "durum": "yapildi", "mesaj": "Genel anons: çalındı"}
    kod, _, govde = _fabrika_yoklar(site, [sonuc])
    assert kod == 200 and json.loads(govde)["komutlar"] == []

    kod, _, govde = _istek(f"{site}/api/durum?mudahale=1", basliklar={"Cookie": cerez})
    son = json.loads(govde)["mudahale"]["komutlar"][0]
    assert (son["durum"], son["mesaj"]) == ("yapildi", "Genel anons: çalındı")


def test_mudahale_oturum_koken_ve_icerik_turu_ister(site):  # noqa: F811
    _rapor_gonder(site, {**RAPOR, "mudahale": MUDAHALE})
    kod, _, _ = _mudahale_iste(site, "", {"tur": "anons", "mesaj_id": 3})
    assert kod == 401
    cerez = _cerez(_giris(site)[1])
    kod, _, govde = _mudahale_iste(
        site, cerez, {"tur": "anons", "mesaj_id": 3}, "https://kotu.example"
    )
    assert kod == 403 and json.loads(govde)["hata"] == "koken"
    kod, _, _ = _istek(
        f"{site}/api/mudahale",
        "POST",
        b"tur=anons",
        {"Content-Type": "application/x-www-form-urlencoded", "Cookie": cerez},
    )
    assert kod == 415
    kod, _, _ = _istek(f"{site}/api/mudahale", basliklar={"Cookie": cerez})
    assert kod == 405


def test_komut_yoklamasi_imza_ister(site):  # noqa: F811
    kod, basliklar, govde = _fabrika_yoklar(site, anahtar="b" * 40)
    assert kod == 401 and json.loads(govde)["hata"] == "imza_gecersiz"
    assert _pano.IMZA_BASLIGI not in basliklar  # doğrulanmamış isteğe imzalı cevap yok
    kod, _, _ = _istek(f"{site}/api/komut", "POST", b"{}", {"Content-Type": "application/json"})
    assert kod == 401


def test_mudahale_kapaliyken_rapor_isaret_okumaz(site):  # noqa: F811
    cerez = _cerez(_giris(site)[1])
    _istek(f"{site}/api/durum?mudahale=1", basliklar={"Cookie": cerez})
    kod, _, govde = _rapor_gonder(site, RAPOR)
    assert kod == 200 and json.loads(govde)["komut"] == {"hizli": False}
