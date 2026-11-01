"""Hesaplar, roller, oturum ve /api/hesap (docs/19 §3.1-§3.4).

Birim düzeyi: şifre özeti, çerez (noktalı ad, oturum sürümü, hesap kimliği,
iptal), rolün her istekte kayıttan okunması, dizin onarımı. HTTP düzeyi: kurucu
girişi, durum oturum/önizleme, hesap yaşam döngüsü, roller, süzgeç, işlem kaydı
ve uç nokta sırası.
"""

import json

import _pano
import pytest
from test_uctan_uca import SIFRE, _cerez, _giris, _istek, site  # noqa: F401


def _ayar(**d):
    alanlar = {
        "pano_sifresi": "kurucu-sifresi-123",
        "rapor_anahtari": "r" * 40,
        "redis_adresi": "https://x",
        "redis_jetonu": "t",
        "fabrika_adresi": "",
    }
    alanlar.update(d)
    return _pano.Ayar(**alanlar)


def _hesap(
    ad, rol="operator", kimlik="1234567890abcdef", surum=1, acik=True, sifre="dogru-sifre-1"
):
    return {
        "surum": 1,
        "ad": ad,
        "hesap_kimligi": kimlik,
        "rol": rol,
        "acik": acik,
        "sifre": _pano.sifre_ozetle(sifre),
        "sifre_degismeli": False,
        "oturum_surumu": surum,
        "olusturuldu": 1793450000,
        "olusturan": "kurucu",
        "guncellendi": 1793450000,
    }


def _yaz_hesap(depo, kayit):
    depo.boru_hatti([["SET", _pano.KULLANICI_ONEKI + kayit["ad"], json.dumps(kayit)]])


# -------------------------------------------------------------------- şifre


def test_sifre_ozetle_ve_dogrula():
    kayit = _pano.sifre_ozetle("gizli-parola-99")
    assert kayit["alg"] in ("scrypt", "pbkdf2")
    assert _pano.sifre_dogrula(kayit, "gizli-parola-99")
    assert not _pano.sifre_dogrula(kayit, "yanlis")
    assert not _pano.sifre_dogrula({}, "gizli-parola-99")


def test_bozuk_parametre_asiri_bellek_acmaz():
    """Ele geçen bir kayıt büyük n ile belleği doldurmasın: n sınırlanır,
    doğrulama güvenle False döner (asmadan)."""
    kayit = {**_pano.sifre_ozetle("gizli-parola-99"), "n": 10**9}
    assert _pano.sifre_dogrula(kayit, "gizli-parola-99") is False


# -------------------------------------------------------------------- çerez


def test_noktali_adli_cerez_dogru_cozulur():
    ayar = _ayar()
    depo = _pano.BellekDepo()
    _yaz_hesap(depo, _hesap("ahmet.yil.maz", kimlik="abcdef0123456789", surum=4))
    deger = _pano.cerez_uret(ayar, "ahmet.yil.maz", "abcdef0123456789", 4, 1_800_000_000)
    oturum = _pano.oturum_coz(depo, ayar, deger, 1_800_000_000)
    assert oturum.ad == "ahmet.yil.maz" and oturum.rol == "operator" and not oturum.kurucu


def test_rol_her_istekte_kayittan_okunur():
    ayar = _ayar()
    depo = _pano.BellekDepo()
    _yaz_hesap(depo, _hesap("ali", rol="operator"))
    deger = _pano.cerez_uret(ayar, "ali", "1234567890abcdef", 1, 1_800_000_000)
    assert _pano.oturum_coz(depo, ayar, deger, 1_800_000_000).rol == "operator"
    # Rol düşürülünce aynı çerez yeni rolü taşır (düşürme anında geçerli)
    _yaz_hesap(depo, _hesap("ali", rol="izleyici"))
    assert _pano.oturum_coz(depo, ayar, deger, 1_800_000_000).rol == "izleyici"


def test_oturum_surumu_degisince_cerez_duser():
    ayar = _ayar()
    depo = _pano.BellekDepo()
    _yaz_hesap(depo, _hesap("ali", surum=1))
    deger = _pano.cerez_uret(ayar, "ali", "1234567890abcdef", 1, 1_800_000_000)
    _yaz_hesap(depo, _hesap("ali", surum=2))
    with pytest.raises(_pano.PanoHatasi) as e:
        _pano.oturum_coz(depo, ayar, deger, 1_800_000_000)
    assert e.value.hata == "oturum_kapandi"


def test_hesap_kimligi_degisince_eski_cerez_gecmez():
    """Aynı ad silinip yeniden açılınca (yeni hesap_kimligi) eski çerez geçmez."""
    ayar = _ayar()
    depo = _pano.BellekDepo()
    _yaz_hesap(depo, _hesap("ali", kimlik="1111111111111111"))
    deger = _pano.cerez_uret(ayar, "ali", "1111111111111111", 1, 1_800_000_000)
    _yaz_hesap(depo, _hesap("ali", kimlik="2222222222222222"))  # yeniden açıldı
    with pytest.raises(_pano.PanoHatasi) as e:
        _pano.oturum_coz(depo, ayar, deger, 1_800_000_000)
    assert e.value.hata == "oturum_kapandi"


