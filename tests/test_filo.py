"""Çoklu fabrika / filo görünümü (öneri 10, docs/20 §4).

Tesissiz rapor bugünkü gibi davranır (aynı Redis komutları, aynı cevap). Tesis
kullanılınca tek bir ana tesis vardır: yalnız o panonun durumunu yazar ve komut
alır; öbürleri yalnız kütüğe yazılır ve izlenir. Komut asla yanlış fabrikaya
gitmez. /api/durum?filo=1 yalnız yöneticiye açıktır."""

import json
import re
import time
from pathlib import Path

import _pano
import pytest
from test_cekirdek import Saat, _ayar, _rapor
from test_hesap import _hesap, _yaz_hesap
from test_komut import YON, _veri
from test_uctan_uca import (  # noqa: F401
    ANAHTAR,
    RAPOR,
    _cerez,
    _giris,
    _istek,
    _rapor_gonder,
    site,
)

KOK = Path(__file__).resolve().parents[1]
PANO_JS = (KOK / "public" / "pano.js").read_text(encoding="utf-8")
PANO_HTML = (KOK / "public" / "pano.html").read_text(encoding="utf-8")
T0 = 1_800_000_000.0


class KayitliDepo(_pano.BellekDepo):
    """Depoya giden her çağrıyı sırasıyla kaydeder: tek komut da bir listedir."""

    def __init__(self, saat):
        super().__init__(saat)
        self.cagrilar = []

    def komut(self, *parcalar):
        self.cagrilar.append([[str(p) for p in parcalar]])
        return super().komut(*parcalar)

    def boru_hatti(self, komutlar):
        self.cagrilar.append([[str(p) for p in k] for k in komutlar])
        return super().boru_hatti(komutlar)


def _tesisli(kimlik, ad=None, **degisen):
    return _rapor(tesis={"id": kimlik, "ad": ad or kimlik.capitalize()}, **degisen)


def _kaydet(depo, ham, simdi, ayar=None):
    return _pano.rapor_kaydet(depo, _pano.rapor_temizle(ham), simdi, ayar or _ayar())


def _bugunku_komutlar(rapor, simdi):
    """Tesis özelliğinden ÖNCEKİ rapor_kaydet'in gönderdiği komutlar (canlı site)."""
    kayit = json.dumps({"rapor": rapor}, ensure_ascii=False, separators=(",", ":"))
    return [
        ["SET", "dalsan:durum", kayit, "EX", "604800"],
        ["SET", "dalsan:son_rapor", str(int(simdi))],
        [
            "MGET",
            "dalsan:mudahale:izleyen",
            "dalsan:komut:isaret",
            "dalsan:kare:izleyen",
            "dalsan:fotolar",
        ],
    ]


# ------------------------------------------------- tesissiz rapor: bugünkü gibi


def test_tesissiz_rapor_bugunku_komutlarin_aynisini_gonderir():
    rapor = _pano.rapor_temizle(_rapor())
    assert "tesis" not in rapor
    ayarlar = (
        None,
        _ayar(),
        _pano.ayar_oku({"PANO_SIFRESI": "x" * 12, "RAPOR_ANAHTARI": "k" * 40}),
        _ayar(ana_tesis="gebze"),  # filo ayarı tesissiz raporu değiştirmez
    )
    for ayar in ayarlar:
        depo = KayitliDepo(Saat(T0))
        cevap = _pano.rapor_kaydet(depo, rapor, T0, ayar)
        assert depo.cagrilar == [_bugunku_komutlar(rapor, T0)]
        assert set(cevap) == {"komut", "kare", "foto"}


def test_bekci_acikken_tesissiz_rapor_isareti_ayni_okumada_okur_yalniz_varsa_siler():
    """BEKCI=acik rapor başına komut eklemez (30 sn'de bir DEL ayda ~86 bin komut
    olurdu): işaret raporun zaten yaptığı MGET'in beşinci anahtarıdır. DEL yalnız
    işaret varsa (kesintiden sonraki ilk taze rapor) gider ve işaret kalkar."""
    rapor = _pano.rapor_temizle(_rapor())
    ayar = _ayar(bekci="acik")
    depo = KayitliDepo(Saat(T0))
    _pano.rapor_kaydet(depo, rapor, T0, ayar)
    beklenen = _bugunku_komutlar(rapor, T0)
    beklenen[2] = [*beklenen[2], "dalsan:bekci:uyarildi"]
    assert depo.cagrilar == [beklenen]

    depo.komut("SET", "dalsan:bekci:uyarildi", "1")  # bekçi bu kesinti için uyardı
    depo.cagrilar.clear()
    cevap = _pano.rapor_kaydet(depo, rapor, T0 + 30, ayar)
    assert depo.cagrilar == [
        _bugunku_komutlar(rapor, T0 + 30)[:2] + [beklenen[2]],
        [["DEL", "dalsan:bekci:uyarildi"]],
    ]
    assert depo.komut("GET", "dalsan:bekci:uyarildi") is None
    assert set(cevap) == {"komut", "kare", "foto"}


