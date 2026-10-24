"""Sayfaların bütünlüğü: güvenlik başlığıyla çalışırlar, simgeleri ve
betiğin aradığı öğeler gerçekten vardır, telefon kuralları korunur."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

PUBLIC = Path(__file__).resolve().parents[1] / "public"
SAYFALAR = sorted(PUBLIC.glob("*.html"))
PANO_JS = (PUBLIC / "pano.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("sayfa", SAYFALAR, ids=lambda p: p.name)
def test_satir_ici_stil_ve_betik_yok(sayfa):
    """vercel.json'daki Content-Security-Policy satır içi stili ve betiği
    engeller: sayfada çalışmazlardı."""
    metin = sayfa.read_text(encoding="utf-8")
    assert not re.search(r"\sstyle\s*=", metin), "style= özniteliği CSP'de çalışmaz"
    assert not re.search(r"<style[\s>]", metin)
    assert not re.search(r"<script(?![^>]*\ssrc=)[^>]*>", metin), "satır içi betik var"
    assert not re.search(r"\son[a-z]+\s*=", metin), "satır içi olay işleyicisi var"


@pytest.mark.parametrize("sayfa", SAYFALAR, ids=lambda p: p.name)
def test_kullanilan_her_simge_sayfada_tanimli(sayfa):
    metin = sayfa.read_text(encoding="utf-8")
    tanimli = set(re.findall(r'<symbol id="(i-[a-z-]+)"', metin))
    kullanilan = set(re.findall(r'href="#(i-[a-z-]+)"', metin))
    if sayfa.name == "pano.html":
        kullanilan |= set(re.findall(r'"(i-[a-z-]+)"', PANO_JS))
    assert kullanilan <= tanimli, f"tanımsız simge: {sorted(kullanilan - tanimli)}"


def test_betigin_aradigi_her_oge_panoda_var():
    html = (PUBLIC / "pano.html").read_text(encoding="utf-8")
    kimlikler = set(re.findall(r'\sid="([a-z0-9-]+)"', html))
    aranan = set(re.findall(r'\$\("([a-z0-9-]+)"\)', PANO_JS))
    for liste in re.findall(r"for \(const kimlik of \[([^\]]+)\]", PANO_JS):
        aranan |= set(re.findall(r'"([a-z0-9-]+)"', liste))
    assert aranan, "betikte aranan öğe bulunamadı"
    assert aranan <= kimlikler, f"panoda olmayan öğe: {sorted(aranan - kimlikler)}"


@pytest.mark.parametrize("sayfa", SAYFALAR, ids=lambda p: p.name)
def test_telefonda_guvenli_alan(sayfa):
    """Çentikli telefonda env(safe-area-inset-*) ancak viewport-fit=cover ile çalışır."""
    metin = sayfa.read_text(encoding="utf-8")
    assert re.search(r'name="viewport" content="[^"]*viewport-fit=cover', metin)


def test_buyuk_harf_css_ile_yazilmaz():
    """text-transform Türkçe i'yi I yapar (lafmobil kuralı): büyük harf metnin
    kendisiyle yazılır."""
    css = (PUBLIC / "stil.css").read_text(encoding="utf-8")
    assert "uppercase" not in css


def test_dokunmatikte_44_px():
    """Telefonda dokunma hedefi en az 44 px (lafmobil minTouchTarget, Innex
    dokunmatik düğmesi)."""
    css = (PUBLIC / "stil.css").read_text(encoding="utf-8")
    assert re.search(
        r"@media \(pointer: coarse\), \(max-width: 1023\.98px\)\s*{\s*:root\s*{\s*"
        r"--dugme-boyu: 44px;",
        css,
    )
    assert "--dokunma: 44px;" in css


LOGOLAR = ["logo.svg", "logo-kucuk.svg"]


@pytest.mark.parametrize("ad", LOGOLAR)
def test_logo_gecerli_svg(ad):
    """Bozuk XML (ör. yorumda iki tire yan yana) logoyu her sayfada kırık resim
    olarak gösterir: tarayıcı SVG'yi XML olarak ayrıştırır."""
    kok = ET.parse(PUBLIC / ad).getroot()
    assert kok.tag == "{http://www.w3.org/2000/svg}svg"
    assert kok.get("viewBox")


@pytest.mark.parametrize("sayfa", SAYFALAR, ids=lambda p: p.name)
def test_logo_ve_simge_basvurulari_var_olan_dosyayi_gosterir(sayfa):
    metin = sayfa.read_text(encoding="utf-8")
    basvurular = re.findall(r'<img\s[^>]*\bsrc="([^"]+)"', metin)
    basvurular += re.findall(r'<link\s[^>]*\bhref="([^"]+)"', metin)
    assert basvurular, "sayfada logo ya da simge başvurusu yok"
    for adres in basvurular:
        assert adres.startswith("/") and not adres.startswith("//"), adres
        dosya = PUBLIC / adres.lstrip("/").split("?")[0]
        assert dosya.is_file(), f"{sayfa.name}: {adres} public/ altında yok"
    # Sekme simgesi küçük boydur: 24 px ve altı için çizilen sürüm
    assert re.search(r'<link rel="icon" href="/logo-kucuk.svg"', metin)
