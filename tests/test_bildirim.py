"""Kişinin kendi bildirimleri, derin bağlantılar ve iki yeni e-posta (21.11.2026).

Sistem > Bildirimler: her hesap (kurucu hariç) kendi adresini ve iki anahtarı
("Sistem uyarıları", "Haftalık özet"; varsayılan kapalı) kaydeder. Alıcılar
gönderim anında birleşir: Vercel listesinin bütün adresleri + anahtarı açık
hesaplar (hesaptaki anahtar listedeki adresi düşürmez); girişi kapalı ya da
silinen hesap eklemez.
Hesaplar YALNIZ e-posta gidecekken okunur: sıradan bekçi çağrısı komut eklemez.
"Sistem yeniden haber veriyor" kesinti başına bir kez (raporun isteği e-posta
göndermez), "Ayar sorunu" günde en çok bir kez gider; ikisi de değer yazmaz.
Ağ yok: gönderenler sahtedir."""

import html
import json
import re
import urllib.parse
from pathlib import Path

import _pano
import pytest
from test_bekci import GIZLI, T0, SahteGonderici, _bearer, _bekci_iste, _kaydet
from test_cekirdek import Saat, _ayar, _rapor
from test_haftalik_ozet import OLAYLAR, PAZARTESI, SayanDepo, _arsivli_depo, _ozet_ayari
from test_hesap import _hazir_hesap, _hesap, _kurucu, _post, _yaz_hesap
from test_uctan_uca import SIFRE, _istek, site  # noqa: F401

DK = 60
KOK = Path(__file__).resolve().parents[1]
PANO_JS = (KOK / "public" / "pano.js").read_text(encoding="utf-8")
DEMO_JS = (KOK / "public" / "demo.js").read_text(encoding="utf-8")
PANO_HTML = (KOK / "public" / "pano.html").read_text(encoding="utf-8")


class Gonderici(SahteGonderici):
    """Her çağrının alıcılarını, konusunu, metnini ve HTML'ini kaydeder."""

    def __call__(self, ayar, alicilar, konu, metin, basarida=None, html_metni="", ne=""):
        self.htmller = [*getattr(self, "htmller", []), html_metni]
        return super().__call__(ayar, alicilar, konu, metin, basarida=basarida)


def _hesapli(depo, ad, eposta=None, sistem=False, haftalik=False, acik=True):
    """Dizine ve kayda bir hesap yazar; `eposta` varsa bildirim ayarıyla."""
    kayit = _hesap(ad, acik=acik)
    if eposta is not None:
        kayit["bildirim"] = {"eposta": eposta, "sistem": sistem, "haftalik": haftalik}
    _yaz_hesap(depo, kayit)
    depo.boru_hatti([["RPUSH", _pano.KULLANICILAR_ANAHTARI, ad]])


# ------------------------------------------------------------ alıcı kuralı


def test_alicilar_liste_arti_acik_hesaplar_hesap_liste_adresini_dusurmez():
    depo = _pano.BellekDepo()
    ayar = _ayar(
        bekci_alicilar=("Sef@Ornek.com", "mudur@ornek.com", "bekci@ornek.com"),
        haftalik_alicilar=("mudur@ornek.com",),
    )
    _hesapli(depo, "ali", "sef@ornek.com", sistem=True)  # listede de var: bir kez, liste
    _hesapli(depo, "veli", "MUDUR@ornek.com", sistem=False, haftalik=True)  # kapalı: etkisiz
    _hesapli(depo, "can", "can@ornek.com", sistem=True, haftalik=True)  # yalnız hesaptan
    _hesapli(depo, "eda", "eda@ornek.com", sistem=True, acik=False)  # girişi kapalı: eklemez
    _hesapli(depo, "bekir", "bekci@ornek.com", sistem=True, acik=False)  # liste adresi kalır
    _hesapli(depo, "nur")  # ayarı yok: etkisi yok
    depo.boru_hatti([["RPUSH", _pano.KULLANICILAR_ANAHTARI, "silinen"]])  # kaydı yok
    assert _pano.bildirim_alicilari(depo, ayar, "sistem") == [
        ("Sef@Ornek.com", "liste"),
        ("mudur@ornek.com", "liste"),
        ("bekci@ornek.com", "liste"),
        ("can@ornek.com", "hesap"),
    ]
    assert _pano.bildirim_alicilari(depo, ayar, "haftalik") == [
        ("mudur@ornek.com", "liste"),
        ("can@ornek.com", "hesap"),
    ]
    # Aynı adresi iki hesap yazdıysa açan kazanır; adres bir kez
    _hesapli(depo, "ayse", "CAN@ornek.com", sistem=False)
    assert [a for a, _ in _pano.bildirim_alicilari(depo, ayar, "sistem")].count(
        "can@ornek.com"
    ) == 1
    # Liste tek başına: kaynak liste, büyük-küçük harf farkı bir kez
    bos = _pano.BellekDepo()
    ayar = _ayar(bekci_alicilar=("a@b.co", "A@B.co", "c@d.co"))
    beklenen = [("a@b.co", "liste"), ("c@d.co", "liste")]
    assert _pano.bildirim_alicilari(bos, ayar, "sistem") == beklenen


