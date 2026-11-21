"""Görüntü (fabrika içi kullanım kararı, 24.10.2026): kanıt fotoğrafı ve anlık görüntü.

Fabrika imzalı gönderir; pano yalnız oturumla görür. JPEG olmayan içerik ve
sınırı aşan görüntü depoya girmez. Hangi olayın fotoğrafı olduğunu site
kendisi tutar ve fabrikaya söyler; fotoğraf sayısı sınırlıdır. Anlık görüntü
yalnız Kameralar ekranı açıkken istenir.
"""

import base64
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import _pano
import pytest
from test_uctan_uca import (  # noqa: F401
    ANAHTAR,
    RAPOR,
    _cerez,
    _giris,
    _istek,
    _rapor_gonder,
    imza_damgasi,
    site,
)

PANO_JS = (Path(__file__).resolve().parents[1] / "public" / "pano.js").read_text(encoding="utf-8")
JPEG = b"\xff\xd8\xff\xe0" + b"\x10JFIF" + bytes(range(256)) * 4 + b"\xff\xd9"
RAPOR_KAMERALI = {
    **RAPOR,
    "kameralar": [
        {"id": 4, "ad": "Sevkiyat Rampası", "bolum": "Sevkiyat", "durum": "online"},
        {"id": 5, "ad": "Depo Girişi", "bolum": "Depo", "durum": "online"},
    ],
    "son_olaylar": [
        {"id": 123, "tur": "ihlal", "baslik": "Baret yok"},
        {"id": 122, "tur": "ihlal", "baslik": "Yelek yok"},
    ],
}


def _imzali(adres, yol, govde_sozluk, anahtar=ANAHTAR):
    govde = json.dumps(govde_sozluk).encode()
    zaman = imza_damgasi(govde)
    return _istek(
        f"{adres}{yol}",
        "POST",
        govde,
        {
            "Content-Type": "application/json",
            _pano.ZAMAN_BASLIGI: zaman,
            _pano.IMZA_BASLIGI: _pano.imza_hesapla(anahtar, zaman, govde),
        },
    )


def _b64(veri: bytes) -> str:
    return base64.b64encode(veri).decode()


def _foto_yolla(site, olay_id):  # noqa: F811
    govde = {"surum": 1, "olay_id": olay_id, "jpeg": _b64(JPEG)}
    kod, _, cevap = _imzali(site, "/api/foto", govde)
    assert kod == 200, cevap


def _olaylar(site, cerez):  # noqa: F811
    kod, _, govde = _istek(f"{site}/api/durum", basliklar={"Cookie": cerez})
    assert kod == 200
    return {o["id"]: o["foto"] for o in json.loads(govde)["rapor"]["son_olaylar"]}


def test_kanit_fotografi_yuklenir_ve_yalniz_oturumla_gorulur(site):  # noqa: F811
    # Fotoğraf gelmeden: rapor cevabı "hiçbiri bende yok" der, pano göstermez
    kod, _, govde = _rapor_gonder(site, RAPOR_KAMERALI)
    assert json.loads(govde)["foto"] == {"var": []}
    cerez = _cerez(_giris(site)[1])
    assert _olaylar(site, cerez) == {123: False, 122: False}

    _foto_yolla(site, 123)

    kod, _, _ = _istek(f"{site}/api/foto?olay=123")
    assert kod == 401
    kod, basliklar, veri = _istek(f"{site}/api/foto?olay=123", basliklar={"Cookie": cerez})
    assert kod == 200
    assert basliklar["Content-Type"] == "image/jpeg"
    assert basliklar["X-Content-Type-Options"] == "nosniff"
    # Kanıt fotoğrafı kişisel veridir: paylaşılan bilgisayarda çıkıştan sonra
    # tarayıcı önbelleğinden açılamasın (inceleme 02.11.2026). Küçük fotoğraf
    # öğesi tazelemelerde yeniden kullanıldığı için bant genişliği değişmez.
    assert basliklar["Cache-Control"] == "private, no-store"
    assert veri == JPEG
    assert _istek(f"{site}/api/foto?olay=999", basliklar={"Cookie": cerez})[0] == 404
    assert _istek(f"{site}/api/foto?olay=../x", basliklar={"Cookie": cerez})[0] == 400

    # Pano hangi olayın fotoğrafı olduğunu bilir; fabrika aynısını yeniden göndermez
    assert _olaylar(site, cerez) == {123: True, 122: False}
    kod, _, govde = _rapor_gonder(site, RAPOR_KAMERALI)
    assert json.loads(govde)["foto"] == {"var": [123]}