def test_iptal_edilen_oturum_duser():
    ayar = _ayar()
    depo = _pano.BellekDepo()
    _yaz_hesap(depo, _hesap("ali"))
    deger = _pano.cerez_uret(ayar, "ali", "1234567890abcdef", 1, 1_800_000_000)
    _, _, _, _, imza = _pano._cerez_coz(deger)
    depo.boru_hatti([["SET", _pano._iptal_anahtari(imza), "1"]])
    with pytest.raises(_pano.PanoHatasi) as e:
        _pano.oturum_coz(depo, ayar, deger, 1_800_000_000)
    assert e.value.hata == "oturum_kapandi"


def test_kapali_hesabin_oturumu_duser():
    ayar = _ayar()
    depo = _pano.BellekDepo()
    _yaz_hesap(depo, _hesap("ali", acik=False))
    deger = _pano.cerez_uret(ayar, "ali", "1234567890abcdef", 1, 1_800_000_000)
    with pytest.raises(_pano.PanoHatasi) as e:
        _pano.oturum_coz(depo, ayar, deger, 1_800_000_000)
    assert e.value.hata == "oturum_kapandi"


# -------------------------------------------------------------- dizin onarımı


def test_listeleme_kaydi_olmayan_dizin_adini_atar():
    depo = _pano.BellekDepo()
    depo.komut("RPUSH", _pano.KULLANICILAR_ANAHTARI, "ali", "hayalet", "veli")
    _yaz_hesap(depo, _hesap("ali"))
    _yaz_hesap(depo, _hesap("veli"))
    veri = _pano.hesap_verisi(depo, 1000)
    adlar = [k["ad"] for k in veri["kullanicilar"]]
    assert adlar == ["kurucu", "ali", "veli"]  # hayalet atıldı
    assert depo.komut("LRANGE", _pano.KULLANICILAR_ANAHTARI, "0", "-1") == ["ali", "veli"]


# ------------------------------------------------------------------- HTTP


def _post(site, yol, govde, cerez="", koken=None):  # noqa: F811
    basliklar = {"Content-Type": "application/json", "Cookie": cerez}
    if koken:
        basliklar["Origin"] = koken
    return _istek(f"{site}{yol}", "POST", json.dumps(govde).encode(), basliklar)


def _kurucu(site):  # noqa: F811
    return _cerez(_giris(site)[1])


def _ekle(site, cerez, ad, rol, ilk_sifre, onay=SIFRE):  # noqa: F811
    return _post(
        site,
        "/api/hesap",
        {"eylem": "ekle", "ad": ad, "rol": rol, "ilk_sifre": ilk_sifre, "sifre": onay},
        cerez,
    )


def test_kurucu_girisi_durum_oturumu_tasir(site):  # noqa: F811
    cerez = _kurucu(site)
    kod, _, govde = _istek(f"{site}/api/durum", basliklar={"Cookie": cerez})
    assert kod == 200
    veri = json.loads(govde)
    assert veri["oturum"] == {
        "ad": "kurucu",
        "rol": "yonetici",
        "rol_adi": "Yönetici",
        "kurucu": True,
        "sifre_degismeli": False,
    }
    assert veri["onizleme"] is False


def test_hesap_ekle_sonra_giris_ve_sifre_degistir(site):  # noqa: F811
    cerez = _kurucu(site)
    kod, _, govde = _ekle(site, cerez, "ahmet", "operator", "ilk-parola-123")
    assert kod == 200, govde
    # Yeni hesap sifre_degismeli: önce şifre değiştirmeden müdahale yapamaz
    kod, basliklar, _ = _giris(site, "ilk-parola-123", ad="ahmet")
    assert kod == 200
    ah_cerez = _cerez(basliklar)
    kod, _, govde = _post(site, "/api/mudahale", {"tur": "anons", "mesaj_id": 3}, ah_cerez, site)
    assert kod == 403 and json.loads(govde)["hata"] == "sifre_degismeli"
    # Şifre değiştirince yeni çerez gelir, sifre_degismeli kalkar
    kod, basliklar, govde = _post(
        site,
        "/api/hesap",
        {
            "eylem": "sifre_degistir",
            "eski_sifre": "ilk-parola-123",
            "yeni_sifre": "yeni-parola-456",
        },
        ah_cerez,
        site,
    )
    assert kod == 200, govde
    yeni_cerez = _cerez(basliklar)
    kod, _, govde = _istek(f"{site}/api/durum", basliklar={"Cookie": yeni_cerez})
    assert json.loads(govde)["oturum"]["sifre_degismeli"] is False
    # Yanlış eski şifre 400 eski_sifre (401 değil)
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {"eylem": "sifre_degistir", "eski_sifre": "yanlis", "yeni_sifre": "baska-parola-789"},
        yeni_cerez,
        site,
    )
    assert kod == 400 and json.loads(govde)["hata"] == "eski_sifre"


