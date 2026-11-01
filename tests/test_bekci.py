"""'Sistemden haber yok' dış alarmı (öneri 5, docs/20 §3).

Bayat rapor -> tek uyarı -> ikinci çağrı susar -> taze rapor işareti siler ->
yeniden kesilince yeniden uyarır. Hiçbir bildirim gidemezse işaret bırakılır ve
sonraki çağrı yeniden dener. Ana pano ve her izlenen tesis ayrı işaret taşır.
Uç nokta yalnız CRON_SECRET / BEKCI_ANAHTARI ile açılır; bayat hedef varsa 503
döner (dış izleme servisi kendisi alarm verebilsin). Sırlar hiçbir cevaba ve
günlüğe girmez. Ağ yok: gönderenler sahtedir."""

import http.client
import json
import smtplib
import socket
import time
import urllib.parse
from pathlib import Path

import _pano
import pytest
from test_cekirdek import Saat, _ayar, _rapor
from test_uctan_uca import RAPOR, _istek, _rapor_gonder, site  # noqa: F401

KOK = Path(__file__).resolve().parents[1]
T0 = 1_800_000_000.0
DK = 60
ISARET = "dalsan:bekci:uyarildi"
GIZLI = {
    "BEKCI_ANAHTARI": "bekci-gizli-anahtar-0123456789",
    "CRON_SECRET": "cron-gizli-sir-0123456789",
    "SMTP_SIFRESI": "smtp-gizli-sifre-0123",
    "TELEGRAM_BOT": "123456:telegram-gizli-jeton",
}


class SahteGonderici:
    """bekci_uyari_gonder yerine: çağrıları kaydeder, istenen sayıyı döner."""

    def __init__(self, sonuc=1):
        self.sonuc = sonuc
        self.cagrilar = []

    def __call__(self, ayar, alicilar, konu, metin, basarida=None):
        self.cagrilar.append((alicilar, konu, metin))
        if self.sonuc and basarida:
            basarida()
        return self.sonuc


class Oldurulen(Exception):
    """Gönderim sürerken Vercel işlevi durdurulmuş gibi."""


def _bekci_ayari(**degisen):
    alanlar = {"bekci": "acik", "bekci_alicilar": ("sef@ornek.com.tr", "tg:12345")}
    alanlar.update(degisen)
    return _ayar(**alanlar)


def _kaydet(depo, ham, simdi, ayar):
    return _pano.rapor_kaydet(depo, _pano.rapor_temizle(ham), simdi, ayar)


def _tesisli(kimlik):
    return _rapor(tesis={"id": kimlik, "ad": kimlik.capitalize() + " fabrikası"})


# ------------------------------------------------------------------- ayarlar


def test_bekci_ayarlari_okunur_sirlar_gizli_ve_eksiklere_girmez():
    ortam = {
        "BEKCI": " Acik ",
        "BEKCI_ESIK_DK": "30",
        "BEKCI_ALICILAR": "a@b.co, tg:-100123 ,, c@d.co",
        "SMTP_SUNUCU": "smtp.ornek.com",
        "SMTP_PORT": "465",
        "SMTP_KULLANICI": "pano@ornek.com",
        "SMTP_KIMDEN": "pano@ornek.com",
        "TELEGRAM_SOHBET": "-100999",
        **GIZLI,
    }
    ayar = _pano.ayar_oku(ortam)
    assert ayar.bekci == "acik" and ayar.bekci_esik_dk == 30 and ayar.smtp_port == 465
    assert ayar.bekci_alicilar == ("a@b.co", "tg:-100123", "c@d.co")
    assert _pano.bekci_alicilari(ayar) == ("a@b.co", "tg:-100123", "c@d.co", "tg:-100999")
    for sir in GIZLI.values():
        assert sir not in repr(ayar)
    assert _pano.eksikler(ayar) == _pano.eksikler(_pano.ayar_oku({}))

    bos = _pano.ayar_oku({})
    assert (bos.bekci, bos.bekci_esik_dk, bos.bekci_alicilar, bos.smtp_port) == (
        "kapali",
        20,
        (),
        587,
    )
    assert _pano.bekci_alicilari(bos) == ()
    for ham, beklenen in (("abc", 20), ("0", 1), ("99999", 1440), ("-5", 20)):
        assert _pano.ayar_oku({"BEKCI_ESIK_DK": ham}).bekci_esik_dk == beklenen