def test_en_dusuk_rol_baskasinin_liste_adresini_susturamaz_kart_ayni_sayar(site, monkeypatch):  # noqa: F811
    """İnceleme 21.11.2026: adresin sahibi olduğu kanıtlanmıyor. İzleyici,
    Vercel listesindeki müdürün adresini büyük harfle yazıp iki anahtarı kapalı
    kaydetse de uyarı ve özet müdüre gider; Kurulum denetimi kartı gönderimdeki
    birleşimi sayar (aynı adresi açan hesap ikinci alıcı sayılmaz)."""
    monkeypatch.setenv("BEKCI_ALICILAR", "mudur@firma.example")
    kurucu = _kurucu(site)
    ali = _hazir_hesap(site, kurucu, "ali", "izleyici", "ali-parola-123")
    kod, _, _ = _bildirim(site, ali, eposta="MUDUR@firma.example", sistem=False, haftalik=False)
    assert kod == 200
    ayar = _pano.ayar_oku()
    for tur in ("sistem", "haftalik"):
        beklenen = [("mudur@firma.example", "liste")]
        assert _pano.bildirim_alicilari(_pano.DEPO, ayar, tur) == beklenen
    kod, _, _ = _bildirim(site, ali, eposta="MUDUR@firma.example", sistem=True, haftalik=True)
    assert kod == 200
    _, _, govde = _istek(f"{site}/api/hesap?islem=kurulum", basliklar={"Cookie": kurucu})
    kart = json.loads(govde)["kurulum"]
    sayilar = ("alici", "alici_hesap", "haftalik_alici", "haftalik_alici_hesap")
    assert tuple(kart[ad] for ad in sayilar) == (1, 0, 1, 0)


def test_ayar_bozuk_ve_eski_alicilari_sayar_degerleri_tutmaz():
    ayar = _pano.ayar_oku(
        {
            "BEKCI_ALICILAR": "a@b.co, tg:1, adres-degil, x@y",
            "HAFTALIK_OZET_ALICILAR": "tg:2, bozuk",
        }
    )
    assert ayar.bekci_alicilar == ("a@b.co",) and ayar.bekci_alici_gecersiz == 2
    assert ayar.bekci_tg_yok_sayildi and ayar.haftalik_tg_yok_sayildi
    assert ayar.haftalik_alici_gecersiz == 1
    # Özet listesi yazılı ama hepsi geçersiz: özet bekçinin listesine düşmez (inceleme
    # 21.11.2026); yalnız hiç girdi yoksa düşer
    assert ayar.haftalik_alicilar == ()
    for bos in ("", " , ", None):
        ortam = {"BEKCI_ALICILAR": "a@b.co"} | (
            {} if bos is None else {"HAFTALIK_OZET_ALICILAR": bos}
        )
        assert _pano.ayar_oku(ortam).haftalik_alicilar == ("a@b.co",)
    for deger in ("adres-degil", "bozuk", "x@y"):
        assert deger not in repr(ayar)


# ------------------------------------------- sıradan bekçi çağrısı: komut yok


def test_siradan_bekci_cagrisi_hesap_okumaz_komut_eklemez():
    saat = Saat(T0)
    depo = SayanDepo(saat)
    ayar = _ayar(bekci="acik", bekci_alicilar=("sef@ornek.com",))
    _hesapli(depo, "ali", "ali@ornek.com", sistem=True)
    _kaydet(depo, _rapor(), T0, ayar)
    depo.istek, depo.komutlar = 0, []
    okunan = []
    gercek = depo.al_coklu
    depo.al_coklu = lambda anahtarlar: okunan.extend(anahtarlar) or gercek(anahtarlar)
    gonder = Gonderici()
    saat.simdi = T0 + 5 * DK  # canlı: uyarı yok
    sonuc = _pano.bekci_isle(depo, ayar, saat.simdi, gonder)
    assert sonuc["uyarildi"] is False and gonder.cagrilar == []
    # Bugünkü okumalar: pano (MGET, "döndü" işareti aynı MGET'te), ana tesis, kütük
    assert depo.komutlar == ["MGET", "GET", "LRANGE"] and depo.istek == 3
    assert not any(a.startswith(_pano.KULLANICI_ONEKI) for a in okunan)
    # Eşik doldu: hesaplar bir kez okunur, açan kişi de alır
    saat.simdi = T0 + 25 * DK
    depo.komutlar = []
    sonuc = _pano.bekci_isle(depo, ayar, saat.simdi, gonder)
    assert sonuc["uyarildi"] is True and sonuc["gonderilen"] == 2
    assert [c[0] for c in gonder.cagrilar] == [("sef@ornek.com",), ("ali@ornek.com",)]
    assert depo.komutlar.count("LRANGE") == 2  # kütük + hesap dizini (tek kez)