def test_fotograf_sayisi_sinirlidir_tasan_silinir(site, monkeypatch):  # noqa: F811
    monkeypatch.setattr(_pano, "FOTO_EN_COK", 3)
    for olay_id in (1, 2, 3, 4, 5):
        _foto_yolla(site, olay_id)
    anahtar = _pano.FOTO_ONEKI
    var = [_pano.DEPO.al_coklu([anahtar + str(k)])[0] is not None for k in (1, 2, 3, 4, 5)]
    assert var == [False, False, True, True, True]
    # Yeniden gelen fotoğraf öne geçer, iki kez yazılmaz
    _foto_yolla(site, 3)
    (ham,) = _pano.DEPO.al_coklu([_pano.FOTO_LISTESI_ANAHTARI])
    assert [k for k, _ in _pano.foto_listesi(ham, time.time())] == [3, 5, 4]


def test_foto_listesi_suresi_dolani_ve_bozugu_atar():
    simdi = 10_000_000
    eski = simdi - _pano.FOTO_SAKLAMA_SN
    ham = json.dumps(
        [[7, simdi], [6, eski], ["5", simdi], [True, simdi], [4, 1.5], [3], 9, [2, simdi]]
    )
    assert _pano.foto_listesi(ham, simdi) == [(7, simdi), (2, simdi)]
    assert _pano.foto_listesi("bozuk{", simdi) == []
    assert _pano.foto_listesi(None, simdi) == []


def test_gecersiz_goruntu_depoya_girmez(site):  # noqa: F811
    yol = "/api/foto"
    imzasiz = _istek(
        f"{site}{yol}",
        "POST",
        json.dumps({"surum": 1, "olay_id": 1, "jpeg": _b64(JPEG)}).encode(),
        {"Content-Type": "application/json"},
    )
    assert imzasiz[0] == 401
    yanlis = _imzali(site, yol, {"surum": 1, "olay_id": 1, "jpeg": _b64(JPEG)}, anahtar="b" * 40)
    assert yanlis[0] == 401
    html = _b64(b"<html><script>alert(1)</script></html>")
    assert _imzali(site, yol, {"surum": 1, "olay_id": 1, "jpeg": html})[0] == 400
    assert _imzali(site, yol, {"surum": 1, "olay_id": 1, "jpeg": "base64 değil!"})[0] == 400
    assert _imzali(site, yol, {"surum": 1, "jpeg": _b64(JPEG)})[0] == 400
    buyuk = JPEG[:3] + bytes(_pano.FOTO_EN_BUYUK_BAYT)
    kod, _, govde = _imzali(site, yol, {"surum": 1, "olay_id": 1, "jpeg": _b64(buyuk)})
    assert kod == 413 and "küçültüp" in json.loads(govde)["mesaj"]
    assert _pano.DEPO.al_coklu([_pano.FOTO_ONEKI + "1"]) == [None]


def test_anlik_goruntu_yalniz_kameralar_ekrani_acikken_istenir(site):  # noqa: F811
    kod, _, govde = _rapor_gonder(site, RAPOR_KAMERALI)
    assert json.loads(govde)["kare"] == {"iste": False}
    kod, _, govde = _imzali(site, "/api/kare", {"surum": 1, "kamera_id": 4, "jpeg": _b64(JPEG)})
    assert kod == 200 and json.loads(govde)["iste"] is False

    cerez = _cerez(_giris(site)[1])
    kod, _, govde = _istek(f"{site}/api/durum?kare=1", basliklar={"Cookie": cerez})
    assert json.loads(govde)["kareler"] == {"4": json.loads(govde)["kareler"]["4"]}
    # Kameralar ekranı açıldı: rapor ve görüntü cevabı "gönder" der
    assert json.loads(_rapor_gonder(site, RAPOR_KAMERALI)[2])["kare"] == {"iste": True}
    kod, _, govde = _imzali(site, "/api/kare", {"surum": 1, "kamera_id": 5, "jpeg": _b64(JPEG)})
    assert kod == 200 and json.loads(govde)["iste"] is True

    kod, _, govde = _istek(f"{site}/api/durum?kare=1", basliklar={"Cookie": cerez})
    kareler = json.loads(govde)["kareler"]
    assert set(kareler) == {"4", "5"} and kareler["5"].endswith("+00:00")
    kod, basliklar, veri = _istek(f"{site}/api/kare?kamera=5", basliklar={"Cookie": cerez})
    assert kod == 200 and veri == JPEG and basliklar["Cache-Control"] == "no-store"
    assert _istek(f"{site}/api/kare?kamera=5")[0] == 401
    assert _istek(f"{site}/api/kare?kamera=6", basliklar={"Cookie": cerez})[0] == 404


