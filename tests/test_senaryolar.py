"""Saha senaryoları: birkaç kişinin ve fabrika programının aynı panoyu birlikte
kullandığı günler, baştan sona gerçek HTTP ile (yerel sunucu, bellekte depo).

Her test bir hikâyedir ve adım adım ilerler: kurulum günü, yetkisi düşürülen
operatör, şifre deneyen biri, eski programla çalışan fabrika... Tek tek
özellikler öbür test dosyalarında ayrıntılı sınanır; burada aynı akışın
parçalarının birlikte, doğru sırayla çalıştığı denetlenir.

Fabrika programının tarafı imzalı isteklerle taklit edilir (tests/sozlesme
örnekleri programın gerçek çıktısıdır). Programın gerçek istemci koduyla
birlikte koşan senaryolar DALSAN deposunda: tests/test_senaryo_site.py.
"""

from __future__ import annotations

import copy
import json
import secrets
import time
import types
from pathlib import Path

import _pano
import pytest
from test_uctan_uca import ANAHTAR, SIFRE, _istek

import yerel_sunucu

SOZLESME = Path(__file__).resolve().parent / "sozlesme"


class Saat:
    """Ayarlanabilir saat: senaryo dakikaları beklemeden ilerletir."""

    def __init__(self) -> None:
        self.kayma = 0.0

    def __call__(self) -> float:
        return time.time() + self.kayma

    def ilerlet(self, saniye: float) -> None:
        self.kayma += saniye


@pytest.fixture
def saat():
    return Saat()


@pytest.fixture
def site(monkeypatch, saat):
    """Yerel sunucu; sitenin saati (`_pano` içindeki time.time ve depo süreleri)
    senaryonun saatine bağlıdır."""
    monkeypatch.setenv("PANO_SIFRESI", SIFRE)
    monkeypatch.setenv("RAPOR_ANAHTARI", ANAHTAR)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    saatli = types.SimpleNamespace(time=saat, sleep=time.sleep, monotonic=time.monotonic)
    monkeypatch.setattr(_pano, "time", saatli)
    sunucu = yerel_sunucu.sunucu_olustur(port=0, depo=_pano.BellekDepo(saat))
    yerel_sunucu.arka_planda_baslat(sunucu)
    yield f"http://127.0.0.1:{sunucu.server_address[1]}"
    sunucu.shutdown()
    sunucu.server_close()
    _pano.DEPO = None


class Kisi:
    """Panoyu açan biri: çerezini kendisi taşır (Secure çerez http'de
    tarayıcıya girmez; üretimde site https'tir)."""

    def __init__(self, site: str) -> None:
        self.site = site
        self.cerez = ""

    def iste(self, yol: str, govde: dict | None = None) -> tuple[int, dict]:
        basliklar = {"Cookie": self.cerez} if self.cerez else {}
        veri = None
        if govde is not None:
            veri = json.dumps(govde).encode()
            basliklar.update({"Content-Type": "application/json", "Origin": self.site})
        kod, cevap_basliklari, ham = _istek(
            f"{self.site}{yol}", "GET" if veri is None else "POST", veri, basliklar
        )
        cerez = cevap_basliklari.get("Set-Cookie")
        if cerez:
            cift = cerez.split(";")[0]
            self.cerez = "" if cift.endswith("=") else cift
        return kod, (json.loads(ham) if ham else {})

    def giris(self, ad: str, sifre: str) -> Kisi:
        kod, govde = self.iste("/api/giris", {"ad": ad, "sifre": sifre})
        assert kod == 200, govde
        return self