def test_alt_yazi_kaynaga_gore_liste_ve_hesap_ayri_gider():
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _ayar(
        bekci="acik", bekci_alicilar=("sef@ornek.com",), pano_adresi="https://d.vercel.app/pano"
    )
    _hesapli(depo, "ali", "ali@ornek.com", sistem=True)
    _kaydet(depo, _rapor(), T0, ayar)
    gonder = Gonderici()
    _pano.bekci_isle(depo, ayar, T0 + 25 * DK, gonder)
    (liste, _, liste_metni), (hesap, _, hesap_metni) = gonder.cagrilar
    assert liste == ("sef@ornek.com",) and "Vercel'deki BEKCI_ALICILAR" in liste_metni
    assert hesap == ("ali@ornek.com",) and "hesabınızda Sistem > Bildirimler" in hesap_metni
    ayarlar = "https://d.vercel.app/pano?bolum=bildirimler#sistem"
    for metin, html_metni in zip((liste_metni, hesap_metni), gonder.htmller, strict=True):
        assert f"Bildirim ayarları: {ayarlar}" in metin and f'href="{ayarlar}"' in html_metni
        assert "ali@ornek.com" not in metin and "sef@ornek.com" not in metin


# ---------------------------------------------- "Sistem yeniden haber veriyor"


def test_duzelme_kesinti_basina_bir_kez_rapor_istegi_eposta_gondermez(monkeypatch):
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _ayar(bekci="acik", bekci_alicilar=("sef@ornek.com",))
    gonder = Gonderici()
    _kaydet(depo, _rapor(), T0, ayar)
    saat.simdi = T0 + 30 * DK
    assert _pano.bekci_isle(depo, ayar, saat.simdi, gonder)["uyarildi"] is True

    def yasak(*_, **__):
        raise AssertionError("rapor isteği e-posta göndermemeli")

    monkeypatch.setattr(_pano, "_eposta_gonder", yasak)
    monkeypatch.setattr(_pano, "bekci_uyari_gonder", yasak)
    saat.simdi = T0 + 95 * DK
    _kaydet(depo, _rapor(), saat.simdi, ayar)  # rapor döndü
    assert depo.komut("GET", "dalsan:bekci:uyarildi") is None
    assert depo.komut("TTL", "dalsan:bekci:dondu") > 6 * 86400
    saat.simdi += DK
    sonuc = _pano.bekci_isle(depo, ayar, saat.simdi, gonder)
    assert sonuc["duzelme"] == 1 and len(gonder.cagrilar) == 2
    _, konu, metin = gonder.cagrilar[1]
    assert konu.startswith("Düzeldi: ") and "Kesinti: yaklaşık 1 saat 35 dakika" in metin
    # Kesinti başına bir kez: sonraki çağrılar göndermez
    for _ in range(3):
        saat.simdi += 5 * DK
        assert "duzelme" not in _pano.bekci_isle(depo, ayar, saat.simdi, gonder)
    assert len(gonder.cagrilar) == 2


def test_duzelme_gidemezse_isaret_geri_yazilir_yeniden_kesilirse_duzelme_gitmez():
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _ayar(bekci="acik", bekci_alicilar=("sef@ornek.com",))
    _kaydet(depo, _rapor(), T0, ayar)
    _pano.bekci_isle(depo, ayar, T0 + 25 * DK, Gonderici())
    _kaydet(depo, _rapor(), T0 + 40 * DK, ayar)
    gidemeyen = Gonderici(sonuc=0)
    assert "duzelme" not in _pano.bekci_isle(depo, ayar, T0 + 41 * DK, gidemeyen)
    assert len(gidemeyen.cagrilar) == 1 and depo.komut("GET", "dalsan:bekci:dondu")
    _kaydet(depo, _rapor(), T0 + 42 * DK, ayar)  # düzelme yalnız hedef canlıyken gider
    gonder = Gonderici()
    assert _pano.bekci_isle(depo, ayar, T0 + 42 * DK, gonder)["duzelme"] == 1

    # Yeni kesinti; rapor döner ama düzelme gitmeden yeniden kesilir: yeni uyarı gider,
    # eski düzelme işareti kalkar (düzelme e-postası gitmez)
    _pano.bekci_isle(depo, ayar, T0 + 70 * DK, gonder)
    _kaydet(depo, _rapor(), T0 + 80 * DK, ayar)
    gonder = Gonderici()
    sonuc = _pano.bekci_isle(depo, ayar, T0 + 110 * DK, gonder)
    assert sonuc["uyarildi"] is True and "duzelme" not in sonuc
    assert [c[1].split(":")[0] for c in gonder.cagrilar] == ["Alarm"]
    assert depo.komut("GET", "dalsan:bekci:dondu") is None


def test_uyari_gidemediyse_ya_da_hic_uyari_yoksa_duzelme_yok():
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _ayar(bekci="acik", bekci_alicilar=("sef@ornek.com",))
    _kaydet(depo, _rapor(), T0, ayar)
    _kaydet(depo, _rapor(), T0 + 10 * DK, ayar)  # eşik dolmadan döndü: işaret yoktu
    assert depo.komut("GET", "dalsan:bekci:dondu") is None
    _pano.bekci_isle(depo, ayar, T0 + 40 * DK, Gonderici(sonuc=0))  # uyarı gidemedi
    _kaydet(depo, _rapor(), T0 + 41 * DK, ayar)
    gonder = Gonderici()
    assert "duzelme" not in _pano.bekci_isle(depo, ayar, T0 + 42 * DK, gonder)
    assert gonder.cagrilar == []