def test_onay_sifresi_eksik_ya_da_yanlissa_hesap_islemi_olmaz(site):  # noqa: F811
    cerez = _kurucu(site)
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {"eylem": "ekle", "ad": "veli", "rol": "izleyici", "ilk_sifre": "parola-1234"},
        cerez,
        site,
    )
    assert kod == 400 and json.loads(govde)["hata"] == "onay_sifresi"
    kod, _, govde = _ekle(site, cerez, "veli", "izleyici", "parola-1234", onay="yanlis-onay")
    assert kod == 400 and json.loads(govde)["hata"] == "onay_sifresi"


def test_ad_ve_sifre_dogrulamasi(site):  # noqa: F811
    cerez = _kurucu(site)
    assert (
        json.loads(_ekle(site, cerez, "sistem", "izleyici", "parola-1234")[2])["hata"]
        == "ad_ayrilmis"
    )
    assert (
        json.loads(_ekle(site, cerez, "Ad Soyad", "izleyici", "parola-1234")[2])["hata"]
        == "ad_gecersiz"
    )
    assert json.loads(_ekle(site, cerez, "veli", "izleyici", "kisa")[2])["hata"] == "sifre_kisa"
    assert (
        json.loads(_ekle(site, cerez, "veli", "veli", "parola-1234")[2])["hata"] == "rol"
    )  # rol geçersiz


def test_yonetici_hesabini_yalniz_kurucu_yonetir(site):  # noqa: F811
    cerez = _kurucu(site)
    # Kurucu bir yönetici açar
    assert _ekle(site, cerez, "mudur", "yonetici", "parola-mudur-1")[0] == 200
    kod, basliklar, _ = _giris(site, "parola-mudur-1", ad="mudur")
    mudur_cerez = _cerez(basliklar)
    # mudur önce kendi şifresini değiştirmeli
    _post(
        site,
        "/api/hesap",
        {"eylem": "sifre_degistir", "eski_sifre": "parola-mudur-1", "yeni_sifre": "mudur-yeni-123"},
        mudur_cerez,
        site,
    )
    kod, basliklar, _ = _giris(site, "mudur-yeni-123", ad="mudur")
    mudur_cerez = _cerez(basliklar)
    # mudur (yönetici ama kurucu değil) yeni yönetici açamaz
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {
            "eylem": "ekle",
            "ad": "baska",
            "rol": "yonetici",
            "ilk_sifre": "parola-1234",
            "sifre": "mudur-yeni-123",
        },
        mudur_cerez,
        site,
    )
    assert kod == 403 and json.loads(govde)["hata"] == "yalniz_kurucu"
    # Ama operatör açabilir
    assert (
        _post(
            site,
            "/api/hesap",
            {
                "eylem": "ekle",
                "ad": "isci",
                "rol": "operator",
                "ilk_sifre": "parola-1234",
                "sifre": "mudur-yeni-123",
            },
            mudur_cerez,
            site,
        )[0]
        == 200
    )


def test_kendi_rolunu_degistiremez(site):  # noqa: F811
    cerez = _kurucu(site)
    _ekle(site, cerez, "mudur", "yonetici", "parola-mudur-1")
    _post(
        site,
        "/api/hesap",
        {"eylem": "sifre_degistir", "eski_sifre": "parola-mudur-1", "yeni_sifre": "mudur-yeni-123"},
        _cerez(_giris(site, "parola-mudur-1", ad="mudur")[1]),
        site,
    )
    mudur_cerez = _cerez(_giris(site, "mudur-yeni-123", ad="mudur")[1])
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {"eylem": "rol", "ad": "mudur", "rol": "izleyici", "sifre": "mudur-yeni-123"},
        mudur_cerez,
        site,
    )
    assert kod == 400 and json.loads(govde)["hata"] == "kendi_hesabi"


def test_izleyici_durum_suzgeci(site):  # noqa: F811
    cerez = _kurucu(site)
    _ekle(site, cerez, "bakici", "izleyici", "parola-bakici-1")
    _post(
        site,
        "/api/hesap",
        {
            "eylem": "sifre_degistir",
            "eski_sifre": "parola-bakici-1",
            "yeni_sifre": "bakici-yeni-12",
        },
        _cerez(_giris(site, "parola-bakici-1", ad="bakici")[1]),
        site,
    )
    bakici_cerez = _cerez(_giris(site, "bakici-yeni-12", ad="bakici")[1])
    # Rapor: bilgisayar.ip/adı + yonetim
    from test_uctan_uca import RAPOR, _rapor_gonder

    _rapor_gonder(
        site,
        {
            **RAPOR,
            "bilgisayar": {"ad": "Gebze", "bilgisayar_adi": "PC-1", "ip": ["192.168.1.9"]},
            "yonetim": {
                "acik": True,
                "isler": ["teshis"],
                "kurulum": "git",
                "yeniden_baslatma": {"mumkun": True, "sebep": ""},
                "guncelleme": {"mumkun": True, "sebep": ""},
            },
        },
    )
    kod, _, govde = _istek(f"{site}/api/durum", basliklar={"Cookie": bakici_cerez})
    veri = json.loads(govde)
    assert veri["fabrika_adresi"] == ""
    assert "yonetim" not in veri["rapor"]
    assert "ip" not in veri["rapor"]["bilgisayar"]
    assert "bilgisayar_adi" not in veri["rapor"]["bilgisayar"]
    assert veri["rapor"]["bilgisayar"]["ad"] == "Gebze"  # ad gizlenmez
    # Yönetici her şeyi görür
    kod, _, govde = _istek(f"{site}/api/durum", basliklar={"Cookie": cerez})
    veri = json.loads(govde)
    assert veri["rapor"]["yonetim"]["acik"] is True
    assert veri["rapor"]["bilgisayar"]["ip"] == ["192.168.1.9"]
    assert veri["fabrika_adresi"] == "http://100.64.0.7:8080"


