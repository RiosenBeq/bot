"""Rol ve yetki sisteminin tek kaynağı (docs/19 §1): yetki tabloları, merdiven,
uçtaki kapılar ve rol süzgeci.

Buradaki testler "yetki nerede yazılı" sorusunu bağlar: rol merdiveni ROLLER'in
sırasından türer, her komut türünün en az rolü KOMUT_EN_AZ_ROL'de, her ekranın
en az rolü GORUNUM_EN_AZ_ROL'de durur ve ön yüz (public/pano.js) aynı iki
tabloyu taşır. Tabloya girmemiş bir iş hiçbir role açılmaz.

Hesap yaşam döngüsünün kendisi tests/test_hesap.py'de; burası yalnız yetkidir.
"""

import json
import re
from pathlib import Path

import _pano
import pytest
from test_hesap import _ekle, _hazir_cerez, _hesap, _kayit, _kurucu, _post, _yaz_hesap
from test_uctan_uca import RAPOR, _istek, _rapor_gonder, site  # noqa: F401

PANO_JS = (Path(__file__).resolve().parents[1] / "public" / "pano.js").read_text(encoding="utf-8")
# `ad: 0` ya da `ad: "metin"` çiftleri (tek ya da çok satırlı JS nesnesi)
CIFT_DESENI = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?:"([^"]*)"|(\d+))')


def _js_tablosu(ad: str) -> dict:
    """public/pano.js'teki `const <ad> = { ... };` nesnesini sözlük olarak okur."""
    bas = PANO_JS.index("const " + ad + " = {")
    govde = PANO_JS[bas : PANO_JS.index("};", bas)]
    return {
        anahtar: metin if sayi == "" else int(sayi)
        for anahtar, metin, sayi in CIFT_DESENI.findall(govde)
    }


# ---------------------------------------------------------------- tablolar


def test_rol_merdiveni_rollerden_turer():
    """ROL_SIRASI elle yazılmaz: ROLLER'in sırasıdır (izleyici < operator < yonetici)."""
    assert _pano.ROL_SIRASI == {"izleyici": 0, "operator": 1, "yonetici": 2}
    assert list(_pano.ROL_SIRASI) == list(_pano.ROLLER)
    assert set(_pano.ROL_ADLARI) == set(_pano.ROLLER)


def test_rol_yeterli_mi_merdiven():
    assert _pano.rol_yeterli_mi("yonetici", "izleyici")
    assert _pano.rol_yeterli_mi("yonetici", "yonetici")
    assert _pano.rol_yeterli_mi("operator", "operator")
    assert not _pano.rol_yeterli_mi("operator", "yonetici")
    assert not _pano.rol_yeterli_mi("izleyici", "operator")


def test_rol_yeterli_mi_tanimsizda_yetmez():
    """Açıkta kalan varsayılan yok: tanınmayan rol ve tanınmayan eşik yetmez."""
    for rol in ("", "patron", None, 3, True):
        assert not _pano.rol_yeterli_mi(rol, "izleyici"), rol
    for en_az in ("", "patron", "kurucu"):
        assert not _pano.rol_yeterli_mi("yonetici", en_az), en_az


def test_her_komut_turunun_en_az_rolu_yazili():
    """Yeni bir iş KOMUT_TURLERI'ne girip burada sınıflanmazsa test kırmızı olur:
    sınıflanmamış iş kendiliğinden operatöre açılmasın."""
    assert set(_pano.KOMUT_EN_AZ_ROL) == set(_pano.KOMUT_TURLERI)
    assert set(_pano.KOMUT_EN_AZ_ROL.values()) <= set(_pano.ROLLER)


def test_yonetim_ve_mudahale_isleri_tabloyla_tutarli():
    """YONETIM_TURLERI tablodan türer; MUDAHALE_ISLERI (raporda bildirilen açık
    işler) kalanların aynısıdır: iki liste KOMUT_TURLERI'ni tam böler."""
    assert _pano.YONETIM_TURLERI == tuple(
        t for t in _pano.KOMUT_TURLERI if _pano.KOMUT_EN_AZ_ROL[t] == "yonetici"
    )
    assert set(_pano.MUDAHALE_ISLERI) | set(_pano.YONETIM_TURLERI) == set(_pano.KOMUT_TURLERI)
    assert not set(_pano.MUDAHALE_ISLERI) & set(_pano.YONETIM_TURLERI)
    assert all(_pano.KOMUT_EN_AZ_ROL[t] == "operator" for t in _pano.MUDAHALE_ISLERI)
    # Ağır işler yönetim işlerinin alt kümesidir (onay şifresi isteyenler)
    assert set(_pano.AGIR_TURLERI) <= set(_pano.YONETIM_TURLERI)


