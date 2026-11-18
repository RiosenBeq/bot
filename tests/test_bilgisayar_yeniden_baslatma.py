"""Bilgisayarı yeniden başlatma (sahibinin kararı 18.11.2026; DALSAN docs/19 §4.9).

Yönetim ekranında "Yeniden başlat"ın yanında ikinci ağır iş: fabrika
bilgisayarını (Windows) yeniden başlatmak. Programı yeniden başlatmanın kurallarıyla
aynı: yalnız Yönetici (bu yetki başka role hiç verilemez), onay şifresi, tek ağır
iş kilidi ve saatte 3 ağır iş penceresi (yeniden başlatma ve güncellemeyle
birlikte), raporda "yapılabilir mi" kapısı ve sebebi. Komut fabrikaya türünden
başka alan taşımaz.
"""

import json

import _pano
import pytest
from _pano import PanoHatasi
from test_hesap import _hazir_cerez, _kurucu, _post
from test_uctan_uca import RAPOR, SIFRE, _istek, _rapor_gonder, site  # noqa: F401
from test_yetki import _yetki_yaz

IS = "bilgisayari_yeniden_baslat"
YETKI = "komut." + IS
YON = {"ad": "kurucu", "rol": "yonetici"}
OTURUM_KAPALI = (
    "Windows otomatik oturum açmıyor; bilgisayar yeniden başlarsa program açılmaz. "
    "Kontrol Paneli > Bakım > Fabrika bilgisayarını hazırla ile kurun."
)


def _yonetim(mumkun=True, sebep="", isler=("teshis", "yeniden_baslat", "guncelle", IS)):
    return {
        "acik": True,
        "isler": list(isler),
        "kurulum": "paket",
        "yeniden_baslatma": {"mumkun": True, "sebep": ""},
        "guncelleme": {"mumkun": True, "sebep": ""},
        "bilgisayar_yeniden_baslatma": {"mumkun": mumkun, "sebep": sebep},
    }


def _veri(yonetim):
    return {"baglanti": "canli", "rapor": {"yonetim": yonetim}}


def _bitir(depo, kimlik, simdi):
    _pano.sonuclari_yaz(depo, [{"id": kimlik, "durum": "yapildi", "mesaj": "tamam"}], simdi)


# ------------------------------------------------------------------ tablolar


def test_tur_yonetici_isi_ve_agir_is():
    assert IS in _pano.KOMUT_TURLERI
    assert _pano.KOMUT_EN_AZ_ROL[IS] == "yonetici"
    assert IS in _pano.YONETIM_TURLERI and IS in _pano.AGIR_TURLERI


def test_sonuc_beklemesi_acilis_ve_saglik_penceresini_kapsar():
    """Bilgisayarın açılışı + programın 180 sn açılışı + 300 sn sağlık penceresi
    + 120 sn kararlılık: programı yeniden başlatmanın 600 sn'si yetmez."""
    assert _pano.SONUC_BEKLEME[IS] == 1200
    assert _pano.SONUC_BEKLEME[IS] > _pano.SONUC_BEKLEME["yeniden_baslat"]


# ------------------------------------------------------------- komut kapıları


def test_yapilabilirse_kuyruga_girer_ozeti_turkce():
    depo = _pano.BellekDepo(lambda: 1000.0)
    komut = _pano.komut_olustur(depo, _veri(_yonetim()), {"tur": IS}, 1000, YON)
    assert komut["tur"] == IS and komut["durum"] == "bekliyor"
    assert komut["ozet"] == "Bilgisayarı yeniden başlatma"


def test_fabrika_yapilamaz_derse_sebebi_soylenir():
    depo = _pano.BellekDepo(lambda: 1000.0)
    with pytest.raises(PanoHatasi) as e:
        _pano.komut_olustur(depo, _veri(_yonetim(False, OTURUM_KAPALI)), {"tur": IS}, 1000, YON)
    assert (e.value.kod, e.value.hata, e.value.mesaj) == (409, "yapilamaz", OTURUM_KAPALI)
    assert depo.komut("LLEN", _pano.KOMUT_SIRA_ANAHTARI) == 0
    # Kilit alınmadı, pencere saymadı
    assert depo.al_coklu([_pano.AGIR_KILIT_ANAHTARI]) == [None]


def test_isi_bilmeyen_program_ve_kapali_yonetim():
    depo = _pano.BellekDepo(lambda: 1000.0)
    eski = _yonetim(isler=("teshis", "yeniden_baslat", "guncelle"))
    with pytest.raises(PanoHatasi) as e:
        _pano.komut_olustur(depo, _veri(eski), {"tur": IS}, 1000, YON)
    assert (e.value.kod, e.value.hata) == (409, "is_desteklenmiyor")
    with pytest.raises(PanoHatasi) as e:
        _pano.komut_olustur(depo, _veri({**_yonetim(), "acik": False}), {"tur": IS}, 1000, YON)
    assert (e.value.kod, e.value.hata) == (409, "yonetim_kapali")


@pytest.mark.parametrize("ilk, ikinci", [("guncelle", IS), (IS, "yeniden_baslat")])
def test_tek_agir_is_kilidini_paylasir(ilk, ikinci):
    depo = _pano.BellekDepo(lambda: 1000.0)
    _pano.komut_olustur(depo, _veri(_yonetim()), {"tur": ilk}, 1000, YON)
    with pytest.raises(PanoHatasi) as e:
        _pano.komut_olustur(depo, _veri(_yonetim()), {"tur": ikinci}, 1000, YON)
    assert (e.value.kod, e.value.hata) == (409, "agir_suruyor")