def test_rapor_alan_uc_bekci_ayarini_rapor_kaydete_verir(site, monkeypatch):  # noqa: F811
    """Canlıda işaret gerçekten silinmeli: /api/rapor ayarı rapor_kaydet'e geçirir."""
    monkeypatch.setenv("BEKCI", "acik")
    _pano.DEPO.komut("SET", "dalsan:bekci:uyarildi", "1")
    assert _rapor_gonder(site, RAPOR)[0] == 200
    assert _pano.DEPO.komut("GET", "dalsan:bekci:uyarildi") is None


@pytest.mark.parametrize("ham", [None, {}, {"id": ""}, {"id": None, "ad": "Gebze"}])
def test_tesis_yoksa_ya_da_kimliksizse_anahtar_hic_girmez(ham):
    assert "tesis" not in _pano.rapor_temizle(_rapor(tesis=ham))


@pytest.mark.parametrize(
    "ham",
    ["Gebze", {"id": "Gebze"}, {"id": "-gebze"}, {"id": "a" * 33}, {"id": 5}, ["gebze"], 7],
)
def test_bozuk_tesis_kimligi_reddedilir(ham):
    """Kimlik yazılmış ama bozuksa sessizce tek fabrika sayılmaz (komut yanlış
    fabrikaya gidebilirdi): rapor 400 ile reddedilir, program hatayı gösterir."""
    with pytest.raises(_pano.PanoHatasi) as hata:
        _pano.rapor_temizle(_rapor(tesis=ham))
    assert hata.value.kod == 400
    assert "UZAK_PANO_TESIS_ID" in hata.value.mesaj


def test_tesis_suzulur_ve_kisaltilir():
    temiz = _pano.rapor_temizle(_rapor(tesis={"id": "gebze", "ad": "G" * 200, "fazla": 1}))
    assert temiz["tesis"] == {"id": "gebze", "ad": "G" * 80}
    assert _pano.rapor_temizle(_rapor(tesis="izmir"))["tesis"] == {"id": "izmir", "ad": "izmir"}
    assert _pano.rapor_temizle(_rapor(tesis={"id": "t_1-a"}))["tesis"]["ad"] == "t_1-a"


def test_ana_tesis_ayari_okunur():
    assert _pano.ayar_oku({}).ana_tesis == ""
    assert _pano.ayar_oku({"ANA_TESIS": " Gebze "}).ana_tesis == "gebze"


def test_ana_tesis_turkce_harfle_yazilabilir_gecersizse_yok_sayilir_ve_uyarilir():
    """ANA_TESIS="İzmir" sessizce etkisiz kalmasın ("İ".lower() i ve U+0307 verir):
    Türkçe harfler kimliğe çevrilir. Kimlik olamayan değer yok sayılır (ilk rapor
    veren ana olur) ve Tesisler ekranı yöneticiyi uyarır."""
    assert _pano.ayar_oku({"ANA_TESIS": "İzmir"}).ana_tesis == "izmir"
    assert _pano.ayar_oku({"ANA_TESIS": " ÇAĞLAYAN "}).ana_tesis == "caglayan"
    assert _pano.ayar_oku({"ANA_TESIS": "Şile_Ünye-Iğdır"}).ana_tesis == "sile_unye-igdir"
    assert _pano.ayar_oku({}).ana_tesis_gecersiz is False
    for ham in ("İzmir fabrikası", "-izmir", "a" * 33, "izmir!"):
        hatali = _pano.ayar_oku({"ANA_TESIS": ham})
        assert (hatali.ana_tesis, hatali.ana_tesis_gecersiz) == ("", True), ham

    depo = _pano.BellekDepo(Saat(T0))
    turkce = _pano.ayar_oku({"ANA_TESIS": "İzmir"})
    assert _kaydet(depo, _tesisli("gebze"), T0, turkce) == {"filo": {"ana": False}}
    assert _kaydet(depo, _tesisli("izmir"), T0 + 5, turkce)["filo"] == {"ana": True}
    assert _pano.filo_verisi(depo, turkce, T0 + 5)["uyarilar"] == []

    depo = _pano.BellekDepo(Saat(T0))
    hatali = _pano.ayar_oku({"ANA_TESIS": "İzmir fabrikası"})
    assert _kaydet(depo, _tesisli("gebze"), T0, hatali)["filo"] == {"ana": True}
    filo = _pano.filo_verisi(depo, hatali, T0)
    assert filo["ana_tesis"] == "gebze"
    assert filo["uyarilar"] == [_pano.ANA_TESIS_GECERSIZ_METNI]
    assert "ANA_TESIS" in filo["uyarilar"][0] and "yok sayılıyor" in filo["uyarilar"][0]


# ------------------------------------------------------------ tek ana tesis


