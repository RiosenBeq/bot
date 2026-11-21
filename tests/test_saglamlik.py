"""Sunucu sağlamlığı ve güvenlik maddeleri (SONRA-YAPILACAKLAR, 20.11.2026).

İşlem kaydı satırı değişiklikle aynı istekte; yetki reddi kendi listesinde ve
görünümden itilemez; oturumlu GET tek okuma; scrypt girişte yeniden özetlenir;
bekçi anahtarının yanlış denemesi sınırlı; cihaz çerezi ad ve genel kilitten
muaf; istek başına JSON günlük satırı; imzalı fabrika isteği tekrar edilemez.
"""

import json
import time
import urllib.request

import _pano
import pytest
from test_goruntu import JPEG, _b64
from test_hesap import _ayar, _ekle, _hesap, _post, _yaz_hesap
from test_uctan_uca import (  # noqa: F401
    ANAHTAR,
    RAPOR,
    SIFRE,
    _cerez,
    _giris,
    _istek,
    _rapor_gonder,
    imza_damgasi,
    site,
)

T0 = 1_800_000_000


def _istekleri_kaydet(depo) -> list:
    """Depoya giden her isteği (tek komut da, boru hattı da bir istek) komut
    listesi olarak kaydeder."""
    istekler = []
    boru, komut = depo.boru_hatti, depo.komut

    def kayitli_boru(komutlar):
        istekler.append([[str(p) for p in k] for k in komutlar])
        return boru(komutlar)

    def kayitli_komut(*parcalar):
        istekler.append([[str(p) for p in parcalar]])
        return komut(*parcalar)

    depo.boru_hatti, depo.komut = kayitli_boru, kayitli_komut
    return istekler


def _yazan_istek(istekler, anahtar):
    """`anahtar`ı yazan (SET/DEL) isteğin komutları."""
    for istek in istekler:
        if any(k[0] in ("SET", "DEL") and k[1] == anahtar for k in istek):
            return istek
    raise AssertionError(f"{anahtar} yazılmadı")


def _kayit_satiri_var(istek, liste=_pano.KAYIT_ANAHTARI):
    return any(k[0] == "LPUSH" and k[1] == liste for k in istek)


# ------------------------------------------- işlem kaydı aynı boru hattında


def test_hesap_degisikligi_ve_kayit_satiri_tek_istekte(site):  # noqa: F811
    cerez = _cerez(_giris(site)[1])
    istekler = _istekleri_kaydet(_pano.DEPO)
    anahtar = _pano.KULLANICI_ONEKI + "ayse"
    assert _ekle(site, cerez, "ayse", "operator", "ilk-parola-123")[0] == 200
    assert _kayit_satiri_var(_yazan_istek(istekler, anahtar))
    for eylem in (
        {"eylem": "rol", "rol": "izleyici"},
        {"eylem": "sifre_sifirla", "yeni_sifre": "yeni-parola-456"},
        {"eylem": "kapat"},
        {"eylem": "ac"},
        {"eylem": "sil"},
    ):
        istekler.clear()
        kod, _, govde = _post(site, "/api/hesap", {**eylem, "ad": "ayse", "sifre": SIFRE}, cerez)
        assert kod == 200, govde
        assert _kayit_satiri_var(_yazan_istek(istekler, anahtar)), eylem
    istekler.clear()
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {"eylem": "rol_yetkileri", "yetkiler": {"izleyici": ["komut.anons"]}, "sifre": SIFRE},
        cerez,
    )
    assert kod == 200, govde
    assert _kayit_satiri_var(_yazan_istek(istekler, _pano.ROL_YETKILERI_ANAHTARI))