class Fabrika:
    """Fabrika programının siteye giden imzalı istekleri (sözleşme örnekleriyle)."""

    def __init__(self, site: str, saat: Saat, tesis: dict | None = None) -> None:
        self.site = site
        self.saat = saat
        self.tesis = tesis  # {"id", "ad"}: çok tesisli kurulumda programın kimliği

    def _imzali(self, yol: str, govde_sozluk: dict) -> tuple[int, dict, bytes]:
        govde = json.dumps(govde_sozluk).encode()
        damga = str(int(self.saat()))
        return _istek(
            f"{self.site}{yol}",
            "POST",
            govde,
            {
                "Content-Type": "application/json",
                _pano.ZAMAN_BASLIGI: damga,
                _pano.IMZA_BASLIGI: _pano.imza_hesapla(ANAHTAR, damga, govde),
            },
        )

    def rapor(self, rapor: dict | None = None) -> dict:
        rapor = rapor or sozlesme_raporu()
        rapor["uretildi"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(self.saat()))
        if self.tesis:
            rapor["tesis"] = self.tesis
        kod, _, ham = self._imzali("/api/rapor", rapor)
        assert kod == 200, ham
        return json.loads(ham)

    def yokla(self, sonuclar=()) -> dict:
        """Komut sorusu: cevabın imzası ve nonce'u programdaki gibi denetlenir."""
        nonce = secrets.token_hex(16)
        soru = {"surum": 1, "nonce": nonce, "sonuclar": list(sonuclar)}
        if self.tesis:
            soru["tesis"] = self.tesis["id"]
        kod, basliklar, ham = self._imzali("/api/komut", soru)
        assert kod == 200, ham
        # Program imzası tutmayan cevaptaki komutu yürütmez: aynı denetim
        _pano.imza_dogrula(
            ANAHTAR, basliklar[_pano.ZAMAN_BASLIGI], basliklar[_pano.IMZA_BASLIGI], ham, self.saat()
        )
        cevap = json.loads(ham)
        assert cevap["nonce"] == nonce
        return cevap


