"""E-posta yolu (Resend ya da SMTP), ortak tasarım ve deneme e-postası (20.11.2026).

RESEND_API_KEY yazılıysa bütün e-postalar Resend'in HTTPS API'siyle, yoksa SMTP
ile bugünkü gibi gider. Resend anahtarı hiçbir hata metnine, günlüğe ya da
cevaba girmez. Her şablon aynı tasarımı kullanır, değerler kaçışlıdır. Deneme
e-postası yalnız yöneticidir, hesap başına saatte 5'tir ve işlem kaydına girer.
Ağ yok: urlopen sahtedir (yerel test sunucusuna gidenler gerçeğine geçer)."""

import io
import json
import traceback
import urllib.error
import urllib.parse
import urllib.request

import _pano
import pytest
from eposta_onizleme import ORNEK_ADRES, epostalar, onizlemeleri_yaz
from test_cekirdek import Saat, _ayar, _rapor
from test_hesap import _hazir_hesap, _kurucu, _post
from test_uctan_uca import _istek, site  # noqa: F401

RESEND_ANAHTARI = "re_gizli_resend_anahtari_0123456789"
KIMDEN = "NextGen Detector <alarm@ornek.com.tr>"
ALICI = "sef@ornek.com.tr"


class ResendSahtesi:
    """urlopen yerine: dış adrese gidenleri kaydeder ve sıradaki cevabı verir
    (None: 200, (kod, gövde): HTTPError, istisna: atılır). Yerel test sunucusuna
    giden istekler gerçek urlopen'a geçer."""

    def __init__(self, monkeypatch, cevaplar=()):
        self.istekler = []
        self.cevaplar = list(cevaplar)
        gercek = urllib.request.urlopen

        def sahte(istek, *arg, **ek):
            adres = istek.full_url if isinstance(istek, urllib.request.Request) else str(istek)
            if urllib.parse.urlsplit(adres).hostname == "127.0.0.1":
                return gercek(istek, *arg, **ek)
            self.istekler.append((istek, ek.get("timeout")))
            cevap = self.cevaplar.pop(0) if self.cevaplar else None
            if isinstance(cevap, Exception):
                raise cevap
            if cevap is not None:
                kod, govde = cevap
                raise urllib.error.HTTPError(adres, kod, "hata", {}, io.BytesIO(govde))
            return io.BytesIO(b'{"id": "ileti-1"}')

        monkeypatch.setattr(urllib.request, "urlopen", sahte)

    def govdeler(self):
        return [json.loads(istek.data) for istek, _ in self.istekler]


def _resend_ayari(**degisen):
    alanlar = {"resend_anahtari": RESEND_ANAHTARI, "eposta_kimden": KIMDEN}
    alanlar.update(degisen)
    return _ayar(**alanlar)


def _smtp_yasak(monkeypatch):
    def patla(*_, **__):
        raise AssertionError("Resend açıkken SMTP'ye bağlanılmamalı")

    monkeypatch.setattr(_pano.smtplib, "SMTP", patla)
    monkeypatch.setattr(_pano.smtplib, "SMTP_SSL", patla)


# ------------------------------------------------------- yol seçimi ve istek


def test_resend_istegi_bicimi(monkeypatch):
    _smtp_yasak(monkeypatch)
    resend = ResendSahtesi(monkeypatch)
    ayar = _resend_ayari(smtp_sunucu="smtp.ornek.com")  # ikisi de varsa Resend
    _pano._eposta_gonder(ayar, ALICI, "Konu", "Düz metin", "<p>HTML</p>")
    ((istek, zaman_asimi),) = resend.istekler
    assert istek.full_url == "https://api.resend.com/emails" and istek.get_method() == "POST"
    assert istek.get_header("Authorization") == f"Bearer {RESEND_ANAHTARI}"
    assert istek.get_header("Content-type") == "application/json"
    assert istek.get_header("User-agent")  # urllib'in varsayılanı değil
    assert zaman_asimi == _pano.BEKCI_GONDERIM_ZAMAN_ASIMI_SN
    assert resend.govdeler() == [
        {
            "from": KIMDEN,
            "to": [ALICI],
            "subject": "Konu",
            "text": "Düz metin",
            "html": "<p>HTML</p>",
        }
    ]
    # HTML yoksa yalnız düz metin
    _pano._eposta_gonder(ayar, ALICI, "K", "M")
    assert "html" not in resend.govdeler()[1]


