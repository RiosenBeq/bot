"""İki depo arası sözleşme (docs/19 §12): tests/sozlesme/*.json örnekleri.

Bu dosyalar iki depoda birebir aynıdır (DALSAN'dan kopyalanır); DÜZENLENMEZ.
Site tarafı: _komut_yuku çıktısı teslim edilen komut biçimiyle, rapor_temizle
yeni alanlarla, sonuclari_yaz sonuç biçimiyle ve rapor_kaydet'in cevabı
rapor-cevabi-kare.json ile uyar.
"""

import json
from pathlib import Path

import _pano

SOZLESME = Path(__file__).resolve().parent / "sozlesme"


def _yukle(ad: str) -> dict:
    return json.loads((SOZLESME / ad).read_text(encoding="utf-8"))


def test_teslim_edilen_komutlar_alan_alan_okunur():
    """Her türden komut (docs/19 §3.7): _komut_yuku kalan_sn dışındaki her alanı
    aynen üretir; başka alan geçmez."""
    for komut in _yukle("komutlar.json")["komutlar"]:
        beklenen = {k: v for k, v in komut.items() if k != "kalan_sn"}
        assert _pano._komut_yuku(json.dumps(komut)) == beklenen


def test_bilinmeyen_tur_ve_rol_komutu_okunmaz():
    """Sözleşmedeki reddedilen örneklerden türü/rolü site de tanımaz."""
    for oge in _yukle("komutlar.json")["reddedilenler"]:
        komut = oge["komut"]
        yuk = _pano._komut_yuku(json.dumps(komut))
        if oge["neden"] == "bilinmeyen tür":
            assert yuk is None
        elif oge["neden"] == "bilinmeyen rol":
            # tür tanınır ama rol boşa düşer (teslimde yetkisiz sayılır)
            assert yuk is not None and yuk["kim"]["rol"] == ""


def test_yeni_rapor_yeni_alanlarla_temizlenir():
    rapor = _yukle("rapor.json")["rapor"]
    temiz = _pano.rapor_temizle(rapor)
    assert temiz["program"]["yapi"]["commit"] == "0123456789abcdef0123456789abcdef01234567"
    assert temiz["program"]["yapi"]["calistirma"] == 123
    durumlar = [o["durum"] for o in temiz["son_olaylar"]]
    assert durumlar == ["new", "reviewed", ""]  # sistem olayında durum yok
    assert temiz["mudahale"]["isler"] == ["anons", "ses_dene", "olay_incele"]
    assert temiz["yonetim"]["acik"] is True
    assert temiz["yonetim"]["isler"] == ["teshis", "yeniden_baslat", "guncelle"]
    assert temiz["yonetim"]["kurulum"] == "paket"
    assert temiz["yonetim"]["yeniden_baslatma"]["mumkun"] is True
    assert temiz["yonetim"]["guncelleme"]["mumkun"] is False
    assert temiz["kapanis_sebebi"] == ""


def test_eski_rapor_guvenli_varsayilanlara_duser():
    rapor = _yukle("rapor-eski.json")["rapor"]
    temiz = _pano.rapor_temizle(rapor)
    assert temiz["program"]["yapi"] == {"commit": "", "tarih": "", "calistirma": 0}
    # son_olaylar[].durum yok -> "" (inceleme düğmesi çıkmaz)
    assert all(o["durum"] == "" for o in temiz["son_olaylar"])
    # mudahale.acik True ama isler gelmez -> bugünkü iki iş varsayılır
    assert temiz["mudahale"]["isler"] == ["anons", "ses_dene"]
    # yonetim hiç gelmez -> her şey kapalı
    assert temiz["yonetim"] == {
        "acik": False,
        "isler": [],
        "kurulum": "",
        "yeniden_baslatma": {"mumkun": False, "sebep": ""},
        "guncelleme": {"mumkun": False, "sebep": ""},
        # 18.11.2026: bilgisayarı yeniden başlatmanın kapısı da kapalı (DALSAN docs/19 §4.9)
        "bilgisayar_yeniden_baslatma": {"mumkun": False, "sebep": ""},
        # 19.11.2026: otomatik güncelleme satırı boş (Yönetim kartında çıkmaz)
        "otomatik_guncelleme": "",
    }


def test_sonuclar_ornegi_yazilir_ve_onaylanir():
    """sonuclar.json'daki id'ler için komut kaydı kurulur; sonuçlar yazılır ve
    hepsi 'alinan'da döner (docs/19 §3.7)."""
    ornek = _yukle("sonuclar.json")["sonuclar"]
    depo = _pano.BellekDepo()
    for s in ornek:
        kayit = {"id": s["id"], "tur": "teshis", "durum": "iletildi", "guncellendi": 0}
        depo.boru_hatti([["SET", _pano.KOMUT_KAYIT_ONEKI + s["id"], json.dumps(kayit)]])
    alinan = _pano.sonuclari_yaz(depo, ornek, 1000)
    assert set(alinan) == {s["id"] for s in ornek}
    # Teşhis ek metni süzülerek kayda yazılır (adres maskeli)
    tanili = next(s for s in ornek if "ek" in s)
    (ham,) = depo.al_coklu([_pano.KOMUT_KAYIT_ONEKI + tanili["id"]])
    yazilan = json.loads(ham)
    assert "(adres)" in yazilan["ek"]


