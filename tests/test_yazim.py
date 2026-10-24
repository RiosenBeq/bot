"""Yalnız düz tire: uzun çizgi (U+2014), orta çizgi (U+2013) ve eksi işareti
(U+2212) hiçbir dosyada yok (DALSAN kuralı, CLAUDE.md §7)."""

from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
YASAK = {chr(0x2014): "uzun çizgi", chr(0x2013): "orta çizgi", chr(0x2212): "eksi işareti"}
UZANTILAR = {".py", ".md", ".html", ".css", ".js", ".json", ".toml", ".txt"}


def test_tipografik_cizgi_yok():
    bulunan = []
    for dosya in sorted(KOK.rglob("*")):
        if any(parca in {".git", ".venv", "__pycache__"} for parca in dosya.parts):
            continue
        if not dosya.is_file() or dosya.suffix not in UZANTILAR:
            continue
        for sira, satir in enumerate(dosya.read_text(encoding="utf-8").splitlines(), 1):
            for harf, ad in YASAK.items():
                if harf in satir:
                    bulunan.append(f"{dosya.relative_to(KOK)}:{sira}: {ad}")
    assert not bulunan, "\n".join(bulunan)
