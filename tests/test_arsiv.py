"""Olay arşivi (Kod maddesi 5) ve inceleme modu (Kod maddesi 6).

Raporlarla gelen olaylar sıralı kümede birikir: olay başına tek üye (tesis +
olay kimliği), durum değişince üye yenilenir, küme 90 gün / ARSIV_EN_COK ile
aynı boru hattında kırpılır ve olaylar değişmedikçe rapor başına komut
eklenmez. GET /api/durum?arsiv=1 süzer ve sayfalar; `&bicim=csv` Excel'in
açtığı dosyayı indirir. Ekranın kablolaması (Olaylar > Arşiv, inceleme modu)
dosya düzeyinde denetlenir (test_sayfalar.py gibi)."""

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import _pano
import pytest
from test_filo import KayitliDepo
from test_hesap import _hazir_hesap, _kurucu
from test_uctan_uca import _istek, _rapor_gonder, site  # noqa: F401

KOK = Path(__file__).resolve().parents[1]
PANO_JS = (KOK / "public" / "pano.js").read_text(encoding="utf-8")
PANO_HTML = (KOK / "public" / "pano.html").read_text(encoding="utf-8")
PANO_CSS = (KOK / "public" / "pano.css").read_text(encoding="utf-8")
DEMO_JS = (KOK / "public" / "demo.js").read_text(encoding="utf-8")
T0 = 1_800_000_000.0  # 2027-01-15 08:00 UTC


def _zaman(saniye_once, simdi=T0):
    return datetime.fromtimestamp(simdi - saniye_once, UTC).isoformat(timespec="seconds")


def _olay(kimlik, saniye_once=60, simdi=T0, **degisen):
    olay = {
        "id": kimlik,
        "zaman": _zaman(saniye_once, simdi),
        "tur": "ihlal",
        "baslik": "Baret yok",
        "yer": "Sevkiyat Rampası · Sevkiyat",
        "onem": "high",
        "onem_adi": "Yüksek",
        "durum": "new",
        "durum_adi": "yeni",
        "suruyor": False,
        "sure": "8 sn",
    }
    olay.update(degisen)
    return olay


def _rapor(olaylar, **degisen):
    ham = {"surum": 1, "aralik_sn": 30, "son_olaylar": olaylar}
    ham.update(degisen)
    return _pano.rapor_temizle(ham)


def _arsiv(depo):
    return _pano.arsiv_coz(depo.komut("ZREVRANGEBYSCORE", _pano.ARSIV_ANAHTARI, "+inf", "-inf"))


def _arsiv_cagrilari(depo):
    """KayitliDepo'nun arşive dokunan boru hatları (komut adları)."""
    return [
        [k[0] for k in cagri]
        for cagri in depo.cagrilar
        if any(
            len(k) > 1 and k[1].startswith("dalsan:olay:arsiv") and k[0] != "MGET" for k in cagri
        )
    ]


# --------------------------------------------------------------- yazım


def test_arsiv_olay_basina_tek_uye_ve_degismeyen_rapor_komut_eklemez():
    depo = KayitliDepo(lambda: T0)
    rapor = _rapor([_olay(12, 60, suruyor=True, sure="8 sn"), _olay(11, 600)])
    _pano.rapor_kaydet(depo, rapor, T0)
    # İlk yazım: yeni olay -> ZADD, kırpma (gün, adet), süre, iz
    assert _arsiv_cagrilari(depo) == [
        ["ZADD", "ZREMRANGEBYSCORE", "ZREMRANGEBYRANK", "EXPIRE", "SET"]
    ]
    assert [o["id"] for o in _arsiv(depo)] == [12, 11]
    # Aynı olaylar yeniden gelince (süren olayın süresi büyüse de) arşive hiç
    # dokunulmaz: tek boru hattı (raporun kendisi), iz aynı MGET'te okunur
    depo.cagrilar.clear()
    rapor = _rapor([_olay(12, 60, suruyor=True, sure="38 sn"), _olay(11, 600)])
    _pano.rapor_kaydet(depo, rapor, T0 + 30)
    assert len(depo.cagrilar) == 1 and "dalsan:olay:arsiv:iz" in depo.cagrilar[0][2]
    # Olay bitti ve incelendi: eski üye çıkar, yenisi girer (kırpma yok)
    depo.cagrilar.clear()
    rapor = _rapor([_olay(12, 60, durum="reviewed", sure="41 sn"), _olay(11, 600)])
    _pano.rapor_kaydet(depo, rapor, T0 + 60)
    assert _arsiv_cagrilari(depo) == [["ZREM", "ZADD", "SET"]]
    olaylar = _arsiv(depo)
    assert len(olaylar) == 2 and depo.komut("ZCARD", _pano.ARSIV_ANAHTARI) == 2
    assert (olaylar[0]["durum"], olaylar[0]["sure"], olaylar[0]["suruyor"]) == (
        "reviewed",
        "41 sn",
        False,
    )
    # Üye kısa JSON'dur: fotoğraf ya da bilinmeyen alan girmez
    uye = depo.komut("ZREVRANGEBYSCORE", _pano.ARSIV_ANAHTARI, "+inf", "-inf")[0]
    assert set(json.loads(uye)) <= {
        "id", "zaman", "tur", "baslik", "yer", "onem", "onem_adi", "durum",
        "durum_adi", "suruyor", "sure", "ayrinti", "tesis",
    }  # fmt: skip


