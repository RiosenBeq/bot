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


def test_bekci_acikken_tesissiz_rapor_isareti_ayni_komutta_siler():
    rapor = _pano.rapor_temizle(_rapor())
    depo = KayitliDepo(Saat(T0))
    _pano.rapor_kaydet(depo, rapor, T0, _ayar(bekci="acik"))
    assert depo.cagrilar == [_bugunku_komutlar(rapor, T0) + [["DEL", "dalsan:bekci:uyarildi"]]]


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
