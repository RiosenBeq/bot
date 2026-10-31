"""Uzaktan yönetim komutları (docs/19 §3.5-§3.7): yönetim kapıları, grup
sınırları, tek ağır iş kilidi ve kayan pencere, teslimde yetki denetimi,
suruyor geçişleri, tür başına sonuç bekleme, ek süzme, nonce ve alinan."""

import json
import time

import _pano
import pytest
from _pano import PanoHatasi
from test_uctan_uca import ANAHTAR, _istek, site  # noqa: F401

KANALLAR = [{"id": 1, "ad": "Genel", "bolum": ""}, {"id": 2, "ad": "Sevkiyat", "bolum": "Sevkiyat"}]
MESAJLAR = [{"id": 3, "metin": "Lütfen baret takınız"}]
OLAYLAR = [
    {
        "id": 1234,
        "tur": "ihlal",
        "baslik": "Baret yok",
        "yer": "Rampa",
        "zaman": "2026-10-31T09:15:02+00:00",
        "durum": "new",
    },
    {
        "id": 1200,
        "tur": "ihlal",
        "baslik": "Yasak bölge",
        "yer": "Rampa",
        "zaman": "2026-10-31T08:00:00+00:00",
        "durum": "reviewed",
    },
    {"id": 1100, "tur": "sistem", "baslik": "Kamera çevrimdışı", "durum": ""},
]
YONETIM_KAPALI = {
    "acik": False,
    "isler": [],
    "kurulum": "",
    "yeniden_baslatma": {"mumkun": False, "sebep": ""},
    "guncelleme": {"mumkun": False, "sebep": ""},
}
YONETIM_ACIK = {
    "acik": True,
    "isler": ["teshis", "yeniden_baslat", "guncelle"],
    "kurulum": "git",
    "yeniden_baslatma": {"mumkun": True, "sebep": ""},
    "guncelleme": {"mumkun": True, "sebep": ""},
}
# Kurucu teslimde her zaman yetkilidir (hesap aranmaz): kapı testlerinde kullanılır.
YON = {"ad": "kurucu", "rol": "yonetici"}


def _veri(yonetim=None, mudahale_acik=True, isler=("anons", "ses_dene", "olay_incele")):
    return {
        "baglanti": "canli",
        "rapor": {
            "mudahale": {
                "acik": mudahale_acik,
                "isler": list(isler),
                "mesajlar": MESAJLAR,
                "kanallar": KANALLAR,
            },
            "son_olaylar": OLAYLAR,
            "yonetim": yonetim or YONETIM_KAPALI,
        },
    }


def _bul(depo, simdi, kimlik, rol="yonetici"):
    for k in _pano.mudahale_verisi(depo, simdi, rol, izliyor=False)["komutlar"]:
        if k["id"] == kimlik:
            return k
    return None


# ------------------------------------------------------------ yönetim kapıları


def test_teshis_yonetim_acikken_kuyruga_girer():
    depo = _pano.BellekDepo()
    komut = _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "teshis"}, 1000, YON)
    assert komut["tur"] == "teshis" and komut["ozet"] == "Teşhis" and komut["durum"] == "bekliyor"


def test_yonetim_kapaliyken_yonetim_komutu_reddedilir():
    depo = _pano.BellekDepo()
    with pytest.raises(PanoHatasi) as e:
        _pano.komut_olustur(depo, _veri(YONETIM_KAPALI), {"tur": "teshis"}, 1000, YON)
    assert (e.value.kod, e.value.hata) == (409, "yonetim_kapali")
    assert depo.komut("LLEN", _pano.KOMUT_SIRA_ANAHTARI) == 0


def test_desteklenmeyen_is_reddedilir():
    depo = _pano.BellekDepo()
    yon = {**YONETIM_ACIK, "isler": ["teshis"]}  # guncelle fabrikada yok
    with pytest.raises(PanoHatasi) as e:
        _pano.komut_olustur(depo, _veri(yon), {"tur": "guncelle"}, 1000, YON)
    assert (e.value.kod, e.value.hata) == (409, "is_desteklenmiyor")