def test_tesis_duzelmesi_kutuk_okumasiyla_gelir():
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _ayar(bekci="acik", bekci_alicilar=("sef@ornek.com",))
    izmir = _rapor(tesis={"id": "izmir", "ad": "İzmir fabrikası"})
    _kaydet(depo, _rapor(tesis={"id": "gebze", "ad": "Gebze fabrikası"}), T0, ayar)
    _kaydet(depo, izmir, T0, ayar)
    gonder = Gonderici()
    saat.simdi = T0 + 25 * DK
    _kaydet(depo, _rapor(tesis={"id": "gebze", "ad": "Gebze fabrikası"}), saat.simdi, ayar)
    assert _pano.bekci_isle(depo, ayar, saat.simdi, gonder)["uyarildi"] is True
    assert "İzmir fabrikası" in gonder.cagrilar[0][1]
    saat.simdi += 10 * DK
    _kaydet(depo, izmir, saat.simdi, ayar)  # öbür tesis (ana değil) döndü
    assert depo.komut("GET", "dalsan:bekci:dondu:izmir") is not None
    _kaydet(depo, _rapor(tesis={"id": "gebze", "ad": "Gebze fabrikası"}), saat.simdi, ayar)
    assert _pano.bekci_isle(depo, ayar, saat.simdi + 30, gonder)["duzelme"] == 1
    assert gonder.cagrilar[1][1] == "Düzeldi: İzmir fabrikası - sistem yeniden haber veriyor"


# ------------------------------------------------------------- "Ayar sorunu"


def _sorunlu_ayar(**degisen):
    alanlar = {
        "bekci": "acik",
        "bekci_alicilar": ("sef@ornek.com",),
        "bekci_alici_gecersiz": 1,
        "oturum_anahtari_kisa": True,
        "smtp_sunucu": "smtp.ornek.com",
    }
    alanlar.update(degisen)
    return _ayar(**alanlar)


def test_ayar_sorunu_gunde_bir_kez_sorun_yoksa_komut_yok():
    depo = SayanDepo(lambda: T0)
    gonder = Gonderici()
    # Sorun yok ya da e-posta yolu yok: hiçbir komut
    assert _pano.ayar_sorunu_isle(depo, _ayar(bekci="acik"), T0, gonder) is None
    assert _pano.ayar_sorunu_isle(depo, _sorunlu_ayar(smtp_sunucu=""), T0, gonder) is None
    assert depo.istek == 0
    ayar = _sorunlu_ayar()
    sonuc = _pano.ayar_sorunu_isle(depo, ayar, T0, gonder)
    assert sonuc == {"gonderildi": True, "gonderilen": 1, "madde": 2}
    (alicilar, konu, metin), html_metni = gonder.cagrilar[0], gonder.htmller[0]
    assert alicilar == ("sef@ornek.com",) and konu == "Ayar sorunu: Vercel'de düzeltilecek 2 madde"
    assert "BEKCI_ALICILAR: 1 girdi" in metin and "OTURUM_ANAHTARI" in metin
    assert "#d97706" in html_metni  # turuncu şerit
    # Aynı gün yeniden: tek SET NX, gönderim yok
    depo.istek = 0
    assert _pano.ayar_sorunu_isle(depo, ayar, T0 + 3600, gonder)["sebep"] == "bugun_gitti"
    assert depo.istek == 1 and len(gonder.cagrilar) == 1
    # Ertesi gün yeniden gider
    assert _pano.ayar_sorunu_isle(depo, ayar, T0 + 86400, gonder)["gonderildi"] is True
    # Hiçbiri gidemezse işaret silinir: sonraki çağrı yeniden dener
    depo2 = _pano.BellekDepo()
    assert _pano.ayar_sorunu_isle(depo2, ayar, T0, Gonderici(sonuc=0))["sebep"] == "gidemedi"
    assert _pano.ayar_sorunu_isle(depo2, ayar, T0 + 60, gonder)["gonderildi"] is True


def test_ayar_sorunu_degerleri_yazmaz_hesaplar_da_alir():
    ortam = {
        "BEKCI": "evet",
        "HAFTALIK_OZET": "belki",
        "BEKCI_ALICILAR": "sef@ornek.com, tg:-100999, gizli-girdi",
        "OTURUM_ANAHTARI": "kisa-gizli-anahtar",
        "ANA_TESIS": "Gizli Tesis!",
        "SMTP_SUNUCU": "smtp.gizli.example",
        "SMTP_SIFRESI": GIZLI["SMTP_SIFRESI"],
    }
    ayar = _pano.ayar_oku(ortam)
    assert len(_pano.ayar_sorunlari(ayar)) == 6
    depo = _pano.BellekDepo()
    _hesapli(depo, "ali", "ali@ornek.com", sistem=True)
    gonder = Gonderici()
    _pano.ayar_sorunu_isle(depo, ayar, T0, gonder)
    assert [c[0] for c in gonder.cagrilar] == [("sef@ornek.com",), ("ali@ornek.com",)]
    for metin in [c[2] for c in gonder.cagrilar] + gonder.htmller:
        for deger in ("evet", "belki", "-100999", "gizli-girdi", "kisa-gizli", "Gizli Tesis"):
            assert deger not in metin
        assert GIZLI["SMTP_SIFRESI"] not in metin and "smtp.gizli" not in metin