def test_ilk_tesis_ana_olur_ikincisi_yalniz_izler():
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    cevap = _kaydet(depo, _tesisli("gebze"), T0)
    assert cevap["filo"] == {"ana": True}
    assert {"komut", "kare", "foto"} <= set(cevap)
    once = depo.al_coklu(["dalsan:durum", "dalsan:son_rapor"])
    assert json.loads(once[0])["rapor"]["tesis"]["id"] == "gebze"

    saat.simdi += 10
    cevap = _kaydet(depo, _tesisli("izmir", sayilar={"bugun_ihlal": 9}), saat.simdi)
    # Yalnız izleyen tesis: komut / kare / fotoğraf anahtarı YOK (program sormaz)
    assert cevap == {"filo": {"ana": False}}
    assert depo.al_coklu(["dalsan:durum", "dalsan:son_rapor"]) == once

    filo = _pano.filo_verisi(depo, _ayar(), saat.simdi)
    assert filo["ana_tesis"] == "gebze"
    satirlar = {s["id"]: s for s in filo["tesisler"]}
    assert set(satirlar) == {"gebze", "izmir"}
    assert satirlar["gebze"]["ana"] is True and satirlar["izmir"]["ana"] is False
    izmir = satirlar["izmir"]
    assert izmir["ad"] == "Izmir" and izmir["bugun_ihlal"] == 9
    assert izmir["baglanti"] == "canli" and izmir["gecikme_sn"] == 0
    assert izmir["son_rapor"] == _pano._iso(saat.simdi)
    assert filo["tesisler"][0]["id"] == "gebze"  # ana tesis başta


def test_ana_tesis_ayari_onceliklidir():
    depo = _pano.BellekDepo(Saat(T0))
    ayar = _ayar(ana_tesis="izmir")
    assert _kaydet(depo, _tesisli("gebze"), T0, ayar) == {"filo": {"ana": False}}
    assert depo.komut("GET", "dalsan:durum") is None
    cevap = _kaydet(depo, _tesisli("izmir"), T0 + 5, ayar)
    assert cevap["filo"] == {"ana": True} and "komut" in cevap
    assert _pano.filo_verisi(depo, ayar, T0 + 5)["ana_tesis"] == "izmir"
    # Ayar kaldırılsa da izmir ana kalır: depodaki işaret ayarla eşlenmiştir
    assert _kaydet(depo, _tesisli("gebze"), T0 + 6) == {"filo": {"ana": False}}


def test_ana_tesisin_kaydi_dusunce_siradaki_devralir():
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    assert _kaydet(depo, _tesisli("gebze"), T0)["filo"] == {"ana": True}
    saat.simdi = T0 + 3600
    assert _kaydet(depo, _tesisli("izmir"), saat.simdi) == {"filo": {"ana": False}}
    # gebze 7 gündür rapor göndermiyor: kütük kaydı düştü, izmir devralır
    saat.simdi = T0 + _pano.TESIS_SAKLAMA_SN + 1
    assert depo.komut("GET", "dalsan:tesis:gebze") is None
    cevap = _kaydet(depo, _tesisli("izmir"), saat.simdi)
    assert cevap["filo"] == {"ana": True} and "komut" in cevap
    # gebze geri gelince yalnız izler; komut artık izmir'e gider
    assert _kaydet(depo, _tesisli("gebze"), saat.simdi + 30) == {"filo": {"ana": False}}


def test_eski_program_canliyken_tesis_ana_olmaz():
    """Tesis kimliği yazılmamış (eski) program canlı rapor gönderirken bir tesis
    ana olsaydı iki fabrika birden komut alırdı: tesis yalnız izler."""
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    _kaydet(depo, _rapor(), T0)
    assert _kaydet(depo, _tesisli("izmir"), T0 + 10) == {"filo": {"ana": False}}
    filo = _pano.filo_verisi(depo, _ayar(), T0 + 10)
    assert filo["ana_tesis"] is None
    ana = [s for s in filo["tesisler"] if s["ana"]]
    assert len(ana) == 1 and ana[0]["id"] == "" and ana[0]["baglanti"] == "canli"
    # Eski program sustu (bağlantı yok): tesis ana olur
    saat.simdi = T0 + 200
    assert _kaydet(depo, _tesisli("izmir"), saat.simdi)["filo"] == {"ana": True}


# ---------------- tek komut alan: kimliksiz (eski) program canlıyken tesis ana değil


def _panodaki(depo):
    """Panonun durumunu en son kim yazdı: tesis kimliği ya da "" (eski program)."""
    rapor = json.loads(depo.komut("GET", "dalsan:durum"))["rapor"]
    return (rapor.get("tesis") or {}).get("id", "")


def test_ana_tesis_ayari_olsa_da_eski_program_canliyken_tesis_ana_olmaz():
    """ANA_TESIS yazılıyken de kural aynı: kimliksiz program canlı rapor
    gönderdiği sürece komutları o alır; ayardaki tesis panoyu ezmez, yalnız
    izlenir. Eski program susunca ayardaki tesis ana olur."""
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _ayar(ana_tesis="izmir")
    _kaydet(depo, _rapor(), T0, ayar)  # gebze: eski program canlı
    assert _kaydet(depo, _tesisli("izmir"), T0 + 10, ayar) == {"filo": {"ana": False}}
    assert _panodaki(depo) == ""
    assert depo.komut("GET", "dalsan:ana_tesis") is None
    _kaydet(depo, _rapor(), T0 + 20, ayar)
    assert _kaydet(depo, _tesisli("izmir"), T0 + 30, ayar) == {"filo": {"ana": False}}
    assert _panodaki(depo) == ""
    saat.simdi = T0 + 200  # eski program sustu
    assert _kaydet(depo, _tesisli("izmir"), saat.simdi, ayar)["filo"] == {"ana": True}
    assert _panodaki(depo) == "izmir"


