"""Yönetici görünümünün alanları: 14 gün, son 7 gün, yerler ve kurulu bilgisayar.

Fabrika programı bu alanları henüz göndermeyebilir (bağlama adımı ayrı):
gelmeyen alan boş döner ve pano o kartı gizler. Gelen alan tip ve uzunluk
denetiminden geçer; bilinmeyen alan (oturumdaki kullanıcı gibi) depoya girmez.
Bilgisayarın IP adresi fabrika içi kullanım kararıyla (24.10.2026) gelir.
"""

import _pano
from test_uctan_uca import RAPOR

BILGISAYAR = {
    "ad": "Gebze fabrikası",
    "bilgisayar_adi": "ISG-PC-01",
    "isletim_sistemi": "Windows 11 Pro",
    "islemci": "Intel Core i7-13700",
    "cekirdek": 16,
    "bellek_gb": 31.7,
    "ekran_karti": "NVIDIA GeForce RTX 4060",
    "cikarim": "Ekran kartı (DirectML)",
    "disk_toplam_gb": 953.9,
    "kurulum_turu": "Windows uygulaması",
    "kurulum_tarihi": "2026-09-23T09:00:00+03:00",
    "acilis": "2026-10-23T07:00:00Z",
}


def test_alanlar_gelmezse_bos_doner():
    temiz = _pano.rapor_temizle(RAPOR)
    assert temiz["gunluk"] is None
    assert temiz["yedi_gun"] is None
    assert temiz["yerler"] == []
    assert temiz["bilgisayar"] is None


def test_alanlar_suzulur():
    temiz = _pano.rapor_temizle(
        {
            **RAPOR,
            "gunluk": [3, 1, 0, 2, 5, 1, 0, 4, 2, 9, 1, 0, 3, 7],
            "yedi_gun": {"ihlal": 20, "incelenen": 99, "yanlis_alarm": 2},
            "yerler": [{"ad": "Forklift Yolu", "bolum": "Üretim", "sayi": 21, "ip": "10.0.0.5"}],
            "bilgisayar": {
                **BILGISAYAR,
                "ip": ["192.168.1.20", "fe80::1", "değil-bir-adres", 7],
                "kullanici": "ahmet",
            },
        }
    )
    assert temiz["gunluk"][-1] == 7 and len(temiz["gunluk"]) == 14
    # İncelenen ihlalden çok olamaz
    assert temiz["yedi_gun"] == {"ihlal": 20, "incelenen": 20, "yanlis_alarm": 2}
    assert temiz["yerler"] == [{"ad": "Forklift Yolu", "bolum": "Üretim", "sayi": 21}]
    bilgi = temiz["bilgisayar"]
    assert "kullanici" not in bilgi
    assert bilgi["ip"] == ["192.168.1.20", "fe80::1"]
    assert bilgi["bilgisayar_adi"] == "ISG-PC-01"
    assert bilgi["cekirdek"] == 16 and bilgi["bellek_gb"] == 31.7
    assert bilgi["kurulum_tarihi"] == "2026-09-23T06:00:00+00:00"
    assert bilgi["acilis"] == "2026-10-23T07:00:00+00:00"


def test_bozuk_alanlar_reddedilir():
    temiz = _pano.rapor_temizle(
        {
            **RAPOR,
            "gunluk": [1, 2, 3],  # 14 gün değil
            "yedi_gun": "çok",
            "yerler": "Forklift Yolu",
            "bilgisayar": {"cekirdek": True, "bellek_gb": "32", "acilis": "dün"},
        }
    )
    assert temiz["gunluk"] is None
    assert temiz["yedi_gun"] is None
    assert temiz["yerler"] == []
    assert temiz["bilgisayar"] is None  # hiçbir alan geçerli değil