def test_taninmayan_bekci_once_ayar_sorunu_gonderir_sonra_503(site, monkeypatch):  # noqa: F811
    for ad, deger in {
        "BEKCI": "evet",
        "BEKCI_ANAHTARI": GIZLI["BEKCI_ANAHTARI"],
        "BEKCI_ALICILAR": "sef@ornek.com",
        "SMTP_SUNUCU": "smtp.ornek.com",
    }.items():
        monkeypatch.setenv(ad, deger)
    giden = []
    monkeypatch.setattr(_pano, "_eposta_gonder", lambda *arg, **ek: giden.append(arg))
    jeton = _bearer(GIZLI["BEKCI_ANAHTARI"])
    for _ in range(2):  # günde bir kez
        kod, _, govde = _bekci_iste(site, jeton)
        assert kod == 503 and json.loads(govde)["hata"] == "bekci_ayari"
    ((_, alici, konu, metin),) = giden
    assert alici == "sef@ornek.com" and konu.startswith("Ayar sorunu") and "BEKCI" in metin
    # Bekçi ve özet kapalıyken uç nokta bugünkü gibi hiçbir şey yapmaz
    monkeypatch.setenv("BEKCI", "kapali")
    monkeypatch.setenv("OTURUM_ANAHTARI", "kisa")
    kod, _, govde = _bekci_iste(site, jeton)
    assert (kod, json.loads(govde)) == (200, {"atlandi": True}) and len(giden) == 1


# ------------------------------------------------ haftalık özet ve hesaplar


def test_haftalik_ozet_hesaptan_alici_liste_bosken_de_gider_liste_adresi_kalir():
    depo = _arsivli_depo()
    _hesapli(depo, "ali", "ali@ornek.com", haftalik=True)
    _hesapli(depo, "veli", "sef@ornek.com", haftalik=False, sistem=True)  # liste adresini düşürmez
    gonder = Gonderici()
    ayar = _ozet_ayari(haftalik_alicilar=("sef@ornek.com", "mudur@ornek.com"))
    depo.istek, depo.komutlar = 0, []
    assert _pano.haftalik_ozet_isle(depo, ayar, PAZARTESI, gonder)["gonderildi"]
    assert [c[0] for c in gonder.cagrilar] == [
        ("sef@ornek.com", "mudur@ornek.com"),
        ("ali@ornek.com",),
    ]
    # Hesap kayıtları tek MGET'te (dizin okuma boru hattındaydı)
    assert depo.komutlar == ["SET", "ZREVRANGEBYSCORE", "MGET", "LRANGE", "MGET", "EXPIRE", "SET"]
    # Liste boş, yalnız hesap: alıcılar işaretten ve arşivden önce okunur
    depo = _arsivli_depo()
    _hesapli(depo, "ali", "ali@ornek.com", haftalik=True)
    gonder = Gonderici()
    depo.istek, depo.komutlar = 0, []
    sonuc = _pano.haftalik_ozet_isle(depo, _ozet_ayari(haftalik_alicilar=()), PAZARTESI, gonder)
    assert sonuc["gonderildi"] and gonder.cagrilar[0][0] == ("ali@ornek.com",)
    assert 'hesabınızda Sistem > Bildirimler\'de "Haftalık özet" açık' in gonder.cagrilar[0][2]
    assert depo.komutlar == ["LRANGE", "MGET", "SET", "ZREVRANGEBYSCORE", "MGET", "EXPIRE", "SET"]


def test_haftalik_ozet_alici_yoksa_isaret_ve_arsiv_okunmaz():
    """İnceleme 21.11.2026: alıcısı olmayan kurulumda gönderim penceresindeki her
    bekçi çağrısı yalnız hesap dizinini (hesap varsa kayıtları da) okur; işaret
    (SET NX / DEL) ve 14 günlük arşiv okunmaz."""
    ayar = _ozet_ayari(haftalik_alicilar=())
    depo = _arsivli_depo()
    sonuc = _pano.haftalik_ozet_isle(depo, ayar, PAZARTESI, Gonderici())
    assert sonuc == {"gonderildi": False, "sebep": "alici_yok"}
    assert depo.komutlar == ["LRANGE"]
    _hesapli(depo, "ali", "ali@ornek.com", sistem=True)  # özeti açmadı
    depo.komutlar = []
    sonuc = _pano.haftalik_ozet_isle(depo, ayar, PAZARTESI, Gonderici())
    assert sonuc["sebep"] == "alici_yok" and depo.komutlar == ["LRANGE", "MGET"]
    # Kişi özeti açınca aynı hafta gider (işaret hiç alınmamıştı)
    _hesapli(depo, "ali", "ali@ornek.com", haftalik=True)
    assert _pano.haftalik_ozet_isle(depo, ayar, PAZARTESI, Gonderici())["gonderildi"]


