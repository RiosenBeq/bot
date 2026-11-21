"""Haftalık özet e-postası (Kod maddesi 4).

Opt-in (HAFTALIK_OZET=acik); yeni cron ya da işlev yok: bekçinin çağrısına
biner. Türkiye saatiyle pazartesi 08:00'den sonraki ilk çağrı geçen haftanın
(pazartesi-pazar) özetini bir kez gönderir; aynı hafta ikinci çağrı göndermez,
hiçbir alıcıya gidemezse sonraki çağrı (öbür günler 08:00-09:00 arası) yeniden
dener. İçerik arşivdeki olayların
sayılarıdır: fotoğraf, olay ayrıntısı ve sır girmez. Ağ yok: gönderenler sahtedir."""

import json
import smtplib
from datetime import datetime
from pathlib import Path

import _pano
from test_bekci import GIZLI, SahteGonderici, _bearer, _bekci_iste
from test_cekirdek import _ayar, _rapor
from test_hesap import _kurucu
from test_uctan_uca import _istek, site  # noqa: F401

TR = _pano.TURKIYE_SAATI
# Pazartesi 23.11.2026 08:10 (Türkiye); özet 16-22.11.2026 haftasını anlatır
PAZARTESI = datetime(2026, 11, 23, 8, 10, tzinfo=TR).timestamp()
GUN = 86400


def _ozet_ayari(**degisen):
    alanlar = {
        "haftalik_ozet": "acik",
        "haftalik_alicilar": ("sef@ornek.com.tr", "mudur@ornek.com.tr"),
        "smtp_sunucu": "smtp.ornek.com",
        "smtp_sifresi": GIZLI["SMTP_SIFRESI"],
    }
    alanlar.update(degisen)
    return _ayar(**alanlar)


def _olay(kimlik, gun, saat, baslik="Baret yok", yer="Depo", durum="new", tur="ihlal"):
    return {
        "id": kimlik,
        "zaman": datetime(2026, 11, gun, saat, tzinfo=TR).isoformat(),
        "tur": tur,
        "baslik": baslik,
        "yer": yer,
        "onem": "high",
        "onem_adi": "Yüksek",
        "durum": durum,
        "durum_adi": "",
        "suruyor": False,
        "sure": "",
        "ayrinti": "Gizli ayrıntı metni",
        "foto": True,
    }


OLAYLAR = [
    _olay(1, 16, 9, "Araç-yaya yakınlığı - 1,85 m", "Rampa"),
    _olay(2, 16, 10, durum="reviewed"),
    _olay(3, 18, 11, "Araç-yaya yakınlığı - 1,20 m", "Rampa", durum="false_alarm"),
    _olay(4, 22, 23, yer="<b>Kapı</b>"),
    _olay(5, 20, 12, "Kamera bağlantısı koptu", "Rampa", durum="", tur="sistem"),
    _olay(6, 10, 12),  # önceki hafta
    _olay(7, 23, 1),  # bu hafta: özete girmez
    _olay(8, 1, 12),  # 14 günden eski: okunmaz
]


class SayanDepo(_pano.BellekDepo):
    """Upstash'e giden komutları sayar (komut başına ve boru hattı başına)."""

    def __init__(self, saat):
        super().__init__(saat)
        self.istek = 0
        self.komutlar = []

    def komut(self, *parcalar):
        self.istek += 1
        self.komutlar.append(parcalar[0])
        return super().komut(*parcalar)

    def boru_hatti(self, komutlar):
        self.istek += 1
        self.komutlar += [k[0] for k in komutlar]
        return super().boru_hatti(komutlar)


def _arsivli_depo(simdi=PAZARTESI, **rapor):
    depo = SayanDepo(lambda: simdi)
    ham = _rapor(son_olaylar=OLAYLAR, **rapor)
    _pano.rapor_kaydet(depo, _pano.rapor_temizle(ham), simdi - 60, _ozet_ayari())
    depo.istek, depo.komutlar = 0, []
    return depo


class OzetGonderici(SahteGonderici):
    def __call__(self, ayar, alicilar, konu, metin, basarida=None, html_metni="", ne=""):
        self.htmller = [*getattr(self, "htmller", []), html_metni]
        return super().__call__(ayar, alicilar, konu, metin, basarida=basarida)


# ------------------------------------------------------------------- ayarlar


