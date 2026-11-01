"""Uzak izleme panosunun ortak çekirdeği.

Vercel'de `api/` altındaki her `.py` dosyası ayrı bir adrestir (`api/rapor.py`
-> `/api/rapor`). Alt çizgiyle başlayan bu dosya adres değildir; onların ortak
parçasıdır. Yalnız Python'un standart kütüphanesi kullanılır: kurulacak paket,
derleme adımı ya da güncellenecek bağımlılık yoktur.

Akış:

    fabrika programı --(imzalı JSON, 30 sn'de bir)--> /api/rapor --> Redis
    tarayıcı --(şifreyle giriş, oturum çerezi)--> /api/durum <-- Redis

Uzaktan müdahale (anons, hoparlör denemesi) da aynı yönden geçer: pano komutu
/api/mudahale ile kuyruğa koyar, fabrika programı /api/komut'tan imzalı
istekle alır ve sonucunu bildirir. Fabrikaya dışarıdan bağlanılmaz; fabrika
yalnız Müdahale ekranı açıkken birkaç saniyede bir sorar ("Uzaktan müdahale"
bölümü).

Görüntü (fabrika içi kullanım kararı, 24.10.2026): ihlallerin kanıt
fotoğrafı /api/foto'ya, Kameralar ekranı açıkken kameraların anlık görüntüsü
/api/kare'ye gelir; ikisi de imzalı ve küçültülmüştür, yalnız giriş yapan görür,
kısa süre sonra silinir. Şifreler, kamera adresleri ve video gelmez (README.md
"Siteye ne gelir, ne gelmez"). Ayarlar Vercel'in Environment Variables
ekranından okunur.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import hmac
import http.cookies
import ipaddress
import json
import math
import os
import re
import secrets
import smtplib
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler

# ------------------------------------------------------------------ sabitler

# Rapor biçiminin sürümü. Fabrika programı aynı sayıyı gönderir; biçim
# değişirse iki taraf birlikte güncellenir (DALSAN: backend/app/uzak_pano.py).
RAPOR_SURUMU = 1
ZAMAN_BASLIGI = "X-Dalsan-Zaman"
IMZA_BASLIGI = "X-Dalsan-Imza"
# Fabrika bilgisayarının saati ile sitenin saati arasında kabul edilen en çok
# fark. Eski bir raporun yeniden gönderilmesini bu pencere sınırlar.
ZAMAN_TOLERANSI_SN = 300
RAPOR_EN_BUYUK_BAYT = 128 * 1024
GIRIS_EN_BUYUK_BAYT = 4 * 1024

SIFRE_EN_AZ = 10
ANAHTAR_EN_AZ = 32
OTURUM_SURESI_SN = 12 * 3600
CEREZ_ADI = "pano_oturum"

# Kaba kuvvet koruması: bir adresten 5 yanlış denemede o adres 5 dakika
# kilitlenir (fabrika programının girişiyle aynı kural, docs/15 §3). Bütün
# adreslerden 15 dakikada 100 yanlış deneme gelirse giriş 15 dakika kapanır;
# açık oturumlar etkilenmez.
KILIT_DENEME = 5
KILIT_SURESI_SN = 300
GENEL_KILIT_DENEME = 100
GENEL_KILIT_SURESI_SN = 900

# Son durum 7 gün saklanır: rapor kesilirse olay başlıkları bu sitede
# süresiz durmaz. Son raporun ZAMANI ise silinmez; pano "son rapor 9 gün
# önce" diyebilsin.
DURUM_SAKLAMA_SN = 7 * 24 * 3600
DURUM_ANAHTARI = "dalsan:durum"
SON_RAPOR_ANAHTARI = "dalsan:son_rapor"
GIRIS_ADRES_ONEKI = "dalsan:giris:adres:"
GIRIS_GENEL_ANAHTARI = "dalsan:giris:genel"

# Rapor aralığının bu katı kadar süre haber gelmezse bağlantı "yok" sayılır:
# tek bir kaçan rapor (anlık ağ kesintisi) panoyu kırmızıya çevirmez.
GECIKME_KATSAYISI = 3

KAMERA_DURUMLARI = ("online", "connecting", "offline", "pasif")
ONEMLER = ("critical", "high", "medium", "low")
OLAY_TURLERI = ("ihlal", "sistem")
OLAY_EN_COK = 50  # rapordaki son olaylar (pano 20'sini gösterir)
# ---- roller (docs/19 §1)
# Hesap rolü her istekte kayıttan okunur; ekranda Türkçe adıyla gösterilir.
ROLLER = ("izleyici", "operator", "yonetici")
ROL_ADLARI = {"izleyici": "İzleyici", "operator": "Operatör", "yonetici": "Yönetici"}

# ---- uzaktan müdahale ve yönetim (docs/19 §3.5-§3.7)
# Pano yalnız bu işleri isteyebilir; fabrika programı da yalnız bunları tanır.
KOMUT_TURLERI = ("anons", "ses_dene", "olay_incele", "teshis", "yeniden_baslat", "guncelle")
# Rol kapısı: yönetim işleri yalnız yöneticide; ötekiler operatör ve üstünde.
YONETIM_TURLERI = ("teshis", "yeniden_baslat", "guncelle")
AGIR_TURLERI = ("yeniden_baslat", "guncelle")
# Raporda bildirilen açık işler ve olay durumları (docs/19 §3.8).
MUDAHALE_ISLERI = ("anons", "ses_dene", "olay_incele")
OLAY_DURUMLARI = ("new", "reviewed", "false_alarm")
KURULUM_TURLERI = ("paket", "git", "diger")
# Komutun durumu; "sonuc_yok" yalnız görünümde türetilir (kayda yazılmaz).
KOMUT_DURUMLARI = ("bekliyor", "iletildi", "suruyor", "yapildi", "hata", "suresi_doldu")
KOMUT_BITMIS = ("yapildi", "hata", "suresi_doldu")
KOMUT_SIRA_ANAHTARI = "dalsan:komut:sira"  # fabrikanın henüz almadığı komutlar
KOMUT_SON_ANAHTARI = "dalsan:komut:son"  # panoda görünen son komutların kimliği
KOMUT_KAYIT_ONEKI = "dalsan:komut:kayit:"  # komutun durumu ve sonucu
# Sıklık sayaçları (grup başına; docs/19 §3.5). Ağır iş ayrı kilitle sayılır.
KOMUT_SAYAC_ONEKI = "dalsan:komut:sayac:"
# İki işaret fabrikaya "sık sor" der: Müdahale/Yönetim ekranı açık ya da yeni komut var.
IZLEYEN_ANAHTARI = "dalsan:mudahale:izleyen"
KOMUT_ISARET_ANAHTARI = "dalsan:komut:isaret"
YOKLAMA_ANAHTARI = "dalsan:komut:yoklama"  # fabrikanın son sorduğu an
# Fabrika komutu bu süre içinde almazsa komut düşer: saatler sonra bağlanan
# bir fabrikada eski bir anons çalmasın.
KOMUT_GECERLILIK_SN = 120
KOMUT_SAKLAMA_SN = 2 * 24 * 3600
KOMUT_SON_SAYISI = 50  # kayıtta tutulan; ekran 20 gösterir
KOMUT_GOSTERILEN = 20
# Çalınan bir şifreyle hoparlörler susturulamaz ama yağmur gibi anons da
# yaptırılamasın. Grup başına kayan pencere (docs/19 §3.5 tablosu).
KOMUT_SINIR_PENCERESI_SN = 300
KOMUT_GRUP_SINIRLARI = {"ses": 10, "inceleme": 60, "teshis": 3}
KOMUT_GRUPLARI = {
    "anons": "ses",
    "ses_dene": "ses",
    "olay_incele": "inceleme",
    "teshis": "teshis",
}
# Eski ad (dış kodda kullanılmaz): ses grubunun sınırı.
KOMUT_SINIRI = KOMUT_GRUP_SINIRLARI["ses"]
IZLEYEN_SURESI_SN = 30
YOKLAMA_TOPLU = 5
# Fabrikaya iletilip bu süre sonuç gelmezse panoda "sonuç gelmedi" yazar.
# Ağır işler uzun sürer: güncelleme yarım saat, yeniden başlatma on dakika.
SONUC_BEKLEME_SN = 180
SONUC_BEKLEME = {"guncelle": 1800, "yeniden_baslat": 600}
KOMUT_EN_BUYUK_BAYT = 64 * 1024  # komut sorusu gövdesi en çok 64 KB (docs/19 §3.7)
KOMUT_SONUC_EN_COK = 10  # bir istekte işlenen sonuç sayısı
EK_EN_BUYUK_BAYT = 8192  # teshis ek metni (docs/19 §3.7)
SURESI_DOLDU_METNI = "Fabrika komutu 2 dakika içinde almadı; yapılmadı."

# ---- tek ağır iş kilidi ve kayan ağır pencere (docs/19 §3.5)
# Aynı anda tek yeniden başlatma/güncelleme; site kilidi yalnız ekran
# kolaylığıdır, gerçek garanti programdadır.
AGIR_KILIT_ANAHTARI = "dalsan:komut:agir"
AGIR_ZAMANLAR_ANAHTARI = "dalsan:komut:agir:zamanlar"
AGIR_PENCERE_SN = 3600
AGIR_SINIR = 3
AGIR_ZAMAN_TUT = 10  # pencerede saklanan damga sayısı

# ---- hesaplar, oturum, kilit, işlem kaydı (docs/19 §3.1-§3.3)
AYRILMIS_ADLAR = frozenset({"kurucu", "fabrika", "sistem", "site"})
KURUCU_AD = "kurucu"
AD_DESENI = re.compile(r"[a-z0-9][a-z0-9._-]{2,31}")
SIFRE_EN_UZUN = 200
HESAP_EN_COK = 50  # kurucu hariç
HESAP_SURUMU = 1
KULLANICI_ONEKI = "dalsan:kullanici:"
KULLANICILAR_ANAHTARI = "dalsan:kullanicilar"
SON_GIRIS_ONEKI = "dalsan:son_giris:"
OTURUM_IPTAL_ONEKI = "dalsan:oturum:iptal:"
# Giriş kilitleri (docs/19 §3.2): adres, ad, genel; hepsi şifreden önce okunur.
GIRIS_AD_ONEKI = "dalsan:giris:ad:"
AD_KILIT_DENEME = 10
AD_KILIT_SURESI_SN = 900
# Yanlış onay/eski şifre bu sayaca da girer; 5'te oturum sürümü artar (§3.1).
ONAY_HATA_ONEKI = "dalsan:onay_hata:"
ONAY_HATA_SINIR = 5
ONAY_HATA_SURESI_SN = 900
# İşlem kaydı (docs/19 §3.3): üç ayrı liste, ayrı uzunluklarla.
KAYIT_ANAHTARI = "dalsan:kayit"
KAYIT_OTURUM_ANAHTARI = "dalsan:kayit:oturum"
KAYIT_GIRIS_ANAHTARI = "dalsan:kayit:giris"
KAYIT_EN_COK = 1000
KAYIT_GIRIS_EN_COK = 200
KAYIT_BIRLESIK_EN_COK = 300  # GET /api/hesap üç listeyi birleşik verir
# Hesap kaydını kimse sel gibi dolduramasın (docs/19 §3.3).
SIFRE_DEGISTIR_SINIRI = 5
SIFRE_DEGISTIR_PENCERESI_SN = 3600
SIFRE_DEGISTIR_SAYAC_ONEKI = "dalsan:kayit:sinir:sifre:"
HESAP_ISLEM_SINIRI = 30
HESAP_ISLEM_PENCERESI_SN = 900
HESAP_ISLEM_SAYAC_ONEKI = "dalsan:kayit:sinir:hesap:"
# Yetkisiz deneme izi (docs/19 §3.3 komut_red): düşük yetkili ya da çalınan bir
# çerez admin uçlarını yoklarsa iz kalsın. Ama bu iz kaydı sel gibi dolduramasın:
# hesap başına bir dakikada en çok KOMUT_RED_SINIRI satır yazılır, fazlası toplanır.
KOMUT_RED_SAYAC_ONEKI = "dalsan:kayit:sinir:red:"
KOMUT_RED_SINIRI = 10
KOMUT_RED_PENCERESI_SN = 60
# Hesap kaydına eşzamanlı yazmayı dizen kısa ömürlü kilit (docs/19 SITE-B2).
# Upstash boru hattı işlemsel değildir; aynı hesaba iki read-modify-write (ör.
# yönetici X'i düşürürken X şifresini değiştirir) birbirini sessizce ezebilir.
# Kilit CAS yerine geçer: alınamazsa kısa süre denenir, sonra 409 mesgul.
KULLANICI_KILIT_ONEKI = "dalsan:kullanici:kilit:"
HESAP_KILIT_SURESI_SN = 5
HESAP_KILIT_DENEME = 5
HESAP_KILIT_BEKLEME_SN = 0.2
HESAP_MESGUL_METNI = "Bu hesapta başka bir işlem sürüyor; birkaç saniye sonra yeniden deneyin."

# ---- görüntü (fabrika içi kullanım kararı, 24.10.2026)
# Kanıt fotoğrafı: ihlal başına bir kez gelir, 7 gün durur (durumla aynı).
# Hangi olayın fotoğrafı olduğunu site kendisi tutar (tek anahtar, en yenisi
# önde) ve rapor cevabında fabrikaya söyler: fabrika aynı fotoğrafı iki kez
# göndermez. En çok FOTO_EN_COK fotoğraf durur; pano son 20 olayı gösterir ve
# depo 256 MB ile sınırlıdır (Upstash ücretsiz plan).
FOTO_ONEKI = "dalsan:foto:"
FOTO_LISTESI_ANAHTARI = "dalsan:fotolar"
FOTO_EN_BUYUK_BAYT = 400 * 1024
FOTO_SAKLAMA_SN = DURUM_SAKLAMA_SN
FOTO_EN_COK = 60
# Anlık görüntü: yalnız Kameralar ekranı açıkken gelir; 2 dakikada silinir
# (eski bir kare "şu anki görüntü" diye gösterilmesin).
KARE_ONEKI = "dalsan:kare:"
KARE_ZAMAN_ONEKI = "dalsan:kare_zaman:"
KARE_IZLEYEN_ANAHTARI = "dalsan:kare:izleyen"
KARE_EN_BUYUK_BAYT = 300 * 1024
KARE_SAKLAMA_SN = 120
KARE_ARALIK_SN = 10  # fabrikaya önerilen gönderme aralığı (README)
JPEG_BASI = b"\xff\xd8\xff"
IP_EN_COK = 4
# Sistem olayının açıklamasında adres olmaz (kamera şifresi adresin içinde
# durur). Fabrika da çıkarır; bu ikinci kilittir.
ADRES_DESENI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S*")

SAYI_ALANLARI = (
    "bugun_ihlal",
    "dun_ihlal",
    "bekleyen",
    "aktif_kural",
    "kamera_toplam",
    "kamera_canli",
)

# ---- "Sistemden haber yok" dış alarmı (öneri 5, docs/20 §3) - hepsi opt-in
# Rapor BEKCI_ESIK_DK dakikadan uzun süre gelmezse seçili kişilere BİR KEZ
# e-posta / Telegram bildirimi gider; taze rapor gelince işaret silinir ve bir
# sonraki kesintide yeniden uyarılır. Bu işaret SET NX EX ile tutulur.
BEKCI_UYARI_ANAHTARI = "dalsan:bekci:uyarildi"
# İşaretin kendiliğinden tazelenme aralığı (uzun tutulur: taze rapor zaten siler).
BEKCI_UYARI_TTL_SN = 24 * 3600
BEKCI_ESIK_VARSAYILAN_DK = 20
# Serverless süresi kısadır: gönderim kısa bir zaman aşımıyla yapılır.
BEKCI_GONDERIM_ZAMAN_ASIMI_SN = 10.0
BEKCI_ALICI_EN_COK = 20

# ---- Çoklu fabrika / filo görünümü (öneri 10, docs/20 §4) - salt okuma, geri uyumlu
# Rapor isteğe bağlı bir "tesis" alanı taşırsa site bu kayıt defterine ek bir
# özet yazar; "dalsan:durum" / "dalsan:son_rapor" HİÇ değişmez (tek fabrika yolu).
TESISLER_ANAHTARI = "dalsan:tesisler"  # tesis kimliklerinin dizini
TESIS_ONEKI = "dalsan:tesis:"  # tesis başına küçük özet
TESIS_SAKLAMA_SN = DURUM_SAKLAMA_SN  # durumla aynı: 7 gün
TESIS_EN_COK = 50
TESIS_ID_DESENI = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")


# ------------------------------------------------------------------- hatalar


class PanoHatasi(Exception):
    """İsteğe verilecek, kullanıcıya gösterilebilir hata (Türkçe)."""

    def __init__(self, kod: int, hata: str, mesaj: str, **ek: object) -> None:
        super().__init__(mesaj)
        self.kod = kod
        self.hata = hata
        self.mesaj = mesaj
        self.ek = ek

    def govde(self) -> dict:
        return {"hata": self.hata, "mesaj": self.mesaj, **self.ek}


class DepoHatasi(Exception):
    """Redis'e (Upstash) ulaşılamadı ya da Redis bir hata döndü."""


# -------------------------------------------------------------------- ayarlar


@dataclass(frozen=True)
class Ayar:
    pano_sifresi: str
    rapor_anahtari: str
    redis_adresi: str
    redis_jetonu: str
    fabrika_adresi: str
    # Bekçi (öneri 5) ve e-posta / Telegram kanalları: hepsi opt-in, varsayılan
    # boş/kapalı. Sırlar repr'de gizlenir ve hiçbir cevaba / hata metnine girmez.
    bekci: str = "kapali"
    bekci_esik_dk: int = BEKCI_ESIK_VARSAYILAN_DK
    bekci_alicilar: tuple[str, ...] = ()
    bekci_anahtari: str = field(default="", repr=False)
    cron_sirri: str = field(default="", repr=False)
    smtp_sunucu: str = ""
    smtp_port: int = 587
    smtp_kullanici: str = ""
    smtp_sifresi: str = field(default="", repr=False)
    smtp_kimden: str = ""
    telegram_bot: str = field(default="", repr=False)
    telegram_sohbet: str = ""


def _tam_ortam(deger: str | None, varsayilan: int, en_az: int, en_cok: int) -> int:
    """Ortamdan okunan tam sayı; boş ya da bozuksa varsayılan, sınırlara kırpılır."""
    ham = (deger or "").strip()
    if not _rakam_mi(ham):
        return varsayilan
    return max(en_az, min(en_cok, int(ham)))


def _alicilar(ham: str | None) -> tuple[str, ...]:
    """Virgülle ayrık alıcı listesi: e-posta ya da `tg:<sohbet_id>`. Boşlar atılır."""
    liste = []
    for parca in (ham or "").split(","):
        alici = parca.strip()
        if alici and len(alici) <= 200:
            liste.append(alici)
        if len(liste) >= BEKCI_ALICI_EN_COK:
            break
    return tuple(liste)