def test_haftalik_ozet_baglantilari_ozetin_haftasini_acar():
    """İnceleme 21.11.2026: bağlantılar tıklandığı günden geriye 7 günü değil,
    özetin haftasını (16-22.11.2026) açar; satırlar e-postadaki ihlal sayısıyla
    aynı süzgeçtedir."""
    adres = "https://d.vercel.app/pano"
    gonder = Gonderici()
    _pano.haftalik_ozet_isle(_arsivli_depo(), _ozet_ayari(pano_adresi=adres), PAZARTESI, gonder)
    (_, _, metin), html_metni = gonder.cagrilar[0], gonder.htmller[0]
    hafta = f"{adres}?hafta=2026-11-16"
    assert f'href="{hafta}#olaylar"' in html_metni
    tip = f"{hafta}&tur=ihlal&tip=Ara%C3%A7-yaya%20yak%C4%B1nl%C4%B1%C4%9F%C4%B1#olaylar"
    # HTML'de & kaçışlıdır (&amp;); düz metinde adres olduğu gibi
    assert f'href="{html.escape(tip)}"' in html_metni and f"    {tip}\n" in metin
    # Programdan gelen kamera adı: bağlantıda kodlu, yazıda kaçışlı
    yer = f"{hafta}&tur=ihlal&yer=%3Cb%3EKap%C4%B1%3C%2Fb%3E#olaylar"
    assert f'href="{html.escape(yer)}"' in html_metni
    assert ">&lt;b&gt;Kapı&lt;/b&gt;</a>" in html_metni
    assert f'href="{html.escape(hafta + "&tur=ihlal&durum=new#olaylar")}"' in html_metni
    assert "<b>Kapı</b>" not in html_metni and "inceleme=" not in html_metni


def test_arsiv_haftasi_ozetin_saydigi_olaylari_verir(site):  # noqa: F811
    """İnceleme 21.11.2026: `hafta` bağlantısı özetin haftasını (pazartesi
    00:00 - pazartesi 00:00, Türkiye) açar: tür, kamera ve bekleyen sayıları
    e-postadakiyle aynı; önceki haftanın ve bu sabahın olayları girmez."""
    cerez = _kurucu(site)
    rapor = _pano.rapor_temizle(_rapor(son_olaylar=OLAYLAR))
    _pano.rapor_kaydet(_pano.DEPO, rapor, PAZARTESI - 60, _ozet_ayari())
    hepsi = _pano.DEPO.komut("ZREVRANGEBYSCORE", _pano.ARSIV_ANAHTARI, "+inf", "-inf")
    gece = _pano._pazartesi_gecesi(PAZARTESI)
    ozet = _pano.haftalik_ozet_icerigi(_pano.arsiv_coz(hepsi), {}, gece)
    hafta = _pano._turkiye_gunu(ozet["bas"])
    assert hafta == "2026-11-16"

    def arsiv(sorgu):
        adres = f"{site}/api/durum?arsiv=1&hafta={hafta}{sorgu}"
        kod, _, govde = _istek(adres, basliklar={"Cookie": cerez})
        assert kod == 200, govde
        return json.loads(govde)["arsiv"]

    a = arsiv("")
    assert sorted(o["id"] for o in a["olaylar"]) == [1, 2, 3, 4, 5] and a["hafta"] == hafta
    assert arsiv("&tur=ihlal")["toplam"] == ozet["toplam"]
    for ad, sayi in ozet["tipler"]:
        assert arsiv("&tur=ihlal&tip=" + urllib.parse.quote(ad))["toplam"] == sayi
    for ad, sayi in ozet["yerler"]:  # Rampa'daki sistem olayı tur=ihlal ile dışarıda
        assert arsiv("&tur=ihlal&yer=" + urllib.parse.quote(ad))["toplam"] == sayi
    assert arsiv("&tur=ihlal&durum=new")["toplam"] == ozet["bekleyen"] == 2
    # CSV dosyasının adı haftanın ilk ve son günü
    adres = f"{site}/api/durum?arsiv=1&hafta={hafta}&bicim=csv"
    _, basliklar, _ = _istek(adres, basliklar={"Cookie": cerez})
    assert "dalsan-olaylar-2026-11-16_2026-11-22.csv" in basliklar["Content-Disposition"]
    # Gün olamayan hafta yok sayılır: dönem (7 gün) geçerli
    for bozuk in ("2026-02-30", "16.11.2026", "2026-11-16x"):
        kod, _, govde = _istek(
            f"{site}/api/durum?arsiv=1&hafta={bozuk}", basliklar={"Cookie": cerez}
        )
        assert kod == 200 and json.loads(govde)["arsiv"]["hafta"] == ""
    # Panoda ve demoda: istek haftayı taşır, demo da aynı aralığı süzer
    assert 'p.set("hafta", arsivSuzgeci.hafta)' in PANO_JS
    assert "hafta: hafta," in DEMO_JS