def test_ayar_opt_in_turkce_yazilabilir_alicilar_bekciden_duser():
    ayar = _pano.ayar_oku({})
    assert (ayar.haftalik_ozet, ayar.haftalik_alicilar) == ("kapali", ())
    ayar = _pano.ayar_oku({"HAFTALIK_OZET": " Açık ", "BEKCI_ALICILAR": "a@b.co, tg:1"})
    assert ayar.haftalik_ozet == "acik" and ayar.haftalik_alicilar == ("a@b.co",)
    ayar = _pano.ayar_oku(
        {
            "HAFTALIK_OZET": "acik",
            "BEKCI_ALICILAR": "a@b.co",
            "HAFTALIK_OZET_ALICILAR": "c@d.co,, e@f.co",
        }
    )
    assert ayar.haftalik_alicilar == ("c@d.co", "e@f.co")
    assert _pano.ayar_oku({"HAFTALIK_OZET": "evet"}).haftalik_ozet == "gecersiz"
    # Opt-in: eksik ayar listesine girmez
    assert _pano.eksikler(_pano.ayar_oku({"HAFTALIK_OZET": "acik"})) == _pano.eksikler(
        _pano.ayar_oku({})
    )


def test_gonderim_zamani_pazartesi_sabahi_turkiye_saatiyle_sonra_her_sabah_bir_saat():
    def an(gun, saat, dakika=0):
        return datetime(2026, 11, gun, saat, dakika, tzinfo=TR).timestamp()

    assert _pano.haftalik_ozet_haftasi(an(23, 7, 59)) is None
    assert _pano.haftalik_ozet_haftasi(an(23, 8)) == "2026-11-23"
    assert _pano.haftalik_ozet_haftasi(an(23, 23, 59)) == "2026-11-23"
    for gun in range(24, 30):  # salı-pazar: yalnız 08:00-08:59, aynı haftanın pazartesisi
        assert _pano.haftalik_ozet_haftasi(an(gun, 7, 59)) is None
        assert _pano.haftalik_ozet_haftasi(an(gun, 8, 30)) == "2026-11-23"
        assert _pano.haftalik_ozet_haftasi(an(gun, 9)) is None
    assert _pano.haftalik_ozet_haftasi(an(30, 8)) == "2026-11-30"
    # Vercel Cron 05:00 UTC = 08:00 Türkiye
    utc = datetime.fromisoformat("2026-11-23T05:00:00+00:00").timestamp()
    assert _pano.haftalik_ozet_haftasi(utc) == "2026-11-23"


# ------------------------------------------------------------------- içerik


def test_icerik_gecen_haftanin_sayilari_foto_ve_ayrinti_yok():
    depo = _arsivli_depo(
        calisma={"ay": "2026-11", "sistem_yuzde": 99.62, "kamera_yuzde": 98.9, "olculen_saat": 530}
    )
    gonder = OzetGonderici()
    sonuc = _pano.haftalik_ozet_isle(depo, _ozet_ayari(), PAZARTESI, gonder)
    assert sonuc == {"gonderildi": True, "gonderilen": 1, "hafta": "2026-11-23"}
    (alicilar, konu, metin), html_metni = gonder.cagrilar[0], gonder.htmller[0]
    assert alicilar == ("sef@ornek.com.tr", "mudur@ornek.com.tr")
    assert konu == "Haftalık özet: Fabrika, 16.11 - 22.11.2026: 4 ihlal"
    assert "16.11.2026 - 22.11.2026" in metin
    assert "4 ihlal (önceki hafta 1, +3); 1 sistem olayı." in metin
    assert "  Pzt 16.11: 2\n  Sal 17.11: 0\n  Çar 18.11: 1\n" in metin
    assert "  Paz 22.11: 1\n" in metin
    # Tür ölçümsüz başlıktır; en çok olan önce, eşitse alfabe sırası
    assert "En sık türler:\n  Araç-yaya yakınlığı: 2\n  Baret yok: 2\n" in metin
    assert "  Rampa: 2\n" in metin
    assert "  Bekliyor: 2\n  İncelendi: 1\n  Yanlış alarm: 1\n" in metin
    assert "Kasım 2026 çalışma oranı: %99,6 (kameralar %98,9; 530 saat ölçüldü)." in metin
    assert "Bağlantı şu an canlı" in metin
    # HTML: aynı sayılar, değerler kaçışlı; fotoğraf, ayrıntı ve sır yok
    assert "&lt;b&gt;Kapı&lt;/b&gt;" in html_metni and "<b>Kapı</b>" not in html_metni
    assert ">4 ihlal (önceki hafta 1, +3); 1 sistem olayı.</p>" in html_metni
    for icerik in (metin, html_metni):
        for yasak in ("Gizli ayrıntı", "<img", "/api/foto", "base64", GIZLI["SMTP_SIFRESI"]):
            assert yasak not in icerik
        assert "1,85" not in icerik  # ölçüm türün adına girmez


