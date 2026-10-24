"""Gerçek HTTP ile: yerel sunucu api/*.py dosyalarını Vercel'deki gibi çalıştırır."""

import json
import time
import urllib.error
import urllib.request

import _pano
import pytest

import yerel_sunucu

ANAHTAR = "a" * 40
SIFRE = "uctan-uca-sifresi"


@pytest.fixture
def site(monkeypatch):
    monkeypatch.setenv("PANO_SIFRESI", SIFRE)
    monkeypatch.setenv("RAPOR_ANAHTARI", ANAHTAR)
    monkeypatch.setenv("FABRIKA_ADRESI", "http://100.64.0.7:8080")
    sunucu = yerel_sunucu.sunucu_olustur(port=0)
    yerel_sunucu.arka_planda_baslat(sunucu)
    yield f"http://127.0.0.1:{sunucu.server_address[1]}"
    sunucu.shutdown()
    sunucu.server_close()
    _pano.DEPO = None


def _istek(adres, yontem="GET", govde=None, basliklar=None):
    istek = urllib.request.Request(adres, data=govde, method=yontem, headers=basliklar or {})
    try:
        with urllib.request.urlopen(istek, timeout=5) as yanit:
            return yanit.status, dict(yanit.headers), yanit.read()
    except urllib.error.HTTPError as hata:
        return hata.code, dict(hata.headers), hata.read()


def _rapor_gonder(site, rapor, anahtar=ANAHTAR, zaman=None):
    govde = json.dumps(rapor).encode()
    zaman = str(int(time.time()) if zaman is None else zaman)
    return _istek(
        f"{site}/api/rapor",
        "POST",
        govde,
        {
            "Content-Type": "application/json",
            _pano.ZAMAN_BASLIGI: zaman,
            _pano.IMZA_BASLIGI: _pano.imza_hesapla(anahtar, zaman, govde),
        },
    )


def _giris(site, sifre=SIFRE):
    return _istek(
        f"{site}/api/giris",
        "POST",
        json.dumps({"sifre": sifre}).encode(),
        {"Content-Type": "application/json"},
    )


def _cerez(basliklar) -> str:
    return basliklar["Set-Cookie"].split(";")[0]


RAPOR = {
    "surum": 1,
    "uretildi": "2026-10-24T10:00:00+03:00",
    "aralik_sn": 30,
    "sistem": {"analiz": True, "hazir": True, "sorunlar": ["Analiz takıldı"]},
    "kameralar": [{"ad": "Sevkiyat Rampası", "bolum": "Sevkiyat", "durum": "online"}],
    "sayilar": {"bugun_ihlal": 4},
}


def test_rapor_giris_ve_pano_akisi(site):
    kod, _, govde = _rapor_gonder(site, RAPOR)
    assert kod == 200, govde
    assert json.loads(govde)["tamam"] is True

    kod, _, govde = _istek(f"{site}/api/durum")
    assert kod == 401
    assert json.loads(govde)["hata"] == "giris_gerekli"

    kod, _, _ = _giris(site, "yanlis-sifre")
    assert kod == 401

    kod, basliklar, _ = _giris(site)
    assert kod == 200
    cerez_satiri = basliklar["Set-Cookie"]
    assert "HttpOnly" in cerez_satiri and "Secure" in cerez_satiri
    assert "SameSite=Strict" in cerez_satiri

    kod, basliklar, govde = _istek(f"{site}/api/durum", basliklar={"Cookie": _cerez(basliklar)})
    assert kod == 200
    assert basliklar["Cache-Control"] == "no-store"
    veri = json.loads(govde)
    assert veri["baglanti"] == "canli"
    assert veri["rapor"]["kameralar"][0]["ad"] == "Sevkiyat Rampası"
    assert veri["rapor"]["sistem"]["sorunlar"] == ["Analiz takıldı"]
    assert veri["fabrika_adresi"] == "http://100.64.0.7:8080"


def test_yanlis_anahtarla_rapor_reddedilir_ve_saklanmaz(site):
    kod, _, govde = _rapor_gonder(site, RAPOR, anahtar="b" * 40)
    assert kod == 401
    assert json.loads(govde)["hata"] == "imza_gecersiz"
    assert _pano.DEPO.al_coklu([_pano.DURUM_ANAHTARI]) == [None]


def test_imzasiz_ve_eski_rapor_reddedilir(site):
    govde = json.dumps(RAPOR).encode()
    kod, _, _ = _istek(f"{site}/api/rapor", "POST", govde, {"Content-Type": "application/json"})
    assert kod == 401
    kod, _, govde = _rapor_gonder(site, RAPOR, zaman=int(time.time()) - 3600)
    assert kod == 401
    assert json.loads(govde)["hata"] == "saat_farki"


def test_cok_buyuk_rapor_okunmadan_reddedilir(site):
    rapor = dict(RAPOR, dolgu="x" * (_pano.RAPOR_EN_BUYUK_BAYT + 1))
    kod, _, govde = _rapor_gonder(site, rapor)
    assert kod == 413
    assert json.loads(govde)["hata"] == "cok_buyuk"


def test_giris_yalniz_json_kabul_eder(site):
    """Başka bir sitedeki düz form, application/json gönderemez."""
    kod, _, govde = _istek(
        f"{site}/api/giris",
        "POST",
        f"sifre={SIFRE}".encode(),
        {"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert kod == 415
    assert json.loads(govde)["hata"] == "icerik_turu"


def test_cikis_cerezi_siler(site):
    kod, basliklar, _ = _istek(
        f"{site}/api/cikis", "POST", b"{}", {"Content-Type": "application/json"}
    )
    assert kod == 200
    assert basliklar["Set-Cookie"].startswith(f"{_pano.CEREZ_ADI}=;")
    assert "Max-Age=0" in basliklar["Set-Cookie"]


def test_yanlis_yontem_405(site):
    kod, _, govde = _istek(f"{site}/api/rapor")
    assert kod == 405
    assert json.loads(govde)["hata"] == "yontem"
    kod, _, _ = _istek(f"{site}/api/durum", "POST", b"{}")
    assert kod == 405


def test_kurulum_eksikse_ne_eksik_oldugu_soylenir(site, monkeypatch):
    monkeypatch.delenv("PANO_SIFRESI")
    kod, _, govde = _istek(f"{site}/api/durum")
    assert kod == 503
    veri = json.loads(govde)
    assert veri["hata"] == "kurulum_eksik"
    assert [e["ad"] for e in veri["eksikler"]] == ["PANO_SIFRESI"]


def test_sayfalar_guvenlik_basligiyla_sunulur(site):
    for yol in ("/", "/pano"):
        kod, basliklar, govde = _istek(f"{site}{yol}")
        assert kod == 200, yol
        assert basliklar["Content-Type"].startswith("text/html")
        assert "script-src 'self'" in basliklar["Content-Security-Policy"]
        assert basliklar["X-Frame-Options"] == "DENY"
        assert b"<html" in govde


def test_public_disina_cikilamaz(site):
    for yol in ("/../api/_pano.py", "/%2e%2e/vercel.json", "/api/_pano"):
        kod, _, govde = _istek(f"{site}{yol}")
        assert kod == 404, yol
        assert b"PANO_SIFRESI" not in govde
