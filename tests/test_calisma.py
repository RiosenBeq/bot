"""Bu ayın çalışma oranı (raporun isteğe bağlı `calisma` alanı).

Program (sonra) raporuna şunu ekleyebilir:
    "calisma": {"ay": "2026-11", "sistem_yuzde": 99.6, "kamera_yuzde": 98.9,
                "olculen_saat": 312}
Site alanı süzer: ay YYYY-AA, yüzdeler 0-100 (bir ondalığa yuvarlanır), ölçülen
saat 0-744 tam sayı. Alan yoksa ya da bir parçası bozuksa anahtar hiç girmez ve
rapor bugünküyle birebir aynıdır. Sistem ekranında her rol tek satır görür.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import _pano
import pytest
from test_cekirdek import _rapor
from test_hesap import _hesap, _yaz_hesap
from test_uctan_uca import RAPOR, _cerez, _giris, _istek, _rapor_gonder, site  # noqa: F401

PUBLIC = Path(__file__).resolve().parents[1] / "public"
PANO_HTML = (PUBLIC / "pano.html").read_text(encoding="utf-8")
PANO_JS = (PUBLIC / "pano.js").read_text(encoding="utf-8")
CALISMA = {"ay": "2026-11", "sistem_yuzde": 99.6, "kamera_yuzde": 98.9, "olculen_saat": 312}
YOK = object()


def test_calisma_suzulur_ve_bir_ondaliga_yuvarlanir():
    ham = {**CALISMA, "sistem_yuzde": 99.64, "kamera_yuzde": 98.86, "fazla": "atılır"}
    assert _pano.rapor_temizle(_rapor(calisma=ham))["calisma"] == CALISMA
    uc = {"ay": "2026-02", "sistem_yuzde": 100, "kamera_yuzde": 0, "olculen_saat": 744}
    assert _pano.rapor_temizle(_rapor(calisma=uc))["calisma"] == {
        "ay": "2026-02",
        "sistem_yuzde": 100.0,
        "kamera_yuzde": 0.0,
        "olculen_saat": 744,
    }
    sifir = {**CALISMA, "olculen_saat": 0}
    assert _pano.rapor_temizle(_rapor(calisma=sifir))["calisma"]["olculen_saat"] == 0


@pytest.mark.parametrize(
    "bozuk",
    [
        YOK,
        None,
        "99.6",
        [],
        {},
        {**CALISMA, "ay": "2026-1"},
        {**CALISMA, "ay": "26-11"},
        {**CALISMA, "ay": "2026/11"},
        {**CALISMA, "ay": "2026-13"},
        {**CALISMA, "ay": "2026-00"},
        {**CALISMA, "ay": "٢٠٢٦-١١"},
        {**CALISMA, "ay": 202611},
        {**CALISMA, "sistem_yuzde": 100.1},
        {**CALISMA, "sistem_yuzde": -0.1},
        {**CALISMA, "sistem_yuzde": float("inf")},
        {**CALISMA, "kamera_yuzde": float("nan")},
        {**CALISMA, "kamera_yuzde": True},
        {**CALISMA, "kamera_yuzde": "98.9"},
        {**CALISMA, "olculen_saat": 745},
        {**CALISMA, "olculen_saat": -1},
        {**CALISMA, "olculen_saat": 312.5},
        {**CALISMA, "olculen_saat": True},
        {k: v for k, v in CALISMA.items() if k != "kamera_yuzde"},
    ],
)
def test_calisma_yoksa_ya_da_bozuksa_rapor_birebir_ayni(bozuk):
    bugunku = json.dumps(_pano.rapor_temizle(_rapor()), ensure_ascii=False)
    temiz = _pano.rapor_temizle(_rapor() if bozuk is YOK else _rapor(calisma=bozuk))
    assert "calisma" not in temiz
    assert json.dumps(temiz, ensure_ascii=False) == bugunku


def test_calisma_her_role_gider(site):  # noqa: F811
    assert _rapor_gonder(site, {**RAPOR, "calisma": CALISMA})[0] == 200
    _yaz_hesap(_pano.DEPO, _hesap("izci", rol="izleyici"))
    izci = _cerez(_giris(site, "dogru-sifre-1", ad="izci")[1])
    kod, _, govde = _istek(f"{site}/api/durum", basliklar={"Cookie": izci})
    assert kod == 200 and json.loads(govde)["rapor"]["calisma"] == CALISMA


def test_sistem_ekraninda_tek_satir_yalniz_varsa():
    gorunum = re.search(
        r'<div class="gorunum" data-gorunum="sistem" hidden>.*?<!-- YÖNETİM', PANO_HTML, re.S
    ).group(0)
    assert '<p id="calisma-satiri" class="kart-dipnot" hidden></p>' in gorunum
    ciz = re.search(r"function sistemiCiz\(veri\) \{.*?\n  \}", PANO_JS, re.S).group(0)
    assert "r.calisma" in ciz
    assert '$("calisma-satiri").textContent = ' in ciz and '$("calisma-satiri").hidden = ' in ciz


@pytest.mark.skipif(shutil.which("node") is None, reason="node yok")
def test_calisma_satirinin_metni():
    """pano.js'teki calismaMetni node ile çalıştırılır: Türkçe ondalık virgül."""
    islev = re.search(r"function calismaMetni\(c\) \{.*?\n  \}", PANO_JS, re.S).group(0)
    betik = (
        islev
        + "\nconsole.log(calismaMetni("
        + json.dumps(CALISMA)
        + "));\nconsole.log(calismaMetni({ay: '2026-11', sistem_yuzde: 100, kamera_yuzde: 0, "
        "olculen_saat: 744}));"
    )
    cikti = subprocess.run(
        ["node", "-e", betik], capture_output=True, text=True, timeout=20, check=True
    ).stdout.splitlines()
    assert cikti == [
        "Bu ay çalışma: %99,6 (kameralar %98,9; 312 saat ölçüldü)",
        "Bu ay çalışma: %100,0 (kameralar %0,0; 744 saat ölçüldü)",
    ]