def test_rol_yeterli_tabloya_girmemis_turu_kimseye_acmaz():
    """Düzeltme öncesi yönetim dışı HER tür operatöre açıktı (varsayılan izin);
    şimdi varsayılan reddir."""
    for rol in _pano.ROLLER:
        assert not _pano._rol_yeterli(rol, "bilinmeyen_is")
        assert not _pano._rol_yeterli(rol, "")
    assert _pano._rol_yeterli("operator", "anons")
    assert not _pano._rol_yeterli("operator", "guncelle")
    assert _pano._rol_yeterli("yonetici", "guncelle")


def test_ekran_tablosu_butun_gorunumleri_kapsar():
    assert set(_pano.GORUNUM_EN_AZ_ROL.values()) <= set(_pano.ROLLER)
    # Yetki isteyen üç ekran ve serbest dördü (docs/19 §1)
    assert _pano.GORUNUM_EN_AZ_ROL["mudahale"] == "operator"
    for ekran in ("yonetim", "kullanicilar", "tesisler"):
        assert _pano.GORUNUM_EN_AZ_ROL[ekran] == "yonetici"
    for ekran in ("genel", "kameralar", "olaylar", "sistem"):
        assert _pano.GORUNUM_EN_AZ_ROL[ekran] == "izleyici"


def test_on_yuz_tablolari_arka_ucun_aynisi():
    """public/pano.js'teki ROL_SIRASI ve GORUNUM_ROLU arka uçtakilerle birebir
    aynı olmalı: ekranı gizleyip ucu açık bırakmak (ya da tersi) iki tabloyu
    birden değiştirmeden olmasın."""
    assert _js_tablosu("ROL_SIRASI") == _pano.ROL_SIRASI
    assert _js_tablosu("GORUNUM_ROLU") == _pano.GORUNUM_EN_AZ_ROL
    assert _js_tablosu("ROL_ADLARI") == _pano.ROL_ADLARI


# ------------------------------------------------- izleyici müdahale süzgeci


def _izleyici_cerez(site, kurucu_cerez):  # noqa: F811
    return _hazir_cerez(
        site, kurucu_cerez, "bakici", "izleyici", "parola-bakici-1", "bakici-yeni-1"
    )


_MUDAHALE_BLOGU = {
    "acik": True,
    "isler": ["anons", "ses_dene", "olay_incele"],
    "mesajlar": [{"id": 3, "metin": "Baret takınız"}],
    "kanallar": [{"id": 1, "ad": "Sevkiyat hoparlörü", "bolum": "Sevkiyat"}],
}


def test_izleyici_mudahale_seceneklerini_gormez(site):  # noqa: F811
    """En az yetki: İzleyici Müdahale ekranını hiç açamaz, bu yüzden hazır anons
    metinleri ve hoparlör kanalları tele de çıkmaz. Blok biçimi aynı kalır
    (`acik`, `isler` durur; listeler boşalır) ki ekran kodu bozulmasın."""
    cerez = _kurucu(site)
    bakici_cerez = _izleyici_cerez(site, cerez)
    _rapor_gonder(site, {**RAPOR, "mudahale": _MUDAHALE_BLOGU})
    kod, _, govde = _istek(f"{site}/api/durum", basliklar={"Cookie": bakici_cerez})
    assert kod == 200, govde
    mudahale = json.loads(govde)["rapor"]["mudahale"]
    assert mudahale["mesajlar"] == [] and mudahale["kanallar"] == []
    assert mudahale["acik"] is True and mudahale["isler"] == ["anons", "ses_dene", "olay_incele"]


def test_operator_mudahale_seceneklerini_gorur(site):  # noqa: F811
    """Süzgeç yalnız izleyiciye: operatör ve yönetici seçenekleri görmeye devam eder."""
    cerez = _kurucu(site)
    opr_cerez = _hazir_cerez(site, cerez, "opr", "operator", "parola-opr-123", "opr-yeni-1234")
    _rapor_gonder(site, {**RAPOR, "mudahale": _MUDAHALE_BLOGU})
    for c in (opr_cerez, cerez):
        kod, _, govde = _istek(f"{site}/api/durum", basliklar={"Cookie": c})
        assert kod == 200, govde
        mudahale = json.loads(govde)["rapor"]["mudahale"]
        assert [m["metin"] for m in mudahale["mesajlar"]] == ["Baret takınız"]
        assert [k["ad"] for k in mudahale["kanallar"]] == ["Sevkiyat hoparlörü"]