def test_bos_hafta_ve_calisma_yoksa_da_okunur_ozet():
    depo = SayanDepo(lambda: PAZARTESI)
    gonder = OzetGonderici()
    assert _pano.haftalik_ozet_isle(depo, _ozet_ayari(), PAZARTESI, gonder)["gonderildi"]
    _, konu, metin = gonder.cagrilar[0]
    assert konu.endswith(": 0 ihlal")
    assert "0 ihlal (önceki hafta da 0); 0 sistem olayı." in metin
    assert "En sık türler:\n  -\n" in metin
    assert "Çalışma oranı: fabrika programı göndermiyor." in metin
    assert "Fabrikadan henüz rapor gelmedi." in metin


# --------------------------------------------------- bir kez, yeniden deneme


def test_hafta_basina_bir_kez_baska_gun_komut_harcamaz():
    depo = _arsivli_depo()
    ayar, gonder = _ozet_ayari(), OzetGonderici()
    # Pazartesi 08:00'den önce ve salı 09:10: hiçbir komut yok
    for simdi in (PAZARTESI - 11 * 60, PAZARTESI + GUN + 3600):
        assert _pano.haftalik_ozet_isle(depo, ayar, simdi, gonder)["sebep"] == "zamani_degil"
    assert depo.istek == 0 and gonder.cagrilar == []
    # Kapalıyken de
    kapali = _ozet_ayari(haftalik_ozet="kapali")
    assert _pano.haftalik_ozet_isle(depo, kapali, PAZARTESI, gonder) == {"atlandi": True}
    assert depo.istek == 0
    # Gönderim: kilit (1) + okuma boru hattı (1) + işareti uzatma ve son an (1)
    assert _pano.haftalik_ozet_isle(depo, ayar, PAZARTESI, gonder)["gonderildi"]
    assert depo.istek == 3
    assert depo.komutlar == ["SET", "ZREVRANGEBYSCORE", "MGET", "EXPIRE", "SET"]
    assert depo.komut("TTL", "dalsan:haftalik_ozet:2026-11-23") > 7 * GUN
    assert depo.komut("GET", _pano.HAFTALIK_OZET_SON_ANAHTARI) == str(int(PAZARTESI))
    # Aynı pazartesi yeniden çağrılınca tek SET NX: göndermez
    depo.istek = 0
    sonuc = _pano.haftalik_ozet_isle(depo, ayar, PAZARTESI + 3600, gonder)
    assert sonuc == {"gonderildi": False, "sebep": "bu_hafta_gitti"} and depo.istek == 1
    assert len(gonder.cagrilar) == 1
    # Salı sabahı (yeniden deneme saati) gitmiş haftada tek SET NX
    depo.istek = 0
    sonuc = _pano.haftalik_ozet_isle(depo, ayar, PAZARTESI + GUN, gonder)
    assert sonuc == {"gonderildi": False, "sebep": "bu_hafta_gitti"} and depo.istek == 1
    # Ertesi pazartesi yeniden gider
    assert _pano.haftalik_ozet_isle(depo, ayar, PAZARTESI + 7 * GUN, gonder)["gonderildi"]
    assert len(gonder.cagrilar) == 2


def test_hic_gidemezse_isaret_silinir_sonraki_cagri_yeniden_dener():
    depo = _arsivli_depo()
    ayar = _ozet_ayari()
    gidemeyen = OzetGonderici(sonuc=0)
    sonuc = _pano.haftalik_ozet_isle(depo, ayar, PAZARTESI, gidemeyen)
    assert sonuc == {"gonderildi": False, "sebep": "gidemedi"}
    assert depo.komut("GET", "dalsan:haftalik_ozet:2026-11-23") is None
    assert depo.komut("GET", _pano.HAFTALIK_OZET_SON_ANAHTARI) is None
    gonder = OzetGonderici()
    assert _pano.haftalik_ozet_isle(depo, ayar, PAZARTESI + 300, gonder)["gonderildi"]
    # Alıcı yoksa kilit bile alınmaz
    bos = _ozet_ayari(haftalik_alicilar=())
    assert _pano.haftalik_ozet_isle(SayanDepo(lambda: PAZARTESI), bos, PAZARTESI, gonder) == {
        "gonderildi": False,
        "sebep": "alici_yok",
    }