def _kare_cevabi(site, cerez, sorgu=""):  # noqa: F811
    """Kameralar ekranı açık panonun bir okuması, ardından fabrikanın raporu: kare bloğu."""
    kod, _, _ = _istek(f"{site}/api/durum?kare=1{sorgu}", basliklar={"Cookie": cerez})
    assert kod == 200
    return json.loads(_rapor_gonder(site, RAPOR_KAMERALI)[2])["kare"]


def test_rapor_cevabi_yalniz_panoda_gorunen_kameralari_ister(site):  # noqa: F811
    """50-60 kameraya hazırlık (17.11.2026): pano Kameralar ekranında görünen
    kutucukların kimliklerini ?kameralar= ile bildirir; rapor cevabı kare.kameralar
    ile yalnız onları ister. Birden çok kişi bakıyorsa birleşimi istenir; listesiz
    bakan (eski pano) varsa bugünkü gibi hepsi."""
    _rapor_gonder(site, RAPOR_KAMERALI)
    cerez = _cerez(_giris(site)[1])
    assert _kare_cevabi(site, cerez, "&kameralar=5") == {"iste": True, "kameralar": [5]}
    # Başka bir ekranda 4 görünüyor: ikisi birden istenir (küçükten büyüğe)
    assert _kare_cevabi(site, cerez, "&kameralar=4") == {"iste": True, "kameralar": [4, 5]}
    # Listesiz bakan (eski pano): fabrika hepsini göndersin (bugünkü cevap)
    assert _kare_cevabi(site, cerez) == {"iste": True}


@pytest.mark.parametrize(
    ("sorgu", "beklenen"),
    [
        ("&kameralar=5,abc,0,-3,99999999999,5,7", {"iste": True, "kameralar": [5]}),
        ("&kameralar=abc", {"iste": True}),  # bozuk liste (tanınmayan istemci): hepsi
        ("&kameralar=", {"iste": False}),  # boş liste: ekranda kutucuk yok, istenmez
        ("&kameralar=7", {"iste": False}),  # raporda olmayan kamera: istenmez
        ("&kameralar=" + ",".join(["4"] * 129), {"iste": True}),  # sınırdan uzun: yok sayılır
        ("&kameralar=4%2C5", {"iste": True, "kameralar": [4, 5]}),
    ],
)
def test_bozuk_kamera_listesi_suzulur_ya_da_yok_sayilir(site, sorgu, beklenen):  # noqa: F811
    _rapor_gonder(site, RAPOR_KAMERALI)
    cerez = _cerez(_giris(site)[1])
    assert _kare_cevabi(site, cerez, sorgu) == beklenen


def test_kamera_listesi_kameralar_ekrani_kapaliyken_bir_sey_istemez(site):  # noqa: F811
    _rapor_gonder(site, RAPOR_KAMERALI)
    cerez = _cerez(_giris(site)[1])
    kod, _, _ = _istek(f"{site}/api/durum?kameralar=4", basliklar={"Cookie": cerez})
    assert kod == 200
    assert json.loads(_rapor_gonder(site, RAPOR_KAMERALI)[2])["kare"] == {"iste": False}
    assert _istek(f"{site}/api/durum?kare=1&kameralar=4")[0] == 401  # oturumsuz bildirilmez