# ------------------------------------------------------- Sistem > Bildirimler


def _bildirim(site, cerez, **govde):  # noqa: F811
    return _post(site, "/api/hesap", {"eylem": "bildirim_ayarla", **govde}, cerez, site)


def _durum_oturumu(site, cerez):  # noqa: F811
    return json.loads(_istek(f"{site}/api/durum", basliklar={"Cookie": cerez})[2])["oturum"]


def test_her_rol_kendi_bildirimini_kaydeder_kurucu_kaydedemez(site):  # noqa: F811
    kurucu = _kurucu(site)
    izleyici = _hazir_hesap(site, kurucu, "bekir", "izleyici", "bekir-parola-123")
    assert "bildirim" not in _durum_oturumu(site, izleyici)  # varsayılan: ayar yok
    kod, _, govde = _bildirim(
        site, izleyici, eposta=" Bekir@Firma.example ", sistem=True, haftalik=False
    )
    assert kod == 200, govde
    beklenen = {"eposta": "Bekir@Firma.example", "sistem": True, "haftalik": False}
    assert json.loads(govde) == {"tamam": True, "bildirim": beklenen}
    assert _durum_oturumu(site, izleyici)["bildirim"] == beklenen
    kayit = json.loads(_pano.DEPO.komut("GET", _pano.KULLANICI_ONEKI + "bekir"))
    assert kayit["bildirim"] == beklenen
    # Kullanıcılar listesi adresi göstermez, yalnız bir bildirim aldığını
    _, _, govde = _istek(f"{site}/api/hesap", basliklar={"Cookie": kurucu})
    veri = json.loads(govde)
    (satir,) = [k for k in veri["kullanicilar"] if k["ad"] == "bekir"]
    assert satir["bildirim"] is True and "Bekir@Firma" not in govde.decode()
    (iz,) = [r for r in veri["kayit"] if r["is"] == "bildirim_ayarla"]
    assert iz["kim"] == "bekir" and iz["ozet"].startswith("Be***@Firma.example · ")
    assert "Sistem uyarıları açık, Haftalık özet kapalı" in iz["ozet"]
    # Kurulum denetimi hesaplardan sayar
    _, _, govde = _istek(f"{site}/api/hesap?islem=kurulum", basliklar={"Cookie": kurucu})
    kart = json.loads(govde)["kurulum"]
    assert (kart["alici_hesap"], kart["haftalik_alici_hesap"]) == (1, 0)
    # Adres boş, anahtarlar kapalı: ayar silinir
    kod, _, govde = _bildirim(site, izleyici, eposta="", sistem=False, haftalik=False)
    assert kod == 200 and json.loads(govde)["bildirim"] is None
    assert "bildirim" not in _durum_oturumu(site, izleyici)
    # Kurucunun kaydı yok
    kod, _, govde = _bildirim(site, kurucu, eposta="kurucu@firma.example", sistem=True)
    assert kod == 400 and json.loads(govde)["hata"] == "kurucu"


@pytest.mark.parametrize(
    "govde",
    [
        {"eposta": "adres-degil", "sistem": True},
        {"eposta": "a@b.co\nBcc: x@y.co", "sistem": True},
        {"eposta": "x" * 250 + "@b.co", "sistem": True},
        {"eposta": "", "haftalik": True},
        {"eposta": "<script>@b.co", "sistem": True},
    ],
)
def test_bildirim_adresi_dogrulanir(site, govde):  # noqa: F811
    kurucu = _kurucu(site)
    operator = _hazir_hesap(site, kurucu, "ali", "operator", "ali-parola-123")
    kod, _, cevap = _bildirim(site, operator, **govde)
    assert kod == 400 and json.loads(cevap)["hata"] == "eposta"
    kayit = json.loads(_pano.DEPO.komut("GET", _pano.KULLANICI_ONEKI + "ali"))
    assert "bildirim" not in kayit


def test_kapali_hesabin_etiketi_yok_ve_bildirim_gitmez(site):  # noqa: F811
    kurucu = _kurucu(site)
    ali = _hazir_hesap(site, kurucu, "ali", "operator", "ali-parola-123")
    assert _bildirim(site, ali, eposta="ali@firma.example", sistem=True)[0] == 200
    istek = {"eylem": "kapat", "ad": "ali", "sifre": SIFRE}
    assert _post(site, "/api/hesap", istek, kurucu, site)[0] == 200
    _, _, govde = _istek(f"{site}/api/hesap", basliklar={"Cookie": kurucu})
    (satir,) = [k for k in json.loads(govde)["kullanicilar"] if k["ad"] == "ali"]
    assert satir["acik"] is False and "bildirim" not in satir
    ayar = _ayar(bekci_alicilar=())
    assert _pano.bildirim_alicilari(_pano.DEPO, ayar, "sistem") == []


