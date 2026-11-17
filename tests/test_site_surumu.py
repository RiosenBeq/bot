"""Site güncellenince açık kalmış pano kendini yeniler (17.11.2026).

Vercel statik dosyaları her yüklemede yeniden doğrular; ama açık bırakılmış bir
sekme (duvardaki ekran, telefonda ana ekrana eklenmiş uygulama) eski pano.js ile
çalışmaya devam eder. Eski betik yeni sunucuyla konuşunca davranış sessizce
bozulabilir (ör. Kameralar ekranında görünen kutucukları bildirmeyen eski pano,
fabrikaya bütün kameraları gönderttirir). Site her cevapta kendi sürümünü söyler;
pano ilk gördüğü sürüm değişince sayfayı yeniler.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import _pano
import pytest
from test_uctan_uca import _cerez, _giris, _istek, site  # noqa: F401

PANO_JS = (Path(__file__).resolve().parents[1] / "public" / "pano.js").read_text(encoding="utf-8")


def test_durum_cevabi_sitenin_surumunu_tasir(site, monkeypatch):  # noqa: F811
    cerez = _cerez(_giris(site)[1])
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "0123456789abcdef0123456789abcdef01234567")
    govde = json.loads(_istek(f"{site}/api/durum", basliklar={"Cookie": cerez})[2])
    assert govde["surum"] == "0123456789ab"


@pytest.mark.parametrize("ham", ["", "yerel", "0123", "<script>", "g" * 40])
def test_surum_yoksa_ya_da_bozuksa_bos(monkeypatch, ham):
    """Vercel dışında (yerel sunucu, test) sürüm yoktur: alan boş gider ve pano
    hiçbir şey yapmaz."""
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", ham)
    assert _pano.site_surumu() == ""


def test_pano_surum_degisince_yeniler_ama_donguye_girmez():
    govde = PANO_JS[PANO_JS.index("  function surumuDenetle(") :]
    govde = govde[: govde.index("\n  }\n")]
    # İlk görülen sürüm hatırlanır; boş sürüm (yerel) hiçbir şey yapmaz
    assert "if (siteSurumu === null)" in govde
    assert "yenilemeGuvenli()" in govde and "location.reload()" in govde
    # Art arda yenileme olmaz: son yenilemenin anı oturum deposunda tutulur
    assert "SURUM_YENILEME_ARASI_MS" in govde and "sessionStorage" in govde
    cagri = PANO_JS[PANO_JS.index("  async function yukle() {") :]
    assert "if (surumuDenetle(veri.surum)) return;" in cagri[: cagri.index("\n  }\n")]


@pytest.mark.skipif(shutil.which("node") is None, reason="node yok")
def test_yazarken_ya_da_pencere_acikken_sayfa_yenilenmez():
    """Onay şifresi yazılırken ya da bir pencere (fotoğraf, onay) açıkken sayfa
    yenilenmez; bir sonraki okumada yeniden bakılır."""
    islev = re.search(r"function yenilemeGuvenli\(\) \{.*?\n  \}", PANO_JS, re.S).group(0)
    betik = (
        """
let pencere = null;
let odak = null;
const document = {
  querySelector: (s) => (s === "dialog[open]" ? pencere : null),
  get activeElement() { return odak; },
};
"""
        + islev
        + """
const sonuc = [];
sonuc.push(yenilemeGuvenli());
odak = { tagName: "BUTTON" }; sonuc.push(yenilemeGuvenli());
odak = { tagName: "INPUT" }; sonuc.push(yenilemeGuvenli());
odak = { tagName: "TEXTAREA" }; sonuc.push(yenilemeGuvenli());
odak = { tagName: "SELECT" }; sonuc.push(yenilemeGuvenli());
odak = null; pencere = {}; sonuc.push(yenilemeGuvenli());
console.log(JSON.stringify(sonuc));
"""
    )
    cikti = subprocess.run(
        ["node", "-e", betik], capture_output=True, text=True, timeout=20, check=True
    ).stdout
    assert json.loads(cikti) == [True, True, False, False, False, False]
