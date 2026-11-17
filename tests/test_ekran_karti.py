"""Seçilen tespit donanımı ve ekran kartının notu (raporun bilgisayar bloğu).

Program (17.11.2026) iki alan ekler:
    "cikarim_secimi": Ayarlar'da seçilen donanımın adı ("Ekran kartı (varsa; yoksa
                      işlemci)"); "cikarim" şu an çalışan donanımdır.
    "cikarim_notu":   fabrikanın Teşhis'indeki "Ekran kartı" satırının metni (kart ve
                      işlemciyle son karşılaştırma ya da kullanılmama sebebi); işlemci
                      seçiliyse boş.
Site ikisini de metin ve adres süzgecinden geçirir (alan yoksa boş, uzunsa
kısalır). Panonun Bilgisayar kartında "Seçilen donanım" ve "Kart notu" satırları
çıkar; kartın öteki satırları gibi her rol görür (yalnız ip ve bilgisayar_adi
veri.bilgisayar ister). Eski programın raporunda iki alan yoktur: satırlar çıkmaz.
"""

import json
import re
from pathlib import Path

import _pano
from test_cekirdek import _rapor
from test_hesap import _hesap, _yaz_hesap
from test_uctan_uca import RAPOR, _cerez, _giris, _istek, _rapor_gonder, site  # noqa: F401

PUBLIC = Path(__file__).resolve().parents[1] / "public"
PANO_JS = (PUBLIC / "pano.js").read_text(encoding="utf-8")
DEMO_JS = (PUBLIC / "demo.js").read_text(encoding="utf-8")
SECIM = "Ekran kartı (varsa; yoksa işlemci)"
NOT = (
    "Kullanılıyor - NVIDIA GeForce RTX 5080 (DirectML, yüksek performanslı kart olduğu tahmin "
    "ediliyor). Sonuçları işlemciyle karşılaştırıldı: 11:42, en büyük puan farkı 0,0012."
)


def _bilgisayar(**alanlar) -> dict:
    ham = {"ad": "Gebze", "ekran_karti": "NVIDIA GeForce RTX 5080", **alanlar}
    return _pano.rapor_temizle(_rapor(bilgisayar=ham))["bilgisayar"]


def test_iki_alan_suzulup_aynen_gecer():
    bilgi = _bilgisayar(cikarim="Ekran kartı (DirectML)", cikarim_secimi=SECIM, cikarim_notu=NOT)
    assert bilgi["cikarim"] == "Ekran kartı (DirectML)"
    assert bilgi["cikarim_secimi"] == SECIM
    assert bilgi["cikarim_notu"] == NOT


def test_alan_yoksa_ya_da_metin_degilse_bos():
    bilgi = _bilgisayar()
    assert (bilgi["cikarim_secimi"], bilgi["cikarim_notu"]) == ("", "")
    bilgi = _bilgisayar(cikarim_secimi=["gpu"], cikarim_notu={"metin": NOT})
    assert (bilgi["cikarim_secimi"], bilgi["cikarim_notu"]) == ("", "")
    bilgi = _bilgisayar(cikarim_secimi=None, cikarim_notu=12)
    assert (bilgi["cikarim_secimi"], bilgi["cikarim_notu"]) == ("", "")


def test_uzunsa_kisalir_kontrol_karakteri_atilir():
    bilgi = _bilgisayar(cikarim_secimi="S" * 500, cikarim_notu="Kart\nnotu\u2028" + "x" * 900)
    assert bilgi["cikarim_secimi"] == "S" * 80
    assert len(bilgi["cikarim_notu"]) == 300
    assert bilgi["cikarim_notu"].startswith("Kart notu x")


def test_adres_ve_dosya_yolu_maskelenir():
    bilgi = _bilgisayar(
        cikarim_secimi="Kart rtsp://admin:gizli@10.0.0.5/akis",
        cikarim_notu=(
            "Kullanılmıyor - kart açılamadı: C:\\Users\\ahmet\\onnx.log, 192.168.1.5:554, "
            "/Users/ayse/veri/x.db"
        ),
    )
    birlikte = bilgi["cikarim_secimi"] + " " + bilgi["cikarim_notu"]
    for sizinti in ("rtsp://", "admin", "gizli", "10.0.0.5", "ahmet", "192.168.1.5", "ayse"):
        assert sizinti not in birlikte, sizinti
    assert "(adres)" in bilgi["cikarim_secimi"]
    assert "(dosya yolu)" in bilgi["cikarim_notu"] and "(adres)" in bilgi["cikarim_notu"]


def test_yalniz_iki_alan_varsa_da_blok_gelir():
    """Bilgisayar bloğunda başka bilgi yoksa da not boşa düşmez (any)."""
    temiz = _pano.rapor_temizle(_rapor(bilgisayar={"cikarim_notu": NOT}))
    assert temiz["bilgisayar"]["cikarim_notu"] == NOT


def test_izleyici_de_gorur_ip_ve_bilgisayar_adi_gizli_kalir(site):  # noqa: F811
    bilgisayar = {
        "ad": "Gebze",
        "bilgisayar_adi": "PC-1",
        "ip": ["192.168.1.9"],
        "cikarim": "Ekran kartı (DirectML)",
        "cikarim_secimi": SECIM,
        "cikarim_notu": NOT,
    }
    assert _rapor_gonder(site, {**RAPOR, "bilgisayar": bilgisayar})[0] == 200
    _yaz_hesap(_pano.DEPO, _hesap("izci", rol="izleyici"))
    izci = _cerez(_giris(site, "dogru-sifre-1", ad="izci")[1])
    kod, _, govde = _istek(f"{site}/api/durum", basliklar={"Cookie": izci})
    bilgi = json.loads(govde)["rapor"]["bilgisayar"]
    assert kod == 200
    assert bilgi["cikarim_secimi"] == SECIM and bilgi["cikarim_notu"] == NOT
    assert "ip" not in bilgi and "bilgisayar_adi" not in bilgi


def test_bilgisayar_kartinda_iki_satir_yalniz_doluysa_textcontent_ile():
    ciz = re.search(r"function bilgisayariCiz\(rapor\) \{.*?\n  \}", PANO_JS, re.S).group(0)
    assert '["Seçilen donanım", b.cikarim_secimi]' in ciz
    assert '["Kart notu", b.cikarim_notu]' in ciz
    # Çalışan donanımdan ("Tespit") hemen sonra, bu sırayla
    assert ciz.index('["Tespit", b.cikarim]') < ciz.index('"Seçilen donanım"')
    assert ciz.index('"Seçilen donanım"') < ciz.index('"Kart notu"')
    # Boş değer satır çizmez; değer el() ile textContent'e yazılır
    assert "if (!deger) continue;" in ciz
    assert 'el("dd", "", deger)' in ciz
    assert "innerHTML" not in ciz


def test_demo_iki_alani_ornekle_gosterir():
    blok = re.search(r"bilgisayar: \{.*?\n      \},", DEMO_JS, re.S).group(0)
    assert "cikarim_secimi:" in blok and "cikarim_notu:" in blok
    assert "Sonuçları işlemciyle karşılaştırıldı" in blok