def test_upstash_hatasi_degisikligi_kayitsiz_birakmaz(site):  # noqa: F811
    """Kayıt satırını taşıyan istek düşerse değişiklik de yazılmamıştır: eskiden
    rol ayrı istekte yazılıyor, kayıt satırı sonraki istekte kaybolabiliyordu."""
    cerez = _cerez(_giris(site)[1])
    assert _ekle(site, cerez, "ayse", "operator", "ilk-parola-123")[0] == 200
    depo = _pano.DEPO
    boru = depo.boru_hatti

    def dusen_boru(komutlar):
        if any(k[0] == "LPUSH" and k[1] == _pano.KAYIT_ANAHTARI for k in komutlar):
            raise _pano.DepoHatasi("Upstash'e ulaşılamadı: deneme")
        return boru(komutlar)

    depo.boru_hatti = dusen_boru
    kod, _, govde = _post(
        site, "/api/hesap", {"eylem": "rol", "ad": "ayse", "rol": "izleyici", "sifre": SIFRE}, cerez
    )
    assert kod == 503 and json.loads(govde)["hata"] == "depo"
    assert _pano.hesap_oku(depo, "ayse")["rol"] == "operator"


# ------------------------------------------------ yetki reddi kendi listesinde


def test_ret_satirlari_basarili_girislerle_kayittan_itilemez():
    depo = _pano.BellekDepo()
    oturum = _pano.Oturum("ali", "izleyici", "1234567890abcdef", 1, False, False, "i", T0 + 99)
    _pano._komut_red_yaz(depo, oturum, "Yetki yetmedi: müdahale", T0)
    _pano.kayit_yaz(
        depo,
        _pano.KAYIT_GIRIS_ANAHTARI,
        _pano._islem_satiri(T0 + 1, "ali", "izleyici", "giris_hatali", "", "hata"),
        _pano.KAYIT_GIRIS_EN_COK,
    )
    # Kişi art arda başarılı giriş yapar: oturum listesi baştan sona dolar
    for sira in range(_pano.KAYIT_EN_COK + 20):
        _pano.kayit_yaz(
            depo,
            _pano.KAYIT_OTURUM_ANAHTARI,
            _pano._islem_satiri(T0 + 10 + sira, "ali", "izleyici", "giris", "", "tamam"),
            _pano.KAYIT_EN_COK,
        )
    kayitli = depo.komut("LRANGE", _pano.KAYIT_RED_ANAHTARI, "0", "-1")
    assert [json.loads(s)["is"] for s in kayitli] == ["komut_red"]
    gorunum = _pano.hesap_verisi(depo, T0 + 5000)["kayit"]
    isler = [satir["is"] for satir in gorunum]
    assert "komut_red" in isler and "giris_hatali" in isler
    assert sum(satir["sonuc"] == "tamam" for satir in gorunum) == _pano.KAYIT_BIRLESIK_EN_COK


# ----------------------------------------------------- oturumlu GET tek okuma


def test_oturumlu_durum_depoya_tek_istek_atar(site):  # noqa: F811
    """Ölçüm: eskiden oturum ve pano verisi iki ayrı MGET'ti (2 istek), şimdi 1."""
    assert _rapor_gonder(site, RAPOR)[0] == 200
    cerez = _cerez(_giris(site)[1])
    assert _ekle(site, cerez, "ayse", "operator", "ilk-parola-123")[0] == 200
    ayse = _cerez(_giris(site, "ilk-parola-123", ad="ayse")[1])
    istekler = _istekleri_kaydet(_pano.DEPO)
    for kim in (cerez, ayse):
        istekler.clear()
        kod, _, govde = _istek(f"{site}/api/durum", basliklar={"Cookie": kim})
        assert kod == 200 and json.loads(govde)["baglanti"] == "canli"
        assert len(istekler) == 1, istekler


# ------------------------------------------------------- scrypt yeniden özet