def ayar_oku(ortam: Mapping[str, str] | None = None) -> Ayar:
    """Vercel'in ortam değişkenleri. Upstash bağlantısı iki adla gelebilir:
    Upstash'in kendi adları ya da Vercel'in eski KV adları (README.md).

    Bekçi ve filo ayarları opt-in'dir: tanımlı değilse bekçi sessizce hiçbir şey
    yapmaz ve eksikler()'e GİRMEZ (ikisi de açılmadıkça bugünkü davranış aynı)."""
    ortam = os.environ if ortam is None else ortam
    return Ayar(
        pano_sifresi=ortam.get("PANO_SIFRESI", "").strip(),
        rapor_anahtari=ortam.get("RAPOR_ANAHTARI", "").strip(),
        redis_adresi=(
            ortam.get("UPSTASH_REDIS_REST_URL") or ortam.get("KV_REST_API_URL") or ""
        ).strip(),
        redis_jetonu=(
            ortam.get("UPSTASH_REDIS_REST_TOKEN") or ortam.get("KV_REST_API_TOKEN") or ""
        ).strip(),
        fabrika_adresi=_fabrika_adresi(ortam.get("FABRIKA_ADRESI", "")),
        bekci=ortam.get("BEKCI", "").strip().lower() or "kapali",
        bekci_esik_dk=_tam_ortam(ortam.get("BEKCI_ESIK_DK"), BEKCI_ESIK_VARSAYILAN_DK, 1, 1440),
        bekci_alicilar=_alicilar(ortam.get("BEKCI_ALICILAR")),
        bekci_anahtari=ortam.get("BEKCI_ANAHTARI", "").strip(),
        cron_sirri=ortam.get("CRON_SECRET", "").strip(),
        smtp_sunucu=ortam.get("SMTP_SUNUCU", "").strip(),
        smtp_port=_tam_ortam(ortam.get("SMTP_PORT"), 587, 1, 65535),
        smtp_kullanici=ortam.get("SMTP_KULLANICI", "").strip(),
        smtp_sifresi=ortam.get("SMTP_SIFRESI", ""),
        smtp_kimden=ortam.get("SMTP_KIMDEN", "").strip(),
        telegram_bot=ortam.get("TELEGRAM_BOT", "").strip(),
        telegram_sohbet=ortam.get("TELEGRAM_SOHBET", "").strip(),
    )


def _fabrika_adresi(ham: str) -> str:
    """Canlı görüntü düğmesinin adresi (VPN/Tailscale üzerinden fabrika ekranı).

    Yalnız http(s) adresi kabul edilir: başka bir şema (javascript: gibi)
    düğmeye konursa tıklayan kişinin tarayıcısında kod çalıştırabilirdi.
    """
    adres = ham.strip()
    if re.fullmatch(r"https?://[^\s\"'<>]+", adres):
        return adres
    return ""


def eksikler(ayar: Ayar) -> list[dict]:
    """Kurulumda eksik olanlar; boş liste = site hazır. Sırlar yazılmaz."""
    liste = []
    if not ayar.pano_sifresi:
        liste.append({"ad": "PANO_SIFRESI", "neden": "tanımlı değil"})
    elif len(ayar.pano_sifresi) < SIFRE_EN_AZ:
        liste.append({"ad": "PANO_SIFRESI", "neden": f"en az {SIFRE_EN_AZ} karakter olmalı"})
    if not ayar.rapor_anahtari:
        liste.append({"ad": "RAPOR_ANAHTARI", "neden": "tanımlı değil"})
    elif len(ayar.rapor_anahtari) < ANAHTAR_EN_AZ:
        liste.append({"ad": "RAPOR_ANAHTARI", "neden": f"en az {ANAHTAR_EN_AZ} karakter olmalı"})
    if DEPO is None and not (ayar.redis_adresi and ayar.redis_jetonu):
        liste.append({"ad": "Upstash Redis", "neden": "projeye bağlı değil"})
    return liste


def kurulum_tamam_mi(ayar: Ayar) -> None:
    eksik = eksikler(ayar)
    if eksik:
        raise PanoHatasi(
            503,
            "kurulum_eksik",
            "Site henüz kurulmadı: Vercel'de birkaç ayar eksik.",
            eksikler=eksik,
        )


# ---------------------------------------------------------------------- depo


class _OrtakDepo:
    """İki deponun ortak yardımcıları. Alt sınıf yalnız Redis komutunu
    çalıştırmayı bilir (`komut`, `boru_hatti`); geri kalan her iş bu
    komutlarla yazılır, böylece yerel deneme ile Vercel aynı kodu çalıştırır."""

    def komut(self, *parcalar: str) -> object:
        raise NotImplementedError

    def boru_hatti(self, komutlar: list[list[str]]) -> list[object]:
        raise NotImplementedError

    def al_coklu(self, anahtarlar: list[str]) -> list[str | None]:
        sonuc = self.komut("MGET", *anahtarlar)
        if not isinstance(sonuc, list):
            raise DepoHatasi(f"MGET liste döndürmedi: {sonuc!r:.200}")
        return [deger if isinstance(deger, str) else None for deger in sonuc]

    def yaz_coklu(self, kayitlar: list[tuple[str, str, int | None]]) -> None:
        self.boru_hatti([_set_komutu(anahtar, deger, sure) for anahtar, deger, sure in kayitlar])

    def say(self, anahtar: str, sure_sn: int) -> int:
        """Sayacı bir artırır. Sayaç yoksa `sure_sn` sonra silinmek üzere kurulur;
        varsa süresi uzamaz (pencere ilk denemeden başlar)."""
        sonuc = self.boru_hatti(
            [["SET", anahtar, "0", "EX", str(sure_sn), "NX"], ["INCR", anahtar]]
        )
        return int(sonuc[1])

    def sil(self, anahtar: str) -> None:
        self.komut("DEL", anahtar)


def _set_komutu(anahtar: str, deger: str, sure_sn: int | None) -> list[str]:
    komut = ["SET", anahtar, deger]
    if sure_sn:
        komut += ["EX", str(sure_sn)]
    return komut


class UpstashDepo(_OrtakDepo):
    """Upstash Redis'in REST arayüzü: her komut bir HTTPS isteğidir.

    Komut, JSON dizisi olarak adresin köküne gönderilir (["GET", "a"]);
    birden çok komut tek istekte /pipeline'a. Cevap {"result": ...} ya da
    {"error": "..."} biçimindedir.
    """

    def __init__(self, adres: str, jeton: str, zaman_asimi: float = 5.0) -> None:
        self.adres = adres.rstrip("/")
        self.jeton = jeton
        self.zaman_asimi = zaman_asimi

    def _istek(self, yol: str, govde: list) -> object:
        istek = urllib.request.Request(
            self.adres + yol,
            data=json.dumps(govde).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.jeton}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(istek, timeout=self.zaman_asimi) as yanit:
                return json.loads(yanit.read().decode("utf-8"))
        except urllib.error.HTTPError as hata:
            # Jeton yanlışsa 401, komut hatalıysa 400 döner; gövdede sebep yazar.
            # Jeton hiçbir zaman hata metnine girmez.
            ayrinti = hata.read(300).decode("utf-8", "replace")
            raise DepoHatasi(f"Upstash HTTP {hata.code}: {ayrinti}") from hata
        except (urllib.error.URLError, TimeoutError, OSError) as hata:
            raise DepoHatasi(f"Upstash'e ulaşılamadı: {hata}") from hata
        except ValueError as hata:
            raise DepoHatasi(f"Upstash cevabı JSON değil: {hata}") from hata

    @staticmethod
    def _sonuc(oge: object) -> object:
        if not isinstance(oge, dict):
            raise DepoHatasi(f"Upstash beklenmeyen cevap verdi: {oge!r:.200}")
        if "error" in oge:
            raise DepoHatasi(f"Upstash hatası: {oge['error']}")
        return oge.get("result")

    def komut(self, *parcalar: str) -> object:
        return self._sonuc(self._istek("", list(parcalar)))

    def boru_hatti(self, komutlar: list[list[str]]) -> list[object]:
        cevap = self._istek("/pipeline", komutlar)
        if not isinstance(cevap, list) or len(cevap) != len(komutlar):
            raise DepoHatasi(f"Upstash boru hattı beklenmeyen cevap verdi: {cevap!r:.200}")
        return [self._sonuc(oge) for oge in cevap]


class BellekDepo(_OrtakDepo):
    """Bellekte duran depo. Yalnız testler ve yerel deneme (yerel_sunucu.py)
    içindir: Vercel'de her istek ayrı bir süreçte çalışabilir, bellek paylaşılmaz.

    Sitenin kullandığı Redis komutlarını Upstash'in döndürdüğü biçimde taklit
    eder (dize ve liste değerler, süre). Bilmediği komutta DepoHatasi verir:
    yeni bir komut kullanılırsa önce burada da yazılmalıdır.
    """

    def __init__(self, saat: Callable[[], float] = time.time) -> None:
        self.saat = saat
        self._veri: dict[str, tuple[str | list[str], float | None]] = {}
        self._kilit = threading.Lock()

    def komut(self, *parcalar: str) -> object:
        with self._kilit:
            return self._calistir([str(parca) for parca in parcalar])

    def boru_hatti(self, komutlar: list[list[str]]) -> list[object]:
        with self._kilit:
            return [self._calistir([str(parca) for parca in komut]) for komut in komutlar]

    # ---- iç işler (kilit tutulurken çağrılır)

    def _deger(self, anahtar: str) -> str | list[str] | None:
        kayit = self._veri.get(anahtar)
        if kayit is None:
            return None
        deger, bitis = kayit
        if bitis is not None and bitis <= self.saat():
            del self._veri[anahtar]
            return None
        return deger

    def _dize(self, anahtar: str) -> str | None:
        deger = self._deger(anahtar)
        if isinstance(deger, list):
            raise DepoHatasi("WRONGTYPE Operation against a key holding the wrong kind of value")
        return deger

    def _liste(self, anahtar: str) -> list[str]:
        deger = self._deger(anahtar)
        if isinstance(deger, str):
            raise DepoHatasi("WRONGTYPE Operation against a key holding the wrong kind of value")
        return deger or []

    def _liste_yaz(self, anahtar: str, liste: list[str]) -> None:
        if not liste:
            self._veri.pop(anahtar, None)  # Redis boş listeyi siler
            return
        bitis = self._veri[anahtar][1] if anahtar in self._veri else None
        self._veri[anahtar] = (liste, bitis)

    @staticmethod
    def _aralik(uzunluk: int, bas: str, son: str) -> slice:
        ilk, sonuncu = int(bas), int(son)
        ilk = max(0, ilk + uzunluk if ilk < 0 else ilk)
        sonuncu = sonuncu + uzunluk if sonuncu < 0 else sonuncu
        return slice(ilk, max(ilk, sonuncu + 1))

    def _calistir(self, parcalar: list[str]) -> object:
        ad, *arg = parcalar
        ad = ad.upper()
        if ad == "GET":
            return self._dize(arg[0])
        if ad == "MGET":
            return [d if isinstance(d, str) else None for d in map(self._deger, arg)]
        if ad == "SET":
            anahtar, deger, *secenekler = arg
            secenekler = [s.upper() for s in secenekler]
            if "NX" in secenekler and self._deger(anahtar) is not None:
                return None
            bitis = None
            if "EX" in secenekler:
                bitis = self.saat() + int(secenekler[secenekler.index("EX") + 1])
            self._veri[anahtar] = (deger, bitis)
            return "OK"
        if ad == "DEL":
            silinen = [anahtar for anahtar in arg if self._deger(anahtar) is not None]
            for anahtar in silinen:
                del self._veri[anahtar]
            return len(silinen)
        if ad == "INCR":
            mevcut = self._dize(arg[0])
            if mevcut is not None and not _rakam_mi(mevcut.lstrip("-")):
                raise DepoHatasi("ERR value is not an integer or out of range")
            yeni = int(mevcut or 0) + 1
            bitis = self._veri[arg[0]][1] if mevcut is not None else None
            self._veri[arg[0]] = (str(yeni), bitis)
            return yeni
        if ad == "EXPIRE":
            if self._deger(arg[0]) is None:
                return 0
            self._veri[arg[0]] = (self._veri[arg[0]][0], self.saat() + int(arg[1]))
            return 1
        if ad in ("RPUSH", "LPUSH"):
            liste = list(self._liste(arg[0]))
            for deger in arg[1:]:
                if ad == "RPUSH":
                    liste.append(deger)
                else:
                    liste.insert(0, deger)
            self._liste_yaz(arg[0], liste)
            return len(liste)
        if ad == "LPOP":
            liste = list(self._liste(arg[0]))
            if not liste:
                return None
            adet = int(arg[1]) if len(arg) > 1 else None
            alinan, kalan = liste[: adet or 1], liste[adet or 1 :]
            self._liste_yaz(arg[0], kalan)
            return alinan if adet is not None else alinan[0]
        if ad == "LRANGE":
            liste = self._liste(arg[0])
            return liste[self._aralik(len(liste), arg[1], arg[2])]
        if ad == "LTRIM":
            liste = self._liste(arg[0])
            self._liste_yaz(arg[0], liste[self._aralik(len(liste), arg[1], arg[2])])
            return "OK"
        if ad == "LLEN":
            return len(self._liste(arg[0]))
        if ad == "LREM":
            # LREM key count value: count>0 baştan, <0 sondan, 0 hepsi (Redis).
            # Site yalnız count=0'ı (dizinden bir adı tümüyle çıkarmak) kullanır.
            liste = list(self._liste(arg[0]))
            sayi, deger = int(arg[1]), arg[2]
            hedef = [i for i, oge in enumerate(liste) if oge == deger]
            if sayi > 0:
                hedef = hedef[:sayi]
            elif sayi < 0:
                hedef = hedef[sayi:]
            for i in reversed(hedef):
                del liste[i]
            self._liste_yaz(arg[0], liste)
            return len(hedef)
        raise DepoHatasi(f"ERR unknown command '{ad}'")


# Testler ve yerel_sunucu.py buraya bir BellekDepo koyar; Vercel'de boştur.
DEPO: BellekDepo | None = None


def depo_al(ayar: Ayar) -> UpstashDepo | BellekDepo:
    if DEPO is not None:
        return DEPO
    return UpstashDepo(ayar.redis_adresi, ayar.redis_jetonu)


# ---------------------------------------------------------------------- imza


def imza_hesapla(anahtar: str, zaman: str, govde: bytes) -> str:
    """HMAC-SHA256(anahtar, "<zaman>.<gövde>"). Fabrika programı aynısını yapar."""
    ozet = hmac.new(
        anahtar.encode("utf-8"), zaman.encode("ascii") + b"." + govde, hashlib.sha256
    ).hexdigest()
    return "sha256=" + ozet


def imza_dogrula(
    anahtar: str, zaman_basligi: str | None, imza_basligi: str | None, govde: bytes, simdi: float
) -> None:
    """İmza ve zaman tutmuyorsa PanoHatasi(401). Gövde bundan ÖNCE ayrıştırılmaz."""
    if not zaman_basligi or not imza_basligi:
        raise PanoHatasi(
            401, "imza_yok", "İmza başlıkları eksik: istek fabrika programından gelmiyor."
        )
    zaman = zaman_basligi.strip()
    if not _rakam_mi(zaman):
        raise PanoHatasi(401, "zaman", "Zaman başlığı okunamadı.")
    fark = simdi - int(zaman)
    if abs(fark) > ZAMAN_TOLERANSI_SN:
        yon = "geri" if fark > 0 else "ileri"
        raise PanoHatasi(
            401,
            "saat_farki",
            f"Fabrika bilgisayarının saati yaklaşık {abs(round(fark))} saniye {yon} "
            f"(en çok {ZAMAN_TOLERANSI_SN} saniye kabul edilir). Bilgisayarın tarih ve saat "
            "ayarında 'otomatik ayarla'yı açın.",
        )
    beklenen = imza_hesapla(anahtar, zaman, govde)
    if not hmac.compare_digest(beklenen.encode(), imza_basligi.strip().encode("utf-8", "replace")):
        raise PanoHatasi(
            401,
            "imza_gecersiz",
            "İmza tutmadı: fabrika programındaki uzak pano anahtarı ile sitedeki "
            "RAPOR_ANAHTARI aynı değil.",
        )


# --------------------------------------------------------------- rapor biçimi


def _sozluk(deger: object) -> dict:
    return deger if isinstance(deger, dict) else {}


def _liste(deger: object, en_cok: int) -> list:
    return deger[:en_cok] if isinstance(deger, list) else []


def _metin(deger: object, en_cok: int = 160) -> str:
    """Düz, tek satırlık, kısaltılmış metin. Kontrol karakterleri atılır."""
    if not isinstance(deger, str):
        return ""
    temiz = "".join(harf if harf.isprintable() else " " for harf in deger)
    return " ".join(temiz.split())[:en_cok]


def _sayi(deger: object, en_az: float, en_cok: float) -> float | None:
    if isinstance(deger, bool) or not isinstance(deger, int | float):
        return None
    # isfinite yalnız ondalıkta: çok büyük bir tam sayıyı float'a çeviremez (OverflowError)
    if isinstance(deger, float) and not math.isfinite(deger):
        return None
    if not en_az <= deger <= en_cok:
        return None
    return round(float(deger), 2)


def _tam(deger: object, en_az: int, en_cok: int, varsayilan: int = 0) -> int:
    if isinstance(deger, bool) or not isinstance(deger, int):
        return varsayilan
    return max(en_az, min(en_cok, deger))


def _rakam_mi(metin: str) -> bool:
    """Yalnız 0-9 (str.isdigit '²' gibi harfleri de kabul eder, int() onları okuyamaz)."""
    return re.fullmatch(r"[0-9]{1,15}", metin) is not None


def _mantik(deger: object) -> bool | None:
    return deger if isinstance(deger, bool) else None


def _secim(deger: object, secenekler: tuple[str, ...]) -> str:
    return deger if isinstance(deger, str) and deger in secenekler else ""


def _zaman(deger: object) -> str:
    """Saat dilimli ISO 8601 damgası, UTC'ye çevrilmiş; okunamazsa boş."""
    if not isinstance(deger, str) or len(deger) > 40:
        return ""
    try:
        an = datetime.fromisoformat(deger.replace("Z", "+00:00"))
        if an.tzinfo is None:
            return ""  # saat dilimsiz damga panoda yanlış saate düşerdi
        return an.astimezone(UTC).isoformat(timespec="seconds")
    except (ValueError, OverflowError):  # OverflowError: 0001 yılında +14 saat dilimi gibi
        return ""


def _kamera(ham: dict) -> dict:
    return {
        "id": _kimlik(ham.get("id")),  # anlık görüntünün anahtarı
        "ad": _metin(ham.get("ad"), 80) or "Adsız kamera",
        "bolum": _metin(ham.get("bolum"), 80),
        "durum": _secim(ham.get("durum"), KAMERA_DURUMLARI) or "offline",
        "okunan_fps": _sayi(ham.get("okunan_fps"), 0, 1000),
        "islenen_fps": _sayi(ham.get("islenen_fps"), 0, 1000),
        "hedef_fps": _sayi(ham.get("hedef_fps"), 0, 1000),
        "yavas": ham.get("yavas") is True,
        "son_kare_yasi_sn": _sayi(ham.get("son_kare_yasi_sn"), 0, 10**9),
    }