def test_arsiv_kirpilir_doksan_gun_ve_en_cok(monkeypatch):
    monkeypatch.setattr(_pano, "ARSIV_EN_COK", 3)
    depo = _pano.BellekDepo(lambda: T0)
    gun = 86400
    # 95 gün önceki olay ilk yazımda hemen düşer; kalanlar en çok 3
    olaylar = [_olay(1, 95 * gun)] + [_olay(k, (10 - k) * 60) for k in range(2, 7)]
    _pano.rapor_kaydet(depo, _rapor(olaylar), T0)
    assert [o["id"] for o in _arsiv(depo)] == [6, 5, 4]
    assert depo.komut("TTL", _pano.ARSIV_ANAHTARI) == _pano.ARSIV_SAKLAMA_SN
    assert depo.komut("TTL", _pano.ARSIV_IZ_ANAHTARI) == _pano.ARSIV_SAKLAMA_SN


def test_arsiv_tesis_ve_kimlikle_tekillesir_kimliksiz_olay_atlanir():
    depo = _pano.BellekDepo(lambda: T0)
    _pano.rapor_kaydet(depo, _rapor([_olay(5), {**_olay(None), "id": None}]), T0)
    # Ana tesis değişti (eski program sustu): aynı kimlik başka tesisin olayıdır
    rapor = _rapor([_olay(5, 30, T0 + 600)], tesis={"id": "gebze", "ad": "Gebze"})
    _pano.rapor_kaydet(depo, rapor, T0 + 600, _pano.ayar_oku({"ANA_TESIS": "gebze"}))
    olaylar = _arsiv(depo)
    assert [(o["tesis"], o["id"]) for o in olaylar] == [("gebze", 5), ("", 5)]
    # Ana olmayan tesisin olayları arşive girmez (pano onu da göstermez)
    rapor = _rapor([_olay(77)], tesis={"id": "izmir", "ad": "İzmir"})
    _pano.rapor_kaydet(depo, rapor, T0 + 630, _pano.ayar_oku({"ANA_TESIS": "gebze"}))
    assert 77 not in [o["id"] for o in _arsiv(depo)]


def test_eski_programin_durumu_adindan_cikarilir():
    olay = _olay(9, durum_adi="incelendi")
    del olay["durum"]
    depo = _pano.BellekDepo(lambda: T0)
    _pano.rapor_kaydet(depo, _rapor([olay]), T0)
    assert _arsiv(depo)[0]["durum"] == "reviewed"


def test_yarim_yazimdaki_cift_uyeden_ileri_durum_gosterilir():
    depo = _pano.BellekDepo(lambda: T0)
    _pano.rapor_kaydet(depo, _rapor([_olay(3)]), T0)
    depo.sil(_pano.ARSIV_IZ_ANAHTARI)  # iz kayboldu: eski üye çıkarılamaz
    _pano.rapor_kaydet(depo, _rapor([_olay(3, durum="false_alarm")]), T0 + 30)
    assert depo.komut("ZCARD", _pano.ARSIV_ANAHTARI) == 2
    assert [(o["id"], o["durum"]) for o in _arsiv(depo)] == [(3, "false_alarm")]


