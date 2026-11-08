"""Sayfaların bütünlüğü: güvenlik başlığıyla çalışırlar, simgeleri ve
betiğin aradığı öğeler gerçekten vardır, telefon kuralları korunur."""

import json
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


STILLER = ["stil.css", "pano.css"]


@pytest.mark.parametrize("ad", STILLER)
def test_buyuk_harf_css_ile_yazilmaz(ad):
    """text-transform Türkçe i'yi I yapar (lafmobil kuralı): büyük harf metnin
    kendisiyle yazılır."""
    css = (PUBLIC / ad).read_text(encoding="utf-8")
    assert "uppercase" not in css


@pytest.mark.parametrize("ad", STILLER)
def test_dokunmatikte_44_px(ad):
    """Telefonda dokunma hedefi en az 44 px (lafmobil minTouchTarget, Innex
    dokunmatik düğmesi)."""
    css = (PUBLIC / ad).read_text(encoding="utf-8")
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


DEMO_JS = (PUBLIC / "demo.js").read_text(encoding="utf-8")


def test_demo_betigi_panodan_once_yuklenir():
    """demo.js fetch'i ve resim adreslerini pano.js çalışmadan kurmalı; ikisi de
    defer olduğu için sayfadaki sıra çalışma sırasıdır."""
    html = (PUBLIC / "pano.html").read_text(encoding="utf-8")
    betikler = re.findall(r'<script src="([^"]+)" defer></script>', html)
    assert betikler == ["/demo.js", "/pano.js"]


def test_demo_yalniz_demo_adresinde_calisir():
    """Gerçek panoda (/pano) demo.js hiçbir şey yapmamalı: ilk iş adresi denetler."""
    govde = DEMO_JS.split('"use strict";', 1)[1]
    ilk_satirlar = [s.strip() for s in govde.splitlines() if s.strip()][:2]
    assert ilk_satirlar == [
        "(function () {",
        'if (location.pathname.replace(/\\/+$/, "") !== "/demo") return;',
    ]


def test_demo_vercelde_pano_sayfasina_yonlenir():
    ayar = json.loads((PUBLIC.parent / "vercel.json").read_text(encoding="utf-8"))
    assert {"source": "/demo", "destination": "/pano"} in ayar["rewrites"]


# --------------------------------------------------------------- koyu tema

RENK = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|gradient\(")


def _degiskenler(css, secici):
    """`secici { ... }` bloğundaki --ad: değer; çiftleri (ilk blok)."""
    bas = css.index(secici + " {")
    son = css.index("\n}", bas)
    return dict(re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", css[bas:son]))


@pytest.mark.parametrize("ad", STILLER)
def test_koyu_temada_her_renk_tanimli(ad):
    """Açık temadaki her renk değişkeninin koyu temada karşılığı olmalı: biri
    unutulursa koyu sayfada beyaz bir kart ya da okunmayan bir yazı kalır."""
    css = (PUBLIC / ad).read_text(encoding="utf-8")
    acik = _degiskenler(css, ":root")
    koyu = _degiskenler(css, ':root[data-tema="koyu"]')
    renkler = {ad for ad, deger in acik.items() if RENK.search(deger)}
    assert renkler, "açık temada renk değişkeni bulunamadı"
    assert not sorted(renkler - set(koyu)), f"koyu temada eksik: {sorted(renkler - set(koyu))}"
    assert "color-scheme: dark" in css  # form öğeleri ve kaydırma çubuğu da koyu


@pytest.mark.parametrize("sayfa", SAYFALAR, ids=lambda p: p.name)
def test_tema_cizimden_once_yuklenir(sayfa):
    """Koyu temada beyaz yanıp sönme olmasın: tema.js <head>'de ve defer'siz
    çalışır; theme-color'dan sonra gelir, çünkü onu da günceller."""
    metin = sayfa.read_text(encoding="utf-8")
    bas = metin[: metin.index("</head>")]
    assert '<script src="/tema.js"></script>' in bas
    assert bas.index('name="theme-color"') < bas.index("/tema.js")
    assert (PUBLIC / "tema.js").is_file()


def test_bildirim_karti_tazelemede_yeniden_kurulmaz():
    """Komut bildirimi her tazelemede yeniden kuruluyordu: giriş animasyonu
    birkaç saniyede bir baştan oynuyor (kart saydamdan geliyor), ekran okuyucu
    da aynı bildirimi yeniden okuyordu. Kart komut kimliğiyle saklanır ve
    yalnız içeriği değişince yerinde güncellenir."""
    ciz = re.search(r"function bildirimleriCiz\(\) \{.*?\n  \}", PANO_JS, re.S).group(0)
    assert "temizle(liste)" not in ciz and "bildirimKartlari" in ciz
    guncelle = re.search(r"function bildirimKartiniGuncelle\(kart, k\) \{.*?\n  \}", PANO_JS, re.S)
    assert "kart.dataset.imza === imza" in guncelle.group(0)