def test_yapilamaz_sebep_fabrikanin_sebebini_tasir():
    depo = _pano.BellekDepo()
    yon = {**YONETIM_ACIK, "guncelleme": {"mumkun": False, "sebep": "Paket listesi değişti."}}
    with pytest.raises(PanoHatasi) as e:
        _pano.komut_olustur(depo, _veri(yon), {"tur": "guncelle"}, 1000, YON)
    assert e.value.kod == 409 and e.value.hata == "yapilamaz"
    assert e.value.mesaj == "Paket listesi değişti."


# ------------------------------------------------------------ olay inceleme


def test_olay_incele_yalniz_new_ihlalde():
    depo = _pano.BellekDepo()
    komut = _pano.komut_olustur(
        depo, _veri(), {"tur": "olay_incele", "olay_id": 1234, "karar": "reviewed"}, 1000, YON
    )
    assert komut["ozet"] == "İnceleme: “Baret yok” · Rampa → İncelendi"


@pytest.mark.parametrize(
    ("istek", "kod", "hata"),
    [
        ({"tur": "olay_incele", "olay_id": 1200, "karar": "reviewed"}, 409, "olay_incelenmis"),
        ({"tur": "olay_incele", "olay_id": 9999, "karar": "reviewed"}, 400, "olay"),
        ({"tur": "olay_incele", "olay_id": 1100, "karar": "reviewed"}, 400, "olay"),  # sistem olayı
        ({"tur": "olay_incele", "olay_id": 1234}, 400, "karar"),
    ],
)
def test_olay_incele_hatalari(istek, kod, hata):
    depo = _pano.BellekDepo()
    with pytest.raises(PanoHatasi) as e:
        _pano.komut_olustur(depo, _veri(), istek, 1000, YON)
    assert (e.value.kod, e.value.hata) == (kod, hata)


def test_olay_incele_komutu_olay_zamanini_tasir():
    depo = _pano.BellekDepo()
    komut = _pano.komut_olustur(
        depo, _veri(), {"tur": "olay_incele", "olay_id": 1234, "karar": "false_alarm"}, 1000, YON
    )
    teslim, _ = _pano.komutlari_teslim_et(depo, 1001)
    assert teslim[0]["olay_id"] == 1234
    assert teslim[0]["olay_zaman"] == "2026-10-31T09:15:02+00:00"
    assert teslim[0]["karar"] == "false_alarm"
    assert komut["id"] == teslim[0]["id"]


# ------------------------------------------------------------ grup sınırları


def test_gruplar_ayri_sayilir():
    depo = _pano.BellekDepo(lambda: 1000.0)
    for _ in range(_pano.KOMUT_GRUP_SINIRLARI["teshis"]):
        _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "teshis"}, 1000, YON)
    with pytest.raises(PanoHatasi) as e:
        _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "teshis"}, 1000, YON)
    assert e.value.kod == 429
    # Teşhis dolsa da ses grubu bağımsızdır
    anons = _pano.komut_olustur(
        depo, _veri(YONETIM_ACIK), {"tur": "anons", "mesaj_id": 3}, 1000, YON
    )
    assert anons["durum"] == "bekliyor"


# ------------------------------------------------------------ tek ağır iş


def _bitir(depo, kimlik, simdi):
    _pano.sonuclari_yaz(depo, [{"id": kimlik, "durum": "yapildi", "mesaj": "tamam"}], simdi)


def test_tek_agir_is_kilidi_ikinciyi_reddeder():
    depo = _pano.BellekDepo(lambda: 1000.0)
    _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "guncelle"}, 1000, YON)
    with pytest.raises(PanoHatasi) as e:
        _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "yeniden_baslat"}, 1000, YON)
    assert (e.value.kod, e.value.hata) == (409, "agir_suruyor")