def test_komut_cevabi_nonce_ve_alinan_tasir():
    cevap = _yukle("komut-cevabi.json")["cevap"]
    assert set(cevap) >= {"tamam", "nonce", "alinan", "komutlar", "hizli"}
    istek = _yukle("komut-sorusu.json")["istek"]
    assert cevap["nonce"] == istek["nonce"]  # cevap istekteki nonce'u taşır


def test_rapor_cevabi_kamera_listesini_ornekteki_bicimde_verir():
    """rapor-cevabi-kare.json (17.11.2026): Kameralar ekranında 1 ve 3 görünüyorken
    cevabın kare bloğu örnekle birebir aynıdır; listesiz bakan (eski pano) varken
    eski sitenin cevabıyla aynıdır. Öbür anahtarlar örnekle aynı adları taşır."""
    ornek = _yukle("rapor-cevabi-kare.json")
    rapor = _yukle("rapor.json")["rapor"]
    ilk = rapor["kameralar"][0]
    rapor["kameralar"] = [dict(ilk, id=kimlik) for kimlik in (1, 2, 3)]
    temiz = _pano.rapor_temizle(rapor)
    for anahtar, secim in (("cevap", [1, 3]), ("eski_site", None)):
        depo = _pano.BellekDepo(lambda: 1000.0)
        _pano.kare_zamanlari(depo, temiz, secim, 1000.0)
        cevap = {"tamam": True, "alindi": "", **_pano.rapor_kaydet(depo, temiz, 1000.0)}
        assert set(cevap) == set(ornek[anahtar]), anahtar
        assert cevap["kare"] == ornek[anahtar]["kare"], anahtar
        assert set(cevap["komut"]) == set(ornek[anahtar]["komut"])
        assert set(cevap["foto"]) == set(ornek[anahtar]["foto"])


def test_ekran_karti_ornegi_suzgecten_aynen_gecer():
    """rapor-ekran-karti.json (17.11.2026): programın ürettiği seçilen donanım ve
    kart notu (kart kullanılıyor, bırakıldı, işlemci seçili) süzgeçten bozulmadan
    geçer; bilgisayar bloğunun öteki alanları da örnekteki gibidir."""
    ornek = _yukle("rapor-ekran-karti.json")
    rapor = _yukle("rapor.json")["rapor"]
    temiz = _pano.rapor_temizle({**rapor, "bilgisayar": ornek["kullaniliyor"]})["bilgisayar"]
    for alan, deger in ornek["kullaniliyor"].items():
        assert temiz[alan] == deger, alan
    for ad in ("birakildi", "islemci"):
        bilgi = {**rapor["bilgisayar"], **ornek[ad]}
        temiz = _pano.rapor_temizle({**rapor, "bilgisayar": bilgi})["bilgisayar"]
        for alan in ("cikarim", "cikarim_secimi", "cikarim_notu"):
            assert temiz[alan] == ornek[ad][alan], (ad, alan)


def test_eski_programin_bilgisayari_kart_alanlarini_bos_sayar():
    """rapor.json ve rapor-eski.json'da iki alan yoktur: boş gelir (satır çıkmaz),
    öteki alanlar bugünkü gibi."""
    for ad in ("rapor.json", "rapor-eski.json"):
        rapor = _yukle(ad)["rapor"]
        if "bilgisayar" not in rapor:
            continue
        temiz = _pano.rapor_temizle(rapor)["bilgisayar"]
        assert temiz["cikarim_secimi"] == "" and temiz["cikarim_notu"] == ""
        assert temiz["cikarim"] == rapor["bilgisayar"]["cikarim"]


# ------------------------------------------ bilgisayarı yeniden başlatma (18.11.2026)


def test_bilgisayar_komutu_turunden_baska_alan_tasimaz():
    """bilgisayar-yeniden-baslatma.json: teslim edilen komut tür, kimlik, süre ve
    istek sahibinden ibarettir; programa komut satırına girecek değer gitmez."""
    ornek = _yukle("bilgisayar-yeniden-baslatma.json")
    komut = ornek["komut"]
    beklenen = {k: v for k, v in komut.items() if k != "kalan_sn"}
    assert _pano._komut_yuku(json.dumps(komut)) == beklenen
    assert set(beklenen) == {"id", "tur", "son_gecerlilik", "kim"}


def test_bilgisayar_yonetim_ornegi_temizlenince_aynen_kalir():
    ornek = _yukle("bilgisayar-yeniden-baslatma.json")
    rapor = _yukle("rapor.json")["rapor"]
    temiz = _pano.rapor_temizle({**rapor, "yonetim": ornek["yonetim"]})
    # Bu örneğin programı otomatik güncelleme satırını göndermez: boş gelir (19.11.2026)
    assert temiz["yonetim"] == {**ornek["yonetim"], "otomatik_guncelleme": ""}