def test_yeni_ozet_daha_guclu_eski_ozet_gecerli_ve_giriste_yenilenir(monkeypatch):
    assert _pano.sifre_ozetle("bir-parola-123")["n"] == 2**15
    with monkeypatch.context() as m:
        m.setattr(_pano, "SCRYPT_N", 2**14)
        eski = _pano.sifre_ozetle("dogru-sifre-1")
    assert eski["n"] == 2**14 and _pano.sifre_dogrula(eski, "dogru-sifre-1")
    depo, ayar = _pano.BellekDepo(), _ayar()
    _yaz_hesap(depo, {**_hesap("ali", rol="izleyici", surum=7), "sifre": eski})
    # Yanlış şifre özete dokunmaz
    with pytest.raises(_pano.PanoHatasi):
        _pano.giris_dene(depo, ayar, "10.0.0.1", "ali", "yanlis-sifre", T0)
    assert _pano.hesap_oku(depo, "ali")["sifre"] == eski
    assert _pano.giris_dene(depo, ayar, "10.0.0.1", "ali", "dogru-sifre-1", T0)[2] == 7
    hesap = _pano.hesap_oku(depo, "ali")
    assert hesap["sifre"]["n"] == 2**15 and hesap["sifre"] != eski
    assert hesap["rol"] == "izleyici" and hesap["oturum_surumu"] == 7  # oturumlar düşmez
    assert not depo.komut("GET", _pano.KULLANICI_KILIT_ONEKI + "ali")  # kilit bırakıldı
    yeni = hesap["sifre"]
    assert _pano.giris_dene(depo, ayar, "10.0.0.1", "ali", "dogru-sifre-1", T0)[0] == "ali"
    assert _pano.hesap_oku(depo, "ali")["sifre"] == yeni  # ikinci kez özetlenmez


def test_yeniden_ozet_arada_degisen_sifreye_dokunmaz():
    depo = _pano.BellekDepo()
    _yaz_hesap(depo, _hesap("ali", sifre="yeni-sifre-2"))
    simdiki = _pano.hesap_oku(depo, "ali")["sifre"]
    _pano._sifre_yenile(depo, "ali", {"alg": "scrypt", "n": 2**14}, "eski-sifre-1")
    assert _pano.hesap_oku(depo, "ali")["sifre"] == simdiki


# ----------------------------------------------------- bekçi anahtarı sınırı


def test_bekci_yanlis_anahtari_adres_basina_sinirlanir(site, monkeypatch):  # noqa: F811
    monkeypatch.setenv("BEKCI_ANAHTARI", "bekci-gizli-anahtar-0123456789")
    adres = {"X-Real-IP": "203.0.113.5"}
    for _ in range(_pano.BEKCI_HATA_SINIRI):
        assert _istek(f"{site}/api/bekci?anahtar=yanlis", basliklar=adres)[0] == 403
    kod, _, govde = _istek(f"{site}/api/bekci?anahtar=yanlis", basliklar=adres)
    assert kod == 429 and json.loads(govde)["hata"] == "bekci_kilitli"
    # Kilitli adres doğru anahtarla da giremez: anahtar tahmin edilemez
    dogru = {"Authorization": "Bearer bekci-gizli-anahtar-0123456789"}
    assert _istek(f"{site}/api/bekci", basliklar={**adres, **dogru})[0] == 429
    # Başka adres (izleme servisi) etkilenmez
    kod, _, govde = _istek(f"{site}/api/bekci", basliklar={"X-Real-IP": "198.51.100.7", **dogru})
    assert kod == 200 and json.loads(govde) == {"atlandi": True}


# ----------------------------------------------------------------- cihaz çerezi


def _cihaz(ayar, ad, simdi=T0):
    return _pano.cihaz_cerezi_uret(ayar, ad, simdi).split(";")[0].split("=", 1)[1]


def _dene(depo, ayar, sira, ad, sifre, cihaz=""):
    return _pano.giris_dene(
        depo, ayar, f"10.1.{sira // 250}.{sira % 250}", ad, sifre, T0, "", cihaz
    )