def test_gorunen_kamera_listesi_bakan_kalmayinca_duser():
    """Her kimlik KARE_SECIM_SURESI_SN (45 sn) sonra düşer: kaydırılıp ekrandan
    çıkan kamera bir süre sonra istenmez; kimse bakmıyorsa kare bloğu bugünkü gibi."""
    assert _pano.KARE_SECIM_SURESI_SN == 45
    simdi = [1000.0]
    depo = _pano.BellekDepo(lambda: simdi[0])
    rapor = _pano.rapor_temizle(RAPOR_KAMERALI)
    _pano.kare_zamanlari(depo, rapor, [4], simdi[0])
    simdi[0] += 20
    _pano.kare_zamanlari(depo, rapor, [5], simdi[0])  # 5'ten sonra okuma yok
    assert _pano.rapor_kaydet(depo, rapor, simdi[0])["kare"] == {"iste": True, "kameralar": [4, 5]}
    simdi[0] = 1000.0 + _pano.KARE_SECIM_SURESI_SN  # 4'ün süresi doldu, 5'inki sürüyor
    assert _pano.rapor_kaydet(depo, rapor, simdi[0])["kare"] == {"iste": True, "kameralar": [5]}
    simdi[0] = 1020.0 + _pano.IZLEYEN_SURESI_SN  # kimse bakmıyor
    assert _pano.rapor_kaydet(depo, rapor, simdi[0])["kare"] == {"iste": False}


def test_yeni_panonun_bos_listesi_goruntu_istemez():
    """Kameralar ekranı doğrudan açılınca (yenileme, giriş sonrası) ilk okuma
    kutucuklar çizilmeden gider: yeni pano boş liste bildirir. Boş liste ne
    "hepsi" işaretini ne "ekran açık" işaretini koyar: o arada gelen rapora
    "gönderme" denir. Eskiden işaret konuyor, liste olmadığı için fabrika bir
    rapor aralığı boyunca (50-60 kamerada hepsini) gönderiyordu. Kutucuklar
    çizilince pano listeyi hemen bildirir (pano.js)."""
    simdi = [1000.0]
    depo = _pano.BellekDepo(lambda: simdi[0])
    rapor = _pano.rapor_temizle(RAPOR_KAMERALI)
    _pano.kare_zamanlari(depo, rapor, [], simdi[0])
    assert _pano.rapor_kaydet(depo, rapor, simdi[0])["kare"] == {"iste": False}
    assert depo.al_coklu([_pano.KARE_HEPSI_ANAHTARI, _pano.KARE_IZLEYEN_ANAHTARI]) == [None, None]
    simdi[0] += 5
    _pano.kare_zamanlari(depo, rapor, [4], simdi[0])
    simdi[0] += 1
    assert _pano.rapor_kaydet(depo, rapor, simdi[0])["kare"] == {"iste": True, "kameralar": [4]}
    # Eski pano (liste hiç yok) yine "hepsi" der
    _pano.kare_zamanlari(depo, rapor, None, simdi[0])
    assert _pano.rapor_kaydet(depo, rapor, simdi[0])["kare"] == {"iste": True}


def test_yeni_panonun_bos_listesi_istekte_de_hepsi_demez(site):  # noqa: F811
    """`&kameralar=` boş ama VAR: yeni pano, ekranda henüz kutucuk yok. Sorgunun
    hiç olmaması (eski pano) ise bugünkü gibi hepsini ister."""
    _rapor_gonder(site, RAPOR_KAMERALI)
    cerez = _cerez(_giris(site)[1])
    assert _kare_cevabi(site, cerez, "&kameralar=") == {"iste": False}
    assert _kare_cevabi(site, cerez, "&kameralar=5") == {"iste": True, "kameralar": [5]}


def test_suzgec_butun_kutucuklari_gizleyince_goruntu_istenmez():
    """ "Sorunlu" çipi bütün kutucukları gizlerse pano boş liste bildirir. Eskiden
    seçim 45 sn'de düşüyor, "ekran açık" işareti kalıyor ve ekran açık kaldıkça
    fabrika BÜTÜN kameraları gönderiyordu. Artık boş liste işareti tazelemez:
    işaret 30 sn'de düşer ve fabrikaya "gönderme" denir. Başka biri kutucuk
    görüyorsa onun seçimi geçerlidir."""
    simdi = [1000.0]
    depo = _pano.BellekDepo(lambda: simdi[0])
    rapor = _pano.rapor_temizle(RAPOR_KAMERALI)
    _pano.kare_zamanlari(depo, rapor, [4], simdi[0])
    assert _pano.rapor_kaydet(depo, rapor, simdi[0])["kare"] == {"iste": True, "kameralar": [4]}
    # Süzgeç her şeyi gizledi: pano 5 sn'de bir boş liste bildirir
    for _ in range(12):
        simdi[0] += 5
        _pano.kare_zamanlari(depo, rapor, [], simdi[0])
    assert _pano.rapor_kaydet(depo, rapor, simdi[0])["kare"] == {"iste": False}
    # İkinci bir kişi 5. kamerayı görüyor: yalnız o istenir
    _pano.kare_zamanlari(depo, rapor, [5], simdi[0])
    _pano.kare_zamanlari(depo, rapor, [], simdi[0] + 1)
    assert _pano.rapor_kaydet(depo, rapor, simdi[0] + 2)["kare"] == {
        "iste": True,
        "kameralar": [5],
    }