def test_bilgisayar_ret_sebepleri_aynen_gosterilir():
    """Programın her ret metni rapordan değişmeden geçer ve istek reddedilince
    yöneticiye aynen söylenir (409 yapilamaz)."""
    ornek = _yukle("bilgisayar-yeniden-baslatma.json")
    rapor = _yukle("rapor.json")["rapor"]
    for sebep in ornek["ret_sebepleri"]:
        yonetim = {
            **ornek["yonetim"],
            "bilgisayar_yeniden_baslatma": {"mumkun": False, "sebep": sebep},
        }
        temiz = _pano.rapor_temizle({**rapor, "yonetim": yonetim})
        assert temiz["yonetim"]["bilgisayar_yeniden_baslatma"]["sebep"] == sebep
        veri = {"baglanti": "canli", "rapor": temiz}
        try:
            _pano.komut_olustur(
                _pano.BellekDepo(),
                veri,
                {"tur": "bilgisayari_yeniden_baslat"},
                1000,
                {"ad": "kurucu", "rol": "yonetici"},
            )
        except _pano.PanoHatasi as hata:
            assert (hata.kod, hata.hata, hata.mesaj) == (409, "yapilamaz", sebep)
        else:
            raise AssertionError("yapılamaz denen iş kuyruğa girdi")


def test_bilgisayar_sonuclari_yazilir_ve_onaylanir():
    ornek = _yukle("bilgisayar-yeniden-baslatma.json")["sonuclar"]
    depo = _pano.BellekDepo()
    for kimlik in {s["id"] for s in ornek}:
        kayit = {
            "id": kimlik,
            "tur": "bilgisayari_yeniden_baslat",
            "durum": "iletildi",
            "guncellendi": 0,
        }
        depo.boru_hatti([["SET", _pano.KOMUT_KAYIT_ONEKI + kimlik, json.dumps(kayit)]])
    alinan = _pano.sonuclari_yaz(depo, ornek, 1000)
    assert set(alinan) == {s["id"] for s in ornek}
    for s in ornek[1:]:  # suruyor'dan sonra yapildi; ikinci kayıt hata
        (ham,) = depo.al_coklu([_pano.KOMUT_KAYIT_ONEKI + s["id"]])
        yazilan = json.loads(ham)
        assert (yazilan["durum"], yazilan["mesaj"]) == (s["durum"], s["mesaj"])


def test_otomatik_guncelleme_satiri_suzgecten_bozulmadan_gecer():
    """rapor-otomatik-guncelleme.json (19.11.2026, G46): programın gönderdiği
    otomatik güncelleme satırı (dosya yok, son sonuç, maskelenmiş adres ve yol,
    gizlenmiş ayrıntı, 200 karakterde kesilmiş, kapalı) sitenin süzgecinden
    değişmeden geçer; yönetim bloğunun öteki alanları da değişmez."""
    ornek = _yukle("rapor-otomatik-guncelleme.json")
    rapor = _yukle("rapor.json")["rapor"]
    # Yönetim bloğunun bütün alanları bilgisayar-yeniden-baslatma.json'dadır
    tam_blok = _yukle("bilgisayar-yeniden-baslatma.json")["yonetim"]
    assert set(ornek["durumlar"]) == {"ilk", "son_sonuc", "maskeli", "gizli", "uzun", "kapali"}
    for ad, durum in ornek["durumlar"].items():
        metin = durum["otomatik_guncelleme"]
        yonetim = {**tam_blok, "otomatik_guncelleme": metin}
        temiz = _pano.rapor_temizle({**rapor, "yonetim": yonetim})["yonetim"]
        assert temiz == yonetim, ad


def test_eski_programin_yonetimi_otomatik_guncelleme_satirini_bos_sayar():
    """rapor.json'un programı alanı göndermez: boş gelir, Yönetim kartında satır
    çıkmaz. Metin olmayan değer de boş sayılır; uzun metin 200'de kesilir, adres
    maskelenir."""
    rapor = _yukle("rapor.json")["rapor"]
    assert "otomatik_guncelleme" not in rapor["yonetim"]
    assert _pano.rapor_temizle(rapor)["yonetim"]["otomatik_guncelleme"] == ""
    for bozuk in (None, 12, ["açık"], {"metin": "açık"}):
        yonetim = {**rapor["yonetim"], "otomatik_guncelleme": bozuk}
        temiz = _pano.rapor_temizle({**rapor, "yonetim": yonetim})["yonetim"]
        assert temiz["otomatik_guncelleme"] == "", bozuk
    yonetim = {
        **rapor["yonetim"],
        "otomatik_guncelleme": "açık;\nson: http://10.0.0.5/x " + "a" * 400,
    }
    metin = _pano.rapor_temizle({**rapor, "yonetim": yonetim})["yonetim"]["otomatik_guncelleme"]
    assert len(metin) == 200 and "\n" not in metin
    assert "10.0.0.5" not in metin and "(adres)" in metin