def test_cihaz_cerezi_ad_ve_genel_kilitten_muaf_tutar():
    depo, ayar = _pano.BellekDepo(), _ayar()
    _yaz_hesap(depo, _hesap("ali"))
    for sira in range(_pano.AD_KILIT_DENEME):  # saldırgan adı kilitler (her biri başka adres)
        with pytest.raises(_pano.PanoHatasi):
            _dene(depo, ayar, sira, "ali", "yanlis")
    with pytest.raises(_pano.PanoHatasi) as hata:
        _dene(depo, ayar, 100, "ali", "dogru-sifre-1")
    assert hata.value.hata == "ad_kilitli"
    assert _dene(depo, ayar, 101, "ali", "dogru-sifre-1", _cihaz(ayar, "ali"))[0] == "ali"
    # Başka adın, imzası bozuk ya da süresi dolmuş çerez muafiyet vermez
    gecerli = _cihaz(ayar, "ali")
    bozuk = gecerli[:-1] + ("1" if gecerli.endswith("0") else "0")
    eski = _cihaz(ayar, "ali", T0 - _pano.CIHAZ_SURESI_SN - 1)
    for cerez in (_cihaz(ayar, "veli"), bozuk, eski, "c1.ali.x.1.y", "rastgele"):
        with pytest.raises(_pano.PanoHatasi) as hata:
            _dene(depo, ayar, 102, "ali", "dogru-sifre-1", cerez)
        assert hata.value.hata == "ad_kilitli", cerez
    # Genel kilit de muaf
    depo.komut("SET", _pano.GIRIS_GENEL_ANAHTARI, "500", "EX", "900")
    _yaz_hesap(depo, _hesap("veli"))
    with pytest.raises(_pano.PanoHatasi) as hata:
        _dene(depo, ayar, 103, "veli", "dogru-sifre-1")
    assert hata.value.hata == "genel_kilit"
    assert _dene(depo, ayar, 104, "veli", "dogru-sifre-1", _cihaz(ayar, "veli"))[0] == "veli"


def test_cihaz_cerezinin_kendi_siniri_var():
    depo, ayar = _pano.BellekDepo(), _ayar()
    _yaz_hesap(depo, _hesap("ali"))
    cihaz = _cihaz(ayar, "ali")
    for sira in range(_pano.CIHAZ_KILIT_DENEME):
        with pytest.raises(_pano.PanoHatasi) as hata:
            _dene(depo, ayar, sira, "ali", "yanlis", cihaz)
        assert hata.value.hata == "giris_hatali"
    with pytest.raises(_pano.PanoHatasi) as hata:
        _dene(depo, ayar, 50, "ali", "dogru-sifre-1", cihaz)
    assert hata.value.kod == 429 and hata.value.hata == "cihaz_kilitli"
    # Cihazın yanlışları ad kilidine sayılmadı: çerezsiz giriş açık
    assert _dene(depo, ayar, 51, "ali", "dogru-sifre-1")[0] == "ali"