def test_raporda_olmayan_kamerayi_isteyen_liste_de_goruntu_istemez():
    """Listedeki kimliklerin hiçbiri raporda yoksa (kamera fabrikada silinmiş)
    görünen geçerli kutucuk yoktur: boş liste gibi davranılır."""
    simdi = [1000.0]
    depo = _pano.BellekDepo(lambda: simdi[0])
    rapor = _pano.rapor_temizle(RAPOR_KAMERALI)
    _pano.kare_zamanlari(depo, rapor, [999], simdi[0])
    assert _pano.rapor_kaydet(depo, rapor, simdi[0])["kare"] == {"iste": False}


def test_pano_kutucuklar_cizilince_gorunenleri_hemen_bildirir():
    """İlk okuma boş listeyle gittiyse ve kutucuklar şimdi varsa pano 5 sn'lik
    turu beklemeden yeniden okur: fabrika ilk rapor cevabında listeyi alsın."""
    govde = PANO_JS[PANO_JS.index("  async function yukle() {") :]
    govde = govde[: govde.index("\n  }\n")]
    assert 'kareSorgusu === "&kameralar="' in govde
    assert 'gorunenKameraSorgusu() !== "&kameralar="' in govde
    assert "setTimeout(yukle, KARE_ILK_LISTE_MS)" in govde


def test_secim_izleyen_isaretinden_once_dusmez():
    """Seçim, "ekran açık" işaretinden (son okumadan IZLEYEN_SURESI_SN sonra
    düşer) önce düşmez: bakan ayrılırken gelen rapor listesiz kalıp fabrikaya
    bütün kameraları göndertmez. Okumalar 0, 5, 10; seçim yalnız 0'da yazıldı."""
    simdi = [1000.0]
    depo = _pano.BellekDepo(lambda: simdi[0])
    rapor = _pano.rapor_temizle(RAPOR_KAMERALI)
    for okuma in (0, 5, 10):
        simdi[0] = 1000.0 + okuma
        _pano.kare_zamanlari(depo, rapor, [4], simdi[0])
    for an in (25, 31, 35, 39):
        simdi[0] = 1000.0 + an
        assert _pano.rapor_kaydet(depo, rapor, simdi[0])["kare"] == {
            "iste": True,
            "kameralar": [4],
        }, an
    simdi[0] = 1000.0 + 10 + _pano.IZLEYEN_SURESI_SN + 1
    assert _pano.rapor_kaydet(depo, rapor, simdi[0])["kare"] == {"iste": False}


def test_secimden_sonra_rapordan_cikan_kamera_istenmez():
    """Cevaptaki liste yalnız raporda olan kameralardır: seçimde 4 ve 5 varken
    5 rapordan çıkarsa (silindi) yalnız 4 istenir."""
    simdi = [1000.0]
    depo = _pano.BellekDepo(lambda: simdi[0])
    rapor = _pano.rapor_temizle(RAPOR_KAMERALI)
    _pano.kare_zamanlari(depo, rapor, [4, 5], simdi[0])
    rapor_5siz = _pano.rapor_temizle(
        {**RAPOR_KAMERALI, "kameralar": RAPOR_KAMERALI["kameralar"][:1]}
    )
    assert _pano.rapor_kaydet(depo, rapor_5siz, simdi[0])["kare"] == {
        "iste": True,
        "kameralar": [4],
    }


def test_pano_kameralar_ekraninda_gorunenleri_bildirir():
    """Kameralar ekranının okuması ?kare=1'e ekrandaki kutucukları ekler."""
    assert "const kareSorgusu = kareIzleniyor() ? gorunenKameraSorgusu() : null;" in PANO_JS
    assert '? "/api/durum?kare=1" + kareSorgusu' in PANO_JS