def test_bekci_ayari_turkce_yazilabilir_taninmayan_deger_hicbir_sey_yapmaz():
    """BEKCI="açık" sessizce kapalı kalmasın: Türkçe harfler katlanır. Tanınmayan
    bir değer (ör. "evet") bekçiyi açmaz; /api/bekci onu 503 ile bildirir."""
    for ham in ("acik", " Açık ", "AÇIK", "açık"):
        assert _pano.ayar_oku({"BEKCI": ham}).bekci == "acik", ham
    for ham in ("", "  ", "kapali", "Kapalı", "KAPALI"):
        assert _pano.ayar_oku({"BEKCI": ham}).bekci == "kapali", ham
    for ham in ("evet", "on", "1", "true", "açık değil"):
        ayar = _pano.ayar_oku({"BEKCI": ham, "BEKCI_ALICILAR": "sef@ornek.com.tr"})
        assert ayar.bekci == "gecersiz", ham
        depo = _pano.BellekDepo(Saat(T0))
        _kaydet(depo, _rapor(), T0, ayar)
        gonder = SahteGonderici()
        assert _pano.bekci_isle(depo, ayar, T0 + 3600, gonder) == {"atlandi": True}
        assert not gonder.cagrilar


# ------------------------------------------------------------------ çekirdek