def test_bayat_agir_kilit_yeniden_denenir():
    saat = [1000.0]
    depo = _pano.BellekDepo(lambda: saat[0])
    k1 = _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "guncelle"}, saat[0], YON)
    _bitir(depo, k1["id"], saat[0] + 1)  # kilit artık bayat (komut bitti)
    saat[0] += 10
    k2 = _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "yeniden_baslat"}, saat[0], YON)
    assert k2["durum"] == "bekliyor"


def test_agir_kayan_pencere_saatte_ucten_fazla_reddeder():
    saat = [1000.0]
    depo = _pano.BellekDepo(lambda: saat[0])
    for _ in range(_pano.AGIR_SINIR):
        k = _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "guncelle"}, saat[0], YON)
        _bitir(depo, k["id"], saat[0] + 1)  # kilidi serbest bırak
        saat[0] += 10
    with pytest.raises(PanoHatasi) as e:
        _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "yeniden_baslat"}, saat[0], YON)
    assert (e.value.kod, e.value.hata) == (429, "cok_sik")
    # Pencere dolunca bırakılan kilit başkasını bloke etmez
    assert depo.al_coklu([_pano.AGIR_KILIT_ANAHTARI]) == [None]
    # Pencere (3600 sn) dolunca yeniden yapılabilir
    saat[0] += _pano.AGIR_PENCERE_SN + 1
    k = _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "guncelle"}, saat[0], YON)
    assert k["durum"] == "bekliyor"


# ------------------------------------------------------ teslimde yetki denetimi


def _hesap_yaz(depo, ad, rol, acik=True, surum=1):
    kayit = {"ad": ad, "hesap_kimligi": "0" * 16, "rol": rol, "acik": acik, "oturum_surumu": surum}
    depo.boru_hatti([["SET", _pano.KULLANICI_ONEKI + ad, json.dumps(kayit)]])


def test_rolu_dusen_hesabin_komutu_teslim_edilmez():
    depo = _pano.BellekDepo()
    _hesap_yaz(depo, "ali", "operator")
    k = _pano.komut_olustur(
        depo, _veri(), {"tur": "anons", "mesaj_id": 3}, 1000, {"ad": "ali", "rol": "operator"}
    )
    _hesap_yaz(depo, "ali", "izleyici", surum=2)  # operatörlükten düşürüldü
    teslim, _ = _pano.komutlari_teslim_et(depo, 1001)
    assert teslim == []
    gorunum = _bul(depo, 1002, k["id"])
    assert gorunum["durum"] == "hata" and "yetkisi kalmad" in gorunum["mesaj"]
    assert any(s["is"] == "komut_dustu" for s in _pano._kayit_birlesik(depo))


def test_kapali_hesabin_komutu_teslim_edilmez():
    depo = _pano.BellekDepo()
    _hesap_yaz(depo, "ali", "operator")
    k = _pano.komut_olustur(
        depo, _veri(), {"tur": "ses_dene", "kanal_id": 2}, 1000, {"ad": "ali", "rol": "operator"}
    )
    _hesap_yaz(depo, "ali", "operator", acik=False)
    teslim, _ = _pano.komutlari_teslim_et(depo, 1001)
    assert teslim == []
    assert _bul(depo, 1002, k["id"])["durum"] == "hata"


# ------------------------------------------------------ sonuç durumları


def test_suruyor_sonra_yapildi():
    depo = _pano.BellekDepo()
    k = _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "guncelle"}, 1000, YON)
    _pano.komutlari_teslim_et(depo, 1001)
    _pano.sonuclari_yaz(depo, [{"id": k["id"], "durum": "suruyor", "mesaj": "hazırlanıyor"}], 1002)
    assert _bul(depo, 1003, k["id"])["durum"] == "suruyor"
    _pano.sonuclari_yaz(depo, [{"id": k["id"], "durum": "yapildi", "mesaj": "güncellendi"}], 1004)
    assert _bul(depo, 1005, k["id"])["durum"] == "yapildi"


