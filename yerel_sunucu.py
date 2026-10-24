"""Siteyi Vercel'e göndermeden bu bilgisayarda denemek için.

    python3 yerel_sunucu.py            -> http://127.0.0.1:3000
    python3 yerel_sunucu.py 8000       -> başka bir port

Vercel'in yaptığını taklit eder: /api/<ad> isteğini api/<ad>.py'deki
`handler`'a verir, öbür adresleri public/ klasöründen sunar (".html" yazmadan:
/pano -> public/pano.html) ve vercel.json'daki güvenlik başlıklarını ekler.
Upstash yerine bellekte bir depo kullanır: kapatınca her şey silinir.

Şifre ve anahtar ortam değişkenlerinden okunur; tanımlı değilse aşağıdaki
DENEME değerleri kullanılır ve açılışta ekrana yazılır. Bunlar yalnız bu
bilgisayardaki deneme içindir, Vercel'de KULLANILMAZ.
"""

from __future__ import annotations

import importlib.util
import json
import mimetypes
import os
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib.parse import urlsplit

KOK = Path(__file__).resolve().parent
API = KOK / "api"
PUBLIC = (KOK / "public").resolve()

sys.path.insert(0, str(API))

import _pano  # noqa: E402

DENEME_SIFRESI = "yerel-deneme-sifresi"
DENEME_ANAHTARI = "yerel-deneme-anahtari-yalniz-bu-bilgisayar-icin"

mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/svg+xml", ".svg")


def _api_modulleri() -> dict[str, ModuleType]:
    """api/ altındaki her dosya bir adres (alt çizgiyle başlayanlar hariç)."""
    moduller = {}
    for dosya in sorted(API.glob("*.py")):
        if dosya.name.startswith("_"):
            continue
        tanim = importlib.util.spec_from_file_location(f"api_{dosya.stem}", dosya)
        modul = importlib.util.module_from_spec(tanim)
        tanim.loader.exec_module(modul)
        moduller[dosya.stem] = modul
    return moduller


def _ortak_basliklar() -> list[tuple[str, str]]:
    """vercel.json'da bütün adreslere ("/(.*)") verilen başlıklar."""
    ayar = json.loads((KOK / "vercel.json").read_text(encoding="utf-8"))
    basliklar = []
    for kural in ayar.get("headers", []):
        if kural.get("source") == "/(.*)":
            basliklar += [(b["key"], b["value"]) for b in kural.get("headers", [])]
    return basliklar


API_MODULLERI = _api_modulleri()
ORTAK_BASLIKLAR = _ortak_basliklar()


class YerelIsleyici(_pano.Isleyici):
    def _yonlendir(self, yontem: str) -> None:
        yol = urlsplit(self.path).path
        if yol.startswith("/api/"):
            modul = API_MODULLERI.get(yol[len("/api/") :])
            if modul is None:
                self.yanit(404, {"hata": "yok", "mesaj": "Böyle bir adres yok."})
                return
            # Vercel'deki gibi: dosyanın handler sınıfındaki yöntem çalışır
            getattr(modul.handler, f"do_{yontem}")(self)
            return
        if yontem not in ("GET", "HEAD"):
            self._izin_yok()
            return
        self._statik(yol)

    def end_headers(self) -> None:
        for anahtar, deger in ORTAK_BASLIKLAR:
            self.send_header(anahtar, deger)
        super().end_headers()

    def _statik(self, yol: str) -> None:
        hedef = (PUBLIC / yol.lstrip("/")).resolve()
        if not hedef.is_relative_to(PUBLIC):
            hedef = PUBLIC / "yok"
        if hedef.is_dir():
            hedef = hedef / "index.html"
        if not hedef.is_file() and not hedef.suffix:
            hedef = hedef.with_suffix(".html")  # vercel.json: cleanUrls
        kod = 200
        if not hedef.is_file():
            # Vercel gibi: bulunamayan sayfada public/404.html, durum 404
            hedef, kod = PUBLIC / "404.html", 404
        veri = hedef.read_bytes()
        tur = mimetypes.guess_type(hedef.name)[0] or "application/octet-stream"
        if tur.startswith("text/") or tur in ("application/javascript", "image/svg+xml"):
            tur += "; charset=utf-8"
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(veri)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(veri)

    def do_GET(self) -> None:  # noqa: N802
        self._yonlendir("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._yonlendir("HEAD")

    def do_POST(self) -> None:  # noqa: N802
        self._yonlendir("POST")


def sunucu_olustur(port: int = 3000, depo: _pano.BellekDepo | None = None) -> ThreadingHTTPServer:
    """Sunucuyu kurar (başlatmaz). Testler port=0 ile boş bir port alır."""
    _pano.DEPO = depo or _pano.BellekDepo()
    return ThreadingHTTPServer(("127.0.0.1", port), YerelIsleyici)


def arka_planda_baslat(sunucu: ThreadingHTTPServer) -> threading.Thread:
    is_parcacigi = threading.Thread(target=sunucu.serve_forever, daemon=True)
    is_parcacigi.start()
    return is_parcacigi


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    os.environ.setdefault("PANO_SIFRESI", DENEME_SIFRESI)
    os.environ.setdefault("RAPOR_ANAHTARI", DENEME_ANAHTARI)
    sunucu = sunucu_olustur(port)
    print(f"Site açık: http://127.0.0.1:{port}  (durdurmak için Ctrl+C)")
    print(f"  Pano şifresi : {os.environ['PANO_SIFRESI']}")
    print(f"  Rapor anahtarı: {os.environ['RAPOR_ANAHTARI']}")
    print(f"  Fabrika programında uzak pano adresine http://127.0.0.1:{port} yazın.")
    try:
        sunucu.serve_forever()
    except KeyboardInterrupt:
        print("\nKapatıldı.")


if __name__ == "__main__":
    main()