@pytest.mark.skipif(shutil.which("node") is None, reason="node yok")
def test_pano_yalniz_ekranda_ve_yakininda_gorunen_kutucuklari_sayar():
    """pano.js'teki gorunenKameraSorgusu ve GORUNUR_PAY node ile çalıştırılır:
    ekran 800 px, pay yarım ekran (400 px). Süzgeçle gizlenen, boyu olmayan
    (görünüm kapalı) ve kimliksiz (eski program) kutucuk sayılmaz; büyütülmüş
    görüntünün kamerası sayılır. Hiçbiri yoksa ek BOŞ gider: site onu eski
    panonun listesiz okumasından ayırır ve "hepsi" demez."""
    islev = re.search(r"function gorunenKameraSorgusu\(\) \{.*?\n  \}", PANO_JS, re.S).group(0)
    pay = re.search(r"^  const GORUNUR_PAY = [^;\n]+;$", PANO_JS, re.M).group(0)
    betik = (
        pay
        + """
const window = { innerHeight: 800 };
const document = { documentElement: { clientHeight: 800 } };
let pencereAcik = false;
let acikKare = null;
function $() { return { open: pencereAcik }; }
function kutu(id, ust, boy, gizli) {
  return {
    kamera: { id: id },
    dugme: {
      hidden: !!gizli,
      getBoundingClientRect: () =>
        ({ top: ust, bottom: ust + boy, width: boy ? 300 : 0, height: boy }),
    },
  };
}
const kareKutulari = new Map([
  ["id:1", kutu(1, 0, 200)],
  ["id:2", kutu(2, 1100, 200)],
  ["id:3", kutu(3, 1300, 200)],
  ["id:4", kutu(4, -700, 200)],
  ["id:5", kutu(5, -500, 200)],
  ["id:6", kutu(6, 100, 200, true)],
  ["id:7", kutu(7, 0, 0)],
  ["ad:Eski", kutu(null, 0, 200)],
]);
"""
        + islev
        + """
console.log(gorunenKameraSorgusu());
acikKare = "id:3";
console.log(gorunenKameraSorgusu());
pencereAcik = true;
console.log(gorunenKameraSorgusu());
kareKutulari.clear();
acikKare = null;
console.log(JSON.stringify(gorunenKameraSorgusu()));
"""
    )
    cikti = subprocess.run(
        ["node", "-e", betik], capture_output=True, text=True, timeout=20, check=True
    ).stdout.splitlines()
    assert cikti == [
        "&kameralar=1,2,5",
        "&kameralar=1,2,5",  # pencere kapalıyken büyütülmüş kamera sayılmaz
        "&kameralar=1,2,5,3",
        '"&kameralar="',
    ]


def test_ayni_secim_yarim_sure_dolmadan_yeniden_yazilmaz():
    """Pano 5 sn'de bir okur; seçim her okumada değil, 15 sn'de bir (kalan süresi
    IZLEYEN_SURESI_SN'e inince) ya da yeni kamera görününce yazılır: Upstash'e her
    okumada bir komut daha gitmesin (README "Plan ve maliyet")."""
    simdi = [1000.0]
    yazilan = []

    class Sayan(_pano.BellekDepo):
        def _calistir(self, parcalar):
            if parcalar[:2] == ["SET", _pano.KARE_SECIM_ANAHTARI]:
                yazilan.append(simdi[0])
            return super()._calistir(parcalar)

    depo = Sayan(lambda: simdi[0])
    rapor = _pano.rapor_temizle(RAPOR_KAMERALI)
    for _ in range(7):  # 30 sn boyunca 5 sn'de bir, hep 4 görünüyor
        _pano.kare_zamanlari(depo, rapor, [4], simdi[0])
        assert _pano.rapor_kaydet(depo, rapor, simdi[0])["kare"] == {
            "iste": True,
            "kameralar": [4],
        }
        simdi[0] += 5
    assert yazilan == [1000.0, 1015.0, 1030.0]
    _pano.kare_zamanlari(depo, rapor, [4, 5], simdi[0])  # 5 de göründü: hemen yazılır
    assert yazilan[-1] == simdi[0]
    assert _pano.rapor_kaydet(depo, rapor, simdi[0])["kare"]["kameralar"] == [4, 5]