def _olay(ham: dict) -> dict:
    return {
        "id": _kimlik(ham.get("id")),  # kanıt fotoğrafının anahtarı
        "foto": False,  # sitede fotoğrafı var mı: pano_verisi doldurur
        # Sistem olayının açıklaması; adres ve dosya yolu fabrikada çıkarılır
        "ayrinti": _metin(ADRES_DESENI.sub("(adres)", _metin(ham.get("ayrinti"), 600)), 300),
        "zaman": _zaman(ham.get("zaman")),
        "tur": _secim(ham.get("tur"), OLAY_TURLERI) or "ihlal",
        "baslik": _metin(ham.get("baslik"), 160) or "Olay",
        "yer": _metin(ham.get("yer"), 160),
        "onem": _secim(ham.get("onem"), ONEMLER),
        "onem_adi": _metin(ham.get("onem_adi"), 40),
        "durum_adi": _metin(ham.get("durum_adi"), 40),
        # Ham durum: inceleme düğmesi yalnız "new" ihlalde çıkar (docs/19 §3.8)
        "durum": _secim(ham.get("durum"), OLAY_DURUMLARI),
        "suruyor": ham.get("suruyor") is True,
        "sure": _metin(ham.get("sure"), 40),
    }


def _saatlik(ham: object) -> list[int]:
    if not isinstance(ham, list) or len(ham) != 24:
        return [0] * 24
    return [_tam(deger, 0, 10**7) for deger in ham]


def _kimlik(deger: object) -> int | None:
    if isinstance(deger, bool) or not isinstance(deger, int) or not 0 < deger < 2**31:
        return None
    return deger


def _ip_listesi(ham: object) -> list[str]:
    adresler = []
    for oge in _liste(ham, IP_EN_COK):
        if not isinstance(oge, str):
            continue  # ip_address(7) "0.0.0.7" olurdu
        try:
            adresler.append(str(ipaddress.ip_address(oge.strip())))
        except ValueError:
            continue
    return adresler


def _bilgisayar(ham: object) -> dict | None:
    """Programın kurulu olduğu bilgisayar. Hepsi isteğe bağlıdır; hiçbiri
    yoksa None (pano "henüz gönderilmiyor" der)."""
    if not isinstance(ham, dict):
        return None
    bilgi = {
        "ad": _metin(ham.get("ad"), 80),  # kurulumun adı: "Gebze fabrikası"
        "bilgisayar_adi": _metin(ham.get("bilgisayar_adi"), 64),
        "isletim_sistemi": _metin(ham.get("isletim_sistemi"), 80),
        "islemci": _metin(ham.get("islemci"), 120),
        "cekirdek": _tam(ham.get("cekirdek"), 0, 1024) or None,
        "bellek_gb": _sayi(ham.get("bellek_gb"), 0, 10**5),
        "ekran_karti": _metin(ham.get("ekran_karti"), 120),
        "cikarim": _metin(ham.get("cikarim"), 80),
        "disk_toplam_gb": _sayi(ham.get("disk_toplam_gb"), 0, 10**6),
        "kurulum_turu": _metin(ham.get("kurulum_turu"), 60),
        "kurulum_tarihi": _zaman(ham.get("kurulum_tarihi")),
        "acilis": _zaman(ham.get("acilis")),
        "ip": _ip_listesi(ham.get("ip")),  # fabrika ağındaki adresi
    }
    return bilgi if any(bilgi.values()) else None


def _tesis(ham: object) -> dict | None:
    """Raporun isteğe bağlı tesis kimliği (çoklu fabrika, öneri 10, docs/20 §4).

    `id`: ^[a-z0-9][a-z0-9_-]{0,31}$ (kısa kimlik). `ad`: en çok 80 karakter.
    Alan yoksa ya da bozuksa None: o zaman site bugünkü tek fabrika gibi davranır
    (`dalsan:durum` / `dalsan:son_rapor` birebir aynı)."""
    if not isinstance(ham, dict):
        return None
    kimlik = ham.get("id")
    if not isinstance(kimlik, str) or not TESIS_ID_DESENI.fullmatch(kimlik):
        return None
    return {"id": kimlik, "ad": _metin(ham.get("ad"), 80) or kimlik}


def _gunluk(ham: object) -> list[int] | None:
    """Son 14 günün ihlal sayısı, en eskisi başta, sonuncusu bugün."""
    if not isinstance(ham, list) or len(ham) != 14:
        return None
    return [_tam(deger, 0, 10**7) for deger in ham]


def _yedi_gun(ham: object) -> dict | None:
    if not isinstance(ham, dict):
        return None
    ihlal = _tam(ham.get("ihlal"), 0, 10**7)
    return {
        "ihlal": ihlal,
        "incelenen": min(ihlal, _tam(ham.get("incelenen"), 0, 10**7)),
        "yanlis_alarm": min(ihlal, _tam(ham.get("yanlis_alarm"), 0, 10**7)),
    }


def _mudahale(ham: object) -> dict:
    """Fabrikanın uzaktan müdahaleye izni ve seçenekleri: hazır anons
    mesajlarının metni ve ses kanallarının adı (adres ve cihaz adı gelmez)."""
    ham = _sozluk(ham)
    mesajlar = []
    for oge in _liste(ham.get("mesajlar"), 30):
        if isinstance(oge, dict) and (kimlik := _kimlik(oge.get("id"))):
            mesajlar.append({"id": kimlik, "metin": _metin(oge.get("metin"), 160) or "Mesaj"})
    kanallar = []
    for oge in _liste(ham.get("kanallar"), 30):
        if isinstance(oge, dict) and (kimlik := _kimlik(oge.get("id"))):
            kanallar.append(
                {
                    "id": kimlik,
                    "ad": _metin(oge.get("ad"), 80) or "Kanal",
                    "bolum": _metin(oge.get("bolum"), 80),
                }
            )
    acik = ham.get("acik") is True
    # Açık işler yeni alandır; eski program göndermez: açıksa anons ve ses_dene
    # varsayılır (bugünkü davranış), yoksa hiçbiri (docs/19 §3.8).
    if isinstance(ham.get("isler"), list):
        isler = [is_ for is_ in MUDAHALE_ISLERI if is_ in ham["isler"]]
    else:
        isler = ["anons", "ses_dene"] if acik else []
    return {"acik": acik, "isler": isler, "mesajlar": mesajlar, "kanallar": kanallar}


