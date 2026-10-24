"""Görüntü (fabrika içi kullanım kararı, 24.10.2026): kanıt fotoğrafı ve anlık görüntü.

Fabrika imzalı gönderir; pano yalnız oturumla görür. JPEG olmayan içerik ve
sınırı aşan görüntü depoya girmez. Hangi olayın fotoğrafı olduğunu site
kendisi tutar ve fabrikaya söyler; fotoğraf sayısı sınırlıdır. Anlık görüntü
yalnız Kameralar ekranı açıkken istenir.
"""

import base64
import json
import time

import _pano
from test_uctan_uca import ANAHTAR, RAPOR, _cerez, _giris, _istek, _rapor_gonder, site  # noqa: F401

JPEG = b"\xff\xd8\xff\xe0" + b"\x10JFIF" + bytes(range(256)) * 4 + b"\xff\xd9"
RAPOR_KAMERALI = {
    **RAPOR,
    "kameralar": [
        {"id": 4, "ad": "Sevkiyat Rampası", "bolum": "Sevkiyat", "durum": "online"},
        {"id": 5, "ad": "Depo Girişi", "bolum": "Depo", "durum": "online"},
    ],
    "son_olaylar": [
        {"id": 123, "tur": "ihlal", "baslik": "Baret yok"},
        {"id": 122, "tur": "ihlal", "baslik": "Yelek yok"},
    ],
}


def _imzali(adres, yol, govde_sozluk, anahtar=ANAHTAR):
    govde = json.dumps(govde_sozluk).encode()
    zaman = str(int(time.time()))
    return _istek(
        f"{adres}{yol}",
        "POST",
        govde,
        {
            "Content-Type": "application/json",
            _pano.ZAMAN_BASLIGI: zaman,
            _pano.IMZA_BASLIGI: _pano.imza_hesapla(anahtar, zaman, govde),
        },
    )


def _b64(veri: bytes) -> str:
    return base64.b64encode(veri).decode()


def _foto_yolla(site, olay_id):  # noqa: F811
    govde = {"surum": 1, "olay_id": olay_id, "jpeg": _b64(JPEG)}
    kod, _, cevap = _imzali(site, "/api/foto", govde)
    assert kod == 200, cevap


def _olaylar(site, cerez):  # noqa: F811
    kod, _, govde = _istek(f"{site}/api/durum", basliklar={"Cookie": cerez})
    assert kod == 200
    return {o["id"]: o["foto"] for o in json.loads(govde)["rapor"]["son_olaylar"]}


def test_kanit_fotografi_yuklenir_ve_yalniz_oturumla_gorulur(site):  # noqa: F811
    # Fotoğraf gelmeden: rapor cevabı "hiçbiri bende yok" der, pano göstermez
    kod, _, govde = _rapor_gonder(site, RAPOR_KAMERALI)
    assert json.loads(govde)["foto"] == {"var": []}
    cerez = _cerez(_giris(site)[1])
    assert _olaylar(site, cerez) == {123: False, 122: False}

    _foto_yolla(site, 123)

    kod, _, _ = _istek(f"{site}/api/foto?olay=123")
    assert kod == 401
    kod, basliklar, veri = _istek(f"{site}/api/foto?olay=123", basliklar={"Cookie": cerez})
    assert kod == 200
    assert basliklar["Content-Type"] == "image/jpeg"
    assert basliklar["X-Content-Type-Options"] == "nosniff"
    assert basliklar["Cache-Control"].startswith("private")
    assert veri == JPEG
    assert _istek(f"{site}/api/foto?olay=999", basliklar={"Cookie": cerez})[0] == 404
    assert _istek(f"{site}/api/foto?olay=../x", basliklar={"Cookie": cerez})[0] == 400

    # Pano hangi olayın fotoğrafı olduğunu bilir; fabrika aynısını yeniden göndermez
    assert _olaylar(site, cerez) == {123: True, 122: False}
    kod, _, govde = _rapor_gonder(site, RAPOR_KAMERALI)
    assert json.loads(govde)["foto"] == {"var": [123]}


def test_fotograf_sayisi_sinirlidir_tasan_silinir(site, monkeypatch):  # noqa: F811
    monkeypatch.setattr(_pano, "FOTO_EN_COK", 3)
    for olay_id in (1, 2, 3, 4, 5):
        _foto_yolla(site, olay_id)
    anahtar = _pano.FOTO_ONEKI
    var = [_pano.DEPO.al_coklu([anahtar + str(k)])[0] is not None for k in (1, 2, 3, 4, 5)]
    assert var == [False, False, True, True, True]
    # Yeniden gelen fotoğraf öne geçer, iki kez yazılmaz
    _foto_yolla(site, 3)
    (ham,) = _pano.DEPO.al_coklu([_pano.FOTO_LISTESI_ANAHTARI])
    assert [k for k, _ in _pano.foto_listesi(ham, time.time())] == [3, 5, 4]


def test_foto_listesi_suresi_dolani_ve_bozugu_atar():
    simdi = 10_000_000
    eski = simdi - _pano.FOTO_SAKLAMA_SN
    ham = json.dumps(
        [[7, simdi], [6, eski], ["5", simdi], [True, simdi], [4, 1.5], [3], 9, [2, simdi]]
    )
    assert _pano.foto_listesi(ham, simdi) == [(7, simdi), (2, simdi)]
    assert _pano.foto_listesi("bozuk{", simdi) == []
    assert _pano.foto_listesi(None, simdi) == []