def test_saatte_uc_agir_is_penceresine_birlikte_sayilir():
    saat = [1000.0]
    depo = _pano.BellekDepo(lambda: saat[0])
    for tur in ("guncelle", "yeniden_baslat", IS):
        k = _pano.komut_olustur(depo, _veri(_yonetim()), {"tur": tur}, saat[0], YON)
        _bitir(depo, k["id"], saat[0] + 1)
        saat[0] += 10
    with pytest.raises(PanoHatasi) as e:
        _pano.komut_olustur(depo, _veri(_yonetim()), {"tur": IS}, saat[0], YON)
    assert (e.value.kod, e.value.hata) == (429, "cok_sik")


def test_fabrikaya_turunden_baska_alan_gitmez():
    ham = {
        "id": "eb1b2c3d4e5f6071",
        "tur": IS,
        "son_gecerlilik": 1793450120,
        "kim": {"ad": "mehmet", "rol": "yonetici"},
        "komut": "format c:",  # sahte alan: geçmez
        "gecikme": 0,
    }
    assert _pano._komut_yuku(json.dumps(ham)) == {
        "id": "eb1b2c3d4e5f6071",
        "tur": IS,
        "son_gecerlilik": 1793450120,
        "kim": {"ad": "mehmet", "rol": "yonetici"},
    }


# ------------------------------------------------------------- rapor kapısı


def test_rapor_kapisi_okunur_eski_programda_kapali():
    temiz = _pano.rapor_temizle({**RAPOR, "yonetim": _yonetim(False, "x" * 300)})
    kapi = temiz["yonetim"]["bilgisayar_yeniden_baslatma"]
    assert kapi["mumkun"] is False and len(kapi["sebep"]) <= 200
    assert IS in temiz["yonetim"]["isler"]
    eski = _pano.rapor_temizle({**RAPOR, "yonetim": {"acik": True, "isler": ["teshis"]}})
    assert eski["yonetim"]["bilgisayar_yeniden_baslatma"] == {"mumkun": False, "sebep": ""}
    assert IS not in eski["yonetim"]["isler"]


# ------------------------------------------------------------------ yetki


def test_yetki_yalniz_yoneticinin():
    v = _pano.VARSAYILAN_YETKILER
    assert YETKI in v["yonetici"]
    assert YETKI not in v["operator"] and YETKI not in v["izleyici"]
    assert _pano.YETKI_ADLARI[YETKI] == "Bilgisayarı yeniden başlatma"
    d = _pano.yetki_kumesi_duzelt
    # Başka role hiç verilemez
    assert YETKI not in d(["komut.anons", YETKI], "operator")
    assert YETKI not in d([YETKI, "ekran.yonetim"], "izleyici")
    # Yöneticiden kurucu alabilir (zorla verilmez)
    assert YETKI not in d(["komut.teshis"], "yonetici")
    assert YETKI in d([YETKI], "yonetici")
    assert _pano.yetki_gorunumu(_pano.BellekDepo())["yalniz_yonetici"] == [YETKI]


def test_operator_bilgisayari_yeniden_baslatamaz_kurucu_verse_de(site):  # noqa: F811
    cerez = _kurucu(site)
    opr = _hazir_cerez(site, cerez, "opr", "operator", "parola-opr-123", "opr-yeni-1234")
    _rapor_gonder(site, {**RAPOR, "yonetim": _yonetim()})
    varsayilan = sorted(_pano.VARSAYILAN_YETKILER["operator"])
    kod, _, govde = _yetki_yaz(site, cerez, {"operator": [*varsayilan, "ekran.yonetim", YETKI]})
    assert kod == 200, govde
    kod, _, govde = _istek(f"{site}/api/hesap", basliklar={"Cookie": cerez})
    roller = {r["id"]: r["yetkiler"] for r in json.loads(govde)["yetki"]["roller"]}
    assert YETKI not in roller["operator"] and "ekran.yonetim" in roller["operator"]
    kod, _, govde = _post(site, "/api/mudahale", {"tur": IS, "sifre": "opr-yeni-1234"}, opr, site)
    assert kod == 403 and json.loads(govde)["hata"] == "yetki", govde


def test_onay_sifresi_ister_kurucu_ile_kuyruga_girer(site):  # noqa: F811
    cerez = _kurucu(site)
    _rapor_gonder(site, {**RAPOR, "yonetim": _yonetim()})
    kod, _, govde = _post(site, "/api/mudahale", {"tur": IS}, cerez, site)
    assert kod == 400 and json.loads(govde)["hata"] == "onay_sifresi"
    kod, _, govde = _post(site, "/api/mudahale", {"tur": IS, "sifre": "yanlis-sifre"}, cerez, site)
    assert kod == 400 and json.loads(govde)["hata"] == "onay_sifresi"
    kod, _, govde = _post(site, "/api/mudahale", {"tur": IS, "sifre": SIFRE}, cerez, site)
    assert kod == 200, govde
    komut = json.loads(govde)["komut"]
    assert (komut["tur"], komut["ozet"]) == (IS, "Bilgisayarı yeniden başlatma")
