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
import time
from pathlib import Path

import _pano
import pytest
from test_hesap import _ekle, _hazir_cerez, _hesap, _kayit, _kurucu, _post, _yaz_hesap
from test_uctan_uca import RAPOR, SIFRE, _istek, _rapor_gonder, site  # noqa: F401

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
    """public/pano.js'teki GORUNUM_YETKISI arka uçtaki EKRAN_YETKISI'nin birebir
    aynısı olmalı: ekranı gizleyip ucu açık bırakmak (ya da tersi) iki tabloyu
    birden değiştirmeden olmasın."""
    assert _js_tablosu("GORUNUM_YETKISI") == _pano.EKRAN_YETKISI
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


# ------------------------------------------------ rol yetkilerinin TANIMI (§1)


def test_varsayilan_yetkiler_bugunku_davranisin_aynisi():
    """En önemli denetim: hiçbir ayar yapılmamış sitede yetki kümeleri eski
    tabloların (GORUNUM_EN_AZ_ROL, KOMUT_EN_AZ_ROL) söylediğinin birebir aynısı
    olmalı. Bu test kırmızıysa ayarlanabilir yetki, ayar yapılmadan davranışı
    değiştirmiş demektir."""
    v = _pano.VARSAYILAN_YETKILER
    assert set(v) == set(_pano.ROLLER)
    assert v["izleyici"] == frozenset()
    assert v["operator"] == frozenset(
        {"ekran.mudahale", "komut.anons", "komut.ses_dene", "komut.olay_incele", "veri.bilgisayar"}
    )
    assert v["yonetici"] == frozenset(_pano.YETKILER)
    # Katalog ile tablolar örtüşür: her komut türünün ve yetki isteyen her
    # ekranın anahtarı katalogda var
    for tur in _pano.KOMUT_TURLERI:
        assert "komut." + tur in _pano.YETKILER, tur
    for yetki in _pano.EKRAN_YETKISI.values():
        assert yetki in _pano.YETKILER, yetki
    assert set(_pano.YETKI_ADLARI) == set(_pano.YETKILER)
    assert [y for _, grup in _pano.YETKI_GRUPLARI for y in grup].sort() == list(
        _pano.YETKILER
    ).sort()


def test_yetki_kumesi_duzelt_tanimsizi_atar_kilitliyi_zorlar():
    d = _pano.yetki_kumesi_duzelt
    # Tanınmayan anahtar atılır
    assert d(["komut.anons", "uydurma.yetki"], "operator") == frozenset({"komut.anons"})
    # Kilitli yetki operatöre verilemez
    assert d(["hesap.yonet", "ekran.kullanicilar", "komut.anons"], "operator") == frozenset(
        {"komut.anons"}
    )
    # Kilitli yetki yöneticiden alınamaz
    assert _pano.KILITLI_YETKILER <= d([], "yonetici")
    # Liste değilse varsayılana düşer (bozuk kayıt yetki AÇMAZ)
    for bozuk in (None, "hepsi", {"a": 1}, 5):
        assert d(bozuk, "operator") == _pano.VARSAYILAN_YETKILER["operator"], bozuk
        assert d(bozuk, "izleyici") == frozenset(), bozuk


def test_rol_yetkileri_coz_bozuk_kayitta_varsayilana_duser():
    c = _pano.rol_yetkileri_coz
    assert c(None) == _pano.VARSAYILAN_YETKILER
    assert c("{bozuk json") == _pano.VARSAYILAN_YETKILER
    assert c("[]") == _pano.VARSAYILAN_YETKILER
    # Yalnız gönderilen rol değişir, ötekiler varsayılanda kalır
    cozum = c(json.dumps({"izleyici": ["ekran.mudahale"]}))
    assert cozum["izleyici"] == frozenset({"ekran.mudahale"})
    assert cozum["operator"] == _pano.VARSAYILAN_YETKILER["operator"]
    assert cozum["yonetici"] == _pano.VARSAYILAN_YETKILER["yonetici"]
    # Bilinmeyen rol yok sayılır
    assert "patron" not in c(json.dumps({"patron": ["hesap.yonet"]}))


def test_yetkileri_kaydet_varsayilani_yazmaz():
    """Varsayılanla aynı olan rol kayda girmez; hepsi varsayılana dönerse
    anahtar silinir (ayar yapılmamış siteyle aynı hâle gelir)."""
    depo = _pano.BellekDepo()
    tablo = dict(_pano.VARSAYILAN_YETKILER)
    assert _pano.yetkileri_kaydet(depo, tablo) == {}
    assert depo.al_coklu([_pano.ROL_YETKILERI_ANAHTARI]) == [None]
    tablo["operator"] = frozenset({"komut.anons"})
    kayit = _pano.yetkileri_kaydet(depo, tablo)
    assert kayit == {"operator": ["komut.anons"]}
    assert _pano.rol_yetkileri_oku(depo)["operator"] == frozenset({"komut.anons"})
    # Geri alınca anahtar silinir
    _pano.yetkileri_kaydet(depo, dict(_pano.VARSAYILAN_YETKILER))
    assert depo.al_coklu([_pano.ROL_YETKILERI_ANAHTARI]) == [None]


