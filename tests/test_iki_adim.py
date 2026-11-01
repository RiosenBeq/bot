"""İki adımlı doğrulama (öneri 6): RFC 6238 TOTP, hesap başına isteğe bağlı.

Saf yardımcılar RFC 6238'in SHA1 örnek değerleriyle sınanır. Kurulum, kapatma,
yönetici sıfırlaması, kurucunun PANO_SIFRESI ile kurtarılması ve giriş akışı
gerçek HTTP ile (yerel sunucu, bellekte depo, ayarlanabilir saat) denenir. İki
adımı açılmamış hesap bugünkü gibi girer: öbür test dosyaları değişmeden yeşil
kalır, burada da birkaç uç ayrıca denetlenir.
"""

import base64
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import _pano
import pytest
from test_senaryolar import Kisi, saat, site  # noqa: F401
from test_uctan_uca import SIFRE, _istek

PUBLIC = Path(__file__).resolve().parents[1] / "public"
PANO_HTML = (PUBLIC / "pano.html").read_text(encoding="utf-8")
PANO_JS = (PUBLIC / "pano.js").read_text(encoding="utf-8")

# RFC 6238 Ek B: SHA1 için tohum "12345678901234567890" (20 bayt ASCII)
RFC_SIRRI = base64.b32encode(b"12345678901234567890").decode("ascii")


