"""UpstashDepo'nun REST isteklerini sahte bir Upstash sunucusuyla dener.

Sahte sunucu Upstash'in belgelediği biçimi uygular: komut JSON dizisi olarak
adresin köküne, birden çok komut /pipeline'a gider; cevap {"result": ...} ya da
{"error": "..."} olur. Jeton yanlışsa 401 döner.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import _pano
import pytest

JETON = "gizli-jeton"


class SahteUpstash(BaseHTTPRequestHandler):
    # Komutları sitenin bellek deposu çalıştırır (Redis'i taklit eder); burada
    # sınanan, UpstashDepo'nun istek ve cevap biçimidir.
    depo = _pano.BellekDepo()
    istekler: list = []

    def log_message(self, *args):
        return

    def _komut(self, parcalar):
        try:
            return {"result": self.depo.komut(*parcalar)}
        except _pano.DepoHatasi as hata:
            return {"error": str(hata)}

    def do_POST(self):  # noqa: N802
        govde = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.istekler.append((self.path, govde))
        if self.headers.get("Authorization") != f"Bearer {JETON}":
            cevap, kod = {"error": "WRONGPASS invalid password"}, 401
        elif self.path == "/pipeline":
            cevap, kod = [self._komut(k) for k in govde], 200
        else:
            cevap = self._komut(govde)
            kod = 400 if "error" in cevap else 200
        veri = json.dumps(cevap).encode()
        self.send_response(kod)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(veri)))
        self.end_headers()
        self.wfile.write(veri)


@pytest.fixture
def upstash():
    SahteUpstash.depo = _pano.BellekDepo()
    SahteUpstash.istekler = []
    sunucu = ThreadingHTTPServer(("127.0.0.1", 0), SahteUpstash)
    threading.Thread(target=sunucu.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{sunucu.server_address[1]}"
    sunucu.shutdown()
    sunucu.server_close()


def test_yaz_ve_oku(upstash):
    depo = _pano.UpstashDepo(upstash + "/", JETON)
    depo.yaz_coklu([("a", "1", 60), ("b", "2", None)])
    assert depo.al_coklu(["a", "b", "c"]) == ["1", "2", None]
    yol, govde = SahteUpstash.istekler[0]
    assert yol == "/pipeline"
    assert govde == [["SET", "a", "1", "EX", "60"], ["SET", "b", "2"]]


def test_sayac_ilk_denemede_sureli_kurulur_sonra_artar(upstash):
    depo = _pano.UpstashDepo(upstash, JETON)
    assert depo.say("s", 300) == 1
    assert depo.say("s", 300) == 2
    assert SahteUpstash.istekler[0][1] == [["SET", "s", "0", "EX", "300", "NX"], ["INCR", "s"]]
    depo.sil("s")
    assert depo.al_coklu(["s"]) == [None]


def test_yanlis_jeton_depo_hatasi_olur_jeton_mesaja_girmez(upstash):
    depo = _pano.UpstashDepo(upstash, "yanlis-jeton")
    with pytest.raises(_pano.DepoHatasi) as hata:
        depo.al_coklu(["a"])
    assert "401" in str(hata.value)
    assert "yanlis-jeton" not in str(hata.value)


def test_ulasilamayan_depo_depo_hatasi_olur():
    depo = _pano.UpstashDepo("http://127.0.0.1:9", JETON, zaman_asimi=1)
    with pytest.raises(_pano.DepoHatasi):
        depo.al_coklu(["a"])


def test_liste_komutlari_ve_hata(upstash):
    depo = _pano.UpstashDepo(upstash, JETON)
    sonuc = depo.boru_hatti([["RPUSH", "l", "a", "b"], ["LPOP", "l", "5"], ["LLEN", "l"]])
    assert sonuc == [2, ["a", "b"], 0]
    depo.komut("RPUSH", "l", "x")
    with pytest.raises(_pano.DepoHatasi, match="WRONGTYPE"):
        depo.komut("GET", "l")