def test_tur_basina_sonuc_bekleme():
    depo = _pano.BellekDepo()
    k = _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "guncelle"}, 1000, YON)
    _pano.komutlari_teslim_et(depo, 1001)  # iletildi (an = 1001)
    # guncelle eşiği 1800 sn: 300 sn sonra hâlâ iletildi
    assert _bul(depo, 1001 + 300, k["id"])["durum"] == "iletildi"
    assert _bul(depo, 1001 + 1801, k["id"])["durum"] == "sonuc_yok"


def test_teshis_sonuc_bekleme_kisadir():
    depo = _pano.BellekDepo()
    k = _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "teshis"}, 2000, YON)
    _pano.komutlari_teslim_et(depo, 2001)
    assert _bul(depo, 2001 + _pano.SONUC_BEKLEME_SN + 1, k["id"])["durum"] == "sonuc_yok"


def test_teshis_ek_metni_suzulur_kesilir_operatore_gizlenir():
    depo = _pano.BellekDepo()
    k = _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "teshis"}, 1000, YON)
    _pano.komutlari_teslim_et(depo, 1001)
    ek = "satır1\n\tsekme\x07zil rtsp://admin:gizli@10.0.0.5/x son"
    _pano.sonuclari_yaz(
        depo, [{"id": k["id"], "durum": "yapildi", "mesaj": "Teşhis hazır.", "ek": ek}], 1002
    )
    gorunum = _bul(depo, 1003, k["id"], rol="yonetici")
    assert "\n" in gorunum["ek"] and "\t" in gorunum["ek"]
    assert "\x07" not in gorunum["ek"]
    assert "(adres)" in gorunum["ek"] and "gizli" not in gorunum["ek"]
    # Operatör teşhis komutunu hiç görmez (yalnız ses ve inceleme)
    assert _pano.mudahale_verisi(depo, 1003, "operator", izliyor=False)["komutlar"] == []


def test_ek_8192_bayta_kesilir():
    depo = _pano.BellekDepo()
    k = _pano.komut_olustur(depo, _veri(YONETIM_ACIK), {"tur": "teshis"}, 1000, YON)
    _pano.komutlari_teslim_et(depo, 1001)
    _pano.sonuclari_yaz(
        depo, [{"id": k["id"], "durum": "yapildi", "mesaj": "x", "ek": "a" * 9000}], 1002
    )
    assert len(_bul(depo, 1003, k["id"])["ek"].encode("utf-8")) <= _pano.EK_EN_BUYUK_BAYT


# ------------------------------------------------------ nonce, alinan, en çok 10


def test_en_cok_on_sonuc_islenir():
    depo = _pano.BellekDepo()
    ids = [f"{i:016x}" for i in range(11)]
    for kid in ids:
        kayit = {"id": kid, "tur": "anons", "durum": "iletildi", "guncellendi": 0}
        depo.boru_hatti([["SET", _pano.KOMUT_KAYIT_ONEKI + kid, json.dumps(kayit)]])
    alinan = _pano.sonuclari_yaz(
        depo, [{"id": kid, "durum": "yapildi", "mesaj": "ok"} for kid in ids], 1000
    )
    assert len(alinan) == _pano.KOMUT_SONUC_EN_COK == 10
    # 11. sonucun komutu dokunulmadan kalır (sonraki soruda yeniden gönderilir)
    (ham,) = depo.al_coklu([_pano.KOMUT_KAYIT_ONEKI + ids[10]])
    assert json.loads(ham)["durum"] == "iletildi"