# ------------------------------------------------------------- uçtan uca


def _yetki_yaz(site, cerez, yetkiler, sifre=SIFRE):  # noqa: F811
    return _post(
        site,
        "/api/hesap",
        {"eylem": "rol_yetkileri", "yetkiler": yetkiler, "sifre": sifre},
        cerez,
        site,
    )


def test_yetki_tanimini_yalniz_kurucu_degistirir(site):  # noqa: F811
    """Ayar yönetici yetkisini de kapsar: çalınan bir yönetici hesabı kendi
    rolüne yeni yetki açamasın diye yalnız kurucuya açıktır; deneme kayda girer."""
    cerez = _kurucu(site)
    yon = _hazir_cerez(site, cerez, "patron", "yonetici", "parola-patron-1", "patron-yeni-1")
    kod, _, govde = _yetki_yaz(site, yon, {"izleyici": ["ekran.mudahale"]}, "patron-yeni-1")
    assert kod == 403 and json.loads(govde)["hata"] == "yalniz_kurucu", govde
    redler = [s for s in _kayit(site, cerez) if s["is"] == "komut_red"]
    assert any("rol_yetkileri" in s["ozet"] for s in redler)
    # Tanım değişmedi
    kod, _, govde = _istek(f"{site}/api/hesap", basliklar={"Cookie": cerez})
    roller = {r["id"]: r["yetkiler"] for r in json.loads(govde)["yetki"]["roller"]}
    assert roller["izleyici"] == []


def test_operatore_teshis_yetkisi_verilince_teshis_alabilir(site):  # noqa: F811
    """Tanımın gerçekten işe yaradığı yer: operatör varsayılanda teşhis alamaz;
    kurucu yetkiyi verince alabilir, geri alınca yine alamaz. Yetki her istekte
    okunduğu için oturum düşürmeye gerek yok."""
    cerez = _kurucu(site)
    opr = _hazir_cerez(site, cerez, "opr", "operator", "parola-opr-123", "opr-yeni-1234")
    _rapor_gonder(
        site,
        {
            **RAPOR,
            "yonetim": {
                "acik": True,
                "isler": ["teshis"],
                "kurulum": "git",
                "yeniden_baslatma": {"mumkun": False, "sebep": ""},
                "guncelleme": {"mumkun": False, "sebep": ""},
            },
        },
    )
    kod, _, govde = _post(site, "/api/mudahale", {"tur": "teshis"}, opr, site)
    assert kod == 403 and json.loads(govde)["hata"] == "yetki", govde

    varsayilan = sorted(_pano.VARSAYILAN_YETKILER["operator"])
    kod, _, govde = _yetki_yaz(site, cerez, {"operator": [*varsayilan, "komut.teshis"]})
    assert kod == 200 and json.loads(govde)["degisti"] is True, govde
    kod, _, govde = _post(site, "/api/mudahale", {"tur": "teshis"}, opr, site)
    assert kod == 200, govde  # aynı oturum, yeni yetki

    kod, _, govde = _yetki_yaz(site, cerez, {"operator": varsayilan})
    assert kod == 200, govde
    kod, _, govde = _post(site, "/api/mudahale", {"tur": "teshis"}, opr, site)
    assert kod == 403 and json.loads(govde)["hata"] == "yetki"


def test_yetkisi_alinan_operator_hic_mudahale_edemez(site):  # noqa: F811
    """Bütün komut yetkileri alınınca kaba kapı gövdeyi okumadan 403 verir ve
    deneme kayda girer (sıra docs/19 §3.4: yetki, sifre_degismeli'den önce)."""
    cerez = _kurucu(site)
    opr = _hazir_cerez(site, cerez, "opr", "operator", "parola-opr-123", "opr-yeni-1234")
    assert _yetki_yaz(site, cerez, {"operator": ["ekran.mudahale", "veri.bilgisayar"]})[0] == 200
    kod, _, govde = _post(site, "/api/mudahale", {"tur": "anons", "mesaj_id": 3}, opr, site)
    assert kod == 403 and json.loads(govde)["hata"] == "yetki", govde
    assert any(s["is"] == "komut_red" and s["kim"] == "opr" for s in _kayit(site, cerez))