def test_saglayici_secimi_ve_gonderen(monkeypatch):
    assert _pano.eposta_saglayicisi(_pano.ayar_oku({})) == ""
    smtp = _pano.ayar_oku({"SMTP_SUNUCU": "smtp.ornek.com", "SMTP_KIMDEN": "pano@ornek.com"})
    assert _pano.eposta_saglayicisi(smtp) == "smtp" and smtp.eposta_kimden == "pano@ornek.com"
    ayar = _pano.ayar_oku(
        {
            "RESEND_API_KEY": f" {RESEND_ANAHTARI} ",
            "EPOSTA_KIMDEN": KIMDEN,
            "SMTP_SUNUCU": "smtp.ornek.com",
            "SMTP_KIMDEN": "pano@ornek.com",
        }
    )
    assert _pano.eposta_saglayicisi(ayar) == "resend" and ayar.eposta_kimden == KIMDEN
    assert ayar.resend_anahtari == RESEND_ANAHTARI and RESEND_ANAHTARI not in repr(ayar)
    # Resend yokken SMTP yolu bugünkü gibi: HTTPS isteği yok
    resend = ResendSahtesi(monkeypatch)
    giden = []

    class SMTP:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def starttls(self, context=None):
            pass

        def login(self, *_):
            pass

        def send_message(self, mesaj):
            giden.append(mesaj["From"])

    monkeypatch.setattr(_pano.smtplib, "SMTP", SMTP)
    _pano._eposta_gonder(smtp, ALICI, "K", "M", "<p>H</p>")
    assert giden == ["pano@ornek.com"] and resend.istekler == []


def test_pano_adresi_her_zaman_bilinir_site_adresi_once():
    """SITE_ADRESI (alan adı ya da https adresi) -> VERCEL_PROJECT_PRODUCTION_URL ->
    resmi adres. Alan adı olamayan değer yok sayılır, sıradakine geçilir."""
    varsayilan = "https://dalsansite.vercel.app/pano"

    def adres(vercel="", site_adresi=None):
        ortam = {"VERCEL_PROJECT_PRODUCTION_URL": vercel}
        if site_adresi is not None:
            ortam["SITE_ADRESI"] = site_adresi
        return _pano.ayar_oku(ortam).pano_adresi

    assert _pano.ayar_oku({}).pano_adresi == varsayilan
    assert adres("dalsan.vercel.app") == "https://dalsan.vercel.app/pano"
    assert adres(" Pano.Firma.COM.tr/ ") == "https://pano.firma.com.tr/pano"
    for bozuk in ("", "javascript:alert(1)", "a b.com", "localhost", 'x.com"><b>'):
        assert adres(bozuk) == varsayilan
    # SITE_ADRESI önce gelir; https adresi ve sondaki /pano da olur
    assert adres("dalsan.vercel.app", "izleme.firma.com") == "https://izleme.firma.com/pano"
    assert adres("x.vercel.app", "https://Izleme.Firma.com/pano/") == (
        "https://izleme.firma.com/pano"
    )
    for bozuk in ("http://izleme.firma.com", "javascript:alert(1)", "a b.com", "   "):
        assert adres("dalsan.vercel.app", bozuk) == "https://dalsan.vercel.app/pano"


def test_derin_bag_kodlanir_yalniz_bilinen_adlar():
    kok = "https://dalsan.vercel.app/pano"
    assert _pano.pano_bagi(kok, "genel") == kok + "#genel"
    assert _pano.pano_bagi(kok, "olaylar", hafta="2026-11-16", tip="Baret yok") == (
        kok + "?hafta=2026-11-16&tip=Baret%20yok#olaylar"
    )
    # Türkçe harf UTF-8, ayraçlar (& = # / ? +) ve tırnak kodlanır: parametre bölünmez
    bag = _pano.pano_bagi(kok, "olaylar", hafta="2026-11-16", yer='Kapı & "A"=#/?+')
    assert bag == kok + "?hafta=2026-11-16&yer=Kap%C4%B1%20%26%20%22A%22%3D%23%2F%3F%2B#olaylar"
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(bag).query)["yer"] == ['Kapı & "A"=#/?+']
    # Bilinmeyen ad ve boş değer yazılmaz; adres yoksa bağlantı yok
    bag = _pano.pano_bagi(kok, "olaylar", hafta="2026-11-16", tip="", arsiv="7")
    assert bag == kok + "?hafta=2026-11-16#olaylar"
    assert _pano.pano_bagi("", "genel") == ""


# ------------------------------------------------------------ hata eşlemesi