def test_gecersiz_goruntu_depoya_girmez(site):  # noqa: F811
    yol = "/api/foto"
    imzasiz = _istek(
        f"{site}{yol}",
        "POST",
        json.dumps({"surum": 1, "olay_id": 1, "jpeg": _b64(JPEG)}).encode(),
        {"Content-Type": "application/json"},
    )
    assert imzasiz[0] == 401
    yanlis = _imzali(site, yol, {"surum": 1, "olay_id": 1, "jpeg": _b64(JPEG)}, anahtar="b" * 40)
    assert yanlis[0] == 401
    html = _b64(b"<html><script>alert(1)</script></html>")
    assert _imzali(site, yol, {"surum": 1, "olay_id": 1, "jpeg": html})[0] == 400
    assert _imzali(site, yol, {"surum": 1, "olay_id": 1, "jpeg": "base64 değil!"})[0] == 400
    assert _imzali(site, yol, {"surum": 1, "jpeg": _b64(JPEG)})[0] == 400
    buyuk = JPEG[:3] + bytes(_pano.FOTO_EN_BUYUK_BAYT)
    kod, _, govde = _imzali(site, yol, {"surum": 1, "olay_id": 1, "jpeg": _b64(buyuk)})
    assert kod == 413 and "küçültüp" in json.loads(govde)["mesaj"]
    assert _pano.DEPO.al_coklu([_pano.FOTO_ONEKI + "1"]) == [None]


def test_anlik_goruntu_yalniz_kameralar_ekrani_acikken_istenir(site):  # noqa: F811
    kod, _, govde = _rapor_gonder(site, RAPOR_KAMERALI)
    assert json.loads(govde)["kare"] == {"iste": False}
    kod, _, govde = _imzali(site, "/api/kare", {"surum": 1, "kamera_id": 4, "jpeg": _b64(JPEG)})
    assert kod == 200 and json.loads(govde)["iste"] is False

    cerez = _cerez(_giris(site)[1])
    kod, _, govde = _istek(f"{site}/api/durum?kare=1", basliklar={"Cookie": cerez})
    assert json.loads(govde)["kareler"] == {"4": json.loads(govde)["kareler"]["4"]}
    # Kameralar ekranı açıldı: rapor ve görüntü cevabı "gönder" der
    assert json.loads(_rapor_gonder(site, RAPOR_KAMERALI)[2])["kare"] == {"iste": True}
    kod, _, govde = _imzali(site, "/api/kare", {"surum": 1, "kamera_id": 5, "jpeg": _b64(JPEG)})
    assert kod == 200 and json.loads(govde)["iste"] is True

    kod, _, govde = _istek(f"{site}/api/durum?kare=1", basliklar={"Cookie": cerez})
    kareler = json.loads(govde)["kareler"]
    assert set(kareler) == {"4", "5"} and kareler["5"].endswith("+00:00")
    kod, basliklar, veri = _istek(f"{site}/api/kare?kamera=5", basliklar={"Cookie": cerez})
    assert kod == 200 and veri == JPEG and basliklar["Cache-Control"] == "no-store"
    assert _istek(f"{site}/api/kare?kamera=5")[0] == 401
    assert _istek(f"{site}/api/kare?kamera=6", basliklar={"Cookie": cerez})[0] == 404


def test_anlik_goruntu_iki_dakikada_silinir():
    simdi = [1000.0]
    depo = _pano.BellekDepo(lambda: simdi[0])
    depo.boru_hatti(
        [
            ["SET", _pano.KARE_ONEKI + "4", _b64(JPEG), "EX", str(_pano.KARE_SAKLAMA_SN)],
            ["SET", _pano.KARE_ZAMAN_ONEKI + "4", "z", "EX", str(_pano.KARE_SAKLAMA_SN)],
        ]
    )
    rapor = {"kameralar": [{"id": 4}, {"id": None}, "bozuk"]}
    assert _pano.kare_zamanlari(depo, rapor) == {"4": "z"}
    simdi[0] += _pano.KARE_SAKLAMA_SN
    assert _pano.kare_zamanlari(depo, rapor) == {}
    assert _pano.kare_zamanlari(depo, None) == {}


def test_sistem_olayinin_ayrintisi_ve_kamera_kimligi_suzulur():
    temiz = _pano.rapor_temizle(
        {
            **RAPOR,
            "kameralar": [{"id": True, "ad": "A"}, {"id": 4, "ad": "B"}],
            "son_olaylar": [
                {
                    "id": "12",
                    "foto": "evet",
                    "tur": "sistem",
                    "baslik": "Kamera çevrimdışı",
                    "ayrinti": "Kameraya ulaşılamıyor\n(192.168.1.30:554)",
                }
            ],
        }
    )
    assert [k["id"] for k in temiz["kameralar"]] == [None, 4]
    olay = temiz["son_olaylar"][0]
    # "foto" fabrikadan okunmaz: sitede fotoğraf olup olmadığını site bilir
    assert (olay["id"], olay["foto"]) == (None, False)
    assert olay["ayrinti"] == "Kameraya ulaşılamıyor (192.168.1.30:554)"