def test_izleyici_filo_ve_yonetim_sorgusunu_zorlayamaz(site):  # noqa: F811
    """`?mudahale=1`, `?yonetim=1` ve `?filo=1` rolle kapalı: izleyici sorguyu
    elle eklese de blok gelmez (ekran gizli, uç da kapalı)."""
    cerez = _kurucu(site)
    bakici_cerez = _izleyici_cerez(site, cerez)
    _rapor_gonder(site, {**RAPOR, "mudahale": _MUDAHALE_BLOGU})
    adres = f"{site}/api/durum?mudahale=1&yonetim=1&filo=1"
    kod, _, govde = _istek(adres, basliklar={"Cookie": bakici_cerez})
    assert kod == 200, govde
    veri = json.loads(govde)
    assert "mudahale" not in veri and "filo" not in veri and "yonetim" not in veri["rapor"]


def test_operator_filo_gormez_mudahale_gorur(site):  # noqa: F811
    cerez = _kurucu(site)
    opr_cerez = _hazir_cerez(site, cerez, "opr", "operator", "parola-opr-123", "opr-yeni-1234")
    _rapor_gonder(site, {**RAPOR, "mudahale": _MUDAHALE_BLOGU})
    adres = f"{site}/api/durum?mudahale=1&filo=1"
    kod, _, govde = _istek(adres, basliklar={"Cookie": opr_cerez})
    assert kod == 200, govde
    veri = json.loads(govde)
    assert "mudahale" in veri and "filo" not in veri


# ------------------------------------------------- yetkisiz GET'in izi (§3.3)


def test_get_hesap_yetkisiz_denemesi_komut_red_izi_birakir(site):  # noqa: F811
    """GET /api/hesap bütün hesapları ve işlem kaydını döker: yetkisi yetmeyen
    deneme POST'lardaki gibi kayda geçer (docs/19 §3.3). Düzeltme öncesi yalnız
    403 dönüyordu ve çalınan bir çerez bu ucu iz bırakmadan yokluyordu."""
    cerez = _kurucu(site)
    opr_cerez = _hazir_cerez(site, cerez, "opr", "operator", "parola-opr-123", "opr-yeni-1234")
    kod, _, govde = _istek(f"{site}/api/hesap", basliklar={"Cookie": opr_cerez})
    assert kod == 403 and json.loads(govde)["hata"] == "yetki"
    redler = [s for s in _kayit(site, cerez) if s["is"] == "komut_red"]
    assert len(redler) == 1
    assert redler[0]["kim"] == "opr" and redler[0]["rol"] == "operator"
    assert "hesap listesi" in redler[0]["ozet"] and redler[0]["sonuc"] == "red"


def test_yetkili_get_hesap_iz_birakmaz(site):  # noqa: F811
    cerez = _kurucu(site)
    _ekle(site, cerez, "opr", "operator", "parola-opr-123")
    assert [s for s in _kayit(site, cerez) if s["is"] == "komut_red"] == []


# --------------------------------------- kendi hesabına hesap işi yapılamaz


def test_kendi_hesabina_hesap_isi_yapilamaz(site):  # noqa: F811
    """Kurucu bile kendi satırına hesap işi yapamaz; bir yöneticinin kendi
    hesabına yeni şifre vermesi de "kendi_hesabi" ile durur (eskiden yalnız
    "yönetici hesabına yalnız kurucu dokunur" kuralının yan etkisiyle duruyordu)."""
    cerez = _kurucu(site)
    yon_cerez = _hazir_cerez(site, cerez, "patron", "yonetici", "parola-patron-1", "patron-yeni-1")
    for eylem, ek in (
        ("sifre_sifirla", {"yeni_sifre": "yepyeni-sifre-1"}),
        ("ac", {}),
        ("kapat", {}),
        ("rol", {"rol": "izleyici"}),
        ("sil", {}),
    ):
        govde = {"eylem": eylem, "ad": "patron", "sifre": "patron-yeni-1", **ek}
        kod, _, cevap = _post(site, "/api/hesap", govde, yon_cerez, site)
        assert kod == 400, (eylem, kod, cevap)
        assert json.loads(cevap)["hata"] == "kendi_hesabi", (eylem, cevap)