def test_bellek_deposu_sirali_kume_redis_gibi():
    depo = _pano.BellekDepo(lambda: T0)
    assert depo.komut("ZADD", "k", "3", "c", "1", "a", "2", "b", "2", "aa") == 4
    assert depo.komut("ZADD", "k", "5", "a") == 0  # var olanın puanı güncellenir
    assert depo.komut("ZREVRANGEBYSCORE", "k", "+inf", "-inf") == ["a", "c", "b", "aa"]
    assert depo.komut("ZREVRANGEBYSCORE", "k", "(5", "2") == ["c", "b", "aa"]
    assert depo.komut("ZREMRANGEBYSCORE", "k", "-inf", "(3") == 2
    assert depo.komut("ZREM", "k", "a", "yok", "a") == 1
    assert depo.komut("ZADD", "k", "1", "x", "2", "y", "4", "z") == 3
    assert depo.komut("ZREMRANGEBYRANK", "k", "0", "-3") == 2  # en yeni 2'si kalır
    assert depo.komut("ZREVRANGEBYSCORE", "k", "+inf", "-inf") == ["z", "c"]
    assert depo.komut("ZCARD", "k") == 2
    with pytest.raises(_pano.DepoHatasi):
        depo.komut("GET", "k")
    assert depo.al_coklu(["k"]) == [None]


def test_donem_turkiye_gece_yarisindan_baslar():
    # T0 = 15.01.2027 11:00 Türkiye; bugün 00:00 = 14.01.2027 21:00 UTC
    bugun = _pano.arsiv_baslangici("bugun", T0)
    assert _pano._iso(bugun) == "2027-01-14T21:00:00+00:00"
    assert _pano.arsiv_baslangici("7", T0) == bugun - 6 * 86400
    assert _pano.arsiv_baslangici("90", T0) == bugun - 89 * 86400
    assert _pano.arsiv_baslangici("bozuk", T0) == bugun - 6 * 86400


# ------------------------------------------------------------- süzgeç (HTTP)


def _ornek_arsiv(site):  # noqa: F811
    """Gerçek uçlardan: üç rapor, farklı gün, tür, kamera ve durum."""
    simdi = time.time()
    gun = 86400
    olaylar = [
        _olay(
            30, 60, simdi, baslik="Araç-yaya yakınlığı - 1,85 m", onem="critical", onem_adi="Kritik"
        ),
        _olay(29, 120, simdi, durum="reviewed", yer="Depo Girişi · Depo"),
        _olay(28, 3 * gun, simdi, baslik="Yelek yok", durum="false_alarm"),
        _olay(27, 20 * gun, simdi, baslik="Araç-yaya yakınlığı - 0,90 m", yer="Depo Girişi · Depo"),
        _olay(
            26,
            40 * gun,
            simdi,
            tur="sistem",
            baslik="Kamera bağlantısı koptu",
            yer="Kazan Dairesi",
            onem="",
            onem_adi="",
            durum="",
            durum_adi="",
            sure="",
            ayrinti='Kameraya ulaşılamıyor; "(adres)" yeniden deneniyor',
        ),
    ]
    kod, _, govde = _rapor_gonder(site, {"surum": 1, "son_olaylar": olaylar})
    assert kod == 200, govde
    # 30'un kanıt fotoğrafı sitede var
    _pano.DEPO.boru_hatti([["SET", _pano.FOTO_LISTESI_ANAHTARI, json.dumps([[30, int(simdi)]])]])


def _arsiv_al(site, cerez, sorgu=""):  # noqa: F811
    kod, basliklar, govde = _istek(f"{site}/api/durum?arsiv=1{sorgu}", basliklar={"Cookie": cerez})
    return kod, basliklar, govde