def test_operator_yonetim_blogunu_gormez(site):  # noqa: F811
    cerez = _kurucu(site)
    _ekle(site, cerez, "opr", "operator", "parola-opr-123")
    _post(
        site,
        "/api/hesap",
        {"eylem": "sifre_degistir", "eski_sifre": "parola-opr-123", "yeni_sifre": "opr-yeni-1234"},
        _cerez(_giris(site, "parola-opr-123", ad="opr")[1]),
        site,
    )
    opr_cerez = _cerez(_giris(site, "opr-yeni-1234", ad="opr")[1])
    from test_uctan_uca import RAPOR, _rapor_gonder

    _rapor_gonder(
        site,
        {
            **RAPOR,
            "yonetim": {
                "acik": True,
                "isler": ["teshis"],
                "kurulum": "git",
                "yeniden_baslatma": {"mumkun": True, "sebep": ""},
                "guncelleme": {"mumkun": True, "sebep": ""},
            },
        },
    )
    kod, _, govde = _istek(f"{site}/api/durum?mudahale=1", basliklar={"Cookie": opr_cerez})
    veri = json.loads(govde)
    assert "yonetim" not in veri["rapor"]
    assert "mudahale" in veri  # operatör müdahale ekranını görür


def test_get_hesap_yalniz_yonetici(site):  # noqa: F811
    cerez = _kurucu(site)
    _ekle(site, cerez, "bakici", "izleyici", "parola-bakici-1")
    _post(
        site,
        "/api/hesap",
        {
            "eylem": "sifre_degistir",
            "eski_sifre": "parola-bakici-1",
            "yeni_sifre": "bakici-yeni-12",
        },
        _cerez(_giris(site, "parola-bakici-1", ad="bakici")[1]),
        site,
    )
    bakici_cerez = _cerez(_giris(site, "bakici-yeni-12", ad="bakici")[1])
    assert _istek(f"{site}/api/hesap", basliklar={"Cookie": bakici_cerez})[0] == 403
    kod, _, govde = _istek(f"{site}/api/hesap", basliklar={"Cookie": cerez})
    assert kod == 200
    veri = json.loads(govde)
    adlar = [k["ad"] for k in veri["kullanicilar"]]
    assert adlar[0] == "kurucu" and "bakici" in adlar
    # Özet, tuz, hesap_kimligi asla dönmez
    assert all("sifre" not in k and "hesap_kimligi" not in k for k in veri["kullanicilar"])
    # İşlem kaydı: hesap_ekle ve giriş görünür
    isler = {s["is"] for s in veri["kayit"]}
    assert "hesap_ekle" in isler and "giris" in isler


def test_hesap_sil_ve_giris_durur(site):  # noqa: F811
    cerez = _kurucu(site)
    _ekle(site, cerez, "gidecek", "operator", "parola-gidecek-1")
    gidecek_cerez = _cerez(_giris(site, "parola-gidecek-1", ad="gidecek")[1])
    # Silinince oturum hemen biter
    kod, _, govde = _post(
        site, "/api/hesap", {"eylem": "sil", "ad": "gidecek", "sifre": SIFRE}, cerez, site
    )
    assert kod == 200, govde
    assert _istek(f"{site}/api/durum", basliklar={"Cookie": gidecek_cerez})[0] == 401


def test_hesap_kapat_ac(site):  # noqa: F811
    cerez = _kurucu(site)
    _ekle(site, cerez, "isci", "operator", "parola-isci-123")
    isci_cerez = _cerez(_giris(site, "parola-isci-123", ad="isci")[1])
    _post(site, "/api/hesap", {"eylem": "kapat", "ad": "isci", "sifre": SIFRE}, cerez, site)
    assert _istek(f"{site}/api/durum", basliklar={"Cookie": isci_cerez})[0] == 401
    # Kapalı hesap giriş yapamaz (aynı 401 giris_hatali)
    assert _giris(site, "parola-isci-123", ad="isci")[0] == 401
    _post(site, "/api/hesap", {"eylem": "ac", "ad": "isci", "sifre": SIFRE}, cerez, site)
    assert _giris(site, "parola-isci-123", ad="isci")[0] == 200


