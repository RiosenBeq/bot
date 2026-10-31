"""İki depo arası sözleşme (docs/19 §12): tests/sozlesme/*.json örnekleri.

Bu dosyalar iki depoda birebir aynıdır (DALSAN'dan kopyalanır); DÜZENLENMEZ.
Site tarafı: _komut_yuku çıktısı teslim edilen komut biçimiyle, rapor_temizle
yeni alanlarla ve sonuclari_yaz sonuç biçimiyle uyar.
"""

import json
from pathlib import Path

import _pano

SOZLESME = Path(__file__).resolve().parent / "sozlesme"


def _yukle(ad: str) -> dict:
    return json.loads((SOZLESME / ad).read_text(encoding="utf-8"))


def test_teslim_edilen_komutlar_alan_alan_okunur():
    """Her türden komut (docs/19 §3.7): _komut_yuku kalan_sn dışındaki her alanı
    aynen üretir; başka alan geçmez."""
    for komut in _yukle("komutlar.json")["komutlar"]:
        beklenen = {k: v for k, v in komut.items() if k != "kalan_sn"}
        assert _pano._komut_yuku(json.dumps(komut)) == beklenen


def test_bilinmeyen_tur_ve_rol_komutu_okunmaz():
    """Sözleşmedeki reddedilen örneklerden türü/rolü site de tanımaz."""
    for oge in _yukle("komutlar.json")["reddedilenler"]:
        komut = oge["komut"]
        yuk = _pano._komut_yuku(json.dumps(komut))
        if oge["neden"] == "bilinmeyen tür":
            assert yuk is None
        elif oge["neden"] == "bilinmeyen rol":
            # tür tanınır ama rol boşa düşer (teslimde yetkisiz sayılır)
            assert yuk is not None and yuk["kim"]["rol"] == ""


def test_yeni_rapor_yeni_alanlarla_temizlenir():
    rapor = _yukle("rapor.json")["rapor"]
    temiz = _pano.rapor_temizle(rapor)
    assert temiz["program"]["yapi"]["commit"] == "0123456789abcdef0123456789abcdef01234567"
    assert temiz["program"]["yapi"]["calistirma"] == 123
    durumlar = [o["durum"] for o in temiz["son_olaylar"]]
    assert durumlar == ["new", "reviewed", ""]  # sistem olayında durum yok
    assert temiz["mudahale"]["isler"] == ["anons", "ses_dene", "olay_incele"]
    assert temiz["yonetim"]["acik"] is True
    assert temiz["yonetim"]["isler"] == ["teshis", "yeniden_baslat", "guncelle"]
    assert temiz["yonetim"]["kurulum"] == "paket"
    assert temiz["yonetim"]["yeniden_baslatma"]["mumkun"] is True
    assert temiz["yonetim"]["guncelleme"]["mumkun"] is False
    assert temiz["kapanis_sebebi"] == ""


def test_eski_rapor_guvenli_varsayilanlara_duser():
    rapor = _yukle("rapor-eski.json")["rapor"]
    temiz = _pano.rapor_temizle(rapor)
    assert temiz["program"]["yapi"] == {"commit": "", "tarih": "", "calistirma": 0}
    # son_olaylar[].durum yok -> "" (inceleme düğmesi çıkmaz)
    assert all(o["durum"] == "" for o in temiz["son_olaylar"])
    # mudahale.acik True ama isler gelmez -> bugünkü iki iş varsayılır
    assert temiz["mudahale"]["isler"] == ["anons", "ses_dene"]
    # yonetim hiç gelmez -> her şey kapalı
    assert temiz["yonetim"] == {
        "acik": False,
        "isler": [],
        "kurulum": "",
        "yeniden_baslatma": {"mumkun": False, "sebep": ""},
        "guncelleme": {"mumkun": False, "sebep": ""},
    }


def test_sonuclar_ornegi_yazilir_ve_onaylanir():
    """sonuclar.json'daki id'ler için komut kaydı kurulur; sonuçlar yazılır ve
    hepsi 'alinan'da döner (docs/19 §3.7)."""
    ornek = _yukle("sonuclar.json")["sonuclar"]
    depo = _pano.BellekDepo()
    for s in ornek:
        kayit = {"id": s["id"], "tur": "teshis", "durum": "iletildi", "guncellendi": 0}
        depo.boru_hatti([["SET", _pano.KOMUT_KAYIT_ONEKI + s["id"], json.dumps(kayit)]])
    alinan = _pano.sonuclari_yaz(depo, ornek, 1000)
    assert set(alinan) == {s["id"] for s in ornek}
    # Teşhis ek metni süzülerek kayda yazılır (adres maskeli)
    tanili = next(s for s in ornek if "ek" in s)
    (ham,) = depo.al_coklu([_pano.KOMUT_KAYIT_ONEKI + tanili["id"]])
    yazilan = json.loads(ham)
    assert "(adres)" in yazilan["ek"]


def test_komut_cevabi_nonce_ve_alinan_tasir():
    cevap = _yukle("komut-cevabi.json")["cevap"]
    assert set(cevap) >= {"tamam", "nonce", "alinan", "komutlar", "hizli"}
    istek = _yukle("komut-sorusu.json")["istek"]
    assert cevap["nonce"] == istek["nonce"]  # cevap istekteki nonce'u taşır