# ------------------------- rol düşürme eşzamanlı yazımla kaybolmaz (SITE-B2)


def test_oturum_surumu_arttirma_hesap_kilidini_alir(monkeypatch):
    """Oturum sürümünü artıran oku-değiştir-yaz artık kilit altında: kilit
    başkasındayken yazım HİÇ yapılmaz (409 mesgul). Düzeltme öncesi kilitsizdi
    ve eşzamanlı bir rol düşürmeyi geri yazabiliyordu."""
    monkeypatch.setattr(_pano, "HESAP_KILIT_DENEME", 1, raising=False)
    depo = _pano.BellekDepo()
    _yaz_hesap(depo, _hesap("isci", rol="operator", surum=1))
    kilit = _pano.KULLANICI_KILIT_ONEKI + "isci"
    depo.komut("SET", kilit, "1")  # başka bir işlem rolü yazıyor
    with pytest.raises(_pano.PanoHatasi) as hata:
        _pano._oturum_surumu_arttir(depo, "isci")
    assert hata.value.kod == 409 and hata.value.hata == "mesgul"
    (ham,) = depo.al_coklu([_pano.KULLANICI_ONEKI + "isci"])
    assert json.loads(ham)["oturum_surumu"] == 1  # yazım yapılmadı
    depo.sil(kilit)
    _pano._oturum_surumu_arttir(depo, "isci")
    (ham,) = depo.al_coklu([_pano.KULLANICI_ONEKI + "isci"])
    kayit = json.loads(ham)
    assert kayit["oturum_surumu"] == 2 and kayit["rol"] == "operator"
    assert depo.al_coklu([kilit]) == [None]  # kilit bırakıldı


def test_hesap_kilidi_yeniden_girilebilir(monkeypatch):
    """Kilit altındaki yollar (kendi şifresini değiştirme, iki adımı kapatma)
    yanlış şifrede _oturum_surumu_arttir'ı çağırır: aynı istek aynı kilidi
    yeniden isteyince kendi kendini 409'a düşürmemeli."""
    monkeypatch.setattr(_pano, "HESAP_KILIT_DENEME", 1, raising=False)
    depo = _pano.BellekDepo()
    _yaz_hesap(depo, _hesap("opr", surum=1))
    kilit = _pano.KULLANICI_KILIT_ONEKI + "opr"
    with _pano._hesap_kilidi(depo, "opr"):
        assert depo.al_coklu([kilit]) == ["1"]
        _pano._oturum_surumu_arttir(depo, "opr")  # iç içe: bir şey yapmaz, yazar
        assert depo.al_coklu([kilit]) == ["1"]  # dıştaki kilit duruyor
    (ham,) = depo.al_coklu([_pano.KULLANICI_ONEKI + "opr"])
    assert json.loads(ham)["oturum_surumu"] == 2
    assert depo.al_coklu([kilit]) == [None]  # yalnız dıştaki `with` bıraktı


def test_bes_yanlis_onay_rol_yazmasini_ezmez(site, monkeypatch):  # noqa: F811
    """Uçtan uca: bir hesabın rolü yazılırken (kilit tutuluyor) o hesaptan
    beşinci yanlış onay şifresi gelirse oturum sürümü yazımı eski kaydı GERİ
    YAZMAZ; istek 409 mesgul alır ve kayıt el değmemiş kalır."""
    monkeypatch.setattr(_pano, "HESAP_KILIT_DENEME", 1, raising=False)
    cerez = _kurucu(site)
    opr_cerez = _hazir_cerez(site, cerez, "opr", "operator", "parola-opr-123", "opr-yeni-1234")
    (once,) = _pano.DEPO.al_coklu([_pano.KULLANICI_ONEKI + "opr"])
    for _ in range(_pano.ONAY_HATA_SINIR - 1):  # dört yanlış birikmiş
        _pano.DEPO.say(_pano.ONAY_HATA_ONEKI + "opr", _pano.ONAY_HATA_SURESI_SN)
    _pano.DEPO.komut("SET", _pano.KULLANICI_KILIT_ONEKI + "opr", "1")
    kod, _, govde = _post(
        site, "/api/hesap", {"eylem": "iki_adim_baslat", "sifre": "yanlis"}, opr_cerez, site
    )
    assert kod == 409 and json.loads(govde)["hata"] == "mesgul", govde
    (sonra,) = _pano.DEPO.al_coklu([_pano.KULLANICI_ONEKI + "opr"])
    assert sonra == once  # kayıt hiç yazılmadı (lost update yok)