@pytest.mark.parametrize(
    ("kod", "ad", "beklenen"),
    [
        (401, "missing_api_key", "RESEND_API_KEY"),
        (403, "invalid_api_key", "RESEND_API_KEY"),
        (403, "validation_error", "EPOSTA_KIMDEN"),
        (422, "invalid_from_address", "EPOSTA_KIMDEN"),
        (422, "validation_error", "HTTP 422"),
        (429, "daily_quota_exceeded", "sınırı doldu"),
        (500, "internal_server_error", "HTTP 500"),
    ],
)
def test_resend_hatasi_sabit_metin_anahtar_ve_alici_yok(monkeypatch, kod, ad, beklenen):
    govde = json.dumps({"name": ad, "message": f"{RESEND_ANAHTARI} {ALICI}"}).encode()
    ResendSahtesi(monkeypatch, [(kod, govde)])
    with pytest.raises(_pano.BildirimHatasi) as bilgi:
        _pano._eposta_gonder(_resend_ayari(), ALICI, "K", "M")
    metin = str(bilgi.value) + "".join(traceback.format_exception(bilgi.value))
    assert beklenen in str(bilgi.value)
    assert RESEND_ANAHTARI not in metin and ALICI not in metin


def test_ag_hatasi_ve_saniyelik_sinirda_bir_kez_yeniden_dener(monkeypatch):
    for hata in (urllib.error.URLError("yok"), TimeoutError("zaman")):
        ResendSahtesi(monkeypatch, [hata])
        with pytest.raises(_pano.BildirimHatasi, match="ulaşılamadı"):
            _pano._eposta_gonder(_resend_ayari(), ALICI, "K", "M")
    bekleme = []
    monkeypatch.setattr(_pano.time, "sleep", bekleme.append)
    sinir = (429, b'{"name": "rate_limit_exceeded"}')
    resend = ResendSahtesi(monkeypatch, [sinir])
    _pano._eposta_gonder(_resend_ayari(), ALICI, "K", "M")
    assert len(resend.istekler) == 2 and bekleme == [_pano.RESEND_BEKLE_SN]
    resend = ResendSahtesi(monkeypatch, [sinir, sinir])
    with pytest.raises(_pano.BildirimHatasi, match="sınırı doldu"):
        _pano._eposta_gonder(_resend_ayari(), ALICI, "K", "M")
    assert len(resend.istekler) == 2


def test_gonderen_ve_alici_dogrulanir_istek_gitmez(monkeypatch):
    resend = ResendSahtesi(monkeypatch)
    for kimden in ("", "adres-degil", "Ad <a@b.co>\r\nBcc: x@y.co", "a@b.co, c@d.co"):
        with pytest.raises(_pano.BildirimHatasi, match="EPOSTA_KIMDEN"):
            _pano._eposta_gonder(_resend_ayari(eposta_kimden=kimden), ALICI, "K", "M")
    for alici in ("a@b.co\nBcc: x@y.co", "adres-degil", "a@b.co, c@d.co"):
        with pytest.raises(_pano.BildirimHatasi, match="geçersiz"):
            _pano._eposta_gonder(_resend_ayari(), alici, "K", "M")
    assert resend.istekler == []
    _pano._eposta_gonder(_resend_ayari(eposta_kimden="alarm@ornek.com.tr"), ALICI, "K", "M")
    assert len(resend.istekler) == 1


def test_bekci_resend_ile_her_aliciya_ayri_tasarimli_ileti(monkeypatch, capsys):
    _smtp_yasak(monkeypatch)
    bozuk = (401, json.dumps({"name": "invalid_api_key", "message": RESEND_ANAHTARI}).encode())
    resend = ResendSahtesi(monkeypatch, [bozuk])
    ayar = _resend_ayari(
        bekci="acik",
        bekci_alicilar=("kopuk@ornek.com.tr", ALICI),
        pano_adresi="https://dalsan.vercel.app/pano",
    )
    saat = Saat(1_800_000_000.0)
    depo = _pano.BellekDepo(saat)
    _pano.rapor_kaydet(depo, _pano.rapor_temizle(_rapor()), saat.simdi, ayar)
    saat.simdi += 25 * 60
    sonuc = _pano.bekci_isle(depo, ayar, saat.simdi)
    assert sonuc["uyarildi"] is True and sonuc["gonderilen"] == 1
    govdeler = resend.govdeler()
    assert [g["to"] for g in govdeler] == [["kopuk@ornek.com.tr"], [ALICI]]
    son = govdeler[1]
    assert son["subject"].startswith("Alarm: ") and "sistemden haber yok" in son["subject"]
    assert "Sistemden haber yok" in son["html"]
    assert 'href="https://dalsan.vercel.app/pano#genel"' in son["html"]
    assert "Bağlantı durumunu gör: https://dalsan.vercel.app/pano#genel" in son["text"]
    gunluk = capsys.readouterr().err
    assert "Bekçi bildirimi gidemedi" in gunluk and "RESEND_API_KEY" in gunluk
    assert RESEND_ANAHTARI not in gunluk and "kopuk@ornek" not in gunluk