def test_tesis_ana_olduktan_sonra_eski_program_gelirse_komutu_eski_program_alir():
    """izmir ana olmuşken ikinci fabrikada kimliksiz program başlar: izmir artık
    ana değildir (panoyu sırayla ezmezler); işaret durur, eski program susunca
    izmir yeniden ana olur."""
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    assert _kaydet(depo, _tesisli("izmir"), T0)["filo"] == {"ana": True}
    _kaydet(depo, _rapor(), T0 + 10)  # ikinci fabrikadaki eski program
    assert _kaydet(depo, _tesisli("izmir"), T0 + 20) == {"filo": {"ana": False}}
    assert _panodaki(depo) == ""
    assert depo.komut("GET", "dalsan:ana_tesis") == "izmir"
    saat.simdi = T0 + 200
    assert _kaydet(depo, _tesisli("izmir"), saat.simdi)["filo"] == {"ana": True}
    assert _panodaki(depo) == "izmir"


def test_eski_program_yeniden_baslayip_kimliksiz_donerse_komutu_yine_o_alir():
    """Eski program olağan yeniden başlatmada kapanış raporu gönderir; o arada
    izmir ana olur. Eski program kimliksiz geri gelince izmir bırakır: komut
    alan ve panoyu yazan yine tek fabrikadır."""
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _ayar()
    _kaydet(depo, _rapor(), T0, ayar)
    assert _kaydet(depo, _tesisli("izmir"), T0 + 10, ayar) == {"filo": {"ana": False}}
    _kaydet(depo, _rapor(kapanis=True), T0 + 20, ayar)  # gebze yeniden başlıyor
    assert _kaydet(depo, _tesisli("izmir"), T0 + 25, ayar)["filo"] == {"ana": True}
    _kaydet(depo, _rapor(), T0 + 60, ayar)  # gebze geri geldi, hâlâ kimliksiz
    assert _kaydet(depo, _tesisli("izmir"), T0 + 70, ayar) == {"filo": {"ana": False}}
    assert _panodaki(depo) == ""
    filo = _pano.filo_verisi(depo, ayar, T0 + 70)
    assert [(s["id"], s["ana"]) for s in filo["tesisler"]] == [("", True), ("izmir", False)]


def test_filo_eski_program_canliyken_onu_komut_alan_gosterir_ve_uyarir():
    """Tesisler ekranı komutu gerçekten alanı gösterir: canlı eski program "Ana
    tesis - komut alır" satırıdır, her tesis yalnız izlenir ve yönetici uyarılır.
    Tek fabrikalı kurulumda (tesis kimliği hiç yok) uyarı çıkmaz."""
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    tek = _rapor(bilgisayar={"ad": "Gebze fabrikası"})
    _kaydet(depo, tek, T0)
    assert _pano.filo_verisi(depo, _ayar(), T0)["uyarilar"] == []

    ayar = _ayar(ana_tesis="izmir")
    _kaydet(depo, _tesisli("izmir"), T0 + 5, ayar)
    _kaydet(depo, tek, T0 + 10, ayar)
    filo = _pano.filo_verisi(depo, ayar, T0 + 12)
    assert [(s["id"], s["ad"], s["ana"]) for s in filo["tesisler"]] == [
        ("", "Gebze fabrikası", True),
        ("izmir", "Izmir", False),
    ]
    assert filo["uyarilar"] == [_pano.ESKI_PROGRAM_METNI]
    assert "komutları o alıyor" in filo["uyarilar"][0]
    assert "UZAK_PANO_TESIS_ID" in filo["uyarilar"][0]
    # Pano da aynı fabrikayı gösterir: ekrandaki ile komut alan aynıdır
    assert _pano.pano_verisi(depo, ayar, T0 + 12)["rapor"]["bilgisayar"]["ad"] == "Gebze fabrikası"
    # Eski program susunca uyarı kalkar; ayardaki tesis ana görünür
    filo = _pano.filo_verisi(depo, ayar, T0 + 300)
    assert filo["uyarilar"] == []
    assert [(s["id"], s["ana"]) for s in filo["tesisler"]] == [("izmir", True)]