def _adim(saat) -> int:  # noqa: F811
    return int(saat() // _pano.IKI_ADIM_ADIM_SN)


def _kod(sir, saat, fark=0):  # noqa: F811
    return _pano.totp_kodu(sir, _adim(saat) + fark)


def _yanlis_kod(sir, saat):  # noqa: F811
    """Yakın adımların hiçbirinin kodu olmayan 6 haneli bir kod."""
    yakin = {_kod(sir, saat, fark) for fark in range(-3, 4)}
    return next(f"{n:06d}" for n in range(1000) if f"{n:06d}" not in yakin)


def _hesap_ac(kurucu, ad, rol):
    """Kurucu (ya da yönetici) hesabı açar; kişi ilk şifresini değiştirir. Döner:
    giriş yapmış kişi (şifresi `<ad>-sifresi`)."""
    kod, govde = kurucu.iste(
        "/api/hesap",
        {"eylem": "ekle", "ad": ad, "rol": rol, "ilk_sifre": "ilk-sifre-123", "sifre": SIFRE},
    )
    assert kod == 200, govde
    kisi = Kisi(kurucu.site).giris(ad, "ilk-sifre-123")
    kod, govde = kisi.iste(
        "/api/hesap",
        {"eylem": "sifre_degistir", "eski_sifre": "ilk-sifre-123", "yeni_sifre": f"{ad}-sifresi"},
    )
    assert kod == 200, govde
    return kisi


def _iki_adim_ac(kisi, sifre, saat):  # noqa: F811
    """Kişi iki adımı açar; onay kodu harcandığı için saat bir adım ilerler."""
    kod, govde = kisi.iste("/api/hesap", {"eylem": "iki_adim_baslat", "sifre": sifre})
    assert kod == 200, govde
    sir = govde["sir"]
    kod, govde = kisi.iste("/api/hesap", {"eylem": "iki_adim_onayla", "kod": _kod(sir, saat)})
    assert kod == 200, govde
    saat.ilerlet(_pano.IKI_ADIM_ADIM_SN)
    return sir


def _giris_ham(site, ad, sifre, kod=None):  # noqa: F811
    govde = {"ad": ad, "sifre": sifre}
    if kod is not None:
        govde["kod"] = kod
    durum_kodu, basliklar, ham = _istek(
        f"{site}/api/giris",
        "POST",
        json.dumps(govde).encode(),
        {"Content-Type": "application/json"},
    )
    return durum_kodu, basliklar, ham


def _giris(site, ad, sifre, kod=None):  # noqa: F811
    durum_kodu, basliklar, ham = _giris_ham(site, ad, sifre, kod)
    return durum_kodu, json.loads(ham), basliklar


def _kayit(kurucu):
    kod, liste = kurucu.iste("/api/hesap")
    assert kod == 200, liste
    return liste


# ------------------------------------------------------------ saf yardımcılar


@pytest.mark.parametrize(
    ("zaman", "beklenen"),
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_totp_rfc6238_sha1_ornekleri(zaman, beklenen):
    """RFC 6238 Ek B (SHA1, 30 sn). Pano 6 hane kullanır: aynı sayının son altı hanesi."""
    adim = zaman // 30
    assert _pano.totp_kodu(RFC_SIRRI, adim, hane=8) == beklenen
    assert _pano.totp_kodu(RFC_SIRRI, adim) == beklenen[-6:]
    assert _pano.totp_dogrula(RFC_SIRRI, beklenen[-6:], zaman) == adim


def test_totp_dogrula_bir_adim_once_ve_sonrasini_kabul_eder_eslesen_adimi_doner():
    simdi = 1_800_000_015.0
    adim = int(simdi // 30)
    for fark in (-1, 0, 1):
        kod = _pano.totp_kodu(RFC_SIRRI, adim + fark)
        assert _pano.totp_dogrula(RFC_SIRRI, kod, simdi) == adim + fark
        assert _pano.totp_dogrula(RFC_SIRRI, f" {kod[:3]} {kod[3:]} ", simdi) == adim + fark
    for fark in (-2, 2, 10):
        assert _pano.totp_dogrula(RFC_SIRRI, _pano.totp_kodu(RFC_SIRRI, adim + fark), simdi) is None
    for bozuk in ("", "12345", "1234567", "abcdef", "١٢٣٤٥٦", None, 123456, ["123456"]):
        assert _pano.totp_dogrula(RFC_SIRRI, bozuk, simdi) is None
    dogru = _pano.totp_kodu(RFC_SIRRI, adim)
    for sir in ("", "bozuk-sir!", "0189", None):
        assert _pano.totp_dogrula(sir, dogru, simdi) is None


def test_sir_20_rastgele_bayt_base32_ve_otpauth_adresi():
    sirlar = {_pano.iki_adim_siri_uret() for _ in range(20)}
    assert len(sirlar) == 20
    for sir in sirlar:
        assert re.fullmatch(r"[A-Z2-7]{32}", sir)
        assert len(base64.b32decode(sir)) == 20
    sir = sirlar.pop()
    assert _pano.iki_adim_uri("ahmet.yilmaz", sir) == (
        f"otpauth://totp/DALSAN:ahmet.yilmaz?secret={sir}&issuer=DALSAN"
    )


def test_kod_bir_kez_gecer_eski_adim_da_reddedilir():
    """Eşleşen adım hesap başına saklanır: aynı kod (ya da daha eski adımın kodu)
    ikinci kez geçmez; yeni adımın kodu geçer. Başka hesabı etkilemez."""
    simdi = 1_800_000_015.0
    depo = _pano.BellekDepo(lambda: simdi)
    adim = int(simdi // 30)
    simdiki = _pano.totp_kodu(RFC_SIRRI, adim)
    assert _pano._iki_adim_kod_kullan(depo, "ali", RFC_SIRRI, simdiki, simdi) is True
    assert _pano._iki_adim_kod_kullan(depo, "ali", RFC_SIRRI, simdiki, simdi) is False
    onceki = _pano.totp_kodu(RFC_SIRRI, adim - 1)
    assert _pano._iki_adim_kod_kullan(depo, "ali", RFC_SIRRI, onceki, simdi) is False
    sonraki = _pano.totp_kodu(RFC_SIRRI, adim + 1)
    assert _pano._iki_adim_kod_kullan(depo, "ali", RFC_SIRRI, sonraki, simdi) is True
    assert _pano._iki_adim_kod_kullan(depo, "veli", RFC_SIRRI, simdiki, simdi) is True
    assert _pano._iki_adim_kod_kullan(depo, "veli", RFC_SIRRI, "000000", simdi) is False


# -------------------------------------------------------------- HTTP akışları


def test_kurulum_giris_ve_kapatma(site, saat):  # noqa: F811
    """Operatör iki adımı açar: açmak oturumu düşürmez; yeni girişte kod sorulur
    (çerez yok), yanlış kod reddedilir, doğru kodla girer; aynı kod ikinci kez
    geçmez. Kapatmak şifre VE kod ister, öbür oturumları düşürür, bu oturum sürer."""
    kurucu = Kisi(site).giris("kurucu", SIFRE)
    ahmet = _hesap_ac(kurucu, "ahmet", "operator")
    assert "iki_adim" not in ahmet.iste("/api/durum")[1]["oturum"]

    kod, govde = ahmet.iste("/api/hesap", {"eylem": "iki_adim_baslat", "sifre": "ahmet-sifresi"})
    assert kod == 200, govde
    sir = govde["sir"]
    assert govde["uri"] == f"otpauth://totp/DALSAN:ahmet?secret={sir}&issuer=DALSAN"
    assert govde["sure_sn"] == _pano.IKI_ADIM_BEKLEYEN_SN
    # Bekleyen sır henüz açık değildir: giriş bugünkü gibi
    assert _giris(site, "ahmet", "ahmet-sifresi")[0] == 200

    kod, govde = ahmet.iste(
        "/api/hesap", {"eylem": "iki_adim_onayla", "kod": _yanlis_kod(sir, saat)}
    )
    assert (kod, govde["hata"]) == (400, "kod_yanlis")
    onay_kodu = _kod(sir, saat)
    kod, govde = ahmet.iste("/api/hesap", {"eylem": "iki_adim_onayla", "kod": onay_kodu})
    assert kod == 200, govde
    kod, durum = ahmet.iste("/api/durum")  # açmak oturumu düşürmez
    assert kod == 200 and durum["oturum"]["iki_adim"] is True

    kod, govde, basliklar = _giris(site, "ahmet", "ahmet-sifresi")
    assert (kod, govde["hata"]) == (401, "iki_adim_gerekli")
    assert "Set-Cookie" not in basliklar
    kod, govde, basliklar = _giris(site, "ahmet", "ahmet-sifresi", _yanlis_kod(sir, saat))
    assert (kod, govde["hata"]) == (401, "kod_yanlis")
    assert "Set-Cookie" not in basliklar
    # Onay kodu harcandı: aynı adımın koduyla girilemez
    assert _giris(site, "ahmet", "ahmet-sifresi", onay_kodu)[1]["hata"] == "kod_yanlis"
    saat.ilerlet(_pano.IKI_ADIM_ADIM_SN)
    giris_kodu = _kod(sir, saat)
    kod, govde, basliklar = _giris(site, "ahmet", "ahmet-sifresi", giris_kodu)
    assert kod == 200 and govde == {"tamam": True} and "Set-Cookie" in basliklar
    kod, govde, _ = _giris(site, "ahmet", "ahmet-sifresi", giris_kodu)  # yeniden kullanım
    assert (kod, govde["hata"]) == (401, "kod_yanlis")
    # Şifre yanlışsa kod doğru da olsa bugünkü cevap: iki adım açık mı sızmaz
    saat.ilerlet(_pano.IKI_ADIM_ADIM_SN)
    kod, govde, _ = _giris(site, "ahmet", "yanlis-sifre-1", _kod(sir, saat))
    assert (kod, govde["hata"]) == (401, "giris_hatali")

    ikinci = Kisi(site)
    saat.ilerlet(_pano.IKI_ADIM_ADIM_SN)
    kod, govde = ikinci.iste(
        "/api/giris", {"ad": "ahmet", "sifre": "ahmet-sifresi", "kod": _kod(sir, saat)}
    )
    assert kod == 200, govde

    saat.ilerlet(_pano.IKI_ADIM_ADIM_SN)
    kod, govde = ahmet.iste(
        "/api/hesap", {"eylem": "iki_adim_kapat", "sifre": "yanlis-1234", "kod": _kod(sir, saat)}
    )
    assert (kod, govde["hata"]) == (400, "onay_sifresi")
    kod, govde = ahmet.iste(
        "/api/hesap",
        {"eylem": "iki_adim_kapat", "sifre": "ahmet-sifresi", "kod": _yanlis_kod(sir, saat)},
    )
    assert (kod, govde["hata"]) == (400, "kod_yanlis")
    kod, govde = ahmet.iste(
        "/api/hesap", {"eylem": "iki_adim_kapat", "sifre": "ahmet-sifresi", "kod": _kod(sir, saat)}
    )
    assert kod == 200, govde
    kod, durum = ahmet.iste("/api/durum")  # bu oturum yeni çerezle sürer
    assert kod == 200 and "iki_adim" not in durum["oturum"]
    assert ikinci.iste("/api/durum")[0] == 401  # öbür oturumlar düştü
    saat.ilerlet(_pano.KILIT_SURESI_SN + 1)  # bu adresten altı yanlış deneme oldu: kilit dolsun
    assert _giris(site, "ahmet", "ahmet-sifresi")[0] == 200  # yine kodsuz

    isler = [(s["kim"], s["is"], s["ozet"], s["sonuc"]) for s in _kayit(kurucu)["kayit"]]
    assert ("ahmet", "iki_adim_ac", "", "tamam") in isler
    assert ("ahmet", "iki_adim_kapat", "", "tamam") in isler


def test_kurulum_sifre_ister_bekleyen_sir_kisa_omurlu_deneme_sinirli(site, saat):  # noqa: F811
    kurucu = Kisi(site).giris("kurucu", SIFRE)
    ahmet = _hesap_ac(kurucu, "ahmet", "operator")
    for govde in ({"eylem": "iki_adim_baslat"}, {"eylem": "iki_adim_baslat", "sifre": "yanlis"}):
        kod, cevap = ahmet.iste("/api/hesap", govde)
        assert (kod, cevap["hata"]) == (400, "onay_sifresi")
    kod, cevap = ahmet.iste("/api/hesap", {"eylem": "iki_adim_onayla", "kod": "123456"})
    assert (kod, cevap["hata"]) == (400, "iki_adim_bekleyen_yok")
    kod, cevap = ahmet.iste("/api/hesap", {"eylem": "iki_adim_kapat", "sifre": "ahmet-sifresi"})
    assert (kod, cevap["hata"]) == (409, "iki_adim_kapali")

    # Bekleyen sır kısa ömürlüdür
    sir = ahmet.iste("/api/hesap", {"eylem": "iki_adim_baslat", "sifre": "ahmet-sifresi"})[1]["sir"]
    saat.ilerlet(_pano.IKI_ADIM_BEKLEYEN_SN + 1)
    kod, cevap = ahmet.iste("/api/hesap", {"eylem": "iki_adim_onayla", "kod": _kod(sir, saat)})
    assert (kod, cevap["hata"]) == (400, "iki_adim_bekleyen_yok")

    # Yanlış kod sınırı: sınırda bekleyen sır silinir, baştan başlanır
    sir = ahmet.iste("/api/hesap", {"eylem": "iki_adim_baslat", "sifre": "ahmet-sifresi"})[1]["sir"]
    for _ in range(_pano.IKI_ADIM_DENEME_SINIR):
        kod, cevap = ahmet.iste(
            "/api/hesap", {"eylem": "iki_adim_onayla", "kod": _yanlis_kod(sir, saat)}
        )
        assert (kod, cevap["hata"]) == (400, "kod_yanlis")
    kod, cevap = ahmet.iste("/api/hesap", {"eylem": "iki_adim_onayla", "kod": _kod(sir, saat)})
    assert (kod, cevap["hata"]) == (400, "iki_adim_bekleyen_yok")

    # Yeniden başlatınca sayaç sıfırlanır; açıkken yeniden başlatılamaz
    _iki_adim_ac(ahmet, "ahmet-sifresi", saat)
    assert _pano.DEPO.al_coklu([_pano.IKI_ADIM_BEKLEYEN_ONEKI + "ahmet"]) == [None]
    kod, cevap = ahmet.iste("/api/hesap", {"eylem": "iki_adim_baslat", "sifre": "ahmet-sifresi"})
    assert (kod, cevap["hata"]) == (409, "iki_adim_acik")


def test_kod_eksikse_cerez_yok_kilide_sayilmaz(site, saat):  # noqa: F811
    """Şifre doğru ama kod yok: 401 iki_adim_gerekli, çerez yok; hiçbir kilit
    sayacına ve hatalı giriş kaydına girmez (pano kod kutusunu açıp yeniden sorar)."""
    kurucu = Kisi(site).giris("kurucu", SIFRE)
    ahmet = _hesap_ac(kurucu, "ahmet", "operator")
    sir = _iki_adim_ac(ahmet, "ahmet-sifresi", saat)
    for kod_alani in (None, "", "   ", *[None] * _pano.KILIT_DENEME):
        kod, govde, basliklar = _giris(site, "ahmet", "ahmet-sifresi", kod_alani)
        assert (kod, govde["hata"]) == (401, "iki_adim_gerekli") and "Set-Cookie" not in basliklar
    assert _giris(site, "ahmet", "ahmet-sifresi", _kod(sir, saat))[0] == 200
    assert not [s for s in _kayit(kurucu)["kayit"] if s["is"] == "giris_hatali"]


def test_yanlis_kod_kilitlere_yanlis_sifre_gibi_sayilir(site, saat):  # noqa: F811
    """Yanlış kod, yanlış şifre gibi adres / ad / genel sayaçlarına girer ve
    giris_hatali satırı yazar. Adres kilitlenince doğru şifre ve kod da geçmez;
    kilit süresi dolunca yeni kodla girilir."""
    kurucu = Kisi(site).giris("kurucu", SIFRE)
    ahmet = _hesap_ac(kurucu, "ahmet", "operator")
    sir = _iki_adim_ac(ahmet, "ahmet-sifresi", saat)
    for _ in range(_pano.KILIT_DENEME):
        kod, govde, _ = _giris(site, "ahmet", "ahmet-sifresi", _yanlis_kod(sir, saat))
        assert (kod, govde["hata"]) == (401, "kod_yanlis")
    kod, govde, _ = _giris(site, "ahmet", "ahmet-sifresi", _kod(sir, saat))
    assert (kod, govde["hata"]) == (429, "kilitli")
    for anahtar in (_pano._ad_kilit_anahtari("ahmet"), _pano.GIRIS_GENEL_ANAHTARI):
        assert int(_pano.DEPO.komut("GET", anahtar)) == _pano.KILIT_DENEME
    hatalilar = [
        (s["kim"], s["is"], s["ozet"]) for s in _kayit(kurucu)["kayit"] if s["is"] == "giris_hatali"
    ]
    assert hatalilar == [("ahmet", "giris_hatali", "Doğrulama kodu yanlış")] * _pano.KILIT_DENEME

    saat.ilerlet(_pano.KILIT_SURESI_SN + 1)
    assert _giris(site, "ahmet", "ahmet-sifresi", _kod(sir, saat))[0] == 200


def test_yonetici_iki_adimi_sifirlar_hesap_kurallariyla(site, saat):  # noqa: F811
    """Yönetici operatörün / izleyicinin iki adımını onay şifresiyle sıfırlar;
    yöneticininkini yalnız kurucu. Kendine, kurucuya ve kapalı hesaba olmaz.
    Sıfırlama hesabın bütün oturumlarını düşürür ve işlem kaydına girer."""
    kurucu = Kisi(site).giris("kurucu", SIFRE)
    mudur = _hesap_ac(kurucu, "mudur", "yonetici")
    ahmet = _hesap_ac(kurucu, "ahmet", "operator")
    zeynep = _hesap_ac(kurucu, "zeynep", "izleyici")
    sir = _iki_adim_ac(ahmet, "ahmet-sifresi", saat)
    ikinci = Kisi(site)
    kod, govde = ikinci.iste(
        "/api/giris", {"ad": "ahmet", "sifre": "ahmet-sifresi", "kod": _kod(sir, saat)}
    )
    assert kod == 200, govde
    satirlar = {k["ad"]: k for k in _kayit(kurucu)["kullanicilar"]}
    assert satirlar["ahmet"]["iki_adim"] is True
    assert "iki_adim" not in satirlar["mudur"] and "iki_adim" not in satirlar["kurucu"]

    sifirla = {"eylem": "iki_adim_sifirla", "ad": "ahmet"}
    kod, govde = zeynep.iste("/api/hesap", {**sifirla, "sifre": "zeynep-sifresi"})
    assert (kod, govde["hata"]) == (403, "yetki")
    kod, govde = mudur.iste("/api/hesap", sifirla)
    assert (kod, govde["hata"]) == (400, "onay_sifresi")
    kod, govde = mudur.iste("/api/hesap", {**sifirla, "sifre": "mudur-sifresi"})
    assert kod == 200, govde
    assert ahmet.iste("/api/durum")[0] == 401 and ikinci.iste("/api/durum")[0] == 401
    assert _giris(site, "ahmet", "ahmet-sifresi")[0] == 200  # kodsuz girer
    liste = _kayit(kurucu)
    assert "iki_adim" not in {k["ad"]: k for k in liste["kullanicilar"]}["ahmet"]
    isler = [(s["kim"], s["is"], s["ozet"]) for s in liste["kayit"]]
    assert ("mudur", "iki_adim_sifirla", "ahmet") in isler
    assert ("zeynep", "komut_red", "Yetki yetmedi: iki_adim_sifirla") in isler
    kod, govde = mudur.iste("/api/hesap", {**sifirla, "sifre": "mudur-sifresi"})
    assert (kod, govde["hata"]) == (409, "iki_adim_kapali")

    # Yöneticinin iki adımını yalnız kurucu sıfırlar
    _iki_adim_ac(mudur, "mudur-sifresi", saat)
    mudur2 = _hesap_ac(kurucu, "mudur2", "yonetici")
    kod, govde = mudur2.iste(
        "/api/hesap", {"eylem": "iki_adim_sifirla", "ad": "mudur", "sifre": "mudur2-sifresi"}
    )
    assert (kod, govde["hata"]) == (403, "yalniz_kurucu")
    kod, govde = mudur2.iste(
        "/api/hesap", {"eylem": "iki_adim_sifirla", "ad": "mudur2", "sifre": "mudur2-sifresi"}
    )
    assert (kod, govde["hata"]) == (400, "kendi_hesabi")
    kod, govde = kurucu.iste(
        "/api/hesap", {"eylem": "iki_adim_sifirla", "ad": "mudur", "sifre": SIFRE}
    )
    assert kod == 200, govde
    assert mudur.iste("/api/durum")[0] == 401
    isler = [(s["kim"], s["is"], s["ozet"]) for s in _kayit(kurucu)["kayit"]]
    assert ("mudur2", "komut_red", "Yalnız kurucu: iki_adim_sifirla") in isler
    assert ("kurucu", "iki_adim_sifirla", "mudur") in isler
    for ad, beklenen in (("kurucu", (400, "kurucu")), ("hayalet", (404, "hesap_yok"))):
        kod, govde = kurucu.iste(
            "/api/hesap", {"eylem": "iki_adim_sifirla", "ad": ad, "sifre": SIFRE}
        )
        assert (kod, govde["hata"]) == beklenen, ad


def test_kurucu_iki_adimi_pano_sifresi_degisince_kendiliginden_kapanir(
    site,  # noqa: F811
    saat,  # noqa: F811
    monkeypatch,
):
    """Kurucu da açabilir; sırrı ayrı anahtarda, PANO_SIFRESI'nin izine (HMAC)
    bağlı durur. Vercel'de PANO_SIFRESI değişince ilk girişte kayıt silinir:
    telefonunu kaybeden kurucunun kurtarma yolu budur. Eski şifreye dönmek sırrı
    diriltmez."""
    kurucu = Kisi(site).giris("kurucu", SIFRE)
    sir = _iki_adim_ac(kurucu, SIFRE, saat)
    assert kurucu.iste("/api/durum")[1]["oturum"]["iki_adim"] is True
    assert {k["ad"]: k for k in _kayit(kurucu)["kullanicilar"]}["kurucu"]["iki_adim"] is True
    assert _giris(site, "kurucu", SIFRE)[1]["hata"] == "iki_adim_gerekli"
    assert _giris(site, "kurucu", SIFRE, _kod(sir, saat))[0] == 200
    # Kayıtta ne PANO_SIFRESI ne de düz özeti durur: çevrimdışı denenemez
    ham = _pano.DEPO.komut("GET", _pano.IKI_ADIM_KURUCU_ANAHTARI)
    assert sir in ham and SIFRE not in ham
    assert hashlib.sha256(SIFRE.encode()).hexdigest()[:16] not in ham

    # Kurucu kendisi kapatır (şifre + kod) ve hemen yeni sırla yeniden açar
    saat.ilerlet(_pano.IKI_ADIM_ADIM_SN)
    kod, govde = kurucu.iste(
        "/api/hesap", {"eylem": "iki_adim_kapat", "sifre": SIFRE, "kod": _kod(sir, saat)}
    )
    assert kod == 200, govde
    assert _giris(site, "kurucu", SIFRE)[0] == 200
    sir = _iki_adim_ac(kurucu, SIFRE, saat)
    assert _giris(site, "kurucu", SIFRE)[1]["hata"] == "iki_adim_gerekli"

    monkeypatch.setenv("PANO_SIFRESI", "yeni-kurucu-sifresi-2026")
    assert kurucu.iste("/api/durum")[0] == 401  # bütün oturumlar düştü (bugünkü gibi)
    kod, govde, _ = _giris(site, "kurucu", "yeni-kurucu-sifresi-2026")
    assert kod == 200, govde
    assert _pano.DEPO.komut("GET", _pano.IKI_ADIM_KURUCU_ANAHTARI) is None
    yeni = Kisi(site).giris("kurucu", "yeni-kurucu-sifresi-2026")
    assert "iki_adim" not in yeni.iste("/api/durum")[1]["oturum"]

    monkeypatch.setenv("PANO_SIFRESI", SIFRE)  # kaybolan telefonun sırrı geri gelmez
    assert _giris(site, "kurucu", SIFRE)[0] == 200


def test_sir_yalniz_kurulum_cevabinda_doner(site, saat, capsys):  # noqa: F811
    """Sır ve otpauth adresi yalnız iki_adim_baslat cevabındadır: giriş,
    durum, hesap listesi, üç işlem kaydı listesi ve günlükte görünmez."""
    kurucu = Kisi(site).giris("kurucu", SIFRE)
    ahmet = _hesap_ac(kurucu, "ahmet", "operator")
    sir = _iki_adim_ac(ahmet, "ahmet-sifresi", saat)
    gorulen = [
        _giris_ham(site, "ahmet", "ahmet-sifresi")[2],
        _giris_ham(site, "ahmet", "ahmet-sifresi", _yanlis_kod(sir, saat))[2],
        _giris_ham(site, "ahmet", "ahmet-sifresi", _kod(sir, saat))[2],
        json.dumps(ahmet.iste("/api/durum")[1]),
        json.dumps(_kayit(kurucu)),
        json.dumps(
            ahmet.iste("/api/hesap", {"eylem": "iki_adim_baslat", "sifre": "ahmet-sifresi"})[1]
        ),
    ]
    for metin in gorulen:
        metin = metin.decode() if isinstance(metin, bytes) else metin
        assert sir not in metin
    for liste in (_pano.KAYIT_ANAHTARI, _pano.KAYIT_OTURUM_ANAHTARI, _pano.KAYIT_GIRIS_ANAHTARI):
        assert not any(sir in satir for satir in _pano.DEPO.komut("LRANGE", liste, "0", "-1"))
    yakalanan = capsys.readouterr()
    assert sir not in yakalanan.out and sir not in yakalanan.err


def test_iki_adimsiz_hesap_bugunku_gibi_girer(site, saat):  # noqa: F811
    """İki adımı açık olmayan hesapta `kod` alanı yok sayılır: cevap, çerez ve
    oturum özeti bugünküyle aynıdır; yanlış şifre yine giris_hatali'dır."""
    kod, basliklar, ham = _giris_ham(site, "kurucu", SIFRE)
    kod_ile, basliklar_ile, ham_ile = _giris_ham(site, "kurucu", SIFRE, "123456")
    assert (kod, ham) == (kod_ile, ham_ile) == (200, b'{"tamam": true}')
    assert "Set-Cookie" in basliklar and "Set-Cookie" in basliklar_ile
    kurucu = Kisi(site).giris("kurucu", SIFRE)
    assert kurucu.iste("/api/durum")[1]["oturum"] == {
        "ad": "kurucu",
        "rol": "yonetici",
        "rol_adi": "Yönetici",
        "kurucu": True,
        "sifre_degismeli": False,
    }
    _hesap_ac(kurucu, "ahmet", "operator")
    assert _giris(site, "ahmet", "ahmet-sifresi", "000000")[0] == 200
    kod, basliklar, ham = _giris_ham(site, "ahmet", "yanlis-sifre-9", "000000")
    assert kod == 401 and "Set-Cookie" not in basliklar
    assert json.loads(ham) == {"hata": "giris_hatali", "mesaj": _pano.GIRIS_HATALI_METNI}
    hatalilar = [
        (s["kim"], s["ozet"]) for s in _kayit(kurucu)["kayit"] if s["is"] == "giris_hatali"
    ]
    assert hatalilar == [("ahmet", "")]
    assert all("iki_adim" not in k for k in _kayit(kurucu)["kullanicilar"])


def test_izleyici_de_acar_kapilar_bugunku_gibi(site, saat, monkeypatch):  # noqa: F811
    """Her rol kendi iki adımını açar. Şifresini değiştirmemiş hesap önce şifre
    değiştirir (sifre_degismeli), önizleme yayınında hesap işi yapılmaz."""
    kurucu = Kisi(site).giris("kurucu", SIFRE)
    zeynep = _hesap_ac(kurucu, "zeynep", "izleyici")
    sir = _iki_adim_ac(zeynep, "zeynep-sifresi", saat)
    assert _giris(site, "zeynep", "zeynep-sifresi", _kod(sir, saat))[0] == 200

    kod, govde = kurucu.iste(
        "/api/hesap",
        {
            "eylem": "ekle",
            "ad": "yeni",
            "rol": "operator",
            "ilk_sifre": "ilk-sifre-1",
            "sifre": SIFRE,
        },
    )
    assert kod == 200, govde
    yeni = Kisi(site).giris("yeni", "ilk-sifre-1")
    kod, govde = yeni.iste("/api/hesap", {"eylem": "iki_adim_baslat", "sifre": "ilk-sifre-1"})
    assert (kod, govde["hata"]) == (403, "sifre_degismeli")
    assert Kisi(site).iste("/api/hesap", {"eylem": "iki_adim_baslat"})[0] == 401

    monkeypatch.setenv("VERCEL_ENV", "preview")
    kod, govde = kurucu.iste("/api/hesap", {"eylem": "iki_adim_baslat", "sifre": SIFRE})
    assert (kod, govde["hata"]) == (409, "onizleme")


# ----------------------------------------------------------------- ön yüz


def test_giris_formu_kod_alani_iki_adim_gerekince_acilir():
    alan = re.search(r'<div id="giris-kod-alani"[^>]*>', PANO_HTML)
    assert alan and " hidden" in alan.group(0)
    girdi = re.search(r'<input id="giris-kod"[^>]*>', PANO_HTML).group(0)
    for parca in ('autocomplete="one-time-code"', 'inputmode="numeric"', 'maxlength="7"'):
        assert parca in girdi, parca
    form = re.search(r'\$\("giris-formu"\)\.addEventListener.*?\n  \}\);', PANO_JS, re.S).group(0)
    assert '"iki_adim_gerekli"' in form and '"kod_yanlis"' in form
    assert "govde.kod = kod" in form and "{ ad: ad, sifre: sifre }" in form


def test_hesabim_iki_adim_kutusu_metin_olarak_cizer():
    for kimlik in (
        "iki-adim-karti",
        "iki-adim-durumu",
        "iki-adim-ac-formu",
        "iki-adim-ac-sifre",
        "iki-adim-kurulum",
        "iki-adim-sir",
        "iki-adim-uri",
        "iki-adim-onay-formu",
        "iki-adim-onay-kodu",
        "iki-adim-kapat-formu",
        "iki-adim-kapat-sifre",
        "iki-adim-kapat-kodu",
        "iki-adim-hatasi",
    ):
        assert f'id="{kimlik}"' in PANO_HTML, kimlik
    kart = re.search(r'<section id="iki-adim-karti".*?</section>', PANO_HTML, re.S).group(0)
    for metin in ("İki adımlı doğrulama", "Google Authenticator", "Microsoft Authenticator"):
        assert metin in kart, metin
    assert "anahtarı elle gir" in kart
    for eylem in ("iki_adim_baslat", "iki_adim_onayla", "iki_adim_kapat"):
        assert f'eylem: "{eylem}"' in PANO_JS, eylem
    assert '$("iki-adim-sir").textContent = ' in PANO_JS
    assert '$("iki-adim-uri").textContent = ' in PANO_JS


def test_kullanicilar_ekraninda_iki_adim_rozeti_ve_sifirlama():
    satir = re.search(r"function kullaniciSatiri\(k\) \{.*?\n  \}", PANO_JS, re.S).group(0)
    assert "k.iki_adim" in satir and 'rozet("2 adım"' in satir
    islemler = re.search(r"function kullaniciIslemleri\(k\) \{.*?\n  \}", PANO_JS, re.S).group(0)
    assert '"2 adımı sıfırla"' in islemler and 'eylem: "iki_adim_sifirla"' in islemler
    for is_ in ("iki_adim_ac", "iki_adim_kapat", "iki_adim_sifirla"):
        assert re.search(rf'\b{is_}: "', PANO_JS), is_


class _SayanDepo(_pano.BellekDepo):
    """Depoya giden her isteği kaydeder (tek komut da, boru hattı da bir istek)."""

    def __init__(self):
        super().__init__()
        self.istekler = []

    def komut(self, *parcalar):
        self.istekler.append([str(p) for p in parcalar][:1])
        return super().komut(*parcalar)

    def boru_hatti(self, komutlar):
        self.istekler.append([str(k[0]) for k in komutlar])
        return super().boru_hatti(komutlar)


def test_iki_adimsiz_giris_depoya_bugunku_kadar_istek_atar():
    """Kurucu ve iki adımı kapalı hesap: başarılı giriş bugünkü istekleri yapar
    (kilit ve hesap tek MGET'te; kurucunun iki adım kaydı da o MGET'te okunur)."""
    ayar = _pano.Ayar(
        pano_sifresi="kurucu-sifresi-123",
        rapor_anahtari="r" * 40,
        redis_adresi="https://x",
        redis_jetonu="t",
        fabrika_adresi="",
    )
    depo = _SayanDepo()
    _pano.giris_dene(depo, ayar, "1.2.3.4", "kurucu", "kurucu-sifresi-123", 1_800_000_000)
    assert depo.istekler == [["MGET"], ["LPUSH", "LTRIM"]]
    kayit = {
        "surum": 1,
        "ad": "ali",
        "hesap_kimligi": "1234567890abcdef",
        "rol": "operator",
        "acik": True,
        "sifre": _pano.sifre_ozetle("dogru-sifre-1"),
        "oturum_surumu": 1,
    }
    depo.boru_hatti([["SET", _pano.KULLANICI_ONEKI + "ali", json.dumps(kayit)]])
    depo.istekler.clear()
    _pano.giris_dene(depo, ayar, "1.2.3.4", "ali", "dogru-sifre-1", 1_800_000_000, "123456")
    assert depo.istekler == [["MGET"], ["SET"], ["LPUSH", "LTRIM"]]


def test_kurucu_kaydi_pano_sifresinin_cevrimdisi_denenebilir_ozetini_tasimaz(
    site,  # noqa: F811
    saat,  # noqa: F811
    monkeypatch,
):
    """Kurucu kaydının parmak izi PANO_SIFRESI'nin tuzlu özeti değil, çerez
    anahtarı gibi rapor anahtarını da içeren bir HMAC'tir: Redis dökümünü okuyan
    biri (rapor anahtarı fabrika bilgisayarında ve Vercel'de durur, depoda yok)
    PANO_SIFRESI'ni çevrimdışı deneyemez. Rapor anahtarı değişince de kayıt düşer."""
    kurucu = Kisi(site).giris("kurucu", SIFRE)
    sir = _iki_adim_ac(kurucu, SIFRE, saat)
    kayit = json.loads(_pano.DEPO.komut("GET", _pano.IKI_ADIM_KURUCU_ANAHTARI))
    assert set(kayit) == {"sir", "parmak", "acildi"}
    assert isinstance(kayit["parmak"], str) and re.fullmatch(r"[0-9a-f]{64}", kayit["parmak"])
    assert _giris(site, "kurucu", SIFRE, _kod(sir, saat))[0] == 200

    monkeypatch.setenv("RAPOR_ANAHTARI", "baska-bir-rapor-anahtari-en-az-otuz-iki-krk")
    kod, govde, _ = _giris(site, "kurucu", SIFRE)
    assert kod == 200, govde  # rapor anahtarı değişti: kayıt düştü, kod sorulmaz
    assert _pano.DEPO.komut("GET", _pano.IKI_ADIM_KURUCU_ANAHTARI) is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node yok")
def test_giris_ekranina_donunce_yarim_kurulumun_anahtari_unutulur():
    """Paylaşılan bilgisayar: A kurulumu başlatıp çıkar (ya da oturumu düşer);
    aynı sekmede giren B, A'nın anahtarını görmemeli. Çıkış ve bütün 401 yolları
    giriş ekranını tekEkranGoster("giris") ile açar; bu bekleyen anahtarı ve
    ekrandaki metnini siler."""
    islevler = [
        re.search(r"function tekEkranGoster\(ad\) \{.*?\n  \}", PANO_JS, re.S).group(0),
        re.search(r"function ikiAdimKurulumuUnut\(\) \{.*?\n  \}", PANO_JS, re.S).group(0),
    ]
    betik = "\n".join(
        [
            "const kutular = {};",
            "function $(k) {",
            '  return kutular[k] || (kutular[k] = {hidden: false, textContent: ""});',
            "}",
            'let ikiAdimKurulum = {ad: "ahmet", sir: "KSEMSIR", uri: "otpauth://x?secret=KSEMSIR"};',
            '$("iki-adim-sir").textContent = "KSEMSIR";',
            '$("iki-adim-uri").textContent = "otpauth://x?secret=KSEMSIR";',
            *islevler,
            'tekEkranGoster("yukleniyor");',
            "console.log(JSON.stringify(ikiAdimKurulum));",
            'tekEkranGoster("giris");',
            'console.log(JSON.stringify([ikiAdimKurulum, $("iki-adim-sir").textContent, '
            '$("iki-adim-uri").textContent]));',
        ]
    )
    cikti = subprocess.run(
        ["node", "-e", betik], capture_output=True, text=True, timeout=20, check=True
    ).stdout.splitlines()
    assert json.loads(cikti[0])["sir"] == "KSEMSIR"  # yükleniyor ekranı unutturmaz
    assert json.loads(cikti[1]) == [None, "", ""]


def test_yarim_kurulum_yalniz_baslatan_hesaba_cizilir():
    """Anahtar başlatan hesabın adıyla tutulur; başka hesabın oturumunda kutu
    çizilmeden önce unutulur."""
    assert "ad: oturum.ad," in PANO_JS
    ciz = re.search(r"function ikiAdimCiz\(\) \{.*?\n  \}", PANO_JS, re.S).group(0)
    assert "ikiAdimKurulum.ad !== oturum.ad" in ciz