# ------------------------------------------------------------------ tasarım


# Her e-postanın şeridi ve düğmesinin açtığı yer (pano_bagi)
SABLONLAR = {
    "ayar-sorunu": ("#d97706", "?bolum=kurulum#sistem", "Kurulum denetimini aç"),
    "bekci-haber-yok": ("#dc2626", "#genel", "Bağlantı durumunu gör"),
    "bekci-program-kapali": ("#dc2626", "#genel", "Bağlantı durumunu gör"),
    "bekci-yeniden-haber": ("#15803d", "#genel", "Bağlantı durumunu gör"),
    "deneme": ("#15803d", "?bolum=bildirimler#sistem", "Bildirim ayarlarını aç"),
    "deneme-kendine": ("#15803d", "?bolum=bildirimler#sistem", "Bildirim ayarlarını aç"),
    "haftalik-ozet": ("#616367", "?hafta=2026-11-16#olaylar", "Olay arşivini aç"),
}


def test_her_sablon_ortak_tasarimda_onizleme_yazilir(tmp_path):
    yazilan = onizlemeleri_yaz(tmp_path)
    assert sorted(y.stem for y in yazilan) == sorted(SABLONLAR)
    ayarlar = ORNEK_ADRES + "?bolum=bildirimler#sistem"
    for yol in yazilan:
        serit, yer, dugme = SABLONLAR[yol.stem]
        icerik = yol.read_text(encoding="utf-8")
        assert icerik.startswith("<!doctype html>") and "max-width:560px" in icerik
        assert _pano.EPOSTA_MARKA in icerik and f'href="{ORNEK_ADRES}{yer}"' in icerik
        assert f">{dugme}</a>" in icerik and serit in icerik
        assert "<script" not in icerik and "<img" not in icerik
        metin = yol.with_suffix(".txt").read_text(encoding="utf-8")
        assert metin.startswith("Konu: ") and f"{dugme}: {ORNEK_ADRES}{yer}" in metin
        # Altta neden geldiği ve bildirim ayarlarının bağlantısı (iki parçada da)
        if not yol.stem.startswith("deneme"):
            assert f'href="{ayarlar}"' in icerik and f"Bildirim ayarları: {ayarlar}" in metin
    # Programdan gelen adlar kaçışlı; düz metinde olduğu gibi
    ozet = (tmp_path / "haftalik-ozet.html").read_text(encoding="utf-8")
    assert "Kapı &lt;3&gt;" in ozet and "Kapı <3>" not in ozet
    kapali = (tmp_path / "bekci-program-kapali.html").read_text(encoding="utf-8")
    assert "İzmir &lt;depo&gt;" in kapali and "<depo>" not in kapali
    assert "Kapı <3>" in (tmp_path / "haftalik-ozet.txt").read_text(encoding="utf-8")


def test_adres_yoksa_dugme_yok_tirnak_kacisli():
    hedef = {"baglanti": "yok", "gecikme_sn": 1500, "son_rapor": None}
    konu, metin, html_metni = _pano._bekci_metni('Depo "A" & <b>', hedef)
    assert konu == 'Alarm: Depo "A" & <b> - sistemden haber yok'
    assert "Panoyu aç" not in html_metni and "Panoyu açın" not in metin
    assert "Depo &quot;A&quot; &amp; &lt;b&gt;" in html_metni and "<b>" not in html_metni
    for _, (_, _metin, html_metni) in epostalar("").items():
        assert "<a " not in html_metni


# ------------------------------------------------------- deneme e-postası


def _deneme(site, cerez, alici=ALICI):  # noqa: F811
    return _post(site, "/api/hesap", {"eylem": "deneme_epostasi", "alici": alici}, cerez, site)


def _kayit(site, cerez):  # noqa: F811
    return json.loads(_istek(f"{site}/api/hesap", basliklar={"Cookie": cerez})[2])["kayit"]


