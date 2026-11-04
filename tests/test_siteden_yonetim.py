"""Siteden yönetim ön yüzü: giriş kullanıcı adı, roller, yönetim ve kullanıcı
ekranları, kurucu/önizleme/şifre bantları ve docs/19 §3.9 ile O10'daki yetkili
Türkçe metinler sayfada gerçekten var mı. Yalnız ön yüz dosyalarına bakar;
arka uç (api/*) sözleşmesi öteki testlerdedir."""

from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1] / "public"
PANO_HTML = (PUBLIC / "pano.html").read_text(encoding="utf-8")
PANO_JS = (PUBLIC / "pano.js").read_text(encoding="utf-8")
INDEX_HTML = (PUBLIC / "index.html").read_text(encoding="utf-8")


def test_giriste_kullanici_adi_alani_var():
    # Giriş artık kullanıcı adı + şifre ister (docs/19 §3.2, §3.9)
    assert 'id="ad"' in PANO_HTML
    assert 'autocomplete="username"' in PANO_HTML
    assert "{ ad: ad, sifre: sifre }" in PANO_JS
    # Kurulum ekranı ilk girişteki kurucu hesabını anlatır (docs/19 §3.9)
    assert "kullanıcı adı <code>kurucu</code>" in PANO_HTML


def test_yeni_simgeler_spritede_tanimli():
    # docs/19 §3.9: i-kullanicilar, i-anahtar, i-guc, i-indir, i-teshis
    for simge in ("i-kullanicilar", "i-anahtar", "i-guc", "i-indir", "i-teshis"):
        assert f'<symbol id="{simge}"' in PANO_HTML, simge


def test_fabrika_grubu_rol_menuleri():
    # Kenar çubuğunda Müdahale, Yönetim, Kullanıcılar (rolle gizlenir), Sistem
    for gorunum in ("mudahale", "yonetim", "kullanicilar"):
        assert f'data-gorunum="{gorunum}"' in PANO_HTML, gorunum
    # Telefon sekme çubuğu 5 sekme kalır (Yönetim/Kullanıcılar sekme DEĞİL)
    assert PANO_HTML.count('class="sekme"') == 5


def test_yonetim_ekrani_ogeleri():
    for kimlik in (
        "yonetim-durumu",
        "yonetim-program",
        "teshis-dugmesi",
        "yeniden-dugmesi",
        "yeniden-onayi",
        "yeniden-sifre",
        "yeniden-sebep",
        "guncelle-dugmesi",
        "guncelle-onayi",
        "guncelle-sifre",
        "guncelle-sebep",
        "yonetim-komutlar",
    ):
        assert f'id="{kimlik}"' in PANO_HTML, kimlik
    # Ağır işlerde onay kutusunda şifre alanı (docs/19 §3.4, O10 S9)
    assert "Onaylamak için şifreniz" in PANO_HTML
    assert "Onaylamak için şifrenizi yazın." in PANO_JS


def test_kullanicilar_ekrani_ogeleri():
    for kimlik in (
        "kullanici-listesi",
        "kullanici-formu",
        "yeni-ad",
        "yeni-rol",
        "yeni-ilk-sifre",
        "yeni-onay-sifresi",
        "kayit-tablosu",
    ):
        assert f'id="{kimlik}"' in PANO_HTML, kimlik


def test_hesabim_ve_bantlar():
    for kimlik in (
        "hesabim-formu",
        "hesabim-kurucu",
        "hesabim-ad",
        "hesabim-rol",
        "onizleme-bandi",
        "kurucu-bandi",
        "sifre-bandi",
        "fabrika-yonetim-karti",
    ):
        assert f'id="{kimlik}"' in PANO_HTML, kimlik


def test_o10_rol_aciklamalari():
    # Ekleme ve rol formundaki rol açıklamaları (docs/19 §1, O10)
    assert "durumu, olayları ve kamera görüntülerini görür; hiçbir şey değiştiremez" in PANO_JS
    assert "hazır anons çaldırır, hoparlörü dener" in PANO_JS
    assert "programı yeniden başlatır, günceller, teşhis alır" in PANO_JS


def test_o10_onay_metinleri():
    # Yeniden başlat ve güncelle onay metinleri (O10)
    assert "1-3 dakika kameralar izlenmez ve uyarı çıkmaz" in PANO_HTML
    # 2. tasarım: güncelleme kartının metni onayı da anlatır (Pano v2)
    assert "önce veritabanı yedeklenir, açılmazsa eski sürüme dönülür" in PANO_HTML


def test_o10_kurucu_metinleri():
    # Kurucu bandı (docs/19 §3.1) ve Hesabım kurucu metni (O10)
    assert "Kurucu hesabıyla girdiniz" in PANO_JS
    assert "Kurucu hesabının şifresi burada değişmez" in PANO_JS


def test_o10_per_tur_durum_etiketleri():
    # iletildi: türe göre; suruyor: yeniden/güncelle (docs/19 §3.6, O10)
    etiketler = ("Çalınıyor", "Deneniyor", "Hazırlanıyor", "Yeniden başlatılıyor", "Güncelleniyor")
    for metin in etiketler:
        assert metin in PANO_JS, metin


def test_metin_duzeltmeleri():
    # docs/19 §3.9 metin düzeltmeleri. Panodaki "Bu siteye ne gelir" kartı 2.
    # tasarımda kaldırıldı (Pano v2); eski metin geri gelmesin.
    assert "Yalnız şifreyle giren görür" not in PANO_HTML
    assert "Pano yalnız kişisel hesapla açılır." in INDEX_HTML
    assert "Pano yalnız şifreyle açılır." not in INDEX_HTML


def test_teshis_eki_metincontent_ile_yazilir():
    # Teşhis eki (fabrikadan gelen metin) yalnız textContent ile yazılır
    assert "pre.textContent = k.ek" in PANO_JS
    assert ".innerHTML" not in PANO_JS  # yalnız textContent; innerHTML hiç kullanılmaz