def test_tesis_raporu_ek_istek_atmaz_isareti_kutuk_okumasinda_okur():
    """Eski program denetimi (panonun durumu) ve tesisin bekçi işareti kütük
    yazımıyla aynı boru hattında okunur: ana tesis 2 istekte 10 komut, öbür
    tesis 1 istekte 6 komut. DEL yalnız işaret varsa gider (ana tesiste pano
    boru hattında, öbüründe tek komut) ve taze rapor işareti kaldırır."""
    ayar = _ayar(bekci="acik")
    depo = KayitliDepo(Saat(T0))
    _kaydet(depo, _tesisli("gebze"), T0, ayar)  # ilk rapor sahiplenir
    _kaydet(depo, _tesisli("izmir"), T0, ayar)
    depo.cagrilar.clear()
    _kaydet(depo, _tesisli("gebze"), T0 + 30, ayar)
    assert [len(istek) for istek in depo.cagrilar] == [6, 4]
    _kaydet(depo, _tesisli("izmir"), T0 + 30, ayar)
    assert [len(istek) for istek in depo.cagrilar] == [6, 4, 6]
    assert not any(k[0] == "DEL" for istek in depo.cagrilar for k in istek)

    for kimlik in ("gebze", "izmir"):
        depo.komut("SET", f"dalsan:bekci:uyarildi:{kimlik}", "1")
    depo.cagrilar.clear()
    _kaydet(depo, _tesisli("gebze"), T0 + 60, ayar)
    assert len(depo.cagrilar) == 2
    assert ["DEL", "dalsan:bekci:uyarildi:gebze"] in depo.cagrilar[1]
    depo.cagrilar.clear()
    _kaydet(depo, _tesisli("izmir"), T0 + 60, ayar)
    assert depo.cagrilar[1:] == [[["DEL", "dalsan:bekci:uyarildi:izmir"]]]
    for kimlik in ("gebze", "izmir"):
        assert depo.komut("GET", f"dalsan:bekci:uyarildi:{kimlik}") is None

    # ANA_TESIS yazılıyken öbür tesis panonun durumunu okumaz (bekçi kapalı: 5 komut)
    depo = KayitliDepo(Saat(T0))
    _kaydet(depo, _tesisli("gebze"), T0, _ayar(ana_tesis="izmir"))
    assert [len(istek) for istek in depo.cagrilar] == [5]
    assert "dalsan:durum" not in {p for istek in depo.cagrilar for k in istek for p in k}


def test_tesis_kutugu_sinirlidir():
    depo = _pano.BellekDepo(Saat(T0))
    for sira in range(_pano.TESIS_EN_COK + 5):
        _kaydet(depo, _tesisli(f"t{sira}"), T0 + sira)
    assert depo.komut("LLEN", "dalsan:tesisler") == _pano.TESIS_EN_COK
    assert len(_pano.filo_verisi(depo, _ayar(), T0 + 100)["tesisler"]) == _pano.TESIS_EN_COK


def test_bos_kutukte_bugunku_fabrika_tek_satir():
    depo = _pano.BellekDepo(Saat(T0))
    bos = _pano.filo_verisi(depo, _ayar(), T0)
    assert bos["ana_tesis"] is None
    assert [(s["id"], s["ana"], s["baglanti"]) for s in bos["tesisler"]] == [("", True, "hic")]
    _kaydet(depo, _rapor(bilgisayar={"ad": "Gebze fabrikası"}), T0)
    satir = _pano.filo_verisi(depo, _ayar(), T0 + 10)["tesisler"][0]
    assert satir["ad"] == "Gebze fabrikası" and satir["bugun_ihlal"] == 3


# ----------------------------------------------------------- /api/komut


def _yokla(site, tesis, nonce="cd" * 16):  # noqa: F811
    govde_d = {"surum": 1, "nonce": nonce, "sonuclar": [], "bilinmeyen": {"x": 1}}
    if tesis is not None:
        govde_d["tesis"] = tesis
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


def test_yalniz_izleyen_tesis_komut_alamaz(site):  # noqa: F811
    assert _rapor_gonder(site, {**RAPOR, "tesis": {"id": "gebze", "ad": "Gebze"}})[0] == 200
    kod, _, govde = _rapor_gonder(site, {**RAPOR, "tesis": {"id": "izmir", "ad": "İzmir"}})
    cevap = json.loads(govde)
    assert kod == 200 and cevap["filo"] == {"ana": False} and cevap["tamam"] is True
    assert not {"komut", "kare", "foto"} & set(cevap)

    depo = _pano.DEPO
    komut = _pano.komut_olustur(depo, _veri(), {"tur": "ses_dene", "kanal_id": 1}, time.time(), YON)
    kod, basliklar, ham = _yokla(site, {"id": "izmir"})
    cevap = json.loads(ham)
    assert kod == 200
    assert cevap["komutlar"] == [] and cevap["hizli"] is False and cevap["alinan"] == []
    assert cevap["nonce"] == "cd" * 16 and cevap["filo"] == {"ana": False}
    # Cevap yine imzalıdır (program imzasız cevabı yok sayar)
    _pano.imza_dogrula(
        ANAHTAR, basliklar[_pano.ZAMAN_BASLIGI], basliklar[_pano.IMZA_BASLIGI], ham, time.time()
    )
    assert depo.komut("LLEN", _pano.KOMUT_SIRA_ANAHTARI) == 1  # hiçbir şey çekilmedi

    cevap = json.loads(_yokla(site, "gebze")[2])
    assert [k["id"] for k in cevap["komutlar"]] == [komut["id"]]
    assert cevap["filo"] == {"ana": True}