def test_deneme_epostasi_yalniz_yonetici_kayitli_ve_saatte_bes(site, monkeypatch):  # noqa: F811
    monkeypatch.setenv("RESEND_API_KEY", RESEND_ANAHTARI)
    monkeypatch.setenv("EPOSTA_KIMDEN", KIMDEN)
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "dalsan.vercel.app")
    resend = ResendSahtesi(monkeypatch)
    kurucu = _kurucu(site)
    operator = _hazir_hesap(site, kurucu, "ali", "operator", "ali-parola-123")
    # Yönetici olmayan gönderemez; deneme kayda girer
    kod, _, govde = _deneme(site, operator)
    assert kod == 403 and json.loads(govde)["hata"] == "yetki"
    assert any(r["kim"] == "ali" and r["is"] == "komut_red" for r in _kayit(site, kurucu))
    # Bozuk adres: gitmez, sayılmaz
    kod, _, govde = _deneme(site, kurucu, "adres-degil")
    assert kod == 400 and json.loads(govde)["hata"] == "alici"
    assert resend.istekler == []
    cevaplar = []
    for _ in range(_pano.DENEME_EPOSTA_SINIRI):
        kod, _, govde = _deneme(site, kurucu)
        assert kod == 200, govde
        cevaplar.append(govde.decode())
    assert json.loads(cevaplar[0]) == {"tamam": True, "saglayici": "resend"}
    kod, _, govde = _deneme(site, kurucu)
    assert kod == 429 and json.loads(govde)["hata"] == "cok_sik"
    assert len(resend.istekler) == _pano.DENEME_EPOSTA_SINIRI
    ileti = resend.govdeler()[0]
    assert ileti["to"] == [ALICI] and ileti["subject"].startswith("Deneme")
    assert "E-posta gönderimi çalışıyor" in ileti["html"] and "kurucu" in ileti["text"]
    assert 'href="https://dalsan.vercel.app/pano?bolum=bildirimler#sistem"' in ileti["html"]
    satirlar = [r for r in _kayit(site, kurucu) if r["is"] == "deneme_epostasi"]
    assert len(satirlar) == _pano.DENEME_EPOSTA_SINIRI
    assert {(r["kim"], r["ozet"], r["sonuc"]) for r in satirlar} == {
        ("kurucu", "se***@ornek.com.tr · Resend", "tamam")
    }
    for metin in cevaplar:
        assert RESEND_ANAHTARI not in metin and ALICI not in metin


def test_deneme_epostasi_hatasi_sirsiz_ve_kayitta(site, monkeypatch, capsys):  # noqa: F811
    kurucu = _kurucu(site)
    # Hiç e-posta yolu yoksa ne yazılacağı söylenir
    kod, _, govde = _deneme(site, kurucu)
    assert kod == 409 and json.loads(govde)["hata"] == "eposta_yok"
    monkeypatch.setenv("RESEND_API_KEY", RESEND_ANAHTARI)
    monkeypatch.setenv("EPOSTA_KIMDEN", KIMDEN)
    govde = json.dumps({"name": "invalid_api_key", "message": RESEND_ANAHTARI}).encode()
    ResendSahtesi(monkeypatch, [(403, govde)])
    kod, basliklar, govde = _deneme(site, kurucu)
    veri = json.loads(govde)
    assert kod == 502 and veri["hata"] == "eposta_gitmedi" and "RESEND_API_KEY" in veri["mesaj"]
    (satir,) = [r for r in _kayit(site, kurucu) if r["is"] == "deneme_epostasi"]
    assert satir["sonuc"] == "hata"
    metin = govde.decode() + json.dumps(basliklar) + capsys.readouterr().err
    assert "Deneme e-postası gidemedi" in metin
    assert RESEND_ANAHTARI not in metin and ALICI not in metin


def test_smtp_yolunda_da_gider_saglayici_smtp(site, monkeypatch):  # noqa: F811
    monkeypatch.setenv("SMTP_SUNUCU", "smtp.ornek.com")
    giden = []
    monkeypatch.setattr(_pano, "_eposta_gonder", lambda *arg, **ek: giden.append(arg))
    kod, _, govde = _deneme(site, _kurucu(site))
    assert kod == 200 and json.loads(govde)["saglayici"] == "smtp"
    ((_, alici, konu, metin, html_metni),) = giden
    assert alici == ALICI and "Gönderim yolu: SMTP" in metin and "<html" in html_metni