def test_arsiv_suzgecleri_ve_sayfalama(site, monkeypatch):  # noqa: F811
    _ornek_arsiv(site)
    cerez = _kurucu(site)

    def kimlikler(sorgu):
        kod, _, govde = _arsiv_al(site, cerez, sorgu)
        assert kod == 200, govde
        return [o["id"] for o in json.loads(govde)["arsiv"]["olaylar"]]

    kod, _, govde = _arsiv_al(site, cerez)
    a = json.loads(govde)["arsiv"]
    # Varsayılan 7 gün; dönemin türleri (ölçümsüz) ve kameraları seçenek olur
    assert [o["id"] for o in a["olaylar"]] == [30, 29, 28]
    assert (a["toplam"], a["donemde"], a["sayfa"], a["sayfa_sayisi"], a["donem"]) == (
        3, 3, 1, 1, "7",
    )  # fmt: skip
    assert a["tipler"] == ["Araç-yaya yakınlığı", "Baret yok", "Yelek yok"]
    assert a["yerler"] == ["Depo Girişi · Depo", "Sevkiyat Rampası · Sevkiyat"]
    assert [o["foto"] for o in a["olaylar"]] == [True, False, False]
    assert a["sinir"] == {"gun": 90, "adet": 5000}
    # Bugün: Türkiye gece yarısından beri (test gece yarısına denk gelirse de doğru)
    bugun = _pano.arsiv_baslangici("bugun", time.time())
    beklenen = [k for k, once in ((30, 60), (29, 120)) if time.time() - once >= bugun + 5]
    assert kimlikler("&donem=bugun") == beklenen
    assert kimlikler("&donem=90") == [30, 29, 28, 27, 26]
    assert kimlikler("&donem=90&tur=sistem") == [26]
    assert kimlikler("&donem=90&tip=Ara%C3%A7-yaya+yak%C4%B1nl%C4%B1%C4%9F%C4%B1") == [30, 27]
    assert kimlikler("&donem=90&yer=Depo+Giri%C5%9Fi+%C2%B7+Depo") == [29, 27]
    assert kimlikler("&donem=90&durum=new") == [30, 27]
    assert kimlikler("&donem=90&durum=false_alarm") == [28]
    # Arama: büyük/küçük harf ve Türkçe harf farkı gözetmez; ayrıntıda, durum
    # adında ve olay numarasında da arar
    assert kimlikler("&donem=90&ara=KAZAN") == [26]
    assert kimlikler("&donem=90&ara=depo+giris") == [29, 27]
    assert kimlikler("&donem=90&ara=yanl%C4%B1%C5%9F+alarm") == [28]
    assert kimlikler("&donem=90&ara=27") == [27]
    # Sayfalama: sayfa sınırın dışındaysa son sayfa
    monkeypatch.setattr(_pano, "ARSIV_SAYFA", 2)
    assert kimlikler("&donem=90&sayfa=2") == [28, 27]
    kod, _, govde = _arsiv_al(site, cerez, "&donem=90&sayfa=99")
    a = json.loads(govde)["arsiv"]
    assert (a["sayfa"], a["sayfa_sayisi"], [o["id"] for o in a["olaylar"]]) == (3, 3, [26])


def test_arsiv_csv_excel_icin_ve_her_rol_indirir(site):  # noqa: F811
    _ornek_arsiv(site)
    kurucu = _kurucu(site)
    izleyici = _hazir_hesap(site, kurucu, "bekir", "izleyici", "bekir-parola-123")
    kod, basliklar, govde = _arsiv_al(site, izleyici, "&donem=90&bicim=csv")
    assert kod == 200, govde
    assert basliklar["Content-Type"] == "text/csv; charset=utf-8"
    assert re.fullmatch(
        r'attachment; filename="dalsan-olaylar-\d{4}-\d\d-\d\d_\d{4}-\d\d-\d\d\.csv"',
        basliklar["Content-Disposition"],
    )
    assert basliklar["Cache-Control"] == "private, no-store"
    assert govde.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM: Excel Türkçe harfleri doğru açar
    satirlar = govde.decode("utf-8-sig").split("\r\n")
    assert satirlar[0] == ("Tarih;Saat;Tür;Olay;Önem;Kamera / yer;Durum;Süre;Ayrıntı;Olay no;Tesis")
    assert len(satirlar) == 1 + 5 + 1 and satirlar[-1] == ""
    ilk = satirlar[1].split(";")
    assert re.fullmatch(r"\d\d\.\d\d\.\d{4}", ilk[0]) and re.fullmatch(r"\d\d:\d\d:\d\d", ilk[1])
    assert ilk[2:] == [
        "İhlal", "Araç-yaya yakınlığı - 1,85 m", "Kritik",
        "Sevkiyat Rampası · Sevkiyat", "Bekliyor", "8 sn", "", "30", "",
    ]  # fmt: skip
    # Ayraç ve tırnak taşıyan hücre tırnağa alınır, içindeki tırnak ikilenir
    assert satirlar[5].endswith(';"Kameraya ulaşılamıyor; ""(adres)"" yeniden deneniyor";26;')
    # Süzgeç CSV'ye de uygulanır
    _, _, govde = _arsiv_al(site, izleyici, "&donem=90&durum=false_alarm&bicim=csv")
    assert govde.decode("utf-8-sig").count("\r\n") == 2
    # Oturumsuz indirilemez
    kod, _, _ = _istek(f"{site}/api/durum?arsiv=1&bicim=csv")
    assert kod == 401