@pytest.mark.parametrize("ayarla", [True, False], ids=["ANA_TESIS", "isaret"])
def test_eski_program_canliyken_komut_yalniz_ona_gider(site, monkeypatch, ayarla):  # noqa: F811
    """Kuyruktaki komut iki fabrikaya birden gitmez: kimliksiz program canlıyken
    tesis (ANA_TESIS ayarıyla ya da önceden sahiplendiği işaretle ana olsa da)
    boş cevap alır ve kuyruktan hiçbir şey çekmez; komutu eski program alır."""
    izmir = {**RAPOR, "tesis": {"id": "izmir", "ad": "İzmir"}}
    if ayarla:
        monkeypatch.setenv("ANA_TESIS", "izmir")
    else:
        assert json.loads(_rapor_gonder(site, izmir)[2])["filo"] == {"ana": True}
    assert _rapor_gonder(site, RAPOR)[0] == 200  # ikinci fabrika: eski program canlı
    kod, _, govde = _rapor_gonder(site, izmir)
    assert kod == 200 and json.loads(govde)["filo"] == {"ana": False}

    depo = _pano.DEPO
    komut = _pano.komut_olustur(depo, _veri(), {"tur": "ses_dene", "kanal_id": 1}, time.time(), YON)
    cevap = json.loads(_yokla(site, {"id": "izmir"})[2])
    assert cevap["komutlar"] == [] and cevap["hizli"] is False
    assert cevap["filo"] == {"ana": False}
    assert depo.komut("LLEN", _pano.KOMUT_SIRA_ANAHTARI) == 1  # hiçbir şey çekilmedi
    cevap = json.loads(_yokla(site, None)[2])
    assert [k["id"] for k in cevap["komutlar"]] == [komut["id"]] and "filo" not in cevap


def test_tesissiz_komut_sorusu_bugunku_gibi(site):  # noqa: F811
    cevap = json.loads(_yokla(site, None)[2])
    assert set(cevap) == {"tamam", "nonce", "alinan", "komutlar", "hizli"}


def test_komut_sorusunda_bozuk_tesis_reddedilir(site):  # noqa: F811
    kod, _, govde = _yokla(site, {"id": "İzmir"})
    assert kod == 400 and json.loads(govde)["hata"] == "tesis"


# ---------------------------------------------------- /api/durum?filo=1


def test_filo_verisi_yalniz_yoneticiye(site):  # noqa: F811
    kurucu = _cerez(_giris(site)[1])
    kod, _, govde = _istek(f"{site}/api/durum?filo=1", basliklar={"Cookie": kurucu})
    filo = json.loads(govde)["filo"]
    assert kod == 200 and filo["ana_tesis"] is None
    assert len(filo["tesisler"]) == 1 and filo["tesisler"][0]["ana"] is True

    _rapor_gonder(site, {**RAPOR, "tesis": {"id": "gebze", "ad": "Gebze"}})
    _rapor_gonder(site, {**RAPOR, "tesis": {"id": "izmir", "ad": "İzmir"}})
    filo = json.loads(_istek(f"{site}/api/durum?filo=1", basliklar={"Cookie": kurucu})[2])["filo"]
    assert filo["ana_tesis"] == "gebze"
    assert [(s["id"], s["ana"]) for s in filo["tesisler"]] == [("gebze", True), ("izmir", False)]
    assert "filo" not in json.loads(_istek(f"{site}/api/durum", basliklar={"Cookie": kurucu})[2])

    for ad, rol in (("izci", "izleyici"), ("opr", "operator")):
        _yaz_hesap(_pano.DEPO, _hesap(ad, rol=rol))
        cerez = _cerez(_giris(site, "dogru-sifre-1", ad=ad)[1])
        kod, _, govde = _istek(f"{site}/api/durum?filo=1", basliklar={"Cookie": cerez})
        assert kod == 200 and "filo" not in json.loads(govde), rol


# ----------------------------------------------------------------- ön yüz


def test_tesisler_gorunumu_yalniz_yoneticide_ve_sekme_degil():
    assert re.search(r'tesisler:\s*\["Tesisler"', PANO_JS)
    rol = re.search(r"const GORUNUM_ROLU = \{([^}]*)\}", PANO_JS).group(1)
    assert 'tesisler: "yonetici"' in rol
    # rolUygula yönetici olmayanda menü öğesini gizler
    assert '.menu-ogesi[data-gorunum="tesisler"]' in PANO_JS
    menu = re.search(r'<a class="menu-ogesi"[^>]*data-gorunum="tesisler"[^>]*>', PANO_HTML)
    assert menu and " hidden" in menu.group(0)
    assert '<div class="gorunum" data-gorunum="tesisler" hidden>' in PANO_HTML
    # Telefon sekme çubuğu 5 sekme kalır
    assert PANO_HTML.count('class="sekme"') == 5
    assert 'class="sekme" href="#tesisler"' not in PANO_HTML
    # Filo verisi yalnız görünüm açıkken istenir
    assert "/api/durum?filo=1" in PANO_JS
    assert 'aktifGorunum === "tesisler"' in PANO_JS
    assert "ANA_TESIS" in PANO_HTML


def test_tesisler_gorunumu_uyarilari_metin_olarak_gosterir():
    """Sunucunun uyarıları (eski program canlı, ANA_TESIS geçersiz) Tesisler
    görünümünde yalnız textContent ile yazılır; uyarı yoksa kutu gizlidir."""
    gorunum = re.search(
        r'<div class="gorunum" data-gorunum="tesisler" hidden>.*?\n        </div>', PANO_HTML, re.S
    ).group(0)
    assert '<p id="tesis-uyarisi" class="site-uyarisi" hidden></p>' in gorunum
    ciz = re.search(r"function tesisleriCiz\(filo\) \{.*?\n  \}", PANO_JS, re.S).group(0)
    assert "filo.uyarilar" in ciz
    assert re.search(r'\$\("tesis-uyarisi"\)', ciz)
    assert ".textContent = " in ciz and ".hidden = " in ciz