def test_uc_nokta_sirasi_hesap(site):  # noqa: F811
    cerez = _kurucu(site)
    # izleyici ekle denemesi: oturum yok -> 401
    assert _post(site, "/api/hesap", {"eylem": "ekle"}, "")[0] == 401
    # kurucu + yabancı köken -> 403 koken (rol izleyici-min geçtikten sonra)
    kod, _, govde = _post(site, "/api/hesap", {"eylem": "ekle"}, cerez, "https://kotu.example")
    assert kod == 403 and json.loads(govde)["hata"] == "koken"
    # form içerik türü -> 415
    kod, _, _ = _istek(
        f"{site}/api/hesap",
        "POST",
        b"eylem=ekle",
        {"Content-Type": "application/x-www-form-urlencoded", "Cookie": cerez},
    )
    assert kod == 415
    # bilinmeyen eylem -> 400 eylem
    assert (
        json.loads(_post(site, "/api/hesap", {"eylem": "patla", "sifre": SIFRE}, cerez, site)[2])[
            "hata"
        ]
        == "eylem"
    )


def test_izleyici_hesap_yonetemez_ama_sifre_degistirebilir(site):  # noqa: F811
    cerez = _kurucu(site)
    _ekle(site, cerez, "bakici", "izleyici", "parola-bakici-1")
    bakici_cerez = _cerez(_giris(site, "parola-bakici-1", ad="bakici")[1])
    # Yeni hesap sifre_degismeli: ekle denemesi önce bu engele takılır
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {
            "eylem": "ekle",
            "ad": "x",
            "rol": "izleyici",
            "ilk_sifre": "parola-1234",
            "sifre": "parola-bakici-1",
        },
        bakici_cerez,
        site,
    )
    assert kod == 403 and json.loads(govde)["hata"] == "sifre_degismeli"
    # sifre_degistir izni var (sifre_degismeli engeli sifre_degistir'e uygulanmaz)
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {
            "eylem": "sifre_degistir",
            "eski_sifre": "parola-bakici-1",
            "yeni_sifre": "bakici-yeni-12",
        },
        bakici_cerez,
        site,
    )
    assert kod == 200, govde
    # Şifre değişti; artık ekle denerse 403 yetki (sifre_degismeli kalktı)
    bakici_cerez = _cerez(_giris(site, "bakici-yeni-12", ad="bakici")[1])
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {
            "eylem": "ekle",
            "ad": "x",
            "rol": "izleyici",
            "ilk_sifre": "parola-1234",
            "sifre": "bakici-yeni-12",
        },
        bakici_cerez,
        site,
    )
    assert kod == 403 and json.loads(govde)["hata"] == "yetki"


def test_onizleme_kilidi(site, monkeypatch):  # noqa: F811
    monkeypatch.setenv("VERCEL_ENV", "preview")
    cerez = _kurucu(site)
    kod, _, govde = _istek(f"{site}/api/durum", basliklar={"Cookie": cerez})
    assert json.loads(govde)["onizleme"] is True
    # Hesap değişikliği önizlemede yapılamaz
    kod, _, govde = _ekle(site, cerez, "x", "operator", "parola-1234")
    assert kod == 409 and json.loads(govde)["hata"] == "onizleme"
    # Müdahale de yapılamaz
    from test_uctan_uca import RAPOR, _rapor_gonder

    _rapor_gonder(
        site,
        {
            **RAPOR,
            "mudahale": {
                "acik": True,
                "mesajlar": [{"id": 3, "metin": "m"}],
                "kanallar": [{"id": 1, "ad": "G", "bolum": ""}],
            },
        },
    )
    kod, _, govde = _post(site, "/api/mudahale", {"tur": "anons", "mesaj_id": 3}, cerez, site)
    assert kod == 409 and json.loads(govde)["hata"] == "onizleme"


def test_hesap_siniri(site, monkeypatch):  # noqa: F811
    monkeypatch.setattr(_pano, "HESAP_EN_COK", 1)
    cerez = _kurucu(site)
    assert _ekle(site, cerez, "bir", "operator", "parola-1234")[0] == 200
    kod, _, govde = _ekle(site, cerez, "iki", "operator", "parola-1234")
    assert kod == 409 and json.loads(govde)["hata"] == "hesap_siniri"


def test_kurucu_sifresi_burada_degismez(site):  # noqa: F811
    cerez = _kurucu(site)
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {"eylem": "sifre_degistir", "eski_sifre": SIFRE, "yeni_sifre": "yeni-kurucu-123"},
        cerez,
        site,
    )
    assert kod == 400 and json.loads(govde)["hata"] == "kurucu"


def test_cikis_oturumu_iptal_eder(site):  # noqa: F811
    cerez = _kurucu(site)
    assert _istek(f"{site}/api/durum", basliklar={"Cookie": cerez})[0] == 200
    kod, basliklar, _ = _istek(
        f"{site}/api/cikis", "POST", b"{}", {"Content-Type": "application/json", "Cookie": cerez}
    )
    assert kod == 200 and basliklar["Set-Cookie"].startswith(f"{_pano.CEREZ_ADI}=;")
    # Çıkıştan sonra aynı çerez artık geçmez (iptal edildi)
    assert _istek(f"{site}/api/durum", basliklar={"Cookie": cerez})[0] == 401