def test_kendime_deneme_her_rol_kayitli_adrese_sinir_ortak(site, monkeypatch):  # noqa: F811
    kurucu = _kurucu(site)
    izleyici = _hazir_hesap(site, kurucu, "bekir", "izleyici", "bekir-parola-123")

    def dene(cerez):
        return _post(site, "/api/hesap", {"eylem": "bildirim_dene"}, cerez, site)

    # E-posta yolu yok: izleyiciye kime söyleyeceği (Vercel ayarı değil)
    kod, _, govde = dene(izleyici)
    veri = json.loads(govde)
    assert kod == 409 and veri["hata"] == "eposta_yok" and "yöneticinize" in veri["mesaj"]
    monkeypatch.setenv("SMTP_SUNUCU", "smtp.ornek.com")
    giden = []
    monkeypatch.setattr(_pano, "_eposta_gonder", lambda *arg, **ek: giden.append(arg))
    # Kayıtlı adres yoksa gitmez
    kod, _, govde = dene(izleyici)
    assert kod == 400 and json.loads(govde)["hata"] == "eposta" and giden == []
    assert _bildirim(site, izleyici, eposta="bekir@firma.example")[0] == 200
    for _ in range(_pano.DENEME_EPOSTA_SINIRI):
        kod, _, govde = dene(izleyici)
        assert kod == 200 and json.loads(govde) == {"tamam": True, "saglayici": "smtp"}
    kod, _, govde = dene(izleyici)
    assert kod == 429 and json.loads(govde)["hata"] == "cok_sik"
    (_, alici, konu, metin, html_metni) = giden[0]
    assert alici == "bekir@firma.example" and konu.startswith("Deneme")
    assert "Sistem > Bildirimler'den kendi adresine" in metin
    assert "?bolum=bildirimler#sistem" in html_metni and len(giden) == 5
    # Kurucuda kayıt yok
    kod, _, govde = dene(kurucu)
    assert kod == 400 and json.loads(govde)["hata"] == "kurucu"
    # Yöneticinin Kurulum denetimindeki denemesi aynı sayaca sayılır (hesap başına)
    _, _, govde = _istek(f"{site}/api/hesap", basliklar={"Cookie": kurucu})
    satirlar = [r for r in json.loads(govde)["kayit"] if r["is"] == "deneme_epostasi"]
    assert {(r["kim"], r["ozet"]) for r in satirlar} == {("bekir", "be***@firma.example · SMTP")}


def test_bildirim_ayari_oturum_okumasina_komut_eklemez():
    """Kişinin ayarı /api/durum'un zaten okuduğu hesap kaydından gelir."""
    depo = SayanDepo(lambda: T0)
    ayar = _ayar()
    _hesapli(depo, "ali", "ali@ornek.com", sistem=True)
    cerez = _pano.cerez_uret(ayar, "ali", "1234567890abcdef", 1, T0)
    depo.istek = 0
    oturum = _pano.oturum_coz(depo, ayar, cerez, T0)
    assert depo.istek == 1
    assert _pano.oturum_ozeti(oturum)["bildirim"] == {
        "eposta": "ali@ornek.com",
        "sistem": True,
        "haftalik": False,
    }


# ------------------------------------------------- pano ve demo: derin bağ


def test_pano_derin_bagi_beyaz_listeyle_okur_html_e_yazmaz():
    govde = PANO_JS.split("function derinBagCoz(", 1)[1].split("\n  }\n", 1)[0]
    # Gün biçiminde hafta, bilinen tür dilimi ve durum, düz metin süzgeç, bilinen bölüm
    for parca in ('"hafta"', '"tur"', '"durum"', '"tip"', '"yer"', '"bolum"', "DERIN_BOLUMLER"):
        assert parca in govde
    # Sunucunun ürettiği bütün adlar panoda okunur
    for ad in _pano.DERIN_BAG_ADLARI:
        assert f'"{ad}"' in govde
    assert not re.search(r"\.innerHTML|\.outerHTML|insertAdjacentHTML", PANO_JS)
    # İlk yüklemede ve girişten sonra: yukle() başarılı çizimden sonra uygular
    yukle = PANO_JS.split("async function yukle()", 1)[1].split("\n  }\n", 1)[0]
    assert "derinBagiUygula()" in yukle
    assert "history.replaceState" in PANO_JS


def test_bildirimler_bolumu_panoda_ve_demoda():
    for kimlik in ("bildirim-ayari", "bildirim-adresi", "bildirim-sistem", "bildirim-haftalik"):
        assert f'id="{kimlik}"' in PANO_HTML
    # Gerçek onay kutusu, anahtar rolüyle; etiketiyle sarılı
    for ad in ("sistem", "haftalik"):
        kutu = f'<input id="bildirim-{ad}" class="secim-anahtari" type="checkbox" role="switch"'
        assert kutu in PANO_HTML
    for eylem in ("bildirim_ayarla", "bildirim_dene"):
        assert f'"{eylem}"' in PANO_JS and f'"{eylem}"' in DEMO_JS
    for alan in ("alici_hesap", "haftalik_alici_hesap", "alici_gecersiz"):
        assert f"k.{alan}" in PANO_JS and f"{alan}:" in DEMO_JS
    assert "Bildirim açık" in PANO_JS and 'bildirim_ayarla: "' in PANO_JS