def test_izleyiciye_mudahale_ekrani_acilabilir(site):  # noqa: F811
    """İzleyiciye ekran.mudahale verilince müdahale seçeneklerini (hazır anons,
    kanallar) görür; komut yetkisi verilmediği için yine komut gönderemez."""
    cerez = _kurucu(site)
    bakici = _hazir_cerez(site, cerez, "bakici", "izleyici", "parola-bakici-1", "bakici-yeni-1")
    _rapor_gonder(site, {**RAPOR, "mudahale": _MUDAHALE_BLOGU})
    kod, _, govde = _istek(f"{site}/api/durum", basliklar={"Cookie": bakici})
    assert json.loads(govde)["rapor"]["mudahale"]["mesajlar"] == []

    assert _yetki_yaz(site, cerez, {"izleyici": ["ekran.mudahale"]})[0] == 200
    kod, _, govde = _istek(f"{site}/api/durum?mudahale=1", basliklar={"Cookie": bakici})
    veri = json.loads(govde)
    assert [m["metin"] for m in veri["rapor"]["mudahale"]["mesajlar"]] == ["Baret takınız"]
    assert "mudahale" in veri  # ekranın son komut listesi de gelir
    assert veri["oturum"]["yetkiler"] == ["ekran.mudahale"]
    # Ama komut gönderemez: ekran yetkisi komut yetkisi değildir
    kod, _, govde = _post(site, "/api/mudahale", {"tur": "anons", "mesaj_id": 3}, bakici, site)
    assert kod == 403 and json.loads(govde)["hata"] == "yetki"


def test_kilitli_yetkiler_ayarla_tasinmaz(site):  # noqa: F811
    """Hesap yönetimi ve Kullanıcılar ekranı ayarla başka role verilemez,
    yöneticiden de alınamaz: site kendini kilitleyemez."""
    cerez = _kurucu(site)
    opr = _hazir_cerez(site, cerez, "opr", "operator", "parola-opr-123", "opr-yeni-1234")
    assert _yetki_yaz(site, cerez, {"operator": ["hesap.yonet", "ekran.kullanicilar"]})[0] == 200
    # Operatör hâlâ hesap listesini göremez ve hesap açamaz
    assert _istek(f"{site}/api/hesap", basliklar={"Cookie": opr})[0] == 403
    kod, _, govde = _post(
        site,
        "/api/hesap",
        {
            "eylem": "ekle",
            "ad": "yeni",
            "rol": "izleyici",
            "ilk_sifre": "parola-1234",
            "sifre": "x",
        },
        opr,
        site,
    )
    assert kod == 403 and json.loads(govde)["hata"] == "yetki"
    # Yöneticiden alınamaz
    assert _yetki_yaz(site, cerez, {"yonetici": ["komut.anons"]})[0] == 200
    kod, _, govde = _istek(f"{site}/api/hesap", basliklar={"Cookie": cerez})
    roller = {r["id"]: r["yetkiler"] for r in json.loads(govde)["yetki"]["roller"]}
    assert set(_pano.KILITLI_YETKILER) <= set(roller["yonetici"])


def test_yetkisi_kalkan_hesabin_bekleyen_komutu_teslim_edilmez(site):  # noqa: F811
    """Komut kuyrukta beklerken yetki tanımı değişirse komut gönderilmez
    (docs/19 §3.5): teslim kararı o anki tanımla verilir."""
    cerez = _kurucu(site)
    opr = _hazir_cerez(site, cerez, "opr", "operator", "parola-opr-123", "opr-yeni-1234")
    _rapor_gonder(site, {**RAPOR, "mudahale": _MUDAHALE_BLOGU})
    kod, _, govde = _post(
        site, "/api/mudahale", {"tur": "anons", "mesaj_id": 3, "kanal_id": 1}, opr, site
    )
    assert kod == 200, govde
    assert _yetki_yaz(site, cerez, {"operator": ["ekran.mudahale"]})[0] == 200
    teslim, _ = _pano.komutlari_teslim_et(_pano.DEPO, time.time())
    assert teslim == []
    assert any(s["is"] == "komut_dustu" for s in _kayit(site, cerez))


def test_yetki_degisikligi_isleme_kaydina_gecer(site):  # noqa: F811
    cerez = _kurucu(site)
    assert _yetki_yaz(site, cerez, {"izleyici": ["ekran.mudahale"]})[0] == 200
    satir = next(s for s in _kayit(site, cerez) if s["is"] == "rol_yetkileri")
    assert satir["kim"] == "kurucu" and satir["sonuc"] == "tamam"
    assert "İzleyici" in satir["ozet"]
    # Değişiklik yoksa kayıt yazılmaz
    assert (
        json.loads(_yetki_yaz(site, cerez, {"izleyici": ["ekran.mudahale"]})[2])["degisti"] is False
    )
    assert len([s for s in _kayit(site, cerez) if s["is"] == "rol_yetkileri"]) == 1


def test_yetki_yazimi_onay_sifresi_ister(site):  # noqa: F811
    cerez = _kurucu(site)
    kod, _, govde = _yetki_yaz(site, cerez, {"izleyici": ["ekran.mudahale"]}, "yanlis-sifre")
    assert kod == 400 and json.loads(govde)["hata"] == "onay_sifresi", govde
    kod, _, govde = _post(
        site, "/api/hesap", {"eylem": "rol_yetkileri", "yetkiler": {}, "sifre": SIFRE}, cerez, site
    )
    assert kod == 400 and json.loads(govde)["hata"] == "yetkiler"