# ------------------------------------------------- sınırlar ve onay hatası


class _SahteIstek:
    def istemci_adresi(self):
        return "1.2.3.4"


def test_bes_yanlis_onay_oturumu_dusurur():
    """Aynı hesapta 15 dakikada 5 yanlış onay şifresi -> oturum sürümü artar,
    bütün oturumlar düşer (docs/19 §3.1)."""
    ayar = _ayar()
    depo = _pano.BellekDepo()
    _yaz_hesap(depo, _hesap("mudur", rol="yonetici", surum=1, sifre="dogru-onay-1"))
    oturum = _pano.Oturum("mudur", "yonetici", "1234567890abcdef", 1, False, False, "imza", 10**12)
    for _ in range(_pano.ONAY_HATA_SINIR):
        with pytest.raises(_pano.PanoHatasi) as e:
            _pano.onay_sifresi_dogrula(depo, ayar, oturum, _SahteIstek(), "yanlis")
        assert e.value.hata == "onay_sifresi"
    (ham,) = depo.al_coklu([_pano.KULLANICI_ONEKI + "mudur"])
    assert json.loads(ham)["oturum_surumu"] >= 2


def test_dogru_onay_sifresi_gecer():
    ayar = _ayar()
    depo = _pano.BellekDepo()
    _yaz_hesap(depo, _hesap("mudur", rol="yonetici", sifre="dogru-onay-1"))
    oturum = _pano.Oturum("mudur", "yonetici", "1234567890abcdef", 1, False, False, "imza", 10**12)
    _pano.onay_sifresi_dogrula(depo, ayar, oturum, _SahteIstek(), "dogru-onay-1")  # yükselmez


def test_hatali_giris_kaydi_bilinmeyen_adi_yazmaz():
    depo = _pano.BellekDepo()
    ayar = _ayar()
    _yaz_hesap(depo, _hesap("ali", sifre="dogru-sifre-1"))
    with pytest.raises(_pano.PanoHatasi):
        _pano.giris_dene(depo, ayar, "1.2.3.4", "ali", "yanlis", 1000)
    with pytest.raises(_pano.PanoHatasi):
        _pano.giris_dene(depo, ayar, "1.2.3.5", "hayalet", "yanlis", 1000)
    kimler = [
        json.loads(s)["kim"] for s in depo.komut("LRANGE", _pano.KAYIT_GIRIS_ANAHTARI, "0", "-1")
    ]
    assert "ali" in kimler  # var olan hesap yazılır
    assert "hayalet" not in kimler  # bilinmeyen ad yazılmaz
    assert "" in kimler  # bilinmeyen ad boş kim ile


def test_sifre_degistir_siniri(site, monkeypatch):  # noqa: F811
    monkeypatch.setattr(_pano, "SIFRE_DEGISTIR_SINIRI", 1)
    cerez = _kurucu(site)
    _ekle(site, cerez, "ahmet", "operator", "ilk-parola-123")
    c = _cerez(_giris(site, "ilk-parola-123", ad="ahmet")[1])
    kod, basliklar, govde = _post(
        site,
        "/api/hesap",
        {"eylem": "sifre_degistir", "eski_sifre": "ilk-parola-123", "yeni_sifre": "parola-bir-123"},
        c,
        site,
    )
    assert kod == 200, govde
    c = _cerez(basliklar)
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {"eylem": "sifre_degistir", "eski_sifre": "parola-bir-123", "yeni_sifre": "parola-iki-123"},
        c,
        site,
    )
    assert kod == 429 and json.loads(govde)["hata"] == "cok_sik"


def test_hesap_islem_siniri(site, monkeypatch):  # noqa: F811
    monkeypatch.setattr(_pano, "HESAP_ISLEM_SINIRI", 1)
    cerez = _kurucu(site)
    assert _ekle(site, cerez, "bir", "operator", "parola-1234")[0] == 200
    kod, _, govde = _ekle(site, cerez, "iki", "operator", "parola-1234")
    assert kod == 429 and json.loads(govde)["hata"] == "cok_sik"


def test_izleyici_mudahale_yapamaz(site):  # noqa: F811
    cerez = _kurucu(site)
    _ekle(site, cerez, "bakici", "izleyici", "parola-bakici-1")
    bakici_cerez = _cerez(_giris(site, "parola-bakici-1", ad="bakici")[1])
    # Rol kapısı sifre_degismeli'den önce: izleyici müdahale edemez
    kod, _, govde = _post(
        site, "/api/mudahale", {"tur": "anons", "mesaj_id": 3}, bakici_cerez, site
    )
    assert kod == 403 and json.loads(govde)["hata"] == "yetki"