def test_kare_secimi_coz():
    assert _pano.kare_secimi_coz(None) is None
    assert _pano.kare_secimi_coz("") is None
    assert _pano.kare_secimi_coz("4,5,4") == [4, 5]
    assert _pano.kare_secimi_coz(" 5 , 4 ") == [4, 5]
    assert _pano.kare_secimi_coz("x,1e3,+4,0x5,٣") is None  # yalnız ASCII rakam
    assert _pano.kare_secimi_coz(",".join(str(i) for i in range(1, 130))) is None
    assert _pano.kare_secimi_coz(",".join(str(i) for i in range(1, 129))) == list(range(1, 129))


def test_anlik_goruntu_iki_dakikada_silinir():
    simdi = [1000.0]
    depo = _pano.BellekDepo(lambda: simdi[0])
    depo.boru_hatti(
        [
            ["SET", _pano.KARE_ONEKI + "4", _b64(JPEG), "EX", str(_pano.KARE_SAKLAMA_SN)],
            ["SET", _pano.KARE_ZAMAN_ONEKI + "4", "z", "EX", str(_pano.KARE_SAKLAMA_SN)],
        ]
    )
    rapor = {"kameralar": [{"id": 4}, {"id": None}, "bozuk"]}
    assert _pano.kare_zamanlari(depo, rapor) == {"4": "z"}
    simdi[0] += _pano.KARE_SAKLAMA_SN
    assert _pano.kare_zamanlari(depo, rapor) == {}
    assert _pano.kare_zamanlari(depo, None) == {}


def test_sistem_olayinin_ayrintisi_ve_kamera_kimligi_suzulur():
    temiz = _pano.rapor_temizle(
        {
            **RAPOR,
            "kameralar": [{"id": True, "ad": "A"}, {"id": 4, "ad": "B"}],
            "son_olaylar": [
                {
                    "id": "12",
                    "foto": "evet",
                    "tur": "sistem",
                    "baslik": "Kamera çevrimdışı",
                    "ayrinti": "Kameraya ulaşılamıyor\n(10 sn'dir kare yok)",
                }
            ],
        }
    )
    assert [k["id"] for k in temiz["kameralar"]] == [None, 4]
    olay = temiz["son_olaylar"][0]
    # "foto" fabrikadan okunmaz: sitede fotoğraf olup olmadığını site bilir
    assert (olay["id"], olay["foto"]) == (None, False)
    assert olay["ayrinti"] == "Kameraya ulaşılamıyor (10 sn'dir kare yok)"


def test_sistem_olayinin_ayrintisina_adres_girmez():
    """Fabrika adresi çıkarmayı unutsa da kamera şifresi siteye yazılmaz."""
    temiz = _pano.rapor_temizle(
        {
            **RAPOR,
            "son_olaylar": [
                {
                    "tur": "sistem",
                    "baslik": "Kamera çevrimdışı",
                    "ayrinti": "Ulaşılamıyor: rtsp://admin:gizli@10.0.0.5:554/akis ve "
                    "http://kayit/x?password=1 (10 sn)",
                }
            ],
        }
    )
    ayrinti = temiz["son_olaylar"][0]["ayrinti"]
    assert ayrinti == "Ulaşılamıyor: (adres) ve (adres) (10 sn)"
    assert "gizli" not in ayrinti and "10.0.0.5" not in ayrinti


def test_gorunur_pay_ve_secim_suresi_sahibin_kararidir():
    """Yarım ekran payı ve seçimin 45 sn tutulması belgede karar olarak yoktu;
    sahibi 19.11.2026'da onayladı (G46). Değer ya da onay notu sessizce
    değişmesin: ikisi de tanımının hemen üstündeki yorumda anılır."""
    pay = re.search(r"((?:  //[^\n]*\n)+)  const GORUNUR_PAY = 0\.5;\n", PANO_JS)
    assert pay and "G46" in pay.group(1)
    assert _pano.KARE_SECIM_SURESI_SN == 45
    kaynak = Path(_pano.__file__).read_text(encoding="utf-8")
    secim = re.search(r"((?:#[^\n]*\n)+)KARE_SECIM_SURESI_SN = ", kaynak)
    assert secim and "G46" in secim.group(1)