def test_biten_ve_olmayan_komut_da_onaylanir():
    depo = _pano.BellekDepo()
    bitmis = {"id": "aa" * 8, "tur": "teshis", "durum": "yapildi", "guncellendi": 0}
    depo.boru_hatti([["SET", _pano.KOMUT_KAYIT_ONEKI + "aa" * 8, json.dumps(bitmis)]])
    alinan = _pano.sonuclari_yaz(
        depo,
        [
            {"id": "aa" * 8, "durum": "hata", "mesaj": "geç geldi"},  # zaten bitmiş
            {"id": "bb" * 8, "durum": "yapildi", "mesaj": "kaydı yok"},  # süresi dolmuş
        ],
        1000,
    )
    assert set(alinan) == {"aa" * 8, "bb" * 8}
    # Bitmiş komut yeniden açılmaz
    (ham,) = depo.al_coklu([_pano.KOMUT_KAYIT_ONEKI + "aa" * 8])
    assert json.loads(ham)["durum"] == "yapildi"


def _yokla(site, nonce=None, sonuclar=()):  # noqa: F811
    govde_d = {"surum": 1, "sonuclar": list(sonuclar)}
    if nonce is not None:
        govde_d["nonce"] = nonce
    govde = json.dumps(govde_d).encode()
    zaman = str(int(time.time()))
    return _istek(
        f"{site}/api/komut",
        "POST",
        govde,
        {
            "Content-Type": "application/json",
            _pano.ZAMAN_BASLIGI: zaman,
            _pano.IMZA_BASLIGI: _pano.imza_hesapla(ANAHTAR, zaman, govde),
        },
    )


def test_komut_cevabi_nonce_tasir_eski_programda_bos(site):  # noqa: F811
    nonce = "ab" * 16  # 32 küçük hex
    kod, _, govde = _yokla(site, nonce=nonce)
    assert kod == 200
    cevap = json.loads(govde)
    assert cevap["nonce"] == nonce
    assert cevap["alinan"] == [] and cevap["komutlar"] == []
    # Eski program nonce göndermez: site boş nonce ile cevap verir
    assert json.loads(_yokla(site)[2])["nonce"] == ""
    # Geçersiz nonce da boşa düşer
    assert json.loads(_yokla(site, nonce="KISA")[2])["nonce"] == ""


# ------------------------------------------------------ ağır işin HTTP yolu


def _post(site, yol, govde, cerez, koken=None):  # noqa: F811
    basliklar = {"Content-Type": "application/json", "Cookie": cerez}
    if koken:
        basliklar["Origin"] = koken
    return _istek(f"{site}{yol}", "POST", json.dumps(govde).encode(), basliklar)


def test_yeniden_baslat_onay_sifresi_ister(site):  # noqa: F811
    from test_uctan_uca import RAPOR, SIFRE, _cerez, _giris, _rapor_gonder

    _rapor_gonder(
        site,
        {
            **RAPOR,
            "yonetim": {
                "acik": True,
                "isler": ["teshis", "yeniden_baslat", "guncelle"],
                "kurulum": "git",
                "yeniden_baslatma": {"mumkun": True, "sebep": ""},
                "guncelleme": {"mumkun": True, "sebep": ""},
            },
        },
    )
    cerez = _cerez(_giris(site)[1])  # kurucu = yönetici
    # Şifresiz ağır iş: 400 onay_sifresi
    kod, _, govde = _post(site, "/api/mudahale", {"tur": "yeniden_baslat"}, cerez, site)
    assert kod == 400 and json.loads(govde)["hata"] == "onay_sifresi"
    # Doğru şifre (kurucu = PANO_SIFRESI): komut kuyruğa girer
    kod, _, govde = _post(
        site, "/api/mudahale", {"tur": "yeniden_baslat", "sifre": SIFRE}, cerez, site
    )
    assert kod == 200 and json.loads(govde)["komut"]["tur"] == "yeniden_baslat"
    # İkinci ağır iş kilide takılır
    kod, _, govde = _post(site, "/api/mudahale", {"tur": "guncelle", "sifre": SIFRE}, cerez, site)
    assert kod == 409 and json.loads(govde)["hata"] == "agir_suruyor"