def test_operator_yonetim_komutu_yapamaz(site):  # noqa: F811
    cerez = _kurucu(site)
    _ekle(site, cerez, "opr", "operator", "parola-opr-123")
    _post(
        site,
        "/api/hesap",
        {"eylem": "sifre_degistir", "eski_sifre": "parola-opr-123", "yeni_sifre": "opr-yeni-1234"},
        _cerez(_giris(site, "parola-opr-123", ad="opr")[1]),
        site,
    )
    opr_cerez = _cerez(_giris(site, "opr-yeni-1234", ad="opr")[1])
    kod, _, govde = _post(site, "/api/mudahale", {"tur": "teshis"}, opr_cerez, site)
    assert kod == 403 and json.loads(govde)["hata"] == "yetki"


# ----------------------------------------- komut_red izi (docs/19 §3.3, SITE-B1)


def _hazir_cerez(site, kurucu_cerez, ad, rol, ilk, yeni):  # noqa: F811
    """Hesabı açar, ilk şifresini değiştirir (sifre_degismeli kalkar) ve giriş
    yapıp çerezini verir: artık durum değiştiren işler denenebilir."""
    _ekle(site, kurucu_cerez, ad, rol, ilk)
    _post(
        site,
        "/api/hesap",
        {"eylem": "sifre_degistir", "eski_sifre": ilk, "yeni_sifre": yeni},
        _cerez(_giris(site, ilk, ad=ad)[1]),
        site,
    )
    return _cerez(_giris(site, yeni, ad=ad)[1])


def _kayit(site, kurucu_cerez):  # noqa: F811
    kod, _, govde = _istek(f"{site}/api/hesap", basliklar={"Cookie": kurucu_cerez})
    assert kod == 200, govde
    return json.loads(govde)["kayit"]


def test_yetkisiz_denemede_komut_red_izi_kalir(site):  # noqa: F811
    """Operatör çerezi admin uçlarını yoklarsa iz kalır: /api/hesap ekle ve
    /api/mudahale teshis 403 döner VE işlem kaydına komut_red satırı yazılır
    (docs/19 §3.3). Düzeltme öncesi kayıt boştur; bu test o yüzden kırmızıdır."""
    cerez = _kurucu(site)
    opr_cerez = _hazir_cerez(site, cerez, "opr", "operator", "parola-opr-123", "opr-yeni-1234")
    # Operatör hesap ekleyemez (403 yetki) - admin ucu yoklaması
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {"eylem": "ekle", "ad": "x", "rol": "izleyici", "ilk_sifre": "parola-1234", "sifre": "x"},
        opr_cerez,
        site,
    )
    assert kod == 403 and json.loads(govde)["hata"] == "yetki"
    # Operatör yönetim komutu (teshis) isteyemez (403 yetki)
    kod, _, govde = _post(site, "/api/mudahale", {"tur": "teshis"}, opr_cerez, site)
    assert kod == 403 and json.loads(govde)["hata"] == "yetki"
    # İşlem kaydında iki komut_red satırı (kurucu GET /api/hesap ile görür)
    redler = [s for s in _kayit(site, cerez) if s["is"] == "komut_red"]
    assert len(redler) == 2
    assert all(s["sonuc"] == "red" and s["kim"] == "opr" and s["rol"] == "operator" for s in redler)
    ozetler = " ".join(s["ozet"] for s in redler)
    assert "ekle" in ozetler and "teshis" in ozetler


def test_izleyici_mudahale_denemesi_komut_red_izi_birakir(site):  # noqa: F811
    """İzleyicinin /api/mudahale denemesi rol kapısında (403 yetki) reddedilir VE
    işlem kaydına tek bir komut_red satırı yazılır (docs/19 §3.3: reddedilen her
    deneme kayda geçer). Sıra aynı: oturumsuz istek 401 alır ve iz bırakmaz; rol
    kapısı kökenden önce gelir."""
    cerez = _kurucu(site)
    _ekle(site, cerez, "bakici", "izleyici", "parola-bakici-1")
    bakici_cerez = _cerez(_giris(site, "parola-bakici-1", ad="bakici")[1])
    istek = {"tur": "anons", "mesaj_id": 3}
    assert _post(site, "/api/mudahale", istek, "", site)[0] == 401
    kod, _, govde = _post(site, "/api/mudahale", istek, bakici_cerez, site)
    assert kod == 403 and json.loads(govde)["hata"] == "yetki"
    redler = [s for s in _kayit(site, cerez) if s["is"] == "komut_red"]
    assert [(s["kim"], s["rol"], s["sonuc"], s["ozet"]) for s in redler] == [
        ("bakici", "izleyici", "red", "Yetki yetmedi: müdahale")
    ]
    kod, _, govde = _post(site, "/api/mudahale", istek, bakici_cerez, "https://kotu.example")
    assert kod == 403 and json.loads(govde)["hata"] == "yetki"  # yetki kökenden önce
    assert len([s for s in _kayit(site, cerez) if s["is"] == "komut_red"]) == 2