def test_csv_formul_gibi_baslayan_hucreyi_etkisizlestirir():
    olay = _pano.arsiv_coz([json.dumps(_olay(4, baslik="=HYPERLINK(1)", yer="+90 hat", sure="-3"))])
    hucreler = _pano.arsiv_csv(olay).decode("utf-8-sig").split("\r\n")[1].split(";")
    assert hucreler[3] == "'=HYPERLINK(1)" and hucreler[5] == "'+90 hat" and hucreler[7] == "'-3"
    assert _pano._csv_hucresi("@x") == "'@x" and _pano._csv_hucresi("a\nb") == '"a\nb"'


# ------------------------------------------------------- ekran kablolaması


def test_olaylar_ekraninda_arsiv_modu_ve_inceleme_modu_var():
    """Yeni sekme yok: arşiv ve inceleme Olaylar ekranının içindedir."""
    olaylar = PANO_HTML.split('data-gorunum="olaylar" hidden>', 1)[1].split("<!-- MÜDAHALE -->")[0]
    for kimlik in [
        "arsiv-cipi",
        "inceleme-ac",
        "arsiv-paneli",
        "arsiv-donemi",
        "arsiv-tip",
        "arsiv-yer",
        "arsiv-durum",
        "arsiv-ara",
        "arsiv-csv",
        "arsiv-listesi",
        "arsiv-onceki",
        "arsiv-sonraki",
    ]:
        assert f'id="{kimlik}"' in olaylar, kimlik
    # Dönem düğmeleri: bugün, 7, 30, 90 gün
    assert re.findall(r'data-donem="([a-z0-9]+)"', olaylar) == ["bugun", "7", "30", "90"]
    # İnceleme modu fotoğraf penceresini kullanır: sayaç ve gezinti orada
    pencere = PANO_HTML.split('id="foto-penceresi"', 1)[1].split("</dialog>")[0]
    for kimlik in ["inceleme-gezinti", "inceleme-sayac", "inceleme-onceki", "inceleme-sonraki"]:
        assert f'id="{kimlik}"' in pencere, kimlik


def test_arsiv_ve_csv_ayni_uctan_ve_demoda_tarayicida():
    """Arşiv /api/durum?arsiv=1'den okunur; CSV aynı adresin bağlantısıdır
    (iPhone Safari'de de iner). Demoda istek sunucuya gitmez: demo.js arşivi
    karşılar, CSV'yi tarayıcıda kurar."""
    sorgu = re.search(r"function arsivSorgusu\(csv\) \{.*?\n  \}", PANO_JS, re.S).group(0)
    assert 'arsiv: "1"' in sorgu and 'p.set("bicim", "csv")' in sorgu
    assert '"/api/durum?" + arsivSorgusu(false)' in PANO_JS  # liste
    assert '$("arsiv-csv").href = "/api/durum?" + arsivSorgusu(true)' in PANO_JS  # indirme
    assert "DEMO.arsivCsv" in PANO_JS
    assert 'searchParams.get("arsiv") === "1"' in DEMO_JS and "arsivCsv:" in DEMO_JS
    # Demo arşivi 90 günü kapsar
    assert "ARSIV_GUN = 90" in DEMO_JS


def test_inceleme_modu_yalniz_inceleyebilene_ve_klavyeyle():
    ac = re.search(r"function incelemeDugmesiniCiz\(\) \{.*?\n  \}", PANO_JS, re.S).group(0)
    assert "inceleyebilir()" in ac
    tus = re.search(r"function incelemeTusu\(olay\) \{.*?\n  \}", PANO_JS, re.S).group(0)
    for tus_adi in ['"ArrowRight"', '"ArrowLeft"', '"i"', '"ı"', '"y"']:
        assert tus_adi in tus, tus_adi
    # Mevcut komut yolu: olay_incele
    gonder = re.search(r"async function incelemeKarari\(karar\) \{.*?\n  \}", PANO_JS, re.S)
    assert 'tur: "olay_incele"' in gonder.group(0) and "mudahaleGonder(" in gonder.group(0)


def test_arsiv_ve_inceleme_telefonda_tasmaz():
    """Süzgeç ızgarası dar ekranda tek sütuna iner; inceleme düğmeleri büyük."""
    assert re.search(
        r"\.arsiv-suzgec\s*\{[^}]*grid-template-columns: repeat\(auto-fit, minmax\(", PANO_CSS
    )
    assert re.search(r"\.inceleme-kararlari \.dugme\s*\{[^}]*min-height: 56px", PANO_CSS)