# ------------------------- aynı tesis kimliği iki bilgisayarda (SONRA-YAPILACAKLAR B3)

CAKISMA_UYARISI = (
    "Aynı tesis kimliği iki bilgisayardan geliyor: gebze (Gebze fabrikası · DALSAN-PC, "
    "Gebze fabrikası · ISG-PC-02). Her bilgisayara farklı UZAK_PANO_TESIS_ID yazın."
)


def _bilgisayarli(kimlik, bilgisayar_adi, ad="Gebze fabrikası", **degisen):
    return _tesisli(kimlik, bilgisayar={"ad": ad, "bilgisayar_adi": bilgisayar_adi}, **degisen)


def test_tesis_ozeti_raporun_bilgisayarini_tasir():
    depo = _pano.BellekDepo(Saat(T0))
    _kaydet(depo, _bilgisayarli("gebze", "DALSAN-PC"), T0)
    ozet = json.loads(depo.komut("GET", "dalsan:tesis:gebze"))
    assert ozet["bilgisayar"] == "Gebze fabrikası · DALSAN-PC"
    _kaydet(depo, _tesisli("izmir"), T0)  # bilgisayar bilgisi göndermeyen program
    assert json.loads(depo.komut("GET", "dalsan:tesis:izmir"))["bilgisayar"] == ""


def test_ayni_kimlik_iki_bilgisayardan_gelirse_uyarir_ve_satirda_rozet_cikar():
    """Bir bilgisayarın .env'i öbürüne kopyalanınca ikisi aynı kimliği gönderir.
    Önceki özet hâlâ canlıyken başka bir bilgisayardan rapor gelirse çakışma
    yazılır (iki ad + zaman); filo uyarısı ve satır rozeti çıkar. İkisi
    göndermeyi sürdürdükçe tazelenir; biri susunca yaklaşık bir saatte kalkar."""
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _ayar()
    _kaydet(depo, _bilgisayarli("gebze", "DALSAN-PC"), T0, ayar)
    _kaydet(depo, _bilgisayarli("izmir", "IZMIR-PC", ad="İzmir fabrikası"), T0, ayar)
    saat.simdi = T0 + 15
    _kaydet(depo, _bilgisayarli("gebze", "ISG-PC-02"), saat.simdi, ayar)
    filo = _pano.filo_verisi(depo, ayar, saat.simdi)
    assert filo["uyarilar"] == [CAKISMA_UYARISI]
    satirlar = {s["id"]: s for s in filo["tesisler"]}
    assert satirlar["gebze"]["cakisma"] == {
        "adlar": ["Gebze fabrikası · DALSAN-PC", "Gebze fabrikası · ISG-PC-02"],
        "zaman": _pano._iso(saat.simdi),
    }
    assert "cakisma" not in satirlar["izmir"]

    saat.simdi += 15
    _kaydet(depo, _bilgisayarli("gebze", "DALSAN-PC"), saat.simdi, ayar)  # sıra öbüründe
    son_cakisma = saat.simdi
    for _ in range(3):  # ISG-PC-02 sustu, yalnız DALSAN-PC gönderiyor
        saat.simdi += 30
        _kaydet(depo, _bilgisayarli("gebze", "DALSAN-PC"), saat.simdi, ayar)
    assert _pano.filo_verisi(depo, ayar, saat.simdi)["uyarilar"] == [CAKISMA_UYARISI]
    saat.simdi = son_cakisma + _pano.TESIS_CAKISMA_SN + 1
    _kaydet(depo, _bilgisayarli("gebze", "DALSAN-PC"), saat.simdi, ayar)
    filo = _pano.filo_verisi(depo, ayar, saat.simdi)
    assert filo["uyarilar"] == []
    assert all("cakisma" not in satir for satir in filo["tesisler"])


def test_yalniz_kurulum_adi_farkliysa_da_cakisma_sayilir():
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    _kaydet(depo, _tesisli("gebze", bilgisayar={"ad": "Gebze B"}), T0)
    _kaydet(depo, _tesisli("gebze", bilgisayar={"ad": "Gebze A"}), T0 + 20)
    uyarilar = _pano.filo_verisi(depo, _ayar(), T0 + 20)["uyarilar"]
    assert uyarilar == [
        "Aynı tesis kimliği iki bilgisayardan geliyor: gebze (Gebze A, Gebze B). Her "
        "bilgisayara farklı UZAK_PANO_TESIS_ID yazın."
    ]