def test_yalniz_kurucu_denemesi_komut_red_izi_kalir(site):  # noqa: F811
    """Kurucu olmayan bir yöneticinin yönetici açma denemesi 403 yalniz_kurucu
    döner VE komut_red izi bırakır (docs/19 §3.3). Düzeltme öncesi iz yok."""
    cerez = _kurucu(site)
    mudur_cerez = _hazir_cerez(site, cerez, "mudur", "yonetici", "parola-mudur-1", "mudur-yeni-123")
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {
            "eylem": "ekle",
            "ad": "baska",
            "rol": "yonetici",
            "ilk_sifre": "parola-1234",
            "sifre": "mudur-yeni-123",
        },
        mudur_cerez,
        site,
    )
    assert kod == 403 and json.loads(govde)["hata"] == "yalniz_kurucu"
    redler = [s for s in _kayit(site, cerez) if s["is"] == "komut_red"]
    assert any(
        s["kim"] == "mudur" and s["rol"] == "yonetici" and s["sonuc"] == "red" for s in redler
    )


def test_komut_red_akini_sinirlanir(site, monkeypatch):  # noqa: F811
    """komut_red kaydı sel gibi doldurulamaz: hesap başına pencere başına en çok
    KOMUT_RED_SINIRI satır yazılır, fazlası toplanır (docs/19 §3.3)."""
    monkeypatch.setattr(_pano, "KOMUT_RED_SINIRI", 3, raising=False)
    cerez = _kurucu(site)
    opr_cerez = _hazir_cerez(site, cerez, "opr", "operator", "parola-opr-123", "opr-yeni-1234")
    for _ in range(5):  # 5 yetkisiz deneme, sınır 3
        kod, _, govde = _post(site, "/api/mudahale", {"tur": "teshis"}, opr_cerez, site)
        assert kod == 403 and json.loads(govde)["hata"] == "yetki"
    redler = [s for s in _kayit(site, cerez) if s["is"] == "komut_red"]
    assert len(redler) == 3  # fazlası toplandı


# ------------------------------------ hesap kaydı yazma kilidi (SITE-B2, CAS yerine)


def test_hesap_kaydi_kilidi_eszamanli_rol_yazmayi_engeller(site, monkeypatch):  # noqa: F811
    """Aynı hesaba eşzamanlı iki yazma birbirini ezmesin (docs/19 SITE-B2):
    kayıt kilidi başka bir işlemce tutulurken rol değişikliği 409 mesgul alır ve
    rol değişmez (lost update olmaz); kilit boşalınca işlem geçer ve bitince kilit
    bırakılır. Düzeltme öncesi kilit yok: ilk istek 200 döner, test kırmızıdır."""
    monkeypatch.setattr(_pano, "HESAP_KILIT_DENEME", 1, raising=False)  # testte beklemesiz
    cerez = _kurucu(site)
    _ekle(site, cerez, "isci", "operator", "parola-isci-123")
    kilit = _pano.KULLANICI_KILIT_ONEKI + "isci"
    # Başka bir işlem hesabı kilitlemiş gibi: kilit anahtarını elle tut
    _pano.DEPO.komut("SET", kilit, "1")
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {"eylem": "rol", "ad": "isci", "rol": "izleyici", "sifre": SIFRE},
        cerez,
        site,
    )
    assert kod == 409 and json.loads(govde)["hata"] == "mesgul"
    (ham,) = _pano.DEPO.al_coklu([_pano.KULLANICI_ONEKI + "isci"])
    assert json.loads(ham)["rol"] == "operator"  # yazma hiç yapılmadı (lost update yok)
    # Kilit boşalınca işlem geçer ve bitince kilidini bırakır
    _pano.DEPO.sil(kilit)
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {"eylem": "rol", "ad": "isci", "rol": "izleyici", "sifre": SIFRE},
        cerez,
        site,
    )
    assert kod == 200, govde
    (ham,) = _pano.DEPO.al_coklu([_pano.KULLANICI_ONEKI + "isci"])
    assert json.loads(ham)["rol"] == "izleyici"
    assert _pano.DEPO.al_coklu([kilit]) == [None]  # kilit bırakıldı


def test_sifre_degistir_kaydi_kilidi_tutulur(site, monkeypatch):  # noqa: F811
    """Kişinin kendi şifre değişikliği de kayıt kilidi altında (docs/19 SITE-B2):
    kilit tutulurken 409 mesgul. Düzeltme öncesi 200 dönerdi, test kırmızıdır."""
    monkeypatch.setattr(_pano, "HESAP_KILIT_DENEME", 1, raising=False)
    cerez = _kurucu(site)
    _ekle(site, cerez, "opr", "operator", "parola-opr-123")
    c = _cerez(_giris(site, "parola-opr-123", ad="opr")[1])
    _pano.DEPO.komut("SET", _pano.KULLANICI_KILIT_ONEKI + "opr", "1")
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {"eylem": "sifre_degistir", "eski_sifre": "parola-opr-123", "yeni_sifre": "opr-yeni-1234"},
        c,
        site,
    )
    assert kod == 409 and json.loads(govde)["hata"] == "mesgul"
