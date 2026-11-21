"""Sitenin gönderdiği e-postaların yerel önizlemesi (ağ yok, gönderim yok).

Her şablonu örnek veriyle HTML (ve yanında düz metin) dosyası olarak yazar;
tarayıcıda açıp bakabilirsiniz:

    python3 tests/eposta_onizleme.py /tmp/eposta-onizleme

tests/test_eposta.py de aynı işlevi çağırır: her şablonun yazıldığını ve
değerlerin kaçışlı olduğunu denetler.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import _pano  # noqa: E402

ORNEK_ADRES = "https://ornek-pano.vercel.app/pano"
# Örnek pazartesi: 23.11.2026 08:05 (Türkiye); özet 16-22.11.2026 haftasıdır
SIMDI = datetime(2026, 11, 23, 8, 5, tzinfo=_pano.TURKIYE_SAATI).timestamp()


def _ozet() -> dict:
    gece = _pano._pazartesi_gecesi(SIMDI)
    bas = gece - 7 * 86400
    sayilar = [3, 5, 2, 0, 4, 2, 1]
    return {
        "tesis": "Gebze fabrikası",
        "bas": bas,
        "gunler": [(_pano._turkiye_gunu(bas + i * 86400), n) for i, n in enumerate(sayilar)],
        "toplam": sum(sayilar),
        "onceki": 12,
        "tipler": [
            ("Baret yok", 7),
            ("Yelek yok", 4),
            ("Araç-yaya yakınlığı", 3),
            ("Yasak bölgeye giriş", 2),
            ("Forklift hızı", 1),
        ],
        "yerler": [
            ("Rampa", 6),
            ("Depo girişi", 4),
            ("Hat 2 - paketleme", 4),
            ("Kapı <3>", 2),
            ("Otopark", 1),
        ],
        "bekleyen": 4,
        "incelenen": 11,
        "yanlis_alarm": 2,
        "sistem": 1,
        "calisma": "Kasım 2026 çalışma oranı: %99,6 (kameralar %98,9; 530 saat ölçüldü).",
        "baglanti": "Bağlantı şu an canlı; son rapor 23.11.2026 08:04 (Türkiye saati).",
    }


def epostalar(adres: str = ORNEK_ADRES) -> dict[str, tuple[str, str, str]]:
    """Ad -> (konu, düz metin, HTML): sitenin gönderdiği her e-posta, örnek veriyle."""
    son_rapor = _pano._iso(SIMDI - 27 * 60)
    haber_yok = {"baglanti": "yok", "gecikme_sn": 27 * 60, "son_rapor": son_rapor}
    kapandi = {"baglanti": "kapandi", "gecikme_sn": 95 * 60, "son_rapor": son_rapor}
    return {
        "bekci-haber-yok": _pano._bekci_metni("Gebze fabrikası", haber_yok, adres),
        "bekci-program-kapali": _pano._bekci_metni("İzmir <depo>", kapandi, adres),
        "haftalik-ozet": _pano.haftalik_ozet_metni(_ozet(), adres),
        "deneme": _pano.deneme_epostasi_metni("isg.uzmani", "resend", SIMDI, adres),
    }


def onizlemeleri_yaz(klasor: Path, adres: str = ORNEK_ADRES) -> list[Path]:
    """Her e-postayı `klasor`e <ad>.html ve <ad>.txt olarak yazar; HTML yollarını döner."""
    klasor.mkdir(parents=True, exist_ok=True)
    yazilan = []
    for ad, (konu, metin, html_metni) in epostalar(adres).items():
        (klasor / f"{ad}.txt").write_text(f"Konu: {konu}\n\n{metin}", encoding="utf-8")
        yol = klasor / f"{ad}.html"
        yol.write_text(html_metni, encoding="utf-8")
        yazilan.append(yol)
    return yazilan


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Kullanım: python3 tests/eposta_onizleme.py <klasör>")
    for yol in onizlemeleri_yaz(Path(sys.argv[1])):
        print(yol)