def test_pazartesi_gidemeyen_ozet_sali_sabahi_gider():
    """Tek tetikleyici günde bir çalışan Vercel Cron'dur: pazartesi hiçbir
    alıcıya gidemeyen özet salı 08:00 çağrısında aynı hafta için gider."""
    depo = _arsivli_depo()
    ayar = _ozet_ayari()
    assert _pano.haftalik_ozet_isle(depo, ayar, PAZARTESI, OzetGonderici(sonuc=0))["sebep"] == (
        "gidemedi"
    )
    gonder = OzetGonderici()
    sonuc = _pano.haftalik_ozet_isle(depo, ayar, PAZARTESI + GUN, gonder)
    assert sonuc == {"gonderildi": True, "gonderilen": 1, "hafta": "2026-11-23"}
    # İçerik yine geçen haftadır (16-22.11), salı değil
    assert gonder.cagrilar[0][1] == "Haftalık özet: Fabrika, 16.11 - 22.11.2026: 4 ihlal"
    assert depo.komut("GET", _pano.HAFTALIK_OZET_SON_ANAHTARI) == str(int(PAZARTESI + GUN))


def test_isaret_uzatilamazsa_gonderimden_sonra_bir_kez_daha_denenir():
    """İlk e-postadan sonraki uzatma geçici bir depo hatasıyla düşerse işaret
    gönderimden sonra yeniden uzatılır: 5 dakikalık kilit kalkıp özet bütün
    alıcılara ikinci kez gitmez."""

    class BirKezDusen(SayanDepo):
        dustu = False

        def boru_hatti(self, komutlar):
            if komutlar[0][0] == "EXPIRE" and not self.dustu:
                self.dustu = True
                raise _pano.DepoHatasi("Upstash geçici hata")
            return super().boru_hatti(komutlar)

    giden = []

    def gonder(ayar, alicilar, konu, metin, basarida=None, html_metni="", ne=""):
        # Gerçek alıcı döngüsü (basarida'nın hatasını yutar), sahte e-posta
        return _pano._alicilara_gonder(
            ayar, alicilar, konu, metin, lambda _a, alici, *_: giden.append(alici), basarida, ne
        )

    saat = [PAZARTESI]
    depo = BirKezDusen(lambda: saat[0])
    ayar = _ozet_ayari()
    assert _pano.haftalik_ozet_isle(depo, ayar, PAZARTESI, gonder)["gonderilen"] == 2
    assert depo.dustu
    assert depo.komut("TTL", "dalsan:haftalik_ozet:2026-11-23") > 7 * GUN
    assert depo.komut("GET", _pano.HAFTALIK_OZET_SON_ANAHTARI) == str(int(PAZARTESI))
    # Kilit süresi (300 sn) geçtikten sonraki çağrı göndermez
    saat[0] = PAZARTESI + 301
    sonuc = _pano.haftalik_ozet_isle(depo, ayar, PAZARTESI + 301, gonder)
    assert sonuc == {"gonderildi": False, "sebep": "bu_hafta_gitti"}
    assert giden == ["sef@ornek.com.tr", "mudur@ornek.com.tr"]


def test_eposta_duz_metin_ve_html_tek_smtp_oturumunda_ek_yok(monkeypatch, capsys):
    """Gerçek gönderim yolu (sahte smtplib): her alıcıya multipart/alternative
    (düz metin + HTML), ek (fotoğraf) yok; bir alıcının hatası ötekini
    durdurmaz, günlüğe "Haftalık özet gidemedi" sırsız yazılır."""
    iletiler, acilis = [], []

    class SMTP:
        def __init__(self, sunucu, port, timeout=None):
            acilis.append(sunucu)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def starttls(self, context=None):
            pass

        def login(self, kullanici, sifre):
            pass

        def send_message(self, mesaj):
            if mesaj["To"] == "kopuk@ornek.com.tr":
                raise smtplib.SMTPRecipientsRefused({mesaj["To"]: (550, b"yok")})
            iletiler.append(mesaj)

    monkeypatch.setattr(_pano.smtplib, "SMTP", SMTP)
    ayar = _ozet_ayari(haftalik_alicilar=("kopuk@ornek.com.tr", "sef@ornek.com.tr"))
    sonuc = _pano.haftalik_ozet_isle(_arsivli_depo(), ayar, PAZARTESI)
    assert sonuc["gonderildi"] and sonuc["gonderilen"] == 1 and len(acilis) == 1
    (ileti,) = iletiler
    assert ileti.get_content_type() == "multipart/alternative"
    turler = [parca.get_content_type() for parca in ileti.iter_parts()]
    assert turler == ["text/plain", "text/html"]
    assert list(ileti.iter_attachments()) == []
    assert "4 ihlal" in ileti.get_body(("plain",)).get_content()
    gunluk = capsys.readouterr().err
    assert "Haftalık özet gidemedi" in gunluk and "kopuk@ornek" not in gunluk
    assert GIZLI["SMTP_SIFRESI"] not in gunluk