def _yapi(ham: object) -> dict:
    """Programın yapı bilgisi: commit, tarih, kaçıncı çalıştırma (docs/19 §3.8).
    Eski program göndermez; boş değerlere düşer."""
    ham = _sozluk(ham)
    commit = ham.get("commit")
    if not (isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{7,40}", commit)):
        commit = ""
    return {
        "commit": commit,
        "tarih": _zaman(ham.get("tarih")),
        "calistirma": _tam(ham.get("calistirma"), 0, 10**9),
    }


def _yonetim(ham: object) -> dict:
    """Uzaktan yönetimin durumu: açık mı, hangi işler, kurulum türü ve yeniden
    başlatma / güncelleme yapılabilir mi (docs/19 §3.8). Eski program göndermez:
    her şey kapalı döner, düğmeler pasif kalır."""
    ham = _sozluk(ham)

    def _is_kapisi(deger: object) -> dict:
        deger = _sozluk(deger)
        return {
            "mumkun": deger.get("mumkun") is True,
            "sebep": _metin(deger.get("sebep"), 200),
        }

    isler_ham = ham.get("isler")
    isler = (
        [is_ for is_ in YONETIM_TURLERI if is_ in isler_ham] if isinstance(isler_ham, list) else []
    )
    return {
        "acik": ham.get("acik") is True,
        "isler": isler,
        "kurulum": _secim(ham.get("kurulum"), KURULUM_TURLERI),
        "yeniden_baslatma": _is_kapisi(ham.get("yeniden_baslatma")),
        "guncelleme": _is_kapisi(ham.get("guncelleme")),
    }


def rapor_temizle(ham: object) -> dict:
    """Gelen raporu bilinen alanlara indirger.

    Fabrika programı imzayla doğrulanmış olsa da depoya yalnız bilinen,
    tipi denetlenmiş, kısaltılmış alanlar yazılır: bilinmeyen bir alan
    (bir şifre, büyük bir görüntü) bu siteye girmez. Kanıt fotoğrafı ayrı
    ve imzalı gelir: foto_al.
    """
    if not isinstance(ham, dict):
        raise PanoHatasi(400, "bicim", "Rapor bir JSON nesnesi olmalı.")
    if ham.get("surum") != RAPOR_SURUMU:
        raise PanoHatasi(
            400,
            "surum",
            f"Rapor biçimi desteklenmiyor (gelen: {_metin(str(ham.get('surum')), 10)}, "
            f"beklenen: {RAPOR_SURUMU}). Fabrika programını ya da siteyi güncelleyin.",
        )
    program = _sozluk(ham.get("program"))
    sistem = _sozluk(ham.get("sistem"))
    sayilar = _sozluk(ham.get("sayilar"))
    temiz = {
        "surum": RAPOR_SURUMU,
        "uretildi": _zaman(ham.get("uretildi")),
        "aralik_sn": _tam(ham.get("aralik_sn"), 5, 3600, varsayilan=30),
        "kapanis": ham.get("kapanis") is True,
        # Yalnız kapanış raporunda dolu: güncelleme / yeniden başlatma (docs/19 §3.8)
        "kapanis_sebebi": (
            _secim(ham.get("kapanis_sebebi"), ("guncelleme", "yeniden_baslatma"))
            if ham.get("kapanis") is True
            else ""
        ),
        "program": {
            "ad": _metin(program.get("ad"), 60),
            "surum": _metin(program.get("surum"), 40),
            "yapi": _yapi(program.get("yapi")),
        },
        "sistem": {
            "analiz": _mantik(sistem.get("analiz")),
            "hazir": _mantik(sistem.get("hazir")),
            "model": _metin(sistem.get("model"), 40),
            "uyari_garantisi": _mantik(sistem.get("uyari_garantisi")),
            "sorunlar": [
                metin
                for metin in (_metin(oge, 200) for oge in _liste(sistem.get("sorunlar"), 20))
                if metin
            ],
            "bos_disk_gb": _sayi(sistem.get("bos_disk_gb"), 0, 10**6),
            "calisma_suresi_sn": _tam(sistem.get("calisma_suresi_sn"), 0, 10**9),
        },
        "kameralar": [
            _kamera(oge) for oge in _liste(ham.get("kameralar"), 64) if isinstance(oge, dict)
        ],
        "sayilar": {alan: _tam(sayilar.get(alan), 0, 10**7) for alan in SAYI_ALANLARI},
        "saatlik": _saatlik(ham.get("saatlik")),
        "ogeler": [
            {"ad": _metin(oge.get("ad"), 60) or "Diğer", "sayi": _tam(oge.get("sayi"), 0, 10**7)}
            for oge in _liste(ham.get("ogeler"), 20)
            if isinstance(oge, dict)
        ],
        "son_olaylar": [
            _olay(oge)
            for oge in _liste(ham.get("son_olaylar"), OLAY_EN_COK)
            if isinstance(oge, dict)
        ],
        "mudahale": _mudahale(ham.get("mudahale")),
        # Yönetici görünümü (eskiden gönderilmez; yoksa pano o kartı gizler)
        "gunluk": _gunluk(ham.get("gunluk")),
        "yedi_gun": _yedi_gun(ham.get("yedi_gun")),
        "yerler": [
            {
                "ad": _metin(oge.get("ad"), 80) or "Adsız kamera",
                "bolum": _metin(oge.get("bolum"), 80),
                "sayi": _tam(oge.get("sayi"), 0, 10**7),
            }
            for oge in _liste(ham.get("yerler"), 10)
            if isinstance(oge, dict)
        ],
        "bilgisayar": _bilgisayar(ham.get("bilgisayar")),
        # Yönetici görünümü (eskiden gönderilmez; yoksa her şey kapalı döner)
        "yonetim": _yonetim(ham.get("yonetim")),
    }
    # Tesis (öneri 10) yalnız VARSA eklenir: yoksa anahtar hiç girmez ve tek
    # fabrika yolu birebir aynı kalır (docs/20 §4; test_sozlesme buna dayanır).
    tesis = _tesis(ham.get("tesis"))
    if tesis is not None:
        temiz["tesis"] = tesis
    return temiz


def rapor_kaydet(
    depo: UpstashDepo | BellekDepo, rapor: dict, simdi: float, ayar: Ayar | None = None
) -> dict:
    """Raporu yazar ve fabrikaya cevabı kurar: komutları sık sorsun mu
    (Müdahale ekranı açık ya da komut bekliyor; müdahale kapalıysa hayır),
    anlık görüntü göndersin mi (Kameralar ekranı açık) ve raporundaki hangi
    olayların fotoğrafı sitede zaten var. Hepsi tek komutla okunur."""
    kayit = json.dumps({"rapor": rapor}, ensure_ascii=False, separators=(",", ":"))
    komutlar = [
        _set_komutu(DURUM_ANAHTARI, kayit, DURUM_SAKLAMA_SN),
        _set_komutu(SON_RAPOR_ANAHTARI, str(int(simdi)), None),
        [
            "MGET",
            IZLEYEN_ANAHTARI,
            KOMUT_ISARET_ANAHTARI,
            KARE_IZLEYEN_ANAHTARI,
            FOTO_LISTESI_ANAHTARI,
        ],
    ]
    # Bekçi açıkken taze rapor "sistemden haber yok" işaretini siler (resume):
    # sistem geri gelince bir sonraki kesintide yeniden uyarılabilsin (docs/20 §3).
    # Kapalıyken komut listesine HİÇ eklenmez: tek fabrika yolu birebir aynı kalır.
    if ayar is not None and ayar.bekci == "acik":
        komutlar.append(["DEL", BEKCI_UYARI_ANAHTARI])
    sonuc = depo.boru_hatti(komutlar)
    isaretler = sonuc[2]
    if not (isinstance(isaretler, list) and len(isaretler) == 4):
        isaretler = [None] * 4
    izleyen, komut_var, kare, ham_fotolar = isaretler
    fotolar = foto_kimlikleri(ham_fotolar, simdi)
    # Tesis (öneri 10) VARSA ek bir kayıt defterine yazılır; mevcut anahtarlara
    # (dalsan:durum / dalsan:son_rapor) DOKUNULMAZ (docs/20 §4).
    if rapor.get("tesis"):
        _tesis_kaydet(depo, rapor, simdi)
    # Sık sor: müdahale ya da yönetim açık VE ekran açık ya da komut var (docs/19 §3.8)
    komut_acik = rapor["mudahale"]["acik"] or rapor["yonetim"]["acik"]
    return {
        "komut": {"hizli": bool(komut_acik and (izleyen or komut_var))},
        "kare": {"iste": bool(kare)},
        "foto": {"var": [o["id"] for o in rapor["son_olaylar"] if o["id"] in fotolar]},
    }


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds")


def pano_verisi(depo: UpstashDepo | BellekDepo, ayar: Ayar, simdi: float) -> dict:
    """Panonun gösterdiği her şey; bağlantının durumu burada hesaplanır.

    baglanti: "hic" (hiç rapor gelmedi) · "canli" · "yok" (rapor kesildi)
    · "kapandi" (fabrika programı kapatılırken son raporu gönderdi).
    """
    ham_durum, ham_son, ham_fotolar = depo.al_coklu(
        [DURUM_ANAHTARI, SON_RAPOR_ANAHTARI, FOTO_LISTESI_ANAHTARI]
    )
    rapor = None
    if ham_durum:
        try:
            rapor = _sozluk(json.loads(ham_durum)).get("rapor")
        except ValueError:
            rapor = None
    if isinstance(rapor, dict):
        fotolar = foto_kimlikleri(ham_fotolar, simdi)
        for olay in _liste(rapor.get("son_olaylar"), OLAY_EN_COK):
            if isinstance(olay, dict):
                olay["foto"] = olay.get("id") in fotolar
    son = int(ham_son) if ham_son and _rakam_mi(ham_son) else None
    if son is None:
        baglanti = "hic"
    elif not isinstance(rapor, dict):
        baglanti = "yok"
    elif rapor.get("kapanis"):
        baglanti = "kapandi"
    elif simdi - son <= rapor.get("aralik_sn", 30) * GECIKME_KATSAYISI + 5:
        baglanti = "canli"
    else:
        baglanti = "yok"
    return {
        "baglanti": baglanti,
        "son_rapor": _iso(son) if son is not None else None,
        "gecikme_sn": max(0, round(simdi - son)) if son is not None else None,
        "sunucu_zamani": _iso(simdi),
        "rapor": rapor if isinstance(rapor, dict) else None,
        "fabrika_adresi": ayar.fabrika_adresi,
    }


# ------------------------------------------------- çoklu fabrika / filo (öneri 10)


def _baglanti_hesapla(son: int | None, aralik_sn: int, kapanis: bool, simdi: float) -> str:
    """pano_verisi ile aynı kural, tesis özeti için tekrar kullanılır."""
    if son is None:
        return "hic"
    if kapanis:
        return "kapandi"
    if simdi - son <= aralik_sn * GECIKME_KATSAYISI + 5:
        return "canli"
    return "yok"


def _tesis_kaydet(depo: UpstashDepo | BellekDepo, rapor: dict, simdi: float) -> None:
    """Tesisin küçük özetini kayıt defterine yazar (öneri 10, docs/20 §4). Yalnız
    rapor bir tesis taşıdığında çağrılır; mevcut tek fabrika anahtarlarına
    DOKUNMAZ (ayrı bir boru hattı). Defter indeksine TTL verilir ki bir tesis
    uzun süre rapor göndermezse kendiliğinden düşsün."""
    tesis = rapor["tesis"]
    kimlik = tesis["id"]
    ozet = {
        "id": kimlik,
        "ad": tesis["ad"],
        "son_rapor": int(simdi),
        "aralik_sn": rapor.get("aralik_sn", 30),
        "kapanis": bool(rapor.get("kapanis")),
        "bugun_ihlal": rapor["sayilar"].get("bugun_ihlal", 0),
    }
    metin = json.dumps(ozet, ensure_ascii=False, separators=(",", ":"))
    depo.boru_hatti(
        [
            _set_komutu(TESIS_ONEKI + kimlik, metin, TESIS_SAKLAMA_SN),
            ["LREM", TESISLER_ANAHTARI, "0", kimlik],
            ["RPUSH", TESISLER_ANAHTARI, kimlik],
            ["EXPIRE", TESISLER_ANAHTARI, str(TESIS_SAKLAMA_SN)],
        ]
    )


def _tesis_satiri(kayit: dict, simdi: float) -> dict:
    son = _tam(kayit.get("son_rapor"), 0, 10**12) or None
    aralik = _tam(kayit.get("aralik_sn"), 5, 3600, varsayilan=30)
    return {
        "id": _metin(kayit.get("id"), 32),
        "ad": _metin(kayit.get("ad"), 80) or "Adsız tesis",
        "baglanti": _baglanti_hesapla(son, aralik, kayit.get("kapanis") is True, simdi),
        "son_rapor": _iso(son) if son else None,
        "gecikme_sn": max(0, round(simdi - son)) if son else None,
        "bugun_ihlal": _tam(kayit.get("bugun_ihlal"), 0, 10**7),
    }


def _mevcut_tesis_satiri(veri: dict) -> dict:
    """Kayıt defteri boşken (bugünkü tek fabrika) filo görünümüne tek satır:
    mevcut panonun durumundan türetilir."""
    rapor = veri.get("rapor") or {}
    bilgisayar = rapor.get("bilgisayar") or {}
    return {
        "id": "",
        "ad": _metin(bilgisayar.get("ad"), 80) or "Fabrika",
        "baglanti": veri.get("baglanti"),
        "son_rapor": veri.get("son_rapor"),
        "gecikme_sn": veri.get("gecikme_sn"),
        "bugun_ihlal": _tam((rapor.get("sayilar") or {}).get("bugun_ihlal"), 0, 10**7),
    }


def tesis_ozeti(depo: UpstashDepo | BellekDepo, simdi: float) -> list[dict]:
    """Kayıt defterindeki tesislerin filo özeti (yalnız-yönetici görünümü).
    Süresi dolan tesisler dizinden onarılır; ada göre sıralanır."""
    ham = depo.komut("LRANGE", TESISLER_ANAHTARI, "0", str(TESIS_EN_COK * 2))
    idler, gorulen = [], set()
    for oge in ham if isinstance(ham, list) else []:
        if isinstance(oge, str) and oge not in gorulen:
            gorulen.add(oge)
            idler.append(oge)
    if not idler:
        return []
    kayitlar = depo.al_coklu([TESIS_ONEKI + i for i in idler])
    satirlar, eksik = [], []
    for kimlik, ham_kayit in zip(idler, kayitlar, strict=True):
        kayit = _json_sozluk(ham_kayit)
        if kayit is None:
            eksik.append(kimlik)
        else:
            satirlar.append(_tesis_satiri(kayit, simdi))
    for kimlik in eksik:
        depo.komut("LREM", TESISLER_ANAHTARI, "0", kimlik)
    satirlar.sort(key=lambda s: s["ad"].lower())
    return satirlar


# ----------------------------------- "sistemden haber yok" dış alarmı (öneri 5)


def bekci_karari(veri: dict, esik_dk: int, simdi: float) -> bool:
    """SAF karar (docs/20 §3): pano verisine göre "sistemden haber yok" uyarısı
    verilmeli mi. Bağlantı yok/kapandı VE son rapor esik_dk dakikadan eskiyse
    True. "hic" (hiç rapor gelmedi) ve "canli" uyarı vermez."""
    if veri.get("baglanti") not in ("yok", "kapandi"):
        return False
    son_iso = veri.get("son_rapor")
    if not isinstance(son_iso, str) or not son_iso:
        return False
    try:
        son = datetime.fromisoformat(son_iso).timestamp()
    except (ValueError, TypeError):
        return False
    return simdi - son >= esik_dk * 60


def _eposta_gonder(ayar: Ayar, alici: str, konu: str, govde: str) -> None:
    """Düz metin e-posta (yalnız stdlib: smtplib + ssl). 465 ise SSL, aksi
    halde STARTTLS (587). Gönderen adresi SMTP_KIMDEN ya da SMTP_KULLANICI."""
    if not ayar.smtp_sunucu:
        raise OSError("SMTP sunucusu tanımlı değil")
    mesaj = EmailMessage()
    mesaj["From"] = ayar.smtp_kimden or ayar.smtp_kullanici or alici
    mesaj["To"] = alici
    mesaj["Subject"] = konu
    mesaj.set_content(govde)
    baglam = ssl.create_default_context()
    if ayar.smtp_port == 465:
        with smtplib.SMTP_SSL(
            ayar.smtp_sunucu, 465, context=baglam, timeout=BEKCI_GONDERIM_ZAMAN_ASIMI_SN
        ) as sunucu:
            if ayar.smtp_kullanici:
                sunucu.login(ayar.smtp_kullanici, ayar.smtp_sifresi)
            sunucu.send_message(mesaj)
    else:
        with smtplib.SMTP(
            ayar.smtp_sunucu, ayar.smtp_port, timeout=BEKCI_GONDERIM_ZAMAN_ASIMI_SN
        ) as sunucu:
            sunucu.starttls(context=baglam)
            if ayar.smtp_kullanici:
                sunucu.login(ayar.smtp_kullanici, ayar.smtp_sifresi)
            sunucu.send_message(mesaj)


def _telegram_gonder(ayar: Ayar, sohbet: str, metin: str) -> None:
    """Telegram bildirimi (mevcut urllib kalıbı, UpstashDepo._istek gibi)."""
    if not ayar.telegram_bot:
        raise OSError("Telegram bot jetonu tanımlı değil")
    adres = f"https://api.telegram.org/bot{ayar.telegram_bot}/sendMessage"
    govde = urllib.parse.urlencode({"chat_id": sohbet, "text": metin}).encode("utf-8")
    istek = urllib.request.Request(
        adres,
        data=govde,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(istek, timeout=BEKCI_GONDERIM_ZAMAN_ASIMI_SN) as yanit:
        yanit.read()


def bekci_uyari_gonder(
    ayar: Ayar,
    alicilar: tuple[str, ...],
    konu: str,
    metin: str,
    eposta_gonder: Callable[[Ayar, str, str, str], None] = _eposta_gonder,
    telegram_gonder: Callable[[Ayar, str, str], None] = _telegram_gonder,
) -> int:
    """Her alıcıya e-posta ya da Telegram (`tg:<id>`) gönderir. Her gönderim
    ayrı try/except: bir kanal çökse öteki yine çalışır, hiçbir hata 500
    yapmaz. Gönderenler enjekte edilebilir (testte sahte gönderici verilir).
    Giden bildirim sayısını döndürür."""
    gonderilen = 0
    for alici in alicilar:
        try:
            if alici.startswith("tg:"):
                telegram_gonder(ayar, alici[3:], metin)
            else:
                eposta_gonder(ayar, alici, konu, metin)
            gonderilen += 1
        except (OSError, smtplib.SMTPException, urllib.error.URLError, TimeoutError) as hata:
            # Vercel günlüğüne düşer; sır (şifre / jeton) hata metnine girmez.
            print(f"Bekçi bildirimi gidemedi ({_alici_gizle(alici)}): {hata}", file=sys.stderr)
    return gonderilen


def _alici_gizle(alici: str) -> str:
    """Günlükte alıcıyı kısmen gizler (e-posta adresi tümüyle yazılmasın)."""
    if alici.startswith("tg:"):
        return "tg:***"
    ad, _, alan = alici.partition("@")
    return (ad[:2] + "***@" + alan) if alan else "***"


def _bekci_metni(veri: dict, simdi: float) -> tuple[str, str]:
    """Kısa Türkçe uyarı metni (sır yok, görüntü yok)."""
    gecikme = veri.get("gecikme_sn")
    dk = round(gecikme / 60) if isinstance(gecikme, int | float) else "?"
    son = veri.get("son_rapor")
    konu = "DALSAN uyarı: sistemden haber yok"
    govde = (
        f"DALSAN izleme panosu yaklaşık {dk} dakikadır fabrikadan rapor almıyor. "
        "Fabrika bilgisayarı kapanmış, çökmüş ya da internet kesilmiş olabilir; "
        "bu sürede kameralar izlenmiyor olabilir.\n\n"
        f"Son rapor: {son or 'hiç gelmedi'}\n"
        "Lütfen fabrikadaki bilgisayarı ve internet bağlantısını kontrol edin."
    )
    return konu, govde


def bekci_isle(
    depo: UpstashDepo | BellekDepo,
    ayar: Ayar,
    simdi: float,
    gonder: Callable[..., int] = bekci_uyari_gonder,
) -> dict:
    """Bekçinin çekirdeği (HTTP'siz, test edilebilir). Bekçi kapalıysa hiçbir
    şey yapmaz. Açıksa bağlantı koptuysa ve son rapor eşikten eskiyse BİR KEZ
    uyarır: SET NX EX işareti ikinci çağrıyı susturur, taze rapor onu siler."""
    if ayar.bekci != "acik":
        return {"atlandi": True}
    veri = pano_verisi(depo, ayar, simdi)
    if not bekci_karari(veri, ayar.bekci_esik_dk, simdi):
        return {"uyarildi": False, "baglanti": veri["baglanti"]}
    # SET NX: yalnız işareti ilk koyan çağrı bildirim gönderir (eşzamanlı cron
    # çağrıları ya da arka arkaya denemeler ikinci bildirimi tetiklemez).
    (alindi,) = depo.boru_hatti(
        [["SET", BEKCI_UYARI_ANAHTARI, str(int(simdi)), "EX", str(BEKCI_UYARI_TTL_SN), "NX"]]
    )
    if alindi != "OK":
        return {"uyarildi": False, "baglanti": veri["baglanti"]}
    konu, metin = _bekci_metni(veri, simdi)
    gonderilen = gonder(ayar, ayar.bekci_alicilar, konu, metin)
    return {"uyarildi": True, "baglanti": veri["baglanti"], "gonderilen": gonderilen}


# --------------------------------------------------------- uzaktan müdahale


def _komut_kimligi_mi(deger: object) -> bool:
    return isinstance(deger, str) and re.fullmatch(r"[0-9a-f]{16}", deger) is not None


def _json_sozluk(ham: object) -> dict | None:
    if not isinstance(ham, str):
        return None
    try:
        deger = json.loads(ham)
    except (ValueError, RecursionError):
        return None
    return deger if isinstance(deger, dict) else None


def _kayit_metni(kayit: dict) -> str:
    return json.dumps(kayit, ensure_ascii=False, separators=(",", ":"))


def _islem_satiri(simdi: float, kim: str, rol: str, is_: str, ozet: str, sonuc: str) -> dict:
    """İşlem kaydının bir satırı (docs/19 §3.3). Şifre asla özete girmez."""
    return {
        "z": int(simdi),
        "kim": _metin(kim, 40),
        "rol": _secim(rol, ROLLER),
        "is": is_,
        "ozet": _metin(ozet, 200),
        "sonuc": sonuc,
    }


def kayit_yaz(depo: UpstashDepo | BellekDepo, liste: str, satir: dict, kesme: int) -> None:
    """Bir işlem kaydı satırını yazar ve listeyi kısaltır (LPUSH + LTRIM)."""
    depo.boru_hatti([["LPUSH", liste, _kayit_metni(satir)], ["LTRIM", liste, "0", str(kesme - 1)]])


def _komut_red_yaz(depo: UpstashDepo | BellekDepo, oturum: Oturum, ozet: str, simdi: float) -> None:
    """Rolü yetmeyen komut ya da hesap işi denemesini işlem kaydına yazar
    (docs/19 §3.3 komut_red): düşük yetkili ya da çalınan bir çerez admin
    uçlarını iz bırakmadan yoklayamasın. Hesap başına bir dakikada en çok
    KOMUT_RED_SINIRI satır; fazlası toplanır (kayıt sel gibi dolmasın)."""
    ad = oturum.ad or ""
    if depo.say(KOMUT_RED_SAYAC_ONEKI + ad, KOMUT_RED_PENCERESI_SN) > KOMUT_RED_SINIRI:
        return
    kayit_yaz(
        depo,
        KAYIT_OTURUM_ANAHTARI,
        _islem_satiri(simdi, ad, oturum.rol, "komut_red", ozet, "red"),
        KAYIT_EN_COK,
    )


def _kim_gorunumu(ham: object) -> dict:
    """Komutu kimin istediği: ad ve rol (docs/19 §3.6). Bozuksa boş döner."""
    ham = _sozluk(ham)
    ad = ham.get("ad")
    rol = _secim(ham.get("rol"), ROLLER)
    temiz_ad = ad if isinstance(ad, str) and (ad == KURUCU_AD or _ad_gecerli_mi(ad)) else ""
    return {"ad": temiz_ad, "rol": rol, "rol_adi": ROL_ADLARI.get(rol, "")}


def _rol_yeterli(rol: str, tur: str) -> bool:
    """Bu rol bu komut türünü isteyebilir mi (docs/19 §1)."""
    if tur in YONETIM_TURLERI:
        return rol == "yonetici"
    return rol in ("operator", "yonetici")


def _ek_temizle(ham: object) -> str:
    """Teşhis ek metni (docs/19 §3.7): satır sonu ve sekme dışındaki denetim
    karakterleri atılır, kalan adresler maskelenir, 8192 bayta kesilir."""
    if not isinstance(ham, str) or not ham:
        return ""
    temiz = "".join(h if (h in "\n\t" or h.isprintable()) else " " for h in ham)
    temiz = ADRES_DESENI.sub("(adres)", temiz)
    kodlu = temiz.encode("utf-8")
    if len(kodlu) > EK_EN_BUYUK_BAYT:
        temiz = kodlu[:EK_EN_BUYUK_BAYT].decode("utf-8", "ignore")
    return temiz


def komut_gorunumu(kayit: dict, simdi: float, ek_goster: bool = False) -> dict:
    """Panonun gösterdiği hal. Süresi dolan ya da sonucu gelmeyen komut
    burada adlandırılır: kuyruktaki kayıt kimse sormadan değişmez."""
    tur = _secim(kayit.get("tur"), KOMUT_TURLERI)
    durum = _secim(kayit.get("durum"), KOMUT_DURUMLARI) or "hata"
    mesaj = _metin(kayit.get("mesaj"), 300)
    guncellendi = _tam(kayit.get("guncellendi"), 0, 10**12)
    iletildi_an = _tam(kayit.get("iletildi"), 0, 10**12) or guncellendi
    bekleme = SONUC_BEKLEME.get(tur, SONUC_BEKLEME_SN)
    if durum == "bekliyor" and simdi >= _tam(kayit.get("son_gecerlilik"), 0, 10**12):
        durum, mesaj = "suresi_doldu", SURESI_DOLDU_METNI
    elif durum in ("iletildi", "suruyor") and simdi - iletildi_an > bekleme:
        durum, mesaj = "sonuc_yok", "Fabrikaya iletildi ama sonucu gelmedi."
    gorunum = {
        "id": kayit.get("id") if _komut_kimligi_mi(kayit.get("id")) else "",
        "tur": tur,
        "ozet": _metin(kayit.get("ozet"), 300),
        "kim": _kim_gorunumu(kayit.get("kim")),
        "olusturuldu": _iso(_tam(kayit.get("olusturuldu"), 0, 10**12)),
        "durum": durum,
        "mesaj": mesaj,
    }
    if ek_goster and isinstance(kayit.get("ek"), str) and kayit["ek"]:
        gorunum["ek"] = kayit["ek"]  # yazarken süzülmüştü (docs/19 §3.7)
    return gorunum


def mudahale_verisi(depo: UpstashDepo | BellekDepo, simdi: float, rol: str, izliyor: bool) -> dict:
    """Müdahale / Yönetim ekranının verisi: son komutlar ve fabrikanın son
    sorduğu an. Operatör anons, ses ve inceleme komutlarını görür; yönetici
    hepsini, teşhis ek metni dahil (docs/19 §3.6). `izliyor`: ekran açık;
    fabrika bir sonraki raporda sık sormaya başlar."""
    istek = [
        ["LRANGE", KOMUT_SON_ANAHTARI, "0", str(KOMUT_GOSTERILEN - 1)],
        ["GET", YOKLAMA_ANAHTARI],
    ]
    if izliyor:
        istek.append(_set_komutu(IZLEYEN_ANAHTARI, "1", IZLEYEN_SURESI_SN))
    sonuc = depo.boru_hatti(istek)
    son = sonuc[0] if isinstance(sonuc[0], list) else []
    kimlikler = [kimlik for kimlik in son if _komut_kimligi_mi(kimlik)]
    kayitlar = depo.al_coklu([KOMUT_KAYIT_ONEKI + k for k in kimlikler]) if kimlikler else []
    yoklama = sonuc[1] if isinstance(sonuc[1], str) and _rakam_mi(sonuc[1]) else None
    ek_goster = rol == "yonetici"
    gorunur = KOMUT_TURLERI if rol == "yonetici" else MUDAHALE_ISLERI
    komutlar = []
    for kayit in map(_json_sozluk, kayitlar):
        if kayit is None or _secim(kayit.get("tur"), KOMUT_TURLERI) not in gorunur:
            continue
        komutlar.append(komut_gorunumu(kayit, simdi, ek_goster=ek_goster))
    return {
        "komutlar": komutlar,
        "son_yoklama": _iso(int(yoklama)) if yoklama else None,
        "yoklama_yasi_sn": max(0, round(simdi - int(yoklama))) if yoklama else None,
    }


def _ses_komutu(rapor: dict, tur: str, istek: dict) -> tuple[dict, str]:
    """anons / ses_dene: kanal (ve anonsta mesaj) fabrikanın son raporunda olmalı."""
    mudahale = _sozluk(rapor.get("mudahale"))
    if mudahale.get("acik") is not True:
        raise PanoHatasi(
            409,
            "mudahale_kapali",
            "Fabrika programında uzaktan müdahale kapalı. Açmak için fabrikadaki "
            "bilgisayarda Ayarlar, Uzak izleme panosu, Uzaktan müdahale'yi seçin.",
        )
    if tur not in mudahale.get("isler", []):
        raise PanoHatasi(
            409, "is_desteklenmiyor", "Fabrika programı bu işi bilmiyor; programı güncelleyin."
        )
    kanallar = {k["id"]: k for k in mudahale.get("kanallar", []) if isinstance(k, dict)}
    kanal_id = istek.get("kanal_id")
    if kanal_id is None and tur == "anons":
        if not any(not k.get("bolum") for k in kanallar.values()):
            raise PanoHatasi(
                400,
                "tum_fabrika_yok",
                "Fabrikada “Tüm fabrika” kanalı yok; listeden bir kanal seçin.",
            )
        yer = "Tüm fabrika"
    elif _kimlik(kanal_id) in kanallar:
        kanal = kanallar[kanal_id]
        yer = kanal["ad"] + (f" ({kanal['bolum']})" if kanal["bolum"] else "")
    else:
        raise PanoHatasi(400, "kanal", "Bu ses kanalı fabrikada yok; sayfayı yenileyin.")
    yuk: dict = {"kanal_id": kanal_id}
    if tur == "anons":
        mesajlar = {m["id"]: m for m in mudahale.get("mesajlar", []) if isinstance(m, dict)}
        mesaj_id = _kimlik(istek.get("mesaj_id"))
        if mesaj_id not in mesajlar:
            raise PanoHatasi(400, "mesaj", "Bu anons mesajı fabrikada yok; sayfayı yenileyin.")
        yuk["mesaj_id"] = mesaj_id
        return yuk, f"Anons: “{mesajlar[mesaj_id]['metin']}” · {yer}"
    return yuk, f"Hoparlör denemesi · {yer}"


def _incele_komutu(rapor: dict, istek: dict) -> tuple[dict, str]:
    """olay_incele: olay son raporda, ihlal ve durumu 'new' olmalı (docs/19 §3.5)."""
    mudahale = _sozluk(rapor.get("mudahale"))
    if mudahale.get("acik") is not True:
        raise PanoHatasi(
            409,
            "mudahale_kapali",
            "Fabrika programında uzaktan müdahale kapalı. Açmak için fabrikadaki "
            "bilgisayarda Ayarlar, Uzak izleme panosu, Uzaktan müdahale'yi seçin.",
        )
    if "olay_incele" not in mudahale.get("isler", []):
        raise PanoHatasi(
            409, "is_desteklenmiyor", "Fabrika programı bu işi bilmiyor; programı güncelleyin."
        )
    olay_id = _kimlik(istek.get("olay_id"))
    olaylar = {
        o["id"]: o
        for o in _liste(rapor.get("son_olaylar"), OLAY_EN_COK)
        if isinstance(o, dict) and o.get("id")
    }
    olay = olaylar.get(olay_id)
    if olay is None or olay.get("tur") != "ihlal":
        raise PanoHatasi(
            400,
            "olay",
            "Bu olay fabrikanın son raporunda yok ya da ihlal değil; sayfayı yenileyin.",
        )
    if olay.get("durum") != "new":
        raise PanoHatasi(
            409, "olay_incelenmis", "Bu olay fabrikada zaten incelenmiş; sayfayı yenileyin."
        )
    karar = _secim(istek.get("karar"), ("reviewed", "false_alarm"))
    if not karar:
        raise PanoHatasi(400, "karar", "Karar (İncelendi / Yanlış alarm) seçilmedi.")
    karar_adi = "İncelendi" if karar == "reviewed" else "Yanlış alarm"
    yer = olay.get("yer") or ""
    ozet = f"İnceleme: “{olay.get('baslik') or 'Olay'}” · {yer} → {karar_adi}"
    return {"olay_id": olay_id, "olay_zaman": olay.get("zaman") or "", "karar": karar}, ozet


def _yonetim_komutu(rapor: dict, tur: str) -> tuple[dict, str]:
    """teshis / yeniden_baslat / guncelle: yönetim açık, iş destekli ve (ağır
    işlerde) fabrika yapılabilir demiş olmalı (docs/19 §3.5)."""
    yonetim = _sozluk(rapor.get("yonetim"))
    if yonetim.get("acik") is not True:
        raise PanoHatasi(
            409,
            "yonetim_kapali",
            "Fabrika programında uzaktan yönetim kapalı. Açmak için fabrikadaki "
            "bilgisayarda Ayarlar, Uzak izleme panosu, Uzaktan yönetim'i seçin.",
        )
    if tur not in yonetim.get("isler", []):
        raise PanoHatasi(
            409, "is_desteklenmiyor", "Fabrika programı bu işi bilmiyor; programı güncelleyin."
        )
    if tur == "teshis":
        return {}, "Teşhis"
    kapi = _sozluk(yonetim.get("yeniden_baslatma" if tur == "yeniden_baslat" else "guncelleme"))
    if kapi.get("mumkun") is not True:
        raise PanoHatasi(409, "yapilamaz", kapi.get("sebep") or "Bu iş şu an yapılamıyor.")
    return {}, ("Yeniden başlatma" if tur == "yeniden_baslat" else "Güncelleme")


def _zaman_listesi(ham: object) -> list[int]:
    try:
        liste = json.loads(ham) if isinstance(ham, str) else []
    except ValueError:
        return []
    return [z for z in liste if isinstance(z, int) and not isinstance(z, bool)][:AGIR_ZAMAN_TUT]


def _agir_kilit_bayat_mi(depo: UpstashDepo | BellekDepo, simdi: float) -> bool:
    """Ağır kilidi tutan komut gerçekten sürüyor mu, yoksa kilit bayat mı
    (docs/19 §3.5)? Bitmiş, süresi geçmiş ya da uzun süredir sessiz komutun
    kilidi bayattır ve bir kez daha denenebilir."""
    (tutan,) = depo.al_coklu([AGIR_KILIT_ANAHTARI])
    if not _komut_kimligi_mi(tutan):
        return True
    (ham_kayit,) = depo.al_coklu([KOMUT_KAYIT_ONEKI + tutan])
    kayit = _json_sozluk(ham_kayit)
    if kayit is None:
        return True
    durum = _secim(kayit.get("durum"), KOMUT_DURUMLARI)
    if durum in KOMUT_BITMIS:
        return True
    guncellendi = _tam(kayit.get("guncellendi"), 0, 10**12)
    bekleme = SONUC_BEKLEME.get(_secim(kayit.get("tur"), KOMUT_TURLERI), SONUC_BEKLEME_SN)
    if durum == "bekliyor":
        return simdi >= _tam(kayit.get("son_gecerlilik"), 0, 10**12)
    if durum == "iletildi":
        return simdi - guncellendi > 90
    if durum == "suruyor":
        return simdi - guncellendi > bekleme
    return True


def _agir_kilit_al(depo: UpstashDepo | BellekDepo, kimlik: str, tur: str, simdi: float) -> None:
    """Tek ağır iş kilidi + kayan ağır pencere (docs/19 §3.5). Kilit yalnız
    ekran kolaylığıdır; aynı anda tek ağır işi program garanti eder."""
    bekleme = SONUC_BEKLEME.get(tur, SONUC_BEKLEME_SN)
    sure = KOMUT_GECERLILIK_SN + bekleme + KOMUT_GECERLILIK_SN
    agir_dolu = "Önceki güncelleme ya da yeniden başlatma henüz bitmedi."
    (alindi,) = depo.boru_hatti([["SET", AGIR_KILIT_ANAHTARI, kimlik, "EX", str(sure), "NX"]])
    if alindi != "OK":
        if not _agir_kilit_bayat_mi(depo, simdi):
            raise PanoHatasi(409, "agir_suruyor", agir_dolu)
        depo.sil(AGIR_KILIT_ANAHTARI)
        (alindi,) = depo.boru_hatti([["SET", AGIR_KILIT_ANAHTARI, kimlik, "EX", str(sure), "NX"]])
        if alindi != "OK":
            raise PanoHatasi(409, "agir_suruyor", agir_dolu)
    # Kilit alındı: kayan pencere sayılır (sayaç ancak kilitten sonra artar).
    now = int(simdi)
    (ham,) = depo.al_coklu([AGIR_ZAMANLAR_ANAHTARI])
    taze = [z for z in _zaman_listesi(ham) if now - z < AGIR_PENCERE_SN]
    if len(taze) >= AGIR_SINIR:
        depo.sil(AGIR_KILIT_ANAHTARI)
        raise PanoHatasi(
            429,
            "cok_sik",
            f"Son bir saatte {AGIR_SINIR} güncelleme ya da yeniden başlatma yapıldı; "
            "bir süre sonra yeniden deneyin.",
        )
    taze = [*taze, now][-AGIR_ZAMAN_TUT:]
    depo.boru_hatti([_set_komutu(AGIR_ZAMANLAR_ANAHTARI, json.dumps(taze), AGIR_PENCERE_SN)])


def _grup_siniri(depo: UpstashDepo | BellekDepo, tur: str) -> None:
    """Grup başına sıklık sınırı (ses, inceleme, teşhis; docs/19 §3.5)."""
    grup = KOMUT_GRUPLARI.get(tur)
    if grup is None:
        return
    if depo.say(KOMUT_SAYAC_ONEKI + grup, KOMUT_SINIR_PENCERESI_SN) > KOMUT_GRUP_SINIRLARI[grup]:
        raise PanoHatasi(
            429,
            "cok_sik",
            f"Kısa sürede çok fazla komut gönderildi. {KOMUT_SINIR_PENCERESI_SN // 60} dakika "
            "sonra yeniden deneyin.",
        )


def komut_olustur(
    depo: UpstashDepo | BellekDepo, veri: dict, istek: dict, simdi: float, kim: dict
) -> dict:
    """Panodan gelen isteği doğrular ve kuyruğa koyar. `veri` pano_verisi'dir:
    seçilen mesaj, kanal ve olay fabrikanın son raporunda olmalı. Rolün bu işe
    yettiği ve (ağır işlerde) onay şifresi uç noktada denetlenmiştir."""
    if veri["baglanti"] != "canli":
        raise PanoHatasi(
            409,
            "fabrika_bagli_degil",
            "Fabrika programından şu an haber gelmiyor; komut gönderilemez.",
        )
    tur = _secim(istek.get("tur"), KOMUT_TURLERI)
    if not tur:
        raise PanoHatasi(400, "tur", "Bilinmeyen müdahale.")
    rapor = _sozluk(veri.get("rapor"))
    if tur in ("anons", "ses_dene"):
        yuk, ozet = _ses_komutu(rapor, tur, istek)
    elif tur == "olay_incele":
        yuk, ozet = _incele_komutu(rapor, istek)
    else:
        yuk, ozet = _yonetim_komutu(rapor, tur)
    kimlik = secrets.token_hex(8)
    yuk["id"] = kimlik
    yuk["tur"] = tur
    yuk["kim"] = {"ad": kim["ad"], "rol": kim["rol"]}
    yuk["son_gecerlilik"] = int(simdi) + KOMUT_GECERLILIK_SN
    if tur in AGIR_TURLERI:
        _agir_kilit_al(depo, kimlik, tur, simdi)
    else:
        _grup_siniri(depo, tur)
    kayit = {
        "id": kimlik,
        "tur": tur,
        "ozet": ozet,
        "kim": yuk["kim"],
        "olusturuldu": int(simdi),
        "son_gecerlilik": yuk["son_gecerlilik"],
        "durum": "bekliyor",
        "mesaj": "",
        "guncellendi": int(simdi),
    }
    depo.boru_hatti(
        [
            _set_komutu(KOMUT_KAYIT_ONEKI + kimlik, _kayit_metni(kayit), KOMUT_SAKLAMA_SN),
            ["RPUSH", KOMUT_SIRA_ANAHTARI, _kayit_metni(yuk)],
            ["EXPIRE", KOMUT_SIRA_ANAHTARI, str(KOMUT_SAKLAMA_SN)],
            ["LPUSH", KOMUT_SON_ANAHTARI, kimlik],
            ["LTRIM", KOMUT_SON_ANAHTARI, "0", str(KOMUT_SON_SAYISI - 1)],
            ["EXPIRE", KOMUT_SON_ANAHTARI, str(KOMUT_SAKLAMA_SN)],
            [
                "LPUSH",
                KAYIT_ANAHTARI,
                _kayit_metni(_islem_satiri(simdi, kim["ad"], kim["rol"], "komut", ozet, "tamam")),
            ],
            ["LTRIM", KAYIT_ANAHTARI, "0", str(KAYIT_EN_COK - 1)],
            _set_komutu(KOMUT_ISARET_ANAHTARI, "1", KOMUT_GECERLILIK_SN),
            _set_komutu(IZLEYEN_ANAHTARI, "1", IZLEYEN_SURESI_SN),
        ]
    )
    return komut_gorunumu(kayit, simdi, ek_goster=(kim["rol"] == "yonetici"))


def sonuclari_yaz(depo: UpstashDepo | BellekDepo, ham: object, simdi: float) -> list[str]:
    """Fabrikanın bildirdiği sonuçlar (en çok 10). Yalnız bekleyen, iletilmiş ya
    da süren komutun sonucu yazılır; bitmiş bir komut yeniden açılmaz. Döner:
    `alinan` = yazılan ya da zaten bitmiş bulunan kimlikler (program kalıcı sonuç
    dosyasını ancak burada görünce siler, docs/19 §3.7)."""
    sonuclar: list[tuple[str, str, str, str]] = []
    for oge in _liste(ham, KOMUT_SONUC_EN_COK):
        if not isinstance(oge, dict) or not _komut_kimligi_mi(oge.get("id")):
            continue
        durum = _secim(oge.get("durum"), ("yapildi", "hata", "suruyor"))
        if durum:
            sonuclar.append(
                (oge["id"], durum, _metin(oge.get("mesaj"), 300), _ek_temizle(oge.get("ek")))
            )
    if not sonuclar:
        return []
    kayitlar = depo.al_coklu([KOMUT_KAYIT_ONEKI + s[0] for s in sonuclar])
    alinan, yazilacak, kayit_satirlari = [], [], []
    for (kimlik, durum, mesaj, ek), ham_kayit in zip(sonuclar, kayitlar, strict=True):
        kayit = _json_sozluk(ham_kayit)
        if kayit is None:
            alinan.append(kimlik)  # kaydı yok (süresi dolmuş): program dosyayı silebilir
            continue
        if kayit.get("durum") in KOMUT_BITMIS:
            alinan.append(kimlik)  # zaten bitmiş: idempotent onay
            continue
        if kayit.get("durum") not in ("bekliyor", "iletildi", "suruyor"):
            continue
        kayit.update(durum=durum, mesaj=mesaj, guncellendi=int(simdi))
        if ek and _secim(kayit.get("tur"), KOMUT_TURLERI) == "teshis":
            kayit["ek"] = ek  # ek yalnız teşhis sonucunda tutulur (docs/19 §3.7)
        yazilacak.append(
            _set_komutu(KOMUT_KAYIT_ONEKI + kimlik, _kayit_metni(kayit), KOMUT_SAKLAMA_SN)
        )
        alinan.append(kimlik)
        if (
            durum in ("yapildi", "hata")
            and _secim(kayit.get("tur"), KOMUT_TURLERI) in YONETIM_TURLERI
        ):
            kayit_satirlari.append(
                _islem_satiri(
                    simdi,
                    "fabrika",
                    "",
                    "komut_sonuc",
                    kayit.get("ozet", ""),
                    "tamam" if durum == "yapildi" else "hata",
                )
            )
    if yazilacak:
        depo.boru_hatti(yazilacak)
    for satir in kayit_satirlari:
        kayit_yaz(depo, KAYIT_ANAHTARI, satir, KAYIT_EN_COK)
    return alinan


def _komut_yuku(ham: object) -> dict | None:
    """Kuyruktaki ham komutu (ya da bir sözleşme örneğini) alan alan okur:
    başka alan geçmez (docs/19 §3.7)."""
    yuk = _json_sozluk(ham)
    if yuk is None or not _komut_kimligi_mi(yuk.get("id")):
        return None
    tur = _secim(yuk.get("tur"), KOMUT_TURLERI)
    son = yuk.get("son_gecerlilik")
    if not tur or isinstance(son, bool) or not isinstance(son, int):
        return None
    temiz: dict = {
        "id": yuk["id"],
        "tur": tur,
        "son_gecerlilik": son,
        "kim": _kim_sakla(yuk.get("kim")),
    }
    if tur in ("anons", "ses_dene"):
        temiz["kanal_id"] = _kimlik(yuk.get("kanal_id"))
        if tur == "anons":
            temiz["mesaj_id"] = _kimlik(yuk.get("mesaj_id"))
    elif tur == "olay_incele":
        temiz["olay_id"] = _kimlik(yuk.get("olay_id"))
        temiz["olay_zaman"] = (
            yuk.get("olay_zaman") if isinstance(yuk.get("olay_zaman"), str) else ""
        )
        temiz["karar"] = _secim(yuk.get("karar"), ("reviewed", "false_alarm"))
    return temiz


def _kim_sakla(ham: object) -> dict:
    """Komutun istek sahibi {ad, rol} (yük ve kayıtta saklanan biçim)."""
    ham = _sozluk(ham)
    ad = ham.get("ad")
    return {
        "ad": ad if isinstance(ad, str) and (ad == KURUCU_AD or _ad_gecerli_mi(ad)) else "",
        "rol": _secim(ham.get("rol"), ROLLER),
    }


def _teslim_yetkili(kim: dict, tur: str, hesaplar: dict) -> bool:
    """Teslim anında: istek sahibi hâlâ var, açık ve rolü bu işe yetiyor mu
    (docs/19 §3.5)."""
    ad = kim.get("ad")
    if ad == KURUCU_AD:
        return _rol_yeterli("yonetici", tur)
    hesap = hesaplar.get(ad)
    if hesap is None or hesap.get("acik") is not True:
        return False
    return _rol_yeterli(_secim(hesap.get("rol"), ROLLER), tur)


def komutlari_teslim_et(depo: UpstashDepo | BellekDepo, simdi: float) -> tuple[list[dict], bool]:
    """Kuyruktan en çok YOKLAMA_TOPLU komutu alır (alınan komut kuyruktan
    çıkar: fabrika yeniden başlasa bile aynı anons ikinci kez çalmaz). Teslimden
    önce istek sahibinin yetkisi yeniden okunur; düşmüşse komut gönderilmez
    (docs/19 §3.5). Döner: (fabrikaya gidecek komutlar, sık sormaya devam et mi)."""
    cikan, isaretler, _ = depo.boru_hatti(
        [
            ["LPOP", KOMUT_SIRA_ANAHTARI, str(YOKLAMA_TOPLU)],
            ["MGET", IZLEYEN_ANAHTARI, KOMUT_ISARET_ANAHTARI],
            _set_komutu(YOKLAMA_ANAHTARI, str(int(simdi)), KOMUT_SAKLAMA_SN),
        ]
    )
    hizli = isinstance(isaretler, list) and any(isaretler)
    yukler = [y for y in map(_komut_yuku, cikan if isinstance(cikan, list) else []) if y]
    if not yukler:
        return [], hizli
    kayitlar = depo.al_coklu([KOMUT_KAYIT_ONEKI + yuk["id"] for yuk in yukler])
    adlar = sorted(
        {yuk["kim"]["ad"] for yuk in yukler if yuk["kim"]["ad"] and yuk["kim"]["ad"] != KURUCU_AD}
    )
    hesap_ham = depo.al_coklu([KULLANICI_ONEKI + ad for ad in adlar]) if adlar else []
    hesaplar = {ad: _json_sozluk(h) for ad, h in zip(adlar, hesap_ham, strict=True)}
    teslim, yazilacak, dusen = [], [], []
    for yuk, ham_kayit in zip(yukler, kayitlar, strict=True):
        kayit = _json_sozluk(ham_kayit)
        if kayit is None or kayit.get("durum") != "bekliyor":
            continue  # kaydı olmayan ya da bitmiş komut yürütülmez
        if simdi >= yuk["son_gecerlilik"]:
            kayit.update(durum="suresi_doldu", mesaj=SURESI_DOLDU_METNI, guncellendi=int(simdi))
        elif not _teslim_yetkili(yuk["kim"], yuk["tur"], hesaplar):
            kayit.update(
                durum="hata",
                mesaj="İsteyen hesabın yetkisi kalmadı; gönderilmedi.",
                guncellendi=int(simdi),
            )
            dusen.append(
                _islem_satiri(
                    simdi,
                    yuk["kim"]["ad"],
                    yuk["kim"]["rol"],
                    "komut_dustu",
                    kayit.get("ozet", ""),
                    "hata",
                )
            )
        else:
            kayit.update(durum="iletildi", iletildi=int(simdi), guncellendi=int(simdi))
            teslim.append({**yuk, "kalan_sn": int(yuk["son_gecerlilik"] - simdi)})
        yazilacak.append(
            _set_komutu(KOMUT_KAYIT_ONEKI + yuk["id"], _kayit_metni(kayit), KOMUT_SAKLAMA_SN)
        )
    if yazilacak:
        depo.boru_hatti(yazilacak)
    for satir in dusen:
        kayit_yaz(depo, KAYIT_ANAHTARI, satir, KAYIT_EN_COK)
    return teslim, hizli


# -------------------------------------------------------------------- oturum


ONIZLEME_METNI = (
    "Bu bir önizleme yayını; fabrikaya komut ve hesap değişikliği yalnız ana adresten yapılır."
)
SIFRE_DEGISMELI_METNI = "Önce Sistem > Hesabım'dan şifrenizi değiştirin; sonra yeniden deneyin."
OTURUM_KAPANDI_METNI = "Oturumunuz kapandı; yeniden giriş yapın."
GIRIS_GEREKLI_METNI = "Panoyu görmek için giriş yapın."
GIRIS_HATALI_METNI = "Kullanıcı adı ya da şifre yanlış."


def onizleme_mi() -> bool:
    """Önizleme (preview) yayını mı? VERCEL_ENV tanımlı ama production değilse
    komut ve hesap değişikliği yapılmaz (docs/19 §3.1). Yerel sunucuda yoktur."""
    ortam = os.environ.get("VERCEL_ENV", "")
    return bool(ortam) and ortam != "production"


# ------------------------------------------------------------------- şifre


# scrypt'in bellek sınırı açıkça verilir: varsayılan (0) bazı OpenSSL
# derlemelerinde n=2^14 için ValueError verir ve özet ile doğrulama aynı sınırı
# kullanmazsa giriş kırılır. 64 MB, n=2^14'ün ~16 MB'ını rahatça karşılar.
SCRYPT_MAXMEM = 64 * 1024 * 1024


def sifre_ozetle(sifre: str) -> dict:
    """Şifrenin tuzlu özeti (docs/19 §3.1). scrypt yoksa pbkdf2'ye düşer."""
    tuz = secrets.token_bytes(16)
    ham = sifre.encode("utf-8")
    try:
        ozet = hashlib.scrypt(ham, salt=tuz, n=2**14, r=8, p=1, dklen=32, maxmem=SCRYPT_MAXMEM)
    except (ValueError, MemoryError):
        ozet = hashlib.pbkdf2_hmac("sha256", ham, tuz, 600000, dklen=32)
        return {
            "alg": "pbkdf2",
            "iter": 600000,
            "tuz": base64.b64encode(tuz).decode(),
            "ozet": base64.b64encode(ozet).decode(),
        }
    return {
        "alg": "scrypt",
        "n": 2**14,
        "r": 8,
        "p": 1,
        "tuz": base64.b64encode(tuz).decode(),
        "ozet": base64.b64encode(ozet).decode(),
    }


def sifre_dogrula(kayit_sifre: object, sifre: str) -> bool:
    """Sabit süreli doğrulama. Kayıttaki parametreler, kullanmadan önce güvenli
    aralığa sınırlanır (ele geçen bir kayıt büyük n ile belleği doldurmasın)."""
    kayit_sifre = _sozluk(kayit_sifre)
    try:
        tuz = base64.b64decode(kayit_sifre.get("tuz", ""), validate=True)
        beklenen = base64.b64decode(kayit_sifre.get("ozet", ""), validate=True)
    except (binascii.Error, ValueError):
        return False
    if not tuz or not beklenen:
        return False
    ham = sifre.encode("utf-8")
    alg = kayit_sifre.get("alg")
    if alg == "scrypt":
        n = _tam(kayit_sifre.get("n"), 2**14, 2**17, varsayilan=2**14)
        r = _tam(kayit_sifre.get("r"), 8, 8, varsayilan=8)
        p = _tam(kayit_sifre.get("p"), 1, 1, varsayilan=1)
        try:
            hesap = hashlib.scrypt(
                ham, salt=tuz, n=n, r=r, p=p, dklen=len(beklenen), maxmem=SCRYPT_MAXMEM
            )
        except (ValueError, MemoryError):
            return False
    elif alg == "pbkdf2":
        tekrar = _tam(kayit_sifre.get("iter"), 600000, 2_000_000, varsayilan=600000)
        hesap = hashlib.pbkdf2_hmac("sha256", ham, tuz, tekrar, dklen=len(beklenen))
    else:
        return False
    return hmac.compare_digest(hesap, beklenen)


_SAHTE_KAYIT: dict | None = None


def _sahte_dogrula(sifre: object) -> None:
    """Bilinmeyen ad ve kurucuda da gerçek hesapla aynı maliyette çalışır:
    varlık, zamanlamadan sızmaz (docs/19 §3.2)."""
    global _SAHTE_KAYIT
    if _SAHTE_KAYIT is None:
        _SAHTE_KAYIT = sifre_ozetle("sahte-parola-zaman-esitleme")
    sifre_dogrula(_SAHTE_KAYIT, sifre if isinstance(sifre, str) else "")


# ------------------------------------------------------------------ hesap


def _ad_gecerli_mi(ad: object) -> bool:
    return isinstance(ad, str) and AD_DESENI.fullmatch(ad) is not None


def ad_duzelt(ham: object) -> str:
    """Baştaki/sondaki boşluk atılır, küçük harfe çevrilir (docs/19 §3.1)."""
    return ham.strip().lower() if isinstance(ham, str) else ""


def hesap_oku(depo: UpstashDepo | BellekDepo, ad: str) -> dict | None:
    (ham,) = depo.al_coklu([KULLANICI_ONEKI + ad])
    return _json_sozluk(ham)


def _oturum_surumu_arttir(depo: UpstashDepo | BellekDepo, ad: str) -> None:
    """Hesabın bütün oturumlarını düşürür: oturum sürümü bir artar (docs/19 §3.1)."""
    hesap = hesap_oku(depo, ad)
    if hesap is None:
        return
    hesap["oturum_surumu"] = _tam(hesap.get("oturum_surumu"), 0, 10**12) + 1
    depo.boru_hatti([_set_komutu(KULLANICI_ONEKI + ad, _kayit_metni(hesap), None)])


# ------------------------------------------------------------------ oturum


def _oturum_anahtari(ayar: Ayar) -> bytes:
    """Çerez imzasının anahtarı şifreden VE rapor anahtarından türer: ele geçen
    bir çerezle şifre çevrimdışı denenemez, kurucu şifresi değişince bütün
    oturumlar düşer."""
    return hashlib.sha256(
        f"dalsan-pano-oturum|{ayar.pano_sifresi}|{ayar.rapor_anahtari}".encode()
    ).digest()


def _cerez_imzasi(ayar: Ayar, ad: str, kimlik: str, surum: int, bitis: int) -> str:
    govde = f"v2|{ad}|{kimlik}|{surum}|{bitis}"
    return hmac.new(_oturum_anahtari(ayar), govde.encode("utf-8"), hashlib.sha256).hexdigest()


def cerez_uret(ayar: Ayar, ad: str, kimlik: str, surum: int, simdi: float) -> str:
    """v2 çerezi: ad nokta içerebilir; çözüm sağdan dört parçayı ayırır."""
    bitis = int(simdi) + OTURUM_SURESI_SN
    imza = _cerez_imzasi(ayar, ad, kimlik, surum, bitis)
    return f"v2.{ad}.{kimlik}.{surum}.{bitis}.{imza}"


def cerez_basligi(deger: str, sure_sn: int) -> str:
    return f"{CEREZ_ADI}={deger}; Max-Age={sure_sn}; Path=/; HttpOnly; Secure; SameSite=Strict"


def _cerez_coz(deger: str) -> tuple[str, str, int, int, str] | None:
    """Biçim denetimi (imza değil): (ad, hesap_kimligi, oturum_surumu, bitis, imza)."""
    if not deger.startswith("v2."):
        return None
    parcalar = deger[3:].rsplit(".", 4)  # ad nokta içerebilir
    if len(parcalar) != 5:
        return None
    ad, kimlik, surum, bitis, imza = parcalar
    if not ad or not _rakam_mi(surum) or not _rakam_mi(bitis):
        return None
    return ad, kimlik, int(surum), int(bitis), imza


@dataclass(frozen=True)
class Oturum:
    ad: str
    rol: str
    hesap_kimligi: str
    oturum_surumu: int
    kurucu: bool
    sifre_degismeli: bool
    imza: str
    bitis: int


def oturum_ozeti(oturum: Oturum) -> dict:
    return {
        "ad": oturum.ad,
        "rol": oturum.rol,
        "rol_adi": ROL_ADLARI.get(oturum.rol, ""),
        "kurucu": oturum.kurucu,
        "sifre_degismeli": oturum.sifre_degismeli,
    }


def _iptal_anahtari(imza: str) -> str:
    return OTURUM_IPTAL_ONEKI + hashlib.sha256(imza.encode()).hexdigest()[:32]


def oturum_coz(depo: UpstashDepo | BellekDepo, ayar: Ayar, deger: str, simdi: float) -> Oturum:
    """Çerezi doğrular ve geçerli oturumu döndürür; rol her istekte kayıttan
    okunur (docs/19 §3.2). Geçersiz çerez: 401 giris_gerekli; süresi dolmuş,
    iptal, hesap yok / kapalı / sürüm tutmuyor: 401 oturum_kapandi."""
    cozum = _cerez_coz(deger)
    if cozum is None:
        raise PanoHatasi(401, "giris_gerekli", GIRIS_GEREKLI_METNI)
    ad, kimlik, surum, bitis, imza = cozum
    beklenen = _cerez_imzasi(ayar, ad, kimlik, surum, bitis)
    if not hmac.compare_digest(beklenen.encode(), imza.encode("utf-8", "replace")):
        raise PanoHatasi(401, "giris_gerekli", GIRIS_GEREKLI_METNI)
    if bitis <= simdi:
        raise PanoHatasi(401, "oturum_kapandi", OTURUM_KAPANDI_METNI)
    iptal_anahtari = _iptal_anahtari(imza)
    if ad == KURUCU_AD:
        (iptal,) = depo.al_coklu([iptal_anahtari])
        if iptal or kimlik != "kurucu" or surum != 0:
            raise PanoHatasi(401, "oturum_kapandi", OTURUM_KAPANDI_METNI)
        return Oturum(KURUCU_AD, "yonetici", "kurucu", 0, True, False, imza, bitis)
    hesap_ham, iptal = depo.al_coklu([KULLANICI_ONEKI + ad, iptal_anahtari])
    hesap = _json_sozluk(hesap_ham)
    if (
        hesap is None
        or hesap.get("acik") is not True
        or iptal
        or hesap.get("hesap_kimligi") != kimlik
        or _tam(hesap.get("oturum_surumu"), 0, 10**12) != surum
    ):
        raise PanoHatasi(401, "oturum_kapandi", OTURUM_KAPANDI_METNI)
    rol = _secim(hesap.get("rol"), ROLLER) or "izleyici"
    return Oturum(ad, rol, kimlik, surum, False, hesap.get("sifre_degismeli") is True, imza, bitis)


# ------------------------------------------------------------------ kilit, giriş


def _adres_normal(adres: str) -> str:
    """IPv6 adreste /64 öneki sayılır (docs/19 §3.2): aynı /64'ten denemeler
    tek sayaçta toplanır."""
    try:
        ip = ipaddress.ip_address(adres.strip())
    except ValueError:
        return adres.strip()
    if ip.version == 6:
        ag = ipaddress.ip_network(f"{ip}/64", strict=False)
        return f"{ag.network_address}/64"
    return str(ip)


def _adres_anahtari(adres: str) -> str:
    """Kilit sayacının anahtarı. IP adresi kişisel veridir: depoya kendisi
    değil, geri çevrilemeyen özeti yazılır (ve 5 dakika sonra silinir)."""
    return GIRIS_ADRES_ONEKI + hashlib.sha256(_adres_normal(adres).encode()).hexdigest()[:24]


def _ad_kilit_anahtari(ad: str) -> str:
    return GIRIS_AD_ONEKI + hashlib.sha256(ad.encode()).hexdigest()[:24]


def giris_dene(
    depo: UpstashDepo | BellekDepo, ayar: Ayar, adres: str, ad_ham: str, sifre: str, simdi: float
) -> tuple[str, str, int]:
    """Giriş: doğruysa (ad, hesap_kimligi, oturum_surumu); değilse PanoHatasi.
    Üç kilit de şifreden önce okunur; başarılı giriş adres sayacını silmez
    (süresi dolar). Kurucu ve bilinmeyen adda da aynı maliyette sahte özet
    çalışır (docs/19 §3.2)."""
    ad = ad_duzelt(ad_ham)
    adres_anahtari = _adres_anahtari(adres)
    ad_anahtari = _ad_kilit_anahtari(ad)
    adres_sayisi, ad_sayisi, genel_sayisi, hesap_ham = depo.al_coklu(
        [adres_anahtari, ad_anahtari, GIRIS_GENEL_ANAHTARI, KULLANICI_ONEKI + ad]
    )
    if int(adres_sayisi or 0) >= KILIT_DENEME:
        raise PanoHatasi(
            429,
            "kilitli",
            f"Bu adresten çok fazla yanlış deneme yapıldı. {KILIT_SURESI_SN // 60} dakika "
            "sonra yeniden deneyin.",
        )
    if int(ad_sayisi or 0) >= AD_KILIT_DENEME:
        raise PanoHatasi(
            429,
            "ad_kilitli",
            "Bu kullanıcı adıyla çok fazla yanlış deneme yapıldı. 15 dakika sonra yeniden deneyin.",
        )
    if int(genel_sayisi or 0) >= GENEL_KILIT_DENEME:
        raise PanoHatasi(
            429,
            "genel_kilit",
            "Kısa sürede çok fazla yanlış deneme geldi; giriş bir süre kapalı. "
            f"{GENEL_KILIT_SURESI_SN // 60} dakika sonra yeniden deneyin.",
        )
    hesap = _json_sozluk(hesap_ham)
    oturum_bilgi: tuple[str, str, int] | None = None
    rol = ""
    if ad == KURUCU_AD:
        _sahte_dogrula(sifre)
        if bool(ayar.pano_sifresi) and hmac.compare_digest(
            sifre.encode("utf-8"), ayar.pano_sifresi.encode("utf-8")
        ):
            oturum_bilgi, rol = (KURUCU_AD, "kurucu", 0), "yonetici"
    elif hesap is not None and _ad_gecerli_mi(ad) and hesap.get("acik") is True:
        if sifre_dogrula(hesap.get("sifre"), sifre):
            oturum_bilgi = (
                ad,
                hesap.get("hesap_kimligi", ""),
                _tam(hesap.get("oturum_surumu"), 0, 10**12),
            )
            rol = _secim(hesap.get("rol"), ROLLER)
    else:
        _sahte_dogrula(sifre)
    if oturum_bilgi is None:
        depo.say(adres_anahtari, KILIT_SURESI_SN)
        depo.say(ad_anahtari, AD_KILIT_SURESI_SN)
        depo.say(GIRIS_GENEL_ANAHTARI, GENEL_KILIT_SURESI_SN)
        # Hatalı giriş kaydı: kim yalnız var olan hesapsa yazılır (bilinmeyen ad yazılmaz)
        kim = ad if (ad == KURUCU_AD or hesap is not None) else ""
        kim_rol = (
            ("yonetici" if ad == KURUCU_AD else _secim(_sozluk(hesap).get("rol"), ROLLER))
            if kim
            else ""
        )
        kayit_yaz(
            depo,
            KAYIT_GIRIS_ANAHTARI,
            _islem_satiri(simdi, kim, kim_rol, "giris_hatali", "", "hata"),
            KAYIT_GIRIS_EN_COK,
        )
        raise PanoHatasi(401, "giris_hatali", GIRIS_HATALI_METNI)
    if ad != KURUCU_AD:
        depo.yaz_coklu([(SON_GIRIS_ONEKI + ad, str(int(simdi)), None)])
    kayit_yaz(
        depo,
        KAYIT_OTURUM_ANAHTARI,
        _islem_satiri(simdi, ad, rol, "giris", "", "tamam"),
        KAYIT_EN_COK,
    )
    return oturum_bilgi


def _onay_hatasi_isle(
    depo: UpstashDepo | BellekDepo, oturum: Oturum, istek: Isleyici, kurucu: bool
) -> None:
    """Yanlış onay / eski şifre: adres ve ad kilit sayaçlarına girer; hesapta 15
    dakikada 5 kez yanlışta bütün oturumlar düşer (docs/19 §3.1-§3.2)."""
    depo.say(_adres_anahtari(istek.istemci_adresi()), KILIT_SURESI_SN)
    depo.say(_ad_kilit_anahtari(oturum.ad), AD_KILIT_SURESI_SN)
    if not kurucu:
        if depo.say(ONAY_HATA_ONEKI + oturum.ad, ONAY_HATA_SURESI_SN) >= ONAY_HATA_SINIR:
            _oturum_surumu_arttir(depo, oturum.ad)


def onay_sifresi_dogrula(
    depo: UpstashDepo | BellekDepo, ayar: Ayar, oturum: Oturum, istek: Isleyici, sifre_ham: object
) -> None:
    """Ağır işler ve hesap işleri işi yapanın KENDİ şifresini ister (kurucuda
    PANO_SIFRESI). Yanlışsa 400 onay_sifresi ve kilit sayaçlarına girer."""
    sifre = sifre_ham if isinstance(sifre_ham, str) else ""
    if oturum.kurucu:
        dogru = bool(ayar.pano_sifresi) and hmac.compare_digest(
            sifre.encode("utf-8"), ayar.pano_sifresi.encode("utf-8")
        )
    else:
        hesap = hesap_oku(depo, oturum.ad)
        dogru = hesap is not None and sifre_dogrula(hesap.get("sifre"), sifre)
    if dogru:
        return
    _onay_hatasi_isle(depo, oturum, istek, oturum.kurucu)
    raise PanoHatasi(400, "onay_sifresi", "Şifreniz yanlış; işlem yapılmadı.")


# ------------------------------------------------------------ istek işleyici


@dataclass(frozen=True)
class Ikili:
    """JSON olmayan cevap (fotoğraf): `calistir` onu olduğu gibi yazar."""

    veri: bytes
    tur: str
    onbellek: str


class Isleyici(BaseHTTPRequestHandler):
    """`api/*.py` dosyalarındaki `handler` sınıflarının ortak tabanı.

    Her adres yalnız kendi yöntemini (`do_POST` gibi) tanımlar; öbür yöntemler
    405 alır.
    """

    # Doluysa cevap bu anahtarla imzalanır (fabrikaya giden komutlar): fabrika
    # programı imzası tutmayan cevaptaki komutu yürütmez.
    yanit_anahtari: str | None = None

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Her isteği Vercel günlüğüne yazmaz; hatalar `calistir` içinde yazılır.
        return

    def yanit(self, kod: int, govde: dict, cerez: str | None = None) -> None:
        veri = json.dumps(govde, ensure_ascii=False).encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(veri)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cerez is not None:
            self.send_header("Set-Cookie", cerez)
        if self.yanit_anahtari:
            damga = str(int(time.time()))
            self.send_header(ZAMAN_BASLIGI, damga)
            self.send_header(IMZA_BASLIGI, imza_hesapla(self.yanit_anahtari, damga, veri))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(veri)

    def ikili_yanit(self, kod: int, ikili: Ikili) -> None:
        self.send_response(kod)
        self.send_header("Content-Type", ikili.tur)
        self.send_header("Content-Length", str(len(ikili.veri)))
        self.send_header("Cache-Control", ikili.onbellek)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(ikili.veri)

    def _izin_yok(self) -> None:
        self.yanit(405, {"hata": "yontem", "mesaj": "Bu adres bu yöntemi kabul etmez."})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _izin_yok

    def govde_oku(self, en_cok: int) -> bytes:
        ham = (self.headers.get("Content-Length") or "0").strip()
        if not _rakam_mi(ham):
            raise PanoHatasi(400, "uzunluk", "İsteğin uzunluğu okunamadı.")
        uzunluk = int(ham)
        if uzunluk > en_cok:
            raise PanoHatasi(413, "cok_buyuk", f"Gönderim çok büyük (en çok {en_cok // 1024} KB).")
        return self.rfile.read(uzunluk)

    def json_govdesi(self, en_cok: int) -> dict:
        """Tarayıcıdan gelen JSON. Düz bir form gönderimi (başka bir sitenin
        sayfasından) bu içerik türünü taşıyamaz; reddedilir."""
        tur = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if tur != "application/json":
            raise PanoHatasi(415, "icerik_turu", "İstek JSON olmalı.")
        try:
            govde = json.loads(self.govde_oku(en_cok) or b"{}")
        except ValueError:
            raise PanoHatasi(400, "json", "İstek okunamadı.") from None
        return _sozluk(govde)

    def cerez_al(self, ad: str) -> str:
        cerezler = http.cookies.SimpleCookie()
        try:
            cerezler.load(self.headers.get("Cookie") or "")
        except http.cookies.CookieError:
            return ""
        return cerezler[ad].value if ad in cerezler else ""

    def sorgu(self, ad: str) -> str:
        degerler = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        return degerler.get(ad, [""])[0]

    def koken_dogrula(self) -> None:
        """Tarayıcı başka bir siteden istek gönderiyorsa reddedilir. Oturum
        çerezi SameSite=Strict olduğu için zaten taşınmaz; bu ikinci kilittir."""
        koken = self.headers.get("Origin")
        if koken is None:
            return
        if urllib.parse.urlsplit(koken).netloc != (self.headers.get("Host") or ""):
            raise PanoHatasi(403, "koken", "Bu istek başka bir siteden geldi; reddedildi.")

    def istemci_adresi(self) -> str:
        """Vercel, istemcinin gerçek adresini X-Real-IP / X-Forwarded-For'a
        kendisi yazar (istemcinin yazdığını ezer)."""
        adres = self.headers.get("X-Real-IP") or ""
        if not adres:
            adres = (self.headers.get("X-Forwarded-For") or "").split(",")[0]
        return adres.strip() or self.client_address[0]

    def calistir(self, islem: Callable[[Isleyici], tuple[int, dict | Ikili, str | None]]) -> None:
        try:
            kod, govde, cerez = islem(self)
        except PanoHatasi as hata:
            self.yanit(hata.kod, hata.govde())
            return
        except DepoHatasi as hata:
            # Vercel'in günlüğüne (Logs sekmesi) düşer; jeton hiçbir zaman yazılmaz.
            print(f"Depo hatası: {hata}", file=sys.stderr)
            self.yanit(
                503,
                {
                    "hata": "depo",
                    "mesaj": "Veri deposuna (Upstash Redis) ulaşılamadı. Birkaç dakika sonra "
                    "yeniden deneyin; sürerse Vercel'de Storage bağlantısına bakın.",
                },
            )
            return
        if isinstance(govde, Ikili):
            self.ikili_yanit(kod, govde)
            return
        self.yanit(kod, govde, cerez)


# ------------------------------------------------------------------ adresler


def _fabrika_istegi(istek: Isleyici, en_cok: int) -> tuple[Ayar, object, float]:
    """Fabrika programından gelen imzalı istek: (ayar, JSON gövdesi, şimdi).
    Gövde imza doğrulanmadan ayrıştırılmaz."""
    ayar = ayar_oku()
    if len(ayar.rapor_anahtari) < ANAHTAR_EN_AZ:
        raise PanoHatasi(
            503,
            "kurulum_eksik",
            f"Sitede RAPOR_ANAHTARI tanımlı değil ya da {ANAHTAR_EN_AZ} karakterden kısa.",
        )
    govde = istek.govde_oku(en_cok)
    simdi = time.time()
    imza_dogrula(
        ayar.rapor_anahtari,
        istek.headers.get(ZAMAN_BASLIGI),
        istek.headers.get(IMZA_BASLIGI),
        govde,
        simdi,
    )
    try:
        ham = json.loads(govde)
    except (ValueError, RecursionError):
        raise PanoHatasi(400, "json", "İstek JSON değil.") from None
    if DEPO is None and not (ayar.redis_adresi and ayar.redis_jetonu):
        raise PanoHatasi(503, "kurulum_eksik", "Sitede Upstash Redis bağlı değil.")
    return ayar, ham, simdi


def rapor_al(istek: Isleyici) -> tuple[int, dict, str | None]:
    """POST /api/rapor - fabrika programının imzalı durum raporu. Cevaptaki
    `komut.hizli`: Müdahale ekranı açık ya da komut bekliyor, fabrika sık sorsun;
    `kare.iste`: Kameralar ekranı açık, fabrika anlık görüntü göndersin."""
    ayar, ham, simdi = _fabrika_istegi(istek, RAPOR_EN_BUYUK_BAYT)
    rapor = rapor_temizle(ham)
    cevap = rapor_kaydet(depo_al(ayar), rapor, simdi)
    return 200, {"tamam": True, "alindi": _iso(simdi), **cevap}, None


def komut_al(istek: Isleyici) -> tuple[int, dict, str | None]:
    """POST /api/komut - fabrika programı sonuçları bildirir ve bekleyen
    komutları alır. İstek de cevap da RAPOR_ANAHTARI ile imzalıdır. Cevap,
    istekteki `nonce`'u taşır (yeniden oynatma koruması) ve `alinan` ile hangi
    sonuçların yazıldığını söyler (docs/19 §3.7)."""
    ayar, ham, simdi = _fabrika_istegi(istek, KOMUT_EN_BUYUK_BAYT)
    if not isinstance(ham, dict) or ham.get("surum") != RAPOR_SURUMU:
        raise PanoHatasi(400, "bicim", "Komut isteğinin biçimi tanınmadı.")
    nonce = ham.get("nonce")
    nonce = nonce if isinstance(nonce, str) and re.fullmatch(r"[0-9a-f]{32}", nonce) else ""
    istek.yanit_anahtari = ayar.rapor_anahtari
    depo = depo_al(ayar)
    alinan = sonuclari_yaz(depo, ham.get("sonuclar"), simdi)
    komutlar, hizli = komutlari_teslim_et(depo, simdi)
    return (
        200,
        {"tamam": True, "nonce": nonce, "alinan": alinan, "komutlar": komutlar, "hizli": hizli},
        None,
    )


def giris(istek: Isleyici) -> tuple[int, dict, str | None]:
    """POST /api/giris - {"ad", "sifre"} doğruysa oturum çerezi verir."""
    ayar = ayar_oku()
    kurulum_tamam_mi(ayar)
    govde = istek.json_govdesi(GIRIS_EN_BUYUK_BAYT)
    ad, sifre = govde.get("ad"), govde.get("sifre")
    if not isinstance(ad, str) or not isinstance(sifre, str) or not ad or not sifre:
        raise PanoHatasi(400, "giris_eksik", "Kullanıcı adı ve şifre gerekir.")
    simdi = time.time()
    ad_son, kimlik, surum = giris_dene(
        depo_al(ayar), ayar, istek.istemci_adresi(), ad, sifre, simdi
    )
    cerez = cerez_uret(ayar, ad_son, kimlik, surum, simdi)
    return 200, {"tamam": True}, cerez_basligi(cerez, OTURUM_SURESI_SN)


def cikis(istek: Isleyici) -> tuple[int, dict, str | None]:
    """POST /api/cikis - oturum çerezini siler ve bu cihazın oturumunu iptal
    eder (docs/19 §3.2). Bozuk çerezde de çerez silinir."""
    ayar = ayar_oku()
    simdi = time.time()
    cozum = _cerez_coz(istek.cerez_al(CEREZ_ADI))
    if cozum is not None:
        ad, kimlik, surum, bitis, imza = cozum
        beklenen = _cerez_imzasi(ayar, ad, kimlik, surum, bitis)
        if (
            hmac.compare_digest(beklenen.encode(), imza.encode("utf-8", "replace"))
            and bitis > simdi
        ):
            try:
                depo = depo_al(ayar)
                depo.yaz_coklu([(_iptal_anahtari(imza), "1", max(1, int(bitis - simdi)))])
                kayit_yaz(
                    depo,
                    KAYIT_OTURUM_ANAHTARI,
                    _islem_satiri(simdi, ad, "", "cikis", "", "tamam"),
                    KAYIT_EN_COK,
                )
            except DepoHatasi:
                pass  # çerez yine silinir; iptal yazımı en iyi çabadır
    return 200, {"tamam": True}, cerez_basligi("", 0)


def _oturumlu(istek: Isleyici) -> tuple[Ayar, float, Oturum]:
    ayar = ayar_oku()
    kurulum_tamam_mi(ayar)
    simdi = time.time()
    oturum = oturum_coz(depo_al(ayar), ayar, istek.cerez_al(CEREZ_ADI), simdi)
    return ayar, simdi, oturum


def durum(istek: Isleyici) -> tuple[int, dict, str | None]:
    """GET /api/durum - panonun verisi; oturum ister. Rol süzgeci: izleyici
    bilgisayarın IP'sini, adını ve fabrika adresini ve yönetim bloğunu görmez;
    yönetim bloğunu yalnız yönetici görür (docs/19 §1). `?mudahale=1` (operatör+)
    ve `?yonetim=1` (yönetici): son komutlar gelir ve fabrika sık sorar.
    `?kare=1`: Kameralar ekranı açık; görüntü zamanları gelir."""
    ayar, simdi, oturum = _oturumlu(istek)
    depo = depo_al(ayar)
    veri = pano_verisi(depo, ayar, simdi)
    veri["oturum"] = oturum_ozeti(oturum)
    veri["onizleme"] = onizleme_mi()
    rapor = veri.get("rapor")
    if oturum.rol != "yonetici" and isinstance(rapor, dict):
        rapor.pop("yonetim", None)  # yönetim bloğunu yalnız yönetici görür
    if oturum.rol == "izleyici":
        veri["fabrika_adresi"] = ""
        if isinstance(rapor, dict) and isinstance(rapor.get("bilgisayar"), dict):
            for alan in ("ip", "bilgisayar_adi"):
                rapor["bilgisayar"].pop(alan, None)
    istiyor_mudahale = istek.sorgu("mudahale") == "1" and oturum.rol in ("operator", "yonetici")
    istiyor_yonetim = istek.sorgu("yonetim") == "1" and oturum.rol == "yonetici"
    if istiyor_mudahale or istiyor_yonetim:
        veri["mudahale"] = mudahale_verisi(depo, simdi, oturum.rol, izliyor=True)
    if istek.sorgu("kare") == "1":
        veri["kareler"] = kare_zamanlari(depo, veri.get("rapor"))
    return 200, veri, None


def _durum_degistiren(istek: Isleyici, en_az_rol: str) -> tuple[Ayar, float, Oturum, dict]:
    """Durum değiştiren POST'ların ortak sırası (docs/19 §3.4): oturum (401) ->
    en az rol (403 yetki) -> köken (403 koken) -> JSON (415). JSON gövdeyi döner;
    sifre_degismeli, önizleme ve işe özgü denetimler çağırana bırakılır."""
    ayar, simdi, oturum = _oturumlu(istek)
    sira = {"izleyici": 0, "operator": 1, "yonetici": 2}
    if sira.get(oturum.rol, -1) < sira[en_az_rol]:
        raise PanoHatasi(403, "yetki", "Bu iş için yetkiniz yok.")
    istek.koken_dogrula()
    govde = istek.json_govdesi(KOMUT_EN_BUYUK_BAYT)
    return ayar, simdi, oturum, govde


def mudahale(istek: Isleyici) -> tuple[int, dict, str | None]:
    """POST /api/mudahale - anons, ses_dene, olay_incele (operatör+); teshis,
    yeniden_baslat, guncelle (yönetici). Ağır işler onay şifresi ister."""
    ayar, simdi, oturum, govde = _durum_degistiren(istek, "operator")
    if oturum.sifre_degismeli:
        raise PanoHatasi(403, "sifre_degismeli", SIFRE_DEGISMELI_METNI)
    if onizleme_mi():
        raise PanoHatasi(409, "onizleme", ONIZLEME_METNI)
    depo = depo_al(ayar)
    tur = _secim(govde.get("tur"), KOMUT_TURLERI)
    if tur in YONETIM_TURLERI and oturum.rol != "yonetici":
        _komut_red_yaz(depo, oturum, f"Yetki yetmedi: {tur}", simdi)
        raise PanoHatasi(403, "yetki", "Bu iş için yönetici yetkisi gerekir.")
    if tur in AGIR_TURLERI:
        onay_sifresi_dogrula(depo, ayar, oturum, istek, govde.get("sifre"))
    kim = {"ad": oturum.ad, "rol": oturum.rol}
    komut = komut_olustur(depo, pano_verisi(depo, ayar, simdi), govde, simdi, kim)
    return 200, {"tamam": True, "komut": komut}, None


# ------------------------------------------------------------------ hesaplar


def _kullanici_satiri(kayit: dict, son: object) -> dict:
    """GET /api/hesap kullanıcı satırı; özet, tuz, hesap_kimligi ASLA dönmez."""
    rol = _secim(kayit.get("rol"), ROLLER) or "izleyici"
    olusturuldu = _tam(kayit.get("olusturuldu"), 0, 10**12)
    return {
        "ad": _metin(kayit.get("ad"), 40),
        "rol": rol,
        "rol_adi": ROL_ADLARI.get(rol, ""),
        "acik": kayit.get("acik") is True,
        "kurucu": False,
        "sifre_degismeli": kayit.get("sifre_degismeli") is True,
        "olusturuldu": _iso(olusturuldu) if olusturuldu else None,
        "son_giris": _iso(int(son)) if isinstance(son, str) and _rakam_mi(son) else None,
    }


def _kayit_gorunumu(kayit: dict) -> dict:
    rol = _secim(kayit.get("rol"), ROLLER)
    z = _tam(kayit.get("z"), 0, 10**12)
    return {
        "z": z,
        "zaman": _iso(z),
        "kim": _metin(kayit.get("kim"), 40),
        "rol": rol,
        "rol_adi": ROL_ADLARI.get(rol, ""),
        "is": _metin(kayit.get("is"), 40),
        "ozet": _metin(kayit.get("ozet"), 200),
        "sonuc": _secim(kayit.get("sonuc"), ("tamam", "hata", "red")),
    }


def _kayit_birlesik(depo: UpstashDepo | BellekDepo) -> list[dict]:
    """Üç işlem kaydı listesini zamana göre birleşik, en yeni başta (docs/19 §3.3)."""
    listeler = depo.boru_hatti(
        [
            ["LRANGE", KAYIT_ANAHTARI, "0", str(KAYIT_BIRLESIK_EN_COK - 1)],
            ["LRANGE", KAYIT_OTURUM_ANAHTARI, "0", str(KAYIT_BIRLESIK_EN_COK - 1)],
            ["LRANGE", KAYIT_GIRIS_ANAHTARI, "0", str(KAYIT_BIRLESIK_EN_COK - 1)],
        ]
    )
    satirlar = []
    for ham_liste in listeler:
        for ham in ham_liste if isinstance(ham_liste, list) else []:
            kayit = _json_sozluk(ham)
            if kayit is not None:
                satirlar.append(_kayit_gorunumu(kayit))
    satirlar.sort(key=lambda s: s["z"], reverse=True)
    return satirlar[:KAYIT_BIRLESIK_EN_COK]


def hesap_verisi(depo: UpstashDepo | BellekDepo, simdi: float) -> dict:
    """Kullanıcı listesi (kurucu başta) ve işlem kaydı. Dizinde kaydı olmayan
    adlar onarılır (yarım oluşturma / yarım silme; docs/19 §3.1)."""
    ham_adlar = depo.komut("LRANGE", KULLANICILAR_ANAHTARI, "0", str(HESAP_EN_COK * 2))
    adlar = [a for a in ham_adlar if isinstance(a, str)] if isinstance(ham_adlar, list) else []
    kayitlar = depo.al_coklu([KULLANICI_ONEKI + a for a in adlar]) if adlar else []
    son_girisler = depo.al_coklu([SON_GIRIS_ONEKI + a for a in adlar]) if adlar else []
    satirlar, eksik = [], []
    for ad, ham, son in zip(adlar, kayitlar, son_girisler, strict=True):
        kayit = _json_sozluk(ham)
        if kayit is None:
            eksik.append(ad)
        else:
            satirlar.append(_kullanici_satiri(kayit, son))
    for ad in eksik:
        depo.komut("LREM", KULLANICILAR_ANAHTARI, "0", ad)
    kurucu = {
        "ad": KURUCU_AD,
        "rol": "yonetici",
        "rol_adi": ROL_ADLARI["yonetici"],
        "acik": True,
        "kurucu": True,
        "sifre_degismeli": False,
        "olusturuldu": None,
        "son_giris": None,
    }
    return {"kullanicilar": [kurucu, *satirlar], "kayit": _kayit_birlesik(depo)}


def hesap_getir(istek: Isleyici) -> tuple[int, dict, str | None]:
    """GET /api/hesap - kullanıcılar ve işlem kaydı; yönetici."""
    ayar, simdi, oturum = _oturumlu(istek)
    if oturum.rol != "yonetici":
        raise PanoHatasi(403, "yetki", "Bu sayfa için yönetici yetkisi gerekir.")
    return 200, hesap_verisi(depo_al(ayar), simdi), None


def _yeni_sifre_dogrula(yeni: object, ad: str) -> str:
    if not isinstance(yeni, str) or len(yeni) < SIFRE_EN_AZ:
        raise PanoHatasi(400, "sifre_kisa", f"Şifre en az {SIFRE_EN_AZ} karakter olmalı.")
    if len(yeni) > SIFRE_EN_UZUN:
        raise PanoHatasi(400, "sifre_uzun", f"Şifre en çok {SIFRE_EN_UZUN} karakter olabilir.")
    if yeni == ad:
        raise PanoHatasi(400, "sifre_ad_ayni", "Şifre kullanıcı adıyla aynı olamaz.")
    return yeni


@contextlib.contextmanager
def _hesap_kilidi(depo: UpstashDepo | BellekDepo, ad: str):
    """Hesap kaydına yazarken kısa ömürlü kilit (docs/19 SITE-B2). Aynı hesaba
    eşzamanlı read-modify-write birbirini ezmesin diye okuma ve yazma tek kilit
    altında yapılır. Kilit alınamazsa kısa bir süre denenir, sonra 409 mesgul
    verilir; kilit her durumda finally'de bırakılır."""
    anahtar = KULLANICI_KILIT_ONEKI + ad
    for deneme in range(HESAP_KILIT_DENEME):
        (alindi,) = depo.boru_hatti([["SET", anahtar, "1", "EX", str(HESAP_KILIT_SURESI_SN), "NX"]])
        if alindi == "OK":
            break
        if deneme + 1 < HESAP_KILIT_DENEME:
            time.sleep(HESAP_KILIT_BEKLEME_SN)
    else:
        raise PanoHatasi(409, "mesgul", HESAP_MESGUL_METNI)
    try:
        yield
    finally:
        depo.sil(anahtar)


def _hesap_sifre_degistir(
    depo: UpstashDepo | BellekDepo,
    ayar: Ayar,
    oturum: Oturum,
    govde: dict,
    simdi: float,
    istek: Isleyici,
) -> tuple[int, dict, str | None]:
    if oturum.kurucu:
        raise PanoHatasi(
            400,
            "kurucu",
            "Kurucu hesabının şifresi burada değişmez: Vercel'de Settings > Environment "
            "Variables > PANO_SIFRESI'ni değiştirip Redeploy edin. Bütün oturumlar kapanır.",
        )
    # Kayıt kilidi altında oku-değiştir-yaz (docs/19 SITE-B2): bir yönetici bu
    # hesabı düşürürken kişinin kendi şifre değişikliği düşürmeyi geri almasın.
    with _hesap_kilidi(depo, oturum.ad):
        hesap = hesap_oku(depo, oturum.ad)
        if hesap is None:
            raise PanoHatasi(401, "oturum_kapandi", OTURUM_KAPANDI_METNI)
        eski = govde.get("eski_sifre")
        if not sifre_dogrula(hesap.get("sifre"), eski if isinstance(eski, str) else ""):
            _onay_hatasi_isle(depo, oturum, istek, kurucu=False)
            raise PanoHatasi(400, "eski_sifre", "Eski şifreniz yanlış; işlem yapılmadı.")
        yeni = _yeni_sifre_dogrula(govde.get("yeni_sifre"), oturum.ad)
        if (
            depo.say(SIFRE_DEGISTIR_SAYAC_ONEKI + oturum.ad, SIFRE_DEGISTIR_PENCERESI_SN)
            > SIFRE_DEGISTIR_SINIRI
        ):
            raise PanoHatasi(
                429, "cok_sik", "Şifrenizi çok sık değiştirdiniz; bir saat sonra yeniden deneyin."
            )
        hesap["sifre"] = sifre_ozetle(yeni)
        hesap["sifre_degismeli"] = False
        hesap["oturum_surumu"] = _tam(hesap.get("oturum_surumu"), 0, 10**12) + 1
        hesap["guncellendi"] = int(simdi)
        depo.boru_hatti([_set_komutu(KULLANICI_ONEKI + oturum.ad, _kayit_metni(hesap), None)])
        kayit_yaz(
            depo,
            KAYIT_ANAHTARI,
            _islem_satiri(simdi, oturum.ad, oturum.rol, "sifre_degistir", "", "tamam"),
            KAYIT_EN_COK,
        )
        yeni_cerez = cerez_uret(
            ayar, oturum.ad, hesap["hesap_kimligi"], hesap["oturum_surumu"], simdi
        )
        return 200, {"tamam": True}, cerez_basligi(yeni_cerez, OTURUM_SURESI_SN)


def _hesap_ekle(
    depo: UpstashDepo | BellekDepo, oturum: Oturum, ad: str, rol: str, govde: dict, simdi: float
) -> tuple[int, dict, str | None]:
    if not _ad_gecerli_mi(ad):
        raise PanoHatasi(
            400,
            "ad_gecersiz",
            "Kullanıcı adı 3-32 karakter; küçük harf, rakam, nokta, tire ve alt çizgi.",
        )
    if ad in AYRILMIS_ADLAR:
        raise PanoHatasi(400, "ad_ayrilmis", "Bu ad sistemde kullanılıyor; başka bir ad seçin.")
    if not rol:
        raise PanoHatasi(400, "rol", "Rol seçilmedi.")
    ilk_sifre = _yeni_sifre_dogrula(govde.get("ilk_sifre"), ad)
    if depo.komut("LLEN", KULLANICILAR_ANAHTARI) >= HESAP_EN_COK:
        raise PanoHatasi(409, "hesap_siniri", f"En çok {HESAP_EN_COK} hesap açılabilir.")
    kimlik = secrets.token_hex(8)
    kayit = {
        "surum": HESAP_SURUMU,
        "ad": ad,
        "hesap_kimligi": kimlik,
        "rol": rol,
        "acik": True,
        "sifre": sifre_ozetle(ilk_sifre),
        "sifre_degismeli": True,
        "oturum_surumu": 1,
        "olusturuldu": int(simdi),
        "olusturan": oturum.ad,
        "guncellendi": int(simdi),
    }
    # Önce dizin (yarım kalsa listeleme onarır), sonra kayıt (NX: ad alınmışsa 409)
    depo.boru_hatti(
        [["LREM", KULLANICILAR_ANAHTARI, "0", ad], ["RPUSH", KULLANICILAR_ANAHTARI, ad]]
    )
    (alindi,) = depo.boru_hatti([["SET", KULLANICI_ONEKI + ad, _kayit_metni(kayit), "NX"]])
    if alindi != "OK":
        raise PanoHatasi(409, "ad_alinmis", "Bu kullanıcı adı zaten var.")
    kayit_yaz(
        depo,
        KAYIT_ANAHTARI,
        _islem_satiri(
            simdi,
            oturum.ad,
            oturum.rol,
            "hesap_ekle",
            f"{ad} ({ROL_ADLARI.get(rol, rol)})",
            "tamam",
        ),
        KAYIT_EN_COK,
    )
    return 200, {"tamam": True, "ad": ad}, None


def _hesap_kaydet(depo: UpstashDepo | BellekDepo, ad: str, hesap: dict, simdi: float) -> None:
    hesap["guncellendi"] = int(simdi)
    depo.boru_hatti([_set_komutu(KULLANICI_ONEKI + ad, _kayit_metni(hesap), None)])


def _hesap_yonet(
    depo: UpstashDepo | BellekDepo,
    ayar: Ayar,
    oturum: Oturum,
    eylem: str,
    govde: dict,
    simdi: float,
    istek: Isleyici,
) -> tuple[int, dict, str | None]:
    hedef_ad = ad_duzelt(govde.get("ad"))
    # Hedef hesabın kaydına yazarken kilit (docs/19 SITE-B2): okuma ve yazma tek
    # kilit altında olsun ki eşzamanlı bir yazma rol/açık değişikliğini ezmesin.
    with _hesap_kilidi(depo, hedef_ad):
        yeni_rol = _secim(govde.get("rol"), ROLLER) if eylem in ("ekle", "rol") else ""
        hedef = None if eylem == "ekle" else hesap_oku(depo, hedef_ad)
        hedef_rol = _secim(_sozluk(hedef).get("rol"), ROLLER) if hedef else ""
        # İşe özgü rol: yönetici hesaplarına dokunan işleri yalnız kurucu yapar (403)
        yonetici_isi = (
            (eylem == "ekle" and yeni_rol == "yonetici")
            or (eylem == "rol" and (yeni_rol == "yonetici" or hedef_rol == "yonetici"))
            or (eylem in ("sifre_sifirla", "kapat", "ac", "sil") and hedef_rol == "yonetici")
        )
        # Kurucuya ve kendine dokunma, yalnız_kurucu'dan önce: kendi yönetici
        # hesabını değiştirmeye çalışan bir yönetici "yalnız kurucu" değil "kendi
        # hesabı"nı görür (docs/19 §3.1).
        if hedef_ad == KURUCU_AD:
            raise PanoHatasi(400, "kurucu", "Kurucu hesabı buradan değiştirilemez.")
        if eylem in ("rol", "kapat", "sil") and hedef_ad == oturum.ad:
            raise PanoHatasi(
                400, "kendi_hesabi", "Kendi hesabınızın bu ayarını buradan değiştiremezsiniz."
            )
        if yonetici_isi and not oturum.kurucu:
            _komut_red_yaz(depo, oturum, f"Yalnız kurucu: {eylem}", simdi)
            raise PanoHatasi(
                403, "yalniz_kurucu", "Yönetici hesaplarını yalnız kurucu hesabı değiştirebilir."
            )
        onay_sifresi_dogrula(depo, ayar, oturum, istek, govde.get("sifre"))
        if (
            depo.say(HESAP_ISLEM_SAYAC_ONEKI + oturum.ad, HESAP_ISLEM_PENCERESI_SN)
            > HESAP_ISLEM_SINIRI
        ):
            raise PanoHatasi(
                429,
                "cok_sik",
                "Kısa sürede çok fazla hesap işlemi yaptınız; 15 dakika sonra yeniden deneyin.",
            )
        if eylem == "ekle":
            return _hesap_ekle(depo, oturum, hedef_ad, yeni_rol, govde, simdi)
        if hedef is None:
            raise PanoHatasi(404, "hesap_yok", "Böyle bir hesap yok.")
        if eylem == "rol":
            if not yeni_rol:
                raise PanoHatasi(400, "rol", "Rol seçilmedi.")
            hedef["rol"] = yeni_rol
            hedef["oturum_surumu"] = _tam(hedef.get("oturum_surumu"), 0, 10**12) + 1
            _hesap_kaydet(depo, hedef_ad, hedef, simdi)
            ozet, is_ = f"{hedef_ad} -> {ROL_ADLARI.get(yeni_rol, yeni_rol)}", "rol_degistir"
        elif eylem == "sifre_sifirla":
            yeni = _yeni_sifre_dogrula(govde.get("yeni_sifre"), hedef_ad)
            hedef["sifre"] = sifre_ozetle(yeni)
            hedef["sifre_degismeli"] = True
            hedef["oturum_surumu"] = _tam(hedef.get("oturum_surumu"), 0, 10**12) + 1
            _hesap_kaydet(depo, hedef_ad, hedef, simdi)
            ozet, is_ = hedef_ad, "sifre_sifirla"
        elif eylem in ("kapat", "ac"):
            hedef["acik"] = eylem == "ac"
            if eylem == "kapat":
                hedef["oturum_surumu"] = _tam(hedef.get("oturum_surumu"), 0, 10**12) + 1
            _hesap_kaydet(depo, hedef_ad, hedef, simdi)
            ozet, is_ = hedef_ad, "hesap_kapat" if eylem == "kapat" else "hesap_ac"
        elif eylem == "sil":
            depo.boru_hatti(
                [["DEL", KULLANICI_ONEKI + hedef_ad], ["DEL", SON_GIRIS_ONEKI + hedef_ad]]
            )
            depo.komut("LREM", KULLANICILAR_ANAHTARI, "0", hedef_ad)
            ozet, is_ = hedef_ad, "hesap_sil"
        else:  # ulaşılmaz (eylem üstte doğrulandı)
            raise PanoHatasi(400, "eylem", "Bilinmeyen işlem.")
        kayit_yaz(
            depo,
            KAYIT_ANAHTARI,
            _islem_satiri(simdi, oturum.ad, oturum.rol, is_, ozet, "tamam"),
            KAYIT_EN_COK,
        )
        return 200, {"tamam": True}, None


def hesap_islem(istek: Isleyici) -> tuple[int, dict, str | None]:
    """POST /api/hesap - {"eylem", ...}; sifre_degistir herkese, ötekiler
    yönetici (docs/19 §3.4). Sıra: oturum -> köken -> JSON -> sifre_degismeli ->
    önizleme -> işe özgü rol -> onay şifresi -> doğrulama."""
    ayar, simdi, oturum, govde = _durum_degistiren(istek, "izleyici")
    eylem = govde.get("eylem")
    if oturum.sifre_degismeli and eylem != "sifre_degistir":
        raise PanoHatasi(403, "sifre_degismeli", SIFRE_DEGISMELI_METNI)
    if onizleme_mi():
        raise PanoHatasi(409, "onizleme", ONIZLEME_METNI)
    depo = depo_al(ayar)
    if eylem == "sifre_degistir":
        return _hesap_sifre_degistir(depo, ayar, oturum, govde, simdi, istek)
    if oturum.rol != "yonetici":
        _komut_red_yaz(depo, oturum, f"Yetki yetmedi: {_metin(eylem, 40)}", simdi)
        raise PanoHatasi(403, "yetki", "Bu iş için yönetici yetkisi gerekir.")
    if eylem not in ("ekle", "rol", "sifre_sifirla", "kapat", "ac", "sil"):
        raise PanoHatasi(400, "eylem", "Bilinmeyen işlem.")
    return _hesap_yonet(depo, ayar, oturum, eylem, govde, simdi, istek)


# ------------------------------------------------------------------ görüntü


def _jpeg_al(ham: object, en_cok: int) -> str:
    """Fabrikanın gönderdiği base64 JPEG; doğrulanmış base64 metni döner.
    JPEG olmayan içerik (bir HTML sayfası gibi) depoya hiç girmez."""
    if not isinstance(ham, str) or not ham:
        raise PanoHatasi(400, "jpeg", "Görüntü (jpeg) eksik.")
    try:
        veri = base64.b64decode(ham, validate=True)
    except (binascii.Error, ValueError):
        raise PanoHatasi(400, "jpeg", "Görüntü base64 değil.") from None
    if len(veri) > en_cok:
        raise PanoHatasi(
            413, "cok_buyuk", f"Görüntü çok büyük (en çok {en_cok // 1024} KB); küçültüp gönderin."
        )
    if not veri.startswith(JPEG_BASI):
        raise PanoHatasi(400, "jpeg", "Görüntü JPEG değil.")
    return ham


def _goruntu_istegi(istek: Isleyici, en_cok: int) -> tuple[Ayar, dict, float]:
    # base64 4/3 büyütür; alanlar için 4 KB pay
    ayar, ham, simdi = _fabrika_istegi(istek, en_cok * 4 // 3 + 4096)
    if not isinstance(ham, dict) or ham.get("surum") != RAPOR_SURUMU:
        raise PanoHatasi(400, "bicim", "Görüntü isteğinin biçimi tanınmadı.")
    return ayar, ham, simdi


def foto_listesi(ham: object, simdi: float) -> list[tuple[int, int]]:
    """Sitedeki kanıt fotoğrafları: (olay_id, geldiği an), en yenisi önde.
    Süresi dolan (fotoğrafı silinmiş) ve bozuk kayıtlar atılır."""
    try:
        liste = json.loads(ham) if isinstance(ham, str) else []
    except ValueError:
        return []
    sonuc = []
    for oge in _liste(liste, FOTO_EN_COK * 2):
        if not (isinstance(oge, list) and len(oge) == 2):
            continue
        kimlik, an = _kimlik(oge[0]), oge[1]
        if kimlik is None or isinstance(an, bool) or not isinstance(an, int):
            continue
        if simdi - an < FOTO_SAKLAMA_SN:
            sonuc.append((kimlik, an))
    return sonuc


def foto_kimlikleri(ham: object, simdi: float) -> set[int]:
    return {kimlik for kimlik, _ in foto_listesi(ham, simdi)}


def foto_al(istek: Isleyici) -> tuple[int, dict, str | None]:
    """POST /api/foto - {"surum": 1, "olay_id": 123, "jpeg": "<base64>"}; imzalı.
    İhlalin kanıt fotoğrafı (küçültülmüş); FOTO_SAKLAMA_SN sonra silinir.
    Listeden taşan (en eski) fotoğraf hemen silinir: depo büyümez."""
    ayar, ham, simdi = _goruntu_istegi(istek, FOTO_EN_BUYUK_BAYT)
    olay_id = _kimlik(ham.get("olay_id"))
    if olay_id is None:
        raise PanoHatasi(400, "olay", "Olay kimliği (olay_id) eksik ya da geçersiz.")
    jpeg = _jpeg_al(ham.get("jpeg"), FOTO_EN_BUYUK_BAYT)
    depo = depo_al(ayar)
    # Fabrika fotoğrafları sırayla gönderir; aynı anda iki yazım yarışmaz.
    # Yarışsa bile kaybolan kayıt bir sonraki raporda yeniden istenir.
    (ham_liste,) = depo.al_coklu([FOTO_LISTESI_ANAHTARI])
    liste = [(k, an) for k, an in foto_listesi(ham_liste, simdi) if k != olay_id]
    liste.insert(0, (olay_id, int(simdi)))
    tasan = [k for k, _ in liste[FOTO_EN_COK:]]
    liste = liste[:FOTO_EN_COK]
    komutlar = [
        _set_komutu(FOTO_ONEKI + str(olay_id), jpeg, FOTO_SAKLAMA_SN),
        _set_komutu(FOTO_LISTESI_ANAHTARI, json.dumps(liste), FOTO_SAKLAMA_SN),
    ]
    if tasan:
        komutlar.append(["DEL", *(FOTO_ONEKI + str(k) for k in tasan)])
    depo.boru_hatti(komutlar)
    return 200, {"tamam": True}, None


def kare_al(istek: Isleyici) -> tuple[int, dict, str | None]:
    """POST /api/kare - {"surum": 1, "kamera_id": 4, "jpeg": "<base64>"}; imzalı.
    Kameranın anlık görüntüsü. Cevaptaki `iste`: Kameralar ekranı hâlâ açık mı;
    hayırsa fabrika göndermeyi bırakır."""
    ayar, ham, simdi = _goruntu_istegi(istek, KARE_EN_BUYUK_BAYT)
    kamera_id = _kimlik(ham.get("kamera_id"))
    if kamera_id is None:
        raise PanoHatasi(400, "kamera", "Kamera kimliği (kamera_id) eksik ya da geçersiz.")
    jpeg = _jpeg_al(ham.get("jpeg"), KARE_EN_BUYUK_BAYT)
    # Zaman sitenin saatiyle yazılır: fabrikanın saati birkaç dakika kaymış
    # olsa da "8 sn önce" doğru çıkar.
    _, _, izleyen = depo_al(ayar).boru_hatti(
        [
            _set_komutu(KARE_ONEKI + str(kamera_id), jpeg, KARE_SAKLAMA_SN),
            _set_komutu(KARE_ZAMAN_ONEKI + str(kamera_id), _iso(simdi), KARE_SAKLAMA_SN),
            ["GET", KARE_IZLEYEN_ANAHTARI],
        ]
    )
    return 200, {"tamam": True, "iste": bool(izleyen)}, None


def kare_zamanlari(depo: UpstashDepo | BellekDepo, rapor: object) -> dict[str, str]:
    """Kameralar ekranı açık: her kameranın son görüntüsünün zamanı. Fabrikaya
    "anlık görüntü gönder" işareti de burada konur (IZLEYEN_SURESI_SN)."""
    kimlikler = [
        k["id"]
        for k in _sozluk(rapor).get("kameralar", [])
        if isinstance(k, dict) and _kimlik(k.get("id"))
    ]
    komutlar: list[list[str]] = [
        _set_komutu(KARE_IZLEYEN_ANAHTARI, "1", IZLEYEN_SURESI_SN),
    ]
    if kimlikler:
        komutlar.append(["MGET", *(KARE_ZAMAN_ONEKI + str(k) for k in kimlikler)])
    sonuc = depo.boru_hatti(komutlar)
    zamanlar = sonuc[1] if len(sonuc) > 1 and isinstance(sonuc[1], list) else []
    return {
        str(kimlik): zaman
        for kimlik, zaman in zip(kimlikler, zamanlar, strict=False)
        if isinstance(zaman, str) and zaman
    }


def _resim_ver(istek: Isleyici, parametre: str, onek: str, onbellek: str) -> tuple:
    """Oturumlu GET: depodaki base64 JPEG'i resim olarak döndürür."""
    ayar, _, _ = _oturumlu(istek)
    deger = istek.sorgu(parametre)
    if not _rakam_mi(deger) or _kimlik(int(deger)) is None:
        raise PanoHatasi(400, parametre, "Geçersiz istek.")
    ham = depo_al(ayar).al_coklu([onek + deger])[0]
    if not ham:
        raise PanoHatasi(404, "yok", "Görüntü yok ya da süresi doldu.")
    try:
        veri = base64.b64decode(ham, validate=True)
    except (binascii.Error, ValueError):
        raise PanoHatasi(404, "yok", "Görüntü okunamadı.") from None
    return 200, Ikili(veri, "image/jpeg", onbellek), None


def foto_ver(istek: Isleyici) -> tuple[int, Ikili, str | None]:
    """GET /api/foto?olay=123 - kanıt fotoğrafı; oturum ister. Fotoğraf
    değişmez: tarayıcı bir gün önbellekte tutar (yalnız bu cihazda)."""
    return _resim_ver(istek, "olay", FOTO_ONEKI, "private, max-age=86400")


def kare_ver(istek: Isleyici) -> tuple[int, Ikili, str | None]:
    """GET /api/kare?kamera=4 - anlık görüntü; oturum ister, önbelleğe alınmaz."""
    return _resim_ver(istek, "kamera", KARE_ONEKI, "no-store")