def test_bayat_rapor_tek_uyari_duzelince_yeniden_uyari():
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _bekci_ayari()
    gonder = SahteGonderici()
    rapor = _rapor(bilgisayar={"ad": "Gebze fabrikası"})
    _kaydet(depo, rapor, T0, ayar)

    def kontrol(dk):
        saat.simdi = T0 + dk * DK
        return _pano.bekci_isle(depo, ayar, saat.simdi, gonder)

    sonuc = kontrol(10)  # haber yok ama eşik (20 dk) dolmadı
    assert sonuc["uyarildi"] is False and sonuc["durum"][0]["bayat"] is False
    assert not gonder.cagrilar

    sonuc = kontrol(21)
    assert sonuc["uyarildi"] is True and sonuc["gonderilen"] == 1
    assert sonuc["durum"] == [
        {"ad": "Gebze fabrikası", "baglanti": "yok", "gecikme_dk": 21, "bayat": True}
    ]
    alicilar, konu, metin = gonder.cagrilar[0]
    assert alicilar == ("sef@ornek.com.tr", "tg:12345")
    assert "Gebze fabrikası" in konu and "21 dakika" in metin
    assert "internet" in metin and "Son rapor" in metin

    # Sonraki çağrılar uyarmaz (gönderim başarılı: işaret kilitten uzun yaşar)
    assert kontrol(25)["uyarildi"] is False
    assert kontrol(21 + _pano.BEKCI_KILIT_SN // DK + 2)["uyarildi"] is False
    assert len(gonder.cagrilar) == 1

    # Taze rapor işareti siler
    _kaydet(depo, rapor, T0 + 41 * DK, ayar)
    assert depo.komut("GET", ISARET) is None
    assert kontrol(42)["durum"][0]["bayat"] is False
    # Yeniden kesilince yeniden uyarır
    assert kontrol(41 + 21)["uyarildi"] is True
    assert len(gonder.cagrilar) == 2


def test_hic_bildirim_gidemezse_isaret_birakilir_sonraki_cagri_yeniden_dener():
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _bekci_ayari()
    _kaydet(depo, _rapor(), T0, ayar)
    gonder = SahteGonderici(sonuc=0)
    saat.simdi = T0 + 21 * DK
    sonuc = _pano.bekci_isle(depo, ayar, saat.simdi, gonder)
    assert sonuc["uyarildi"] is False and sonuc["gonderilen"] == 0
    assert sonuc["durum"][0]["bayat"] is True
    assert depo.komut("GET", ISARET) is None
    saat.simdi += DK
    _pano.bekci_isle(depo, ayar, saat.simdi, gonder)
    assert len(gonder.cagrilar) == 2
    gonder.sonuc = 1
    saat.simdi += DK
    assert _pano.bekci_isle(depo, ayar, saat.simdi, gonder)["uyarildi"] is True
    saat.simdi += DK
    assert _pano.bekci_isle(depo, ayar, saat.simdi, gonder)["uyarildi"] is False
    assert len(gonder.cagrilar) == 3


def test_gonderim_yarida_kalirsa_kilit_kisa_surer_ilk_basari_isareti_uzatir():
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _bekci_ayari()
    _kaydet(depo, _rapor(), T0, ayar)
    saat.simdi = T0 + 21 * DK

    def oldur(*_, **__):
        raise Oldurulen

    with pytest.raises(Oldurulen):
        _pano.bekci_isle(depo, ayar, saat.simdi, oldur)
    # Kilit duruyor: aynı anda gelen ikinci çağrı ikinci kez göndermez
    assert depo.komut("GET", ISARET) is not None
    # Hiçbir şey gitmeden durduysa kilit kısa sürede düşer ve yeniden denenir
    saat.simdi += _pano.BEKCI_KILIT_SN + 1
    gonder = SahteGonderici()
    assert _pano.bekci_isle(depo, ayar, saat.simdi, gonder)["uyarildi"] is True

    # Bir alıcıya gittikten sonra durursa işaret uzamıştır: tekrar gönderilmez
    depo2 = _pano.BellekDepo(saat)
    _kaydet(depo2, _rapor(), saat.simdi - 21 * DK, ayar)

    def bir_gidip_oldur(ayar, alicilar, konu, metin, basarida=None):
        basarida()
        raise Oldurulen

    with pytest.raises(Oldurulen):
        _pano.bekci_isle(depo2, ayar, saat.simdi, bir_gidip_oldur)
    saat.simdi += _pano.BEKCI_KILIT_SN + 1
    assert depo2.komut("GET", ISARET) is not None
    assert _pano.bekci_isle(depo2, ayar, saat.simdi, gonder)["uyarildi"] is False


def test_bekci_kapaliyken_hicbir_sey_yapmaz():
    depo = _pano.BellekDepo(Saat(T0))
    _kaydet(depo, _rapor(), T0, _ayar())
    gonder = SahteGonderici()
    assert _pano.bekci_isle(depo, _ayar(), T0 + 3600, gonder) == {"atlandi": True}
    assert not gonder.cagrilar


def test_hic_rapor_gelmediyse_uyari_yok():
    gonder = SahteGonderici()
    sonuc = _pano.bekci_isle(_pano.BellekDepo(Saat(T0)), _bekci_ayari(), T0, gonder)
    assert sonuc["durum"] == [
        {"ad": "Fabrika", "baglanti": "hic", "gecikme_dk": None, "bayat": False}
    ]
    assert not gonder.cagrilar


def test_program_kapatilip_acilmadiysa_uyarir():
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _bekci_ayari()
    _kaydet(depo, _rapor(kapanis=True), T0, ayar)
    gonder = SahteGonderici()
    sonuc = _pano.bekci_isle(depo, ayar, T0 + 25 * DK, gonder)
    assert sonuc["uyarildi"] is True and sonuc["durum"][0]["baglanti"] == "kapandi"
    assert "kapatıldı" in gonder.cagrilar[0][2]


def test_tesis_isaretleri_birbirinden_bagimsiz():
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _bekci_ayari()
    gonder = SahteGonderici()

    def rapor(kimlik, dk):
        saat.simdi = T0 + dk * DK
        assert "filo" in _kaydet(depo, _tesisli(kimlik), saat.simdi, ayar)

    def kontrol(dk):
        saat.simdi = T0 + dk * DK
        return _pano.bekci_isle(depo, ayar, saat.simdi, gonder)

    for kimlik in ("gebze", "izmir", "bursa"):
        rapor(kimlik, 0)  # gebze ana tesis olur
    rapor("gebze", 15)
    rapor("bursa", 15)
    rapor("gebze", 21)
    sonuc = kontrol(21)  # yalnız izmir 21 dakikadır sessiz
    assert sonuc["uyarildi"] is True and len(gonder.cagrilar) == 1
    assert "Izmir fabrikası" in gonder.cagrilar[0][1]
    durum = {d["ad"]: d for d in sonuc["durum"]}
    assert set(durum) == {"Gebze fabrikası", "Izmir fabrikası", "Bursa fabrikası"}
    assert [d["ad"] for d in sonuc["durum"] if d["bayat"]] == ["Izmir fabrikası"]
    assert depo.komut("GET", ISARET + ":izmir") is not None
    assert depo.komut("GET", ISARET) is None and depo.komut("GET", ISARET + ":bursa") is None

    rapor("gebze", 36)
    sonuc = kontrol(36)  # izmir zaten uyarıldı; bursa şimdi 21 dakikadır sessiz
    assert len(gonder.cagrilar) == 2 and "Bursa fabrikası" in gonder.cagrilar[1][1]

    rapor("izmir", 37)  # izmir döndü: yalnız onun işareti silinir
    assert depo.komut("GET", ISARET + ":izmir") is None
    assert depo.komut("GET", ISARET + ":bursa") is not None
    assert depo.komut("GET", ISARET) is None


def _hedefler(sonuc):
    return [(d["ad"], d["baglanti"], d["bayat"]) for d in sonuc["durum"]]


def test_ana_tesis_susarsa_uyari_onu_adiyla_anar_ayni_fabrika_iki_kez_sayilmaz():
    """gebze ana (ilk rapor), izmir izlenir. Yönetici ANA_TESIS=izmir yazar;
    izmir'in programı o sırada kapalı, gebze rapor göndermeyi sürdürür. Pano
    gebze'nin son raporunu gösterse de komut alan izmir'dir: bekçi susan izmir'i
    adıyla anar, canlı gebze bir kez sayılır ve uyarılmaz."""
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    once = _bekci_ayari()
    assert _kaydet(depo, _tesisli("gebze"), T0, once)["filo"] == {"ana": True}
    assert _kaydet(depo, _tesisli("izmir"), T0, once)["filo"] == {"ana": False}
    sonra = _bekci_ayari(ana_tesis="izmir")
    for dk in range(1, 26):  # gebze canlı: her dakika rapor
        saat.simdi = T0 + dk * DK
        assert _kaydet(depo, _tesisli("gebze"), saat.simdi, sonra) == {"filo": {"ana": False}}
    gonder = SahteGonderici()
    sonuc = _pano.bekci_isle(depo, sonra, saat.simdi, gonder)
    assert _hedefler(sonuc) == [("Izmir fabrikası", "yok", True), ("Gebze fabrikası", "canli", False)]
    assert len(gonder.cagrilar) == 1 and "Izmir fabrikası" in gonder.cagrilar[0][1]
    assert not any("Gebze" in konu for _, konu, _ in gonder.cagrilar)

    saat.simdi += 30  # izmir döndü: ana olur, işareti kalkar
    assert _kaydet(depo, _tesisli("izmir"), saat.simdi, sonra)["filo"] == {"ana": True}
    assert depo.komut("GET", ISARET + ":izmir") is None
    sonuc = _pano.bekci_isle(depo, sonra, saat.simdi, gonder)
    assert _hedefler(sonuc) == [("Izmir fabrikası", "canli", False), ("Gebze fabrikası", "canli", False)]


def test_ana_tesis_hic_rapor_gondermediyse_hedef_onun_kimligini_tasir():
    depo = _pano.BellekDepo(Saat(T0))
    ayar = _bekci_ayari(ana_tesis="izmir")
    assert _kaydet(depo, _tesisli("gebze"), T0, ayar) == {"filo": {"ana": False}}  # pano boş
    sonuc = _pano.bekci_isle(depo, ayar, T0 + 30 * DK, SahteGonderici())
    assert _hedefler(sonuc) == [("izmir", "hic", False), ("Gebze fabrikası", "yok", True)]


def test_eski_program_komut_alirken_ana_tesis_ayrica_izlenir():
    """Kimliksiz program canlıyken komutları o alır ve pano onu gösterir; ayardaki
    ana tesis ayrı bir fabrikadır: o susarsa da uyarılır (atlanmaz)."""
    saat = Saat(T0)
    depo = _pano.BellekDepo(saat)
    ayar = _bekci_ayari(ana_tesis="izmir")
    assert _kaydet(depo, _tesisli("izmir"), T0, ayar)["filo"] == {"ana": True}
    for dk in range(1, 26):  # gebze'deki eski program her dakika rapor gönderir
        saat.simdi = T0 + dk * DK
        _kaydet(depo, _rapor(bilgisayar={"ad": "Gebze fabrikası"}), saat.simdi, ayar)
    gonder = SahteGonderici()
    sonuc = _pano.bekci_isle(depo, ayar, saat.simdi, gonder)
    assert _hedefler(sonuc) == [("Gebze fabrikası", "canli", False), ("Izmir fabrikası", "yok", True)]
    assert len(gonder.cagrilar) == 1 and "Izmir fabrikası" in gonder.cagrilar[0][1]


# ---------------------------------------------------------------- gönderim


def test_bir_alicinin_hatasi_otekileri_durdurmaz_gunluge_sir_yazilmaz(capsys):
    ayar = _bekci_ayari(smtp_sifresi="smtp-gizli-sifre-9", telegram_bot="123:gizli-jeton")
    gidenler = []

    def eposta(ayar, alici, konu, metin):
        if alici == "bozuk":
            raise ValueError(f"Invalid address bozuk {ayar.smtp_sifresi}")
        if alici == "kopuk@ornek.com":
            raise smtplib.SMTPAuthenticationError(535, ayar.smtp_sifresi.encode())
        gidenler.append(alici)

    def telegram(ayar, sohbet, metin):
        if sohbet == "1":
            raise http.client.InvalidURL(f"/bot{ayar.telegram_bot}/sendMessage")
        gidenler.append("tg:" + sohbet)

    basari = []
    sayi = _pano.bekci_uyari_gonder(
        ayar,
        ("bozuk", "kopuk@ornek.com", "tg:1", "iyi@ornek.com", "tg:2"),
        "konu",
        "metin",
        eposta,
        telegram,
        lambda: basari.append(1),
    )
    assert sayi == 2 and sorted(gidenler) == ["iyi@ornek.com", "tg:2"]
    assert basari == [1]  # ilk başarıda bir kez
    gunluk = capsys.readouterr().err
    assert gunluk.count("Bekçi bildirimi gidemedi") == 3
    assert "SMTPAuthenticationError" in gunluk and "ValueError" in gunluk
    for sir in ("smtp-gizli-sifre-9", "gizli-jeton", "kopuk@ornek.com"):
        assert sir not in gunluk


def test_eposta_tls_ile_gider_baslik_enjeksiyonu_reddedilir(monkeypatch):
    olaylar = []

    class SahteSMTP:
        def __init__(self, sunucu, port, context=None, timeout=None):
            olaylar.append(("ac", type(self).__name__, sunucu, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            olaylar.append(("kapat",))

        def starttls(self, context=None):
            olaylar.append(("starttls",))

        def login(self, kullanici, sifre):
            olaylar.append(("login", kullanici))

        def send_message(self, mesaj):
            olaylar.append(("gonder", mesaj["To"], mesaj["Subject"], mesaj.get_content().strip()))

    class SMTP(SahteSMTP):
        pass

    class SMTP_SSL(SahteSMTP):  # noqa: N801 - smtplib'deki adın aynısı
        pass

    monkeypatch.setattr(_pano.smtplib, "SMTP", SMTP)
    monkeypatch.setattr(_pano.smtplib, "SMTP_SSL", SMTP_SSL)
    ayar = _bekci_ayari(
        smtp_sunucu="smtp.ornek.com",
        smtp_kullanici="pano@ornek.com",
        smtp_sifresi="s",
        smtp_kimden="pano@ornek.com",
    )
    _pano._eposta_gonder(ayar, "sef@ornek.com.tr", "Konu", "Metin")
    assert [o[0] for o in olaylar] == ["ac", "starttls", "login", "gonder", "kapat"]
    assert olaylar[0][1:4] == ("SMTP", "smtp.ornek.com", 587)
    assert olaylar[3] == ("gonder", "sef@ornek.com.tr", "Konu", "Metin")

    olaylar.clear()
    _pano._eposta_gonder(
        _bekci_ayari(smtp_sunucu="smtp.ornek.com", smtp_port=465), "a@b.co", "K", "M"
    )
    assert [o[0] for o in olaylar] == ["ac", "gonder", "kapat"] and olaylar[0][1] == "SMTP_SSL"

    olaylar.clear()
    for bozuk in ("a@b.co\nBcc: x@y.co", "adres-degil", "a@b.co, c@d.co"):
        with pytest.raises(ValueError):
            _pano._eposta_gonder(ayar, bozuk, "K", "M")
    with pytest.raises(_pano.BildirimHatasi):
        _pano._eposta_gonder(_bekci_ayari(), "a@b.co", "K", "M")  # SMTP tanımlı değil
    assert olaylar == []


def test_eposta_gittikten_sonra_kapanis_hatasi_basarisizlik_sayilmaz(monkeypatch):
    """Sunucu QUIT'e 221 dışında cevap verirse smtplib kapanışta hata atar; ileti
    gitmişse bu başarısızlık sayılmamalı (yoksa işaret bırakılır, her çağrıda
    aynı bildirim yeniden giderdi). Gönderimden önceki hata ise sayılır."""

    class SMTP:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            raise smtplib.SMTPResponseException(421, b"kapanis")

        def starttls(self, context=None):
            pass

        def login(self, *_):
            pass

        def send_message(self, mesaj):
            pass

    class Kopuk(SMTP):
        def send_message(self, mesaj):
            raise smtplib.SMTPServerDisconnected("koptu")

    ayar = _bekci_ayari(smtp_sunucu="smtp.ornek.com")
    monkeypatch.setattr(_pano.smtplib, "SMTP", SMTP)
    _pano._eposta_gonder(ayar, "a@b.co", "K", "M")
    monkeypatch.setattr(_pano.smtplib, "SMTP", Kopuk)
    with pytest.raises(smtplib.SMTPException):
        _pano._eposta_gonder(ayar, "a@b.co", "K", "M")


def test_telegram_urllib_ile_gider_bozuk_jeton_aga_cikmaz(monkeypatch):
    istekler = []

    class SahteYanit:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'{"ok":true}'

    def sahte_urlopen(istek, timeout=None):
        istekler.append((istek.full_url, istek.get_method(), istek.data, timeout))
        return SahteYanit()

    monkeypatch.setattr(_pano.urllib.request, "urlopen", sahte_urlopen)
    _pano._telegram_gonder(_bekci_ayari(telegram_bot="123456:ABC-def_ghi"), "-100123", "Merhaba")
    adres, yontem, veri, sure = istekler[0]
    assert adres == "https://api.telegram.org/bot123456:ABC-def_ghi/sendMessage"
    assert yontem == "POST" and sure == _pano.BEKCI_GONDERIM_ZAMAN_ASIMI_SN
    assert urllib.parse.parse_qs(veri.decode()) == {"chat_id": ["-100123"], "text": ["Merhaba"]}
    for bot, sohbet in (("gizli jeton\n", "1"), ("123:abc", "1; DROP"), ("", "1")):
        with pytest.raises(_pano.BildirimHatasi) as hata:
            _pano._telegram_gonder(_bekci_ayari(telegram_bot=bot), sohbet, "x")
        if bot.strip():
            assert bot.strip() not in str(hata.value)
    assert len(istekler) == 1


# ------------------------------------------------------------ HTTP (uç nokta)


def _bekci_iste(site, basliklar=None, sorgu=""):  # noqa: F811
    return _istek(f"{site}/api/bekci{sorgu}", basliklar=basliklar or {})


def _bearer(jeton):
    return {"Authorization": f"Bearer {jeton}"}


def test_anahtar_yoksa_ya_da_yanlissa_reddedilir(site, monkeypatch):  # noqa: F811
    monkeypatch.setenv("BEKCI", "acik")
    kod, _, govde = _bekci_iste(site, _bearer("herhangi-bir-jeton-123456"))
    assert kod == 403 and json.loads(govde)["hata"] == "bekci_anahtari_yok"
    monkeypatch.setenv("BEKCI_ANAHTARI", GIZLI["BEKCI_ANAHTARI"])
    monkeypatch.setenv("CRON_SECRET", GIZLI["CRON_SECRET"])
    kod, _, govde = _bekci_iste(site)
    assert kod == 401 and "Authorization" in json.loads(govde)["mesaj"]
    assert _bekci_iste(site, _bearer("yanlis-jeton-0123456789"))[0] == 403
    assert _bekci_iste(site, {"Authorization": GIZLI["CRON_SECRET"]})[0] == 401  # "Bearer" yok
    assert _bekci_iste(site, sorgu="?anahtar=yanlis")[0] == 403
    # Sorgu yalnız BEKCI_ANAHTARI'nı kabul eder; CRON_SECRET adrese yazılmaz
    assert _bekci_iste(site, sorgu=f"?anahtar={GIZLI['CRON_SECRET']}")[0] == 403
    assert _bekci_iste(site, _bearer(GIZLI["CRON_SECRET"]))[0] == 200
    assert _bekci_iste(site, _bearer(GIZLI["BEKCI_ANAHTARI"]))[0] == 200
    assert _bekci_iste(site, sorgu=f"?anahtar={GIZLI['BEKCI_ANAHTARI']}")[0] == 200
    # Yalnız GET
    assert _istek(f"{site}/api/bekci", "POST", b"{}", _bearer(GIZLI["CRON_SECRET"]))[0] == 405
    # Kısa anahtar tanımsız sayılır
    monkeypatch.setenv("BEKCI_ANAHTARI", "kisa")
    monkeypatch.delenv("CRON_SECRET")
    assert _bekci_iste(site, _bearer("kisa"))[0] == 403


def test_bekci_kapaliyken_atlanir(site, monkeypatch):  # noqa: F811
    monkeypatch.setenv("BEKCI_ANAHTARI", GIZLI["BEKCI_ANAHTARI"])
    kod, _, govde = _bekci_iste(site, _bearer(GIZLI["BEKCI_ANAHTARI"]))
    assert kod == 200 and json.loads(govde) == {"atlandi": True}


def test_taninmayan_bekci_ayari_anahtarla_cagrilinca_503(site, monkeypatch):  # noqa: F811
    """BEKCI="evet" gibi tanınmayan bir değer sessizce "kapalı" sayılmaz: dış
    izleme servisi fark etsin diye (anahtar doğrulandıktan sonra) 503 döner.
    Boş bırakılan ayar bugünkü gibi atlanır."""
    monkeypatch.setenv("BEKCI", "evet")
    monkeypatch.setenv("BEKCI_ANAHTARI", GIZLI["BEKCI_ANAHTARI"])
    jeton = _bearer(GIZLI["BEKCI_ANAHTARI"])
    assert _bekci_iste(site)[0] == 401  # önce anahtar
    assert _bekci_iste(site, _bearer("yanlis-jeton-0123456789"))[0] == 403
    kod, _, govde = _bekci_iste(site, jeton)
    veri = json.loads(govde)
    assert kod == 503 and veri["hata"] == "bekci_ayari"
    assert "BEKCI" in veri["mesaj"] and "acik" in veri["mesaj"]
    monkeypatch.setenv("BEKCI", "Açık")
    kod, _, govde = _bekci_iste(site, jeton)
    assert kod == 200 and "durum" in json.loads(govde)
    monkeypatch.setenv("BEKCI", "")
    kod, _, govde = _bekci_iste(site, jeton)
    assert kod == 200 and json.loads(govde) == {"atlandi": True}


def _ham_istek(site, yontem, yol):  # noqa: F811
    """Ham HTTP: cevabın baytlarını olduğu gibi döner (urllib HEAD'de gövdeyi
    hiç okumadığı için sunucunun gövde yazıp yazmadığını göstermez)."""
    adres = urllib.parse.urlsplit(site)
    with socket.create_connection((adres.hostname, adres.port), timeout=5) as baglanti:
        baglanti.sendall(
            f"{yontem} {yol} HTTP/1.1\r\nHost: {adres.netloc}\r\nConnection: close\r\n\r\n".encode()
        )
        parcalar = []
        while parca := baglanti.recv(65536):
            parcalar.append(parca)
    basliklar, _, govde = b"".join(parcalar).partition(b"\r\n\r\n")
    return int(basliklar.split()[1]), basliklar.decode("latin-1"), govde


def test_head_istegi_get_ile_ayni_kodu_govdesiz_alir(site, monkeypatch):  # noqa: F811
    """UptimeRobot'un ücretsiz planı HEAD gönderir ve başlık ekleyemez: HEAD,
    ?anahtar= ile GET'in durum kodunu alır; sunucu gövde yazmaz."""
    monkeypatch.setenv("BEKCI", "acik")
    monkeypatch.setenv("BEKCI_ANAHTARI", GIZLI["BEKCI_ANAHTARI"])
    yol = f"/api/bekci?anahtar={GIZLI['BEKCI_ANAHTARI']}"
    kod, basliklar, govde = _ham_istek(site, "GET", yol)
    assert kod == 200 and json.loads(govde)["uyarildi"] is False
    kod, basliklar, govde = _ham_istek(site, "HEAD", yol)
    assert kod == 200 and govde == b"" and "Content-Length:" in basliklar
    assert _ham_istek(site, "HEAD", "/api/bekci")[0] == 401
    assert _ham_istek(site, "HEAD", "/api/bekci?anahtar=yanlis")[0] == 403
    _pano.rapor_kaydet(_pano.DEPO, _pano.rapor_temizle(RAPOR), time.time() - 3600)
    kod, _, govde = _ham_istek(site, "HEAD", yol)
    assert kod == 503 and govde == b""
    assert _ham_istek(site, "GET", yol)[0] == 503


def test_bayat_hedef_varsa_503_yoksa_200(site, monkeypatch):  # noqa: F811
    monkeypatch.setenv("BEKCI", "acik")
    monkeypatch.setenv("BEKCI_ANAHTARI", GIZLI["BEKCI_ANAHTARI"])
    jeton = _bearer(GIZLI["BEKCI_ANAHTARI"])
    _pano.rapor_kaydet(_pano.DEPO, _pano.rapor_temizle(RAPOR), time.time() - 3600)
    kod, _, govde = _bekci_iste(site, jeton)
    veri = json.loads(govde)
    assert kod == 503
    # Alıcı yok: bildirim gitmez ama durum kodu dış izleme servisine alarm verdirir
    assert veri["uyarildi"] is False and veri["gonderilen"] == 0
    assert veri["durum"][0]["bayat"] is True and veri["durum"][0]["gecikme_dk"] == 60
    assert _rapor_gonder(site, RAPOR)[0] == 200
    kod, _, govde = _bekci_iste(site, jeton)
    assert kod == 200 and json.loads(govde)["durum"][0]["baglanti"] == "canli"


def test_sirlar_cevapta_ve_gunlukte_yok(site, monkeypatch, capsys):  # noqa: F811
    for ad, deger in GIZLI.items():
        monkeypatch.setenv(ad, deger)
    monkeypatch.setenv("BEKCI", "acik")
    monkeypatch.setenv("BEKCI_ALICILAR", "sef@ornek.com.tr,tg:12345")
    monkeypatch.setenv("SMTP_SUNUCU", "smtp.ornek.com")
    monkeypatch.setenv("SMTP_KULLANICI", "pano@ornek.com")

    def eposta(ayar, alici, konu, metin):
        raise smtplib.SMTPAuthenticationError(535, f"{ayar.smtp_sifresi} {alici}".encode())

    def telegram(ayar, sohbet, metin):
        raise ValueError(f"/bot{ayar.telegram_bot}/sendMessage {sohbet}")

    monkeypatch.setattr(_pano, "_eposta_gonder", eposta)
    monkeypatch.setattr(_pano, "_telegram_gonder", telegram)
    _pano.rapor_kaydet(_pano.DEPO, _pano.rapor_temizle(RAPOR), time.time() - 3600)
    kod, basliklar, govde = _bekci_iste(site, _bearer(GIZLI["CRON_SECRET"]))
    assert kod == 503 and json.loads(govde)["gonderilen"] == 0
    # Hepsi gidemedi: işaret bırakıldı, sonraki çağrı yeniden dener
    assert _pano.DEPO.komut("GET", ISARET) is None
    metin = govde.decode() + json.dumps(basliklar) + capsys.readouterr().err
    assert "Bekçi bildirimi gidemedi" in metin
    for gizli in [*GIZLI.values(), "sef@ornek.com.tr", "pano@ornek.com"]:
        assert gizli not in metin


def test_vercel_cron_gunluk_ve_islev_sayisi_hobby_sinirinda():
    vercel = json.loads((KOK / "vercel.json").read_text(encoding="utf-8"))
    # Hobby planı günde birden sık cron'u kabul etmez (yayın başarısız olur)
    assert vercel["crons"] == [{"path": "/api/bekci", "schedule": "0 5 * * *"}]
    islevler = sorted(p.name for p in (KOK / "api").glob("*.py") if not p.name.startswith("_"))
    assert "bekci.py" in islevler and len(islevler) <= 12