def sozlesme_raporu(dosya: str = "rapor.json") -> dict:
    ham = json.loads((SOZLESME / dosya).read_text(encoding="utf-8"))
    rapor = copy.deepcopy(ham["rapor"])
    rapor["uretildi"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    return rapor


def ekip_kur(site: str) -> tuple[Kisi, Kisi, Kisi]:
    """Kurucu bir operatör ve bir izleyici açar. İlk şifreyle yalnız şifre
    değiştirilebilir; ikisi de değiştirir ve yeni şifreyle girer."""
    kurucu = Kisi(site).giris("kurucu", SIFRE)
    kisiler = []
    for ad, rol in (("ahmet.operator", "operator"), ("zeynep.izleyici", "izleyici")):
        kod, govde = kurucu.iste(
            "/api/hesap",
            {"eylem": "ekle", "ad": ad, "rol": rol, "ilk_sifre": "ilk-sifre-123", "sifre": SIFRE},
        )
        assert kod == 200, govde
        yeni = Kisi(site).giris(ad, "ilk-sifre-123")
        _, durum = yeni.iste("/api/durum")
        assert durum["oturum"]["sifre_degismeli"] is True
        if rol == "operator":
            kod, govde = yeni.iste("/api/mudahale", {"tur": "anons", "mesaj_id": 3})
            assert (kod, govde["hata"]) == (403, "sifre_degismeli")
        kod, govde = yeni.iste(
            "/api/hesap",
            {"eylem": "sifre_degistir", "eski_sifre": "ilk-sifre-123", "yeni_sifre": f"{ad}-yeni"},
        )
        assert kod == 200, govde
        kisiler.append(Kisi(site).giris(ad, f"{ad}-yeni"))
    return kurucu, kisiler[0], kisiler[1]


def komutlar(kisi: Kisi, yol: str = "/api/durum?mudahale=1") -> dict[str, dict]:
    kod, durum = kisi.iste(yol)
    assert kod == 200, durum
    return {k["id"]: k for k in durum["mudahale"]["komutlar"]}


# ------------------------------------------------------------ kurulum günü


def test_kurulum_gunu_ekip_anons_ve_islem_kaydi(site, saat):
    """Program bağlanır, kurucu ekibi kurar. Operatör Müdahale ekranını açınca
    fabrika komutları sık sormaya başlar; anons fabrikaya bir kez gider, sonucu
    panoya döner. Kurucu işlem kaydında her adımı kimin yaptığını görür."""
    fabrika = Fabrika(site, saat)
    assert fabrika.rapor()["komut"] == {"hizli": False}
    kurucu, operator, izleyici = ekip_kur(site)

    komutlar(operator)  # Müdahale ekranı açıldı
    assert fabrika.rapor()["komut"] == {"hizli": True}
    kod, govde = operator.iste("/api/mudahale", {"tur": "anons", "mesaj_id": 3})
    assert kod == 200, govde
    kimlik = govde["komut"]["id"]

    cevap = fabrika.yokla()
    assert [k["id"] for k in cevap["komutlar"]] == [kimlik]
    assert cevap["komutlar"][0]["kim"] == {"ad": "ahmet.operator", "rol": "operator"}
    assert fabrika.yokla()["komutlar"] == []  # bir kez teslim edilir
    sonuc = {"id": kimlik, "durum": "yapildi", "mesaj": "Tüm fabrika hoparlörü: çalındı."}
    assert kimlik in fabrika.yokla([sonuc])["alinan"]
    son = komutlar(operator)[kimlik]
    assert (son["durum"], son["mesaj"]) == ("yapildi", "Tüm fabrika hoparlörü: çalındı.")

    kod, liste = kurucu.iste("/api/hesap")
    assert kod == 200
    isler = [(s["kim"], s["is"]) for s in liste["kayit"]]
    for beklenen in (
        ("kurucu", "giris"),
        ("ahmet.operator", "sifre_degistir"),
        ("zeynep.izleyici", "sifre_degistir"),
        ("ahmet.operator", "komut"),
    ):
        assert beklenen in isler, f"{beklenen} işlem kaydında yok: {isler}"
    assert {s["ad"] for s in liste["kullanicilar"]} >= {"ahmet.operator", "zeynep.izleyici"}


# ---------------------------------------------- yetkisi düşürülen operatör


def test_yetkisi_dusurulen_operatorun_komutu_fabrikaya_gitmez(site, saat):
    """Operatör bir anons ister; komut fabrikaya ulaşmadan yönetici onu izleyiciye
    düşürür. Kuyruktaki komut teslim edilmez (yetki teslimde yeniden denetlenir)
    ve operatörün açık oturumu düşer: yeniden girince izleyicidir, anons
    yapamaz. Hesap kapatılınca giriş de durur."""
    fabrika = Fabrika(site, saat)
    fabrika.rapor()
    kurucu, operator, _ = ekip_kur(site)
    kod, govde = operator.iste("/api/mudahale", {"tur": "anons", "mesaj_id": 3})
    assert kod == 200, govde

    kod, govde = kurucu.iste(
        "/api/hesap", {"eylem": "rol", "ad": "ahmet.operator", "rol": "izleyici", "sifre": SIFRE}
    )
    assert kod == 200, govde
    assert fabrika.yokla()["komutlar"] == []

    assert operator.iste("/api/durum")[0] == 401  # rol değişti: eski çerez geçmez
    operator.giris("ahmet.operator", "ahmet.operator-yeni")
    _, durum = operator.iste("/api/durum")
    assert durum["oturum"]["rol"] == "izleyici"
    kod, govde = operator.iste("/api/mudahale", {"tur": "anons", "mesaj_id": 3})
    assert (kod, govde["hata"]) == (403, "yetki")

    kod, govde = kurucu.iste(
        "/api/hesap", {"eylem": "kapat", "ad": "ahmet.operator", "sifre": SIFRE}
    )
    assert kod == 200, govde
    assert operator.iste("/api/durum")[0] == 401
    kod, _ = Kisi(site).iste("/api/giris", {"ad": "ahmet.operator", "sifre": "ahmet.operator-yeni"})
    assert kod == 401


# ------------------------------------------------------ şifre deneyen biri


def test_sifre_deneyen_kilitlenir_sure_dolunca_dogru_sifre_gecer(site, saat):
    """Biri kurucunun şifresini dener: beş yanlıştan sonra bu adres kilitlenir,
    doğru şifre bile kabul edilmez. Kilit süresi dolunca doğru şifre geçer;
    her yanlış deneme işlem kaydında görünür."""
    saldirgan = Kisi(site)
    for _ in range(_pano.KILIT_DENEME):
        kod, _ = saldirgan.iste("/api/giris", {"ad": "kurucu", "sifre": "tahmin-123"})
        assert kod == 401
    kod, govde = saldirgan.iste("/api/giris", {"ad": "kurucu", "sifre": SIFRE})
    assert (kod, govde["hata"]) == (429, "kilitli")

    saat.ilerlet(_pano.KILIT_SURESI_SN + 1)
    kurucu = Kisi(site).giris("kurucu", SIFRE)
    _, liste = kurucu.iste("/api/hesap")
    hatalilar = [s for s in liste["kayit"] if s["is"] == "giris_hatali"]
    assert len(hatalilar) >= _pano.KILIT_DENEME


# -------------------------------------------- eski program, yeni site


def test_eski_program_yeni_sitede_calisir_bakim_isi_istenemez(site, saat):
    """Sahada güncellenmemiş bir program kalabilir: raporu (yönetim bloğu yok)
    sitede görünür, anons yürür; yeni bakım işleri (teşhis, güncelleme)
    istenemez ve site sebebini söyler. Program yeni alanları hiç görmeden
    eskisi gibi çalışır."""
    fabrika = Fabrika(site, saat)
    rapor = sozlesme_raporu("rapor-eski.json")
    fabrika.rapor(rapor)
    yonetici = Kisi(site).giris("kurucu", SIFRE)
    _, durum = yonetici.iste("/api/durum?yonetim=1")
    assert durum["baglanti"] == "canli"
    assert durum["rapor"]["yonetim"]["acik"] is False

    for istek in ({"tur": "teshis"}, {"tur": "guncelle", "sifre": SIFRE}):
        kod, govde = yonetici.iste("/api/mudahale", istek)
        assert (kod, govde["hata"]) == (409, "yonetim_kapali"), govde
        assert "uzaktan yönetim kapalı" in govde["mesaj"]
    mesaj_id = rapor["mudahale"]["mesajlar"][0]["id"]
    kod, govde = yonetici.iste("/api/mudahale", {"tur": "anons", "mesaj_id": mesaj_id})
    assert kod == 200, govde
    # Eski program nonce göndermez; site komutu yine verir, nonce boş döner
    damga = str(int(saat()))
    govde_b = json.dumps({"surum": 1, "sonuclar": []}).encode()
    kod, _, ham = _istek(
        f"{site}/api/komut",
        "POST",
        govde_b,
        {
            "Content-Type": "application/json",
            _pano.ZAMAN_BASLIGI: damga,
            _pano.IMZA_BASLIGI: _pano.imza_hesapla(ANAHTAR, damga, govde_b),
        },
    )
    cevap = json.loads(ham)
    assert kod == 200 and cevap["nonce"] == "" and len(cevap["komutlar"]) == 1


# ------------------------------------------------ gece kesintisi (bekçi)

BEKCI_ANAHTARI = "bekci-dis-izleme-anahtari-20"
SMTP_SIFRESI = "smtp-gizli-sifre-123"


class Postaci:
    """E-posta yerine: giden bildirimleri kaydeder (ağa çıkmaz)."""

    def __init__(self) -> None:
        self.giden: list[tuple[str, str, str]] = []  # (kanal, alıcı, metin)

    def eposta(self, _ayar, alici, konu, govde):
        self.giden.append(("eposta", alici, f"{konu}\n{govde}"))


@pytest.fixture
def postaci(monkeypatch):
    postaci = Postaci()
    monkeypatch.setattr(_pano, "_eposta_gonder", postaci.eposta)
    return postaci


@pytest.fixture
def bekci_acik(monkeypatch):
    for ad, deger in {
        "BEKCI": "acik",
        "BEKCI_ESIK_DK": "20",
        "BEKCI_ANAHTARI": BEKCI_ANAHTARI,
        "BEKCI_ALICILAR": "vardiya.amiri@fabrika.example",
        "SMTP_SUNUCU": "smtp.fabrika.example",
        "SMTP_KULLANICI": "pano@fabrika.example",
        "SMTP_SIFRESI": SMTP_SIFRESI,
    }.items():
        monkeypatch.setenv(ad, deger)


def bekci(site: str, anahtar: str | None = BEKCI_ANAHTARI) -> tuple[int, dict]:
    basliklar = {"Authorization": f"Bearer {anahtar}"} if anahtar else {}
    kod, _, ham = _istek(f"{site}/api/bekci", basliklar=basliklar)
    metin = ham.decode("utf-8")
    assert BEKCI_ANAHTARI not in metin and SMTP_SIFRESI not in metin, "sır cevaba girdi"
    return kod, json.loads(metin)


def test_gece_kesintisi_bir_kez_uyarir_sabah_toparlanir(site, saat, postaci, bekci_acik):
    """Gece fabrika bilgisayarı kapanır. Dış izleme her beş dakikada /api/bekci'yi
    çağırır: eşik (20 dk) dolunca vardiya amirine BİR KEZ e-posta gider,
    sonraki çağrılar sessizdir ama 503 döner (izleme servisi de görür).
    Sabah program dönünce işaret kalkar; bir sonraki kesinti yeniden bildirilir."""
    fabrika = Fabrika(site, saat)
    fabrika.rapor()
    assert bekci(site, None)[0] == 401
    assert bekci(site, "yanlis-anahtar-yanlis-anahtar")[0] == 403
    kod, cevap = bekci(site)
    assert kod == 200 and cevap["uyarildi"] is False
    assert cevap["durum"][0]["baglanti"] == "canli"

    saat.ilerlet(10 * 60)  # 10 dk: koptu ama eşik dolmadı
    kod, cevap = bekci(site)
    assert kod == 200 and postaci.giden == []

    saat.ilerlet(15 * 60)  # 25 dk
    kod, cevap = bekci(site)
    assert kod == 503 and cevap["uyarildi"] is True and cevap["gonderilen"] == 1
    assert [(k, alici) for k, alici, _ in postaci.giden] == [
        ("eposta", "vardiya.amiri@fabrika.example")
    ]
    assert all("dakika" in metin for _, _, metin in postaci.giden)
    for _ in range(3):  # sonraki cron çağrıları: bildirim yok, durum yine 503
        saat.ilerlet(5 * 60)
        kod, cevap = bekci(site)
        assert kod == 503 and cevap["uyarildi"] is False
    assert len(postaci.giden) == 1

    saat.ilerlet(8 * 3600)  # sabah: program açıldı
    fabrika.rapor()
    kod, cevap = bekci(site)
    assert kod == 200 and cevap["durum"][0]["baglanti"] == "canli"

    saat.ilerlet(30 * 60)  # öğlen yeni bir kesinti: yeniden bildirilir
    kod, cevap = bekci(site)
    assert kod == 503 and cevap["uyarildi"] is True
    assert len(postaci.giden) == 2


def test_bekci_kapaliyken_hicbir_sey_gondermez(site, saat, postaci, monkeypatch):
    """Bekçi açılmamışsa (varsayılan) cron çağrısı yalnız "atlandı" der."""
    monkeypatch.setenv("BEKCI_ANAHTARI", BEKCI_ANAHTARI)
    Fabrika(site, saat).rapor()
    saat.ilerlet(3600)
    kod, cevap = bekci(site)
    assert (kod, cevap) == (200, {"atlandi": True})
    assert postaci.giden == []


# ------------------------------------------------ iki tesisli şirket (filo)

GEBZE = {"id": "gebze", "ad": "Gebze fabrikası"}
IZMIR = {"id": "izmir", "ad": "İzmir fabrikası"}


def test_iki_tesisli_sirkette_komut_yalniz_ana_tesise_gider(
    site, saat, postaci, bekci_acik, monkeypatch
):
    """Şirket ikinci fabrikayı da aynı siteye bağlar. İlk rapor veren Gebze ana
    tesistir: panoyu o yazar, komutları o alır. İzmir yalnız filo satırıdır:
    panoyu ezmez, kuyruktaki komutu alamaz. Yönetici Tesisler görünümünde
    ikisini görür; İzmir susunca bekçi yalnız İzmir için uyarır. ANA_TESIS
    ayarıyla ana tesis değiştirilebilir."""
    gebze, izmir = Fabrika(site, saat, GEBZE), Fabrika(site, saat, IZMIR)
    cevap = gebze.rapor()
    assert cevap["filo"] == {"ana": True} and "komut" in cevap
    cevap = izmir.rapor()
    assert cevap["filo"] == {"ana": False}
    assert not {"komut", "kare", "foto"} & set(cevap)  # komut sormaz, görüntü göndermez

    kurucu, operator, _ = ekip_kur(site)
    _, durum = kurucu.iste("/api/durum")
    assert durum["rapor"]["tesis"] == GEBZE  # pano Gebze'yi gösterir

    komutlar(operator)  # Müdahale ekranı açıldı
    kod, govde = operator.iste("/api/mudahale", {"tur": "anons", "mesaj_id": 3})
    assert kod == 200, govde
    assert izmir.yokla()["komutlar"] == []  # yanlış fabrikaya komut gitmez
    assert [k["id"] for k in gebze.yokla()["komutlar"]] == [govde["komut"]["id"]]

    _, filo = kurucu.iste("/api/durum?filo=1")
    satirlar = {s["id"]: s for s in filo["filo"]["tesisler"]}
    assert set(satirlar) == {"gebze", "izmir"}
    assert satirlar["gebze"]["ana"] is True and satirlar["izmir"]["ana"] is False
    assert all(s["baglanti"] == "canli" for s in satirlar.values())
    _, operator_durumu = operator.iste("/api/durum?filo=1")
    assert "filo" not in operator_durumu

    saat.ilerlet(25 * 60)  # İzmir sustu, Gebze çalışıyor
    gebze.rapor()
    kod, cevap = bekci(site)
    assert kod == 503 and cevap["uyarildi"] is True
    assert postaci.giden and all("İzmir" in metin for _, _, metin in postaci.giden)
    assert not any("Gebze" in metin for _, _, metin in postaci.giden)

    monkeypatch.setenv("ANA_TESIS", "izmir")  # yönetici ana tesisi değiştirdi
    assert izmir.rapor()["filo"] == {"ana": True}
    cevap = gebze.rapor()
    assert cevap["filo"] == {"ana": False} and "komut" not in cevap