# ------------------------------------------------ uç nokta ve kurulum kartı


def test_bekci_cagrisiyla_gider_bekci_kapaliyken_de_kurulum_karti_gosterir(
    site,  # noqa: F811
    monkeypatch,
):
    for ad, deger in GIZLI.items():
        monkeypatch.setenv(ad, deger)
    monkeypatch.setenv("HAFTALIK_OZET", "acik")
    monkeypatch.setenv("HAFTALIK_OZET_ALICILAR", "sef@ornek.com.tr")
    monkeypatch.setenv("SMTP_SUNUCU", "smtp.ornek.com")
    giden = []
    monkeypatch.setattr(_pano, "_eposta_gonder", lambda *arg, **ek: giden.append((arg, ek)))
    kurucu = _kurucu(site)
    kod, _, govde = _istek(f"{site}/api/hesap?islem=kurulum", basliklar={"Cookie": kurucu})
    kart = json.loads(govde)["kurulum"]
    assert kod == 200 and kart["haftalik_ozet"] is True and kart["haftalik_alici"] == 1
    assert kart["haftalik_ozet_gecersiz"] is False and kart["haftalik_son"] is None
    # Pazartesi değilken bekçi bugünkü gibi cevap verir, özet yalnız durumunu ekler
    monkeypatch.setattr(_pano, "haftalik_ozet_haftasi", lambda simdi: None)
    kod, _, govde = _bekci_iste(site, _bearer(GIZLI["CRON_SECRET"]))
    assert kod == 200
    assert json.loads(govde) == {
        "atlandi": True,
        "haftalik": {"gonderildi": False, "sebep": "zamani_degil"},
    }
    # Pazartesi sabahı: bir kez gider (BEKCI kapalı olsa da)
    monkeypatch.setattr(_pano, "haftalik_ozet_haftasi", lambda simdi: "2026-11-23")
    kod, _, govde = _bekci_iste(site, _bearer(GIZLI["CRON_SECRET"]))
    veri = json.loads(govde)
    assert kod == 200 and veri["haftalik"]["gonderildi"] is True
    ((arg, ek),) = giden
    assert arg[1] == "sef@ornek.com.tr" and "<html" in ek["html_metni"]
    kod, _, govde = _bekci_iste(site, _bearer(GIZLI["CRON_SECRET"]))
    assert json.loads(govde)["haftalik"]["sebep"] == "bu_hafta_gitti" and len(giden) == 1
    metin = govde.decode()
    for gizli in [*GIZLI.values(), "sef@ornek.com.tr", "smtp.ornek.com"]:
        assert gizli not in metin
    # Kurulum kartı son gönderimi görür
    _, _, govde = _istek(f"{site}/api/hesap?islem=kurulum", basliklar={"Cookie": kurucu})
    assert json.loads(govde)["kurulum"]["haftalik_son"] is not None
    # Kapalıyken bekçinin cevabı birebir eskisi gibi
    monkeypatch.delenv("HAFTALIK_OZET")
    kod, _, govde = _bekci_iste(site, _bearer(GIZLI["CRON_SECRET"]))
    assert kod == 200 and json.loads(govde) == {"atlandi": True}


def test_kurulum_karti_satiri_pano_ve_demoda():
    kok = Path(__file__).resolve().parents[1]
    pano = (kok / "public" / "pano.js").read_text(encoding="utf-8")
    demo = (kok / "public" / "demo.js").read_text(encoding="utf-8")
    assert '"Haftalık özet e-postası"' in pano
    for alan in ("haftalik_ozet", "haftalik_ozet_gecersiz", "haftalik_alici", "haftalik_son"):
        assert f"k.{alan}" in pano and f"{alan}:" in demo