def test_giris_cihaz_cerezini_oturum_cerezinden_sonra_verir(site):  # noqa: F811
    istek = urllib.request.Request(
        f"{site}/api/giris",
        data=json.dumps({"ad": "kurucu", "sifre": SIFRE}).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(istek, timeout=5) as yanit:
        cerezler = yanit.headers.get_all("Set-Cookie")
    assert cerezler[0].startswith(_pano.CEREZ_ADI + "=")
    assert cerezler[1].startswith(_pano.CIHAZ_CEREZ_ADI + "=c1.kurucu.")
    for parca in ("Path=/api/giris", "HttpOnly", "Secure", "SameSite=Strict"):
        assert parca in cerezler[1]
    # Bu cihaz, ad kilitliyken de girer
    cihaz = cerezler[1].split(";")[0]
    for sira in range(_pano.AD_KILIT_DENEME + 1):
        _istek(
            f"{site}/api/giris",
            "POST",
            json.dumps({"ad": "kurucu", "sifre": "yanlis"}).encode(),
            {"Content-Type": "application/json", "X-Real-IP": f"10.2.0.{sira}"},
        )
    basliklar = {"Content-Type": "application/json", "X-Real-IP": "10.2.1.1"}
    govde = json.dumps({"ad": "kurucu", "sifre": SIFRE}).encode()
    assert _istek(f"{site}/api/giris", "POST", govde, basliklar)[0] == 429
    assert _istek(f"{site}/api/giris", "POST", govde, {**basliklar, "Cookie": cihaz})[0] == 200


# ---------------------------------------------------------------- istek günlüğü


def test_istek_gunlugu_tek_json_satiri_sir_yazmaz(site, monkeypatch, capsys):  # noqa: F811
    monkeypatch.setenv("BEKCI_ANAHTARI", "bekci-gizli-anahtar-0123456789")
    assert _istek(f"{site}/api/bekci?anahtar=cok-gizli-deger-42")[0] == 403
    kod, basliklar, _ = _giris(site)
    assert kod == 200
    assert _istek(f"{site}/api/durum?kare=1", basliklar={"Cookie": _cerez(basliklar)})[0] == 200
    cikti, son = "", time.monotonic() + 3
    while cikti.count('"gunluk": "istek"') < 3 and time.monotonic() < son:
        time.sleep(0.02)  # satır cevap gittikten sonra yazılır
        cikti += capsys.readouterr().out
    satirlar = [json.loads(s) for s in cikti.splitlines() if '"gunluk": "istek"' in s]
    bekci, giris, durum = satirlar
    assert bekci["yol"] == "/api/bekci" and bekci["sorgu"] == ["anahtar"]
    assert bekci["kod"] == 403 and bekci["hata"] == "anahtar_yanlis" and "rol" not in bekci
    assert giris["yol"] == "/api/giris" and giris["kod"] == 200
    assert durum == {**durum, "yol": "/api/durum", "kod": 200, "rol": "yonetici"}
    assert isinstance(durum["ms"], int) and durum["sorgu"] == ["kare"]
    for sir in ("cok-gizli-deger-42", SIFRE, "pano_oturum", "kurucu"):
        assert sir not in cikti


# ------------------------------------------------ imzalı isteğin tekrarı


def _imzali(site, yol, govde, damga):  # noqa: F811
    return _istek(
        f"{site}{yol}",
        "POST",
        govde,
        {
            "Content-Type": "application/json",
            _pano.ZAMAN_BASLIGI: damga,
            _pano.IMZA_BASLIGI: _pano.imza_hesapla(ANAHTAR, damga, govde),
        },
    )


def test_ayni_imzali_istek_ikinci_kez_islenmez(site):  # noqa: F811
    govde = json.dumps(RAPOR).encode()
    damga = str(int(time.time()))
    assert _imzali(site, "/api/rapor", govde, damga)[0] == 200
    kod, _, cevap = _imzali(site, "/api/rapor", govde, damga)
    assert kod == 409 and json.loads(cevap)["hata"] == "tekrar"
    # Program yeniden denerken yeni damgayla imzalar: aynı gövde yine geçer
    assert _imzali(site, "/api/rapor", govde, str(int(damga) - 1))[0] == 200


def test_imzali_foto_govdesi_rapora_gecmez(site):  # noqa: F811
    """Denetim 08.11.2026: imza adresi kapsamıyor; imzalı bir /api/foto gövdesi
    /api/rapor'a gönderilince panoyu bir rapor boyunca boşaltıyordu."""
    assert _rapor_gonder(site, RAPOR)[0] == 200
    govde = json.dumps({"surum": 1, "olay_id": 123, "jpeg": _b64(JPEG)}).encode()
    damga = imza_damgasi(govde)
    assert _imzali(site, "/api/foto", govde, damga)[0] == 200
    kod, _, cevap = _imzali(site, "/api/rapor", govde, damga)
    assert kod == 409 and json.loads(cevap)["hata"] == "tekrar"
    cerez = _cerez(_giris(site)[1])
    veri = json.loads(_istek(f"{site}/api/durum", basliklar={"Cookie": cerez})[2])
    assert veri["rapor"]["kameralar"][0]["ad"] == "Sevkiyat Rampası"