@pytest.mark.parametrize(
    ("once", "sonra", "aradan_sn"),
    [
        (_bilgisayarli("gebze", "DALSAN-PC"), _bilgisayarli("gebze", "DALSAN-PC"), 15),
        # önceki rapor artık canlı değil (30 sn aralıkta 95 sn): bilgisayar değişmiş
        (_bilgisayarli("gebze", "ESKI-PC"), _bilgisayarli("gebze", "DALSAN-PC"), 200),
        # önceki bilgisayar kapanırken son raporunu gönderdi
        (_bilgisayarli("gebze", "ESKI-PC", kapanis=True), _bilgisayarli("gebze", "DALSAN-PC"), 15),
        # bilgisayar adı göndermeyen (eski) program: karşılaştırılamaz
        (_tesisli("gebze"), _bilgisayarli("gebze", "DALSAN-PC"), 15),
        (_bilgisayarli("gebze", "ESKI-PC"), _tesisli("gebze"), 15),
    ],
    ids=["ayni-bilgisayar", "eski-rapor", "kapanis", "once-adsiz", "sonra-adsiz"],
)
def test_ayni_bilgisayar_canli_olmayan_rapor_ya_da_adsiz_rapor_cakisma_sayilmaz(
    once, sonra, aradan_sn
):
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    _kaydet(depo, once, T0)
    saat.simdi = T0 + aradan_sn
    _kaydet(depo, sonra, saat.simdi)
    filo = _pano.filo_verisi(depo, _ayar(), saat.simdi)
    assert filo["uyarilar"] == []
    assert depo.komut("GET", "dalsan:tesis_cakisma:gebze") is None


def test_onceki_ozet_ayni_komutla_okunur_ek_istek_yalniz_cakismada():
    """Önceki özet kütük yazımıyla aynı komutta okunur (SET ... GET): çakışmasız
    raporun istek ve komut sayısı değişmez (yukarıdaki sayım testi). Çakışma ana
    tesiste panonun boru hattına girer; öbür tesiste tek bir SET isteği olur."""
    ayar = _ayar()
    depo = KayitliDepo(Saat(T0))
    _kaydet(depo, _bilgisayarli("gebze", "DALSAN-PC"), T0, ayar)  # ana tesis
    _kaydet(depo, _bilgisayarli("izmir", "IZMIR-1", ad="İzmir"), T0, ayar)
    assert depo.cagrilar[0][0][:2] == ["SET", "dalsan:tesis:gebze"]
    assert "GET" in depo.cagrilar[0][0][3:]

    depo.cagrilar.clear()
    _kaydet(depo, _bilgisayarli("gebze", "ISG-PC-02"), T0 + 10, ayar)
    assert len(depo.cagrilar) == 2
    yazilan = [k for k in depo.cagrilar[1] if k[:2] == ["SET", "dalsan:tesis_cakisma:gebze"]]
    assert len(yazilan) == 1 and yazilan[0][3:] == ["EX", str(_pano.TESIS_CAKISMA_SN)]
    kayit = json.loads(yazilan[0][2])
    assert kayit == {
        "adlar": ["Gebze fabrikası · DALSAN-PC", "Gebze fabrikası · ISG-PC-02"],
        "z": int(T0 + 10),
    }

    depo.cagrilar.clear()
    _kaydet(depo, _bilgisayarli("izmir", "IZMIR-2", ad="İzmir"), T0 + 10, ayar)
    assert len(depo.cagrilar) == 2
    assert [k[:2] for k in depo.cagrilar[1]] == [["SET", "dalsan:tesis_cakisma:izmir"]]


def test_tesissiz_raporda_bilgisayar_degisse_de_hicbir_sey_degismez():
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    _kaydet(depo, _rapor(bilgisayar={"ad": "Gebze", "bilgisayar_adi": "PC-1"}), T0)
    _kaydet(depo, _rapor(bilgisayar={"ad": "Gebze", "bilgisayar_adi": "PC-2"}), T0 + 10)
    filo = _pano.filo_verisi(depo, _ayar(), T0 + 10)
    assert filo["uyarilar"] == []
    assert [sorted(s) for s in filo["tesisler"]] == [
        ["ad", "ana", "baglanti", "bugun_ihlal", "gecikme_sn", "id", "son_rapor"]
    ]
    assert not [a for a in depo._veri if "cakisma" in a or a.startswith("dalsan:tesis")]


def test_cakisma_tesisler_ekraninda_yoneticiye_gorunur(site):  # noqa: F811
    kurucu = _cerez(_giris(site)[1])
    for bilgisayar_adi in ("DALSAN-PC", "ISG-PC-02"):
        rapor = {
            **RAPOR,
            "tesis": {"id": "gebze", "ad": "Gebze"},
            "bilgisayar": {"ad": "Gebze fabrikası", "bilgisayar_adi": bilgisayar_adi},
        }
        assert _rapor_gonder(site, rapor)[0] == 200
    filo = json.loads(_istek(f"{site}/api/durum?filo=1", basliklar={"Cookie": kurucu})[2])["filo"]
    assert filo["uyarilar"] == [CAKISMA_UYARISI]
    assert filo["tesisler"][0]["cakisma"]["adlar"][1] == "Gebze fabrikası · ISG-PC-02"


def test_tesis_satirinda_cakisma_rozeti_metin_olarak():
    satir = re.search(r"function tesisSatiri\(t\) \{.*?\n  \}", PANO_JS, re.S).group(0)
    assert "t.cakisma" in satir and 'rozet("Kimlik çakışması", "tehlike")' in satir
