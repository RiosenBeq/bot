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
import hashlib
import hmac
import http.cookies
import ipaddress
import json
import math
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
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
# ---- uzaktan müdahale
# Pano yalnız bu işleri isteyebilir; fabrika programı da yalnız bunları tanır.
KOMUT_TURLERI = ("anons", "ses_dene")
KOMUT_DURUMLARI = ("bekliyor", "iletildi", "yapildi", "hata", "suresi_doldu")
KOMUT_SIRA_ANAHTARI = "dalsan:komut:sira"  # fabrikanın henüz almadığı komutlar
KOMUT_SON_ANAHTARI = "dalsan:komut:son"  # panoda görünen son komutların kimliği
KOMUT_KAYIT_ONEKI = "dalsan:komut:kayit:"  # komutun durumu ve sonucu
KOMUT_SAYAC_ANAHTARI = "dalsan:komut:sayac"
# İki işaret fabrikaya "sık sor" der: Müdahale ekranı açık ya da yeni bir komut var.
IZLEYEN_ANAHTARI = "dalsan:mudahale:izleyen"
KOMUT_ISARET_ANAHTARI = "dalsan:komut:isaret"
YOKLAMA_ANAHTARI = "dalsan:komut:yoklama"  # fabrikanın son sorduğu an
# Fabrika komutu bu süre içinde almazsa komut düşer: saatler sonra bağlanan
# bir fabrikada eski bir anons çalmasın.
KOMUT_GECERLILIK_SN = 120
KOMUT_SAKLAMA_SN = 2 * 24 * 3600
KOMUT_SON_SAYISI = 20
KOMUT_GOSTERILEN = 10
# Çalınan bir şifreyle hoparlörler susturulamaz ama yağmur gibi anons da
# yaptırılamasın: 5 dakikada en çok 10 komut.
KOMUT_SINIRI = 10
KOMUT_SINIR_PENCERESI_SN = 300
IZLEYEN_SURESI_SN = 30
YOKLAMA_TOPLU = 5
# Fabrikaya iletilip bu süre sonuç gelmezse panoda "sonuç gelmedi" yazar.
SONUC_BEKLEME_SN = 180
KOMUT_EN_BUYUK_BAYT = 16 * 1024
SURESI_DOLDU_METNI = "Fabrika komutu 2 dakika içinde almadı; yapılmadı."

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

SAYI_ALANLARI = (
    "bugun_ihlal",
    "dun_ihlal",
    "bekleyen",
    "aktif_kural",
    "kamera_toplam",
    "kamera_canli",
)


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


def ayar_oku(ortam: Mapping[str, str] | None = None) -> Ayar:
    """Vercel'in ortam değişkenleri. Upstash bağlantısı iki adla gelebilir:
    Upstash'in kendi adları ya da Vercel'in eski KV adları (README.md)."""
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
        # Sistem olayının açıklaması (şifreler fabrikada gizlenir)
        "ayrinti": _metin(ham.get("ayrinti"), 300),
        "zaman": _zaman(ham.get("zaman")),
        "tur": _secim(ham.get("tur"), OLAY_TURLERI) or "ihlal",
        "baslik": _metin(ham.get("baslik"), 160) or "Olay",
        "yer": _metin(ham.get("yer"), 160),
        "onem": _secim(ham.get("onem"), ONEMLER),
        "onem_adi": _metin(ham.get("onem_adi"), 40),
        "durum_adi": _metin(ham.get("durum_adi"), 40),
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
    return {"acik": ham.get("acik") is True, "mesajlar": mesajlar, "kanallar": kanallar}


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
    return {
        "surum": RAPOR_SURUMU,
        "uretildi": _zaman(ham.get("uretildi")),
        "aralik_sn": _tam(ham.get("aralik_sn"), 5, 3600, varsayilan=30),
        "kapanis": ham.get("kapanis") is True,
        "program": {
            "ad": _metin(program.get("ad"), 60),
            "surum": _metin(program.get("surum"), 40),
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
    }


def rapor_kaydet(depo: UpstashDepo | BellekDepo, rapor: dict, simdi: float) -> dict:
    """Raporu yazar ve fabrikaya cevabı kurar: komutları sık sorsun mu
    (Müdahale ekranı açık ya da komut bekliyor; müdahale kapalıysa hayır),
    anlık görüntü göndersin mi (Kameralar ekranı açık) ve raporundaki hangi
    olayların fotoğrafı sitede zaten var. Hepsi tek komutla okunur."""
    kayit = json.dumps({"rapor": rapor}, ensure_ascii=False, separators=(",", ":"))
    _, _, isaretler = depo.boru_hatti(
        [
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
    )
    if not (isinstance(isaretler, list) and len(isaretler) == 4):
        isaretler = [None] * 4
    izleyen, komut_var, kare, ham_fotolar = isaretler
    fotolar = foto_kimlikleri(ham_fotolar, simdi)
    return {
        "komut": {"hizli": bool(rapor["mudahale"]["acik"] and (izleyen or komut_var))},
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


def komut_gorunumu(kayit: dict, simdi: float) -> dict:
    """Panonun gösterdiği hal. Süresi dolan ya da sonucu gelmeyen komut
    burada adlandırılır: kuyruktaki kayıt kimse sormadan değişmez."""
    durum = _secim(kayit.get("durum"), KOMUT_DURUMLARI) or "hata"
    mesaj = _metin(kayit.get("mesaj"), 300)
    guncellendi = _tam(kayit.get("guncellendi"), 0, 10**12)
    if durum == "bekliyor" and simdi >= _tam(kayit.get("son_gecerlilik"), 0, 10**12):
        durum, mesaj = "suresi_doldu", SURESI_DOLDU_METNI
    elif durum == "iletildi" and simdi - guncellendi > SONUC_BEKLEME_SN:
        durum, mesaj = "sonuc_yok", "Fabrikaya iletildi ama sonucu gelmedi."
    return {
        "id": kayit.get("id") if _komut_kimligi_mi(kayit.get("id")) else "",
        "tur": _secim(kayit.get("tur"), KOMUT_TURLERI),
        "ozet": _metin(kayit.get("ozet"), 300),
        "olusturuldu": _iso(_tam(kayit.get("olusturuldu"), 0, 10**12)),
        "durum": durum,
        "mesaj": mesaj,
    }


def mudahale_verisi(depo: UpstashDepo | BellekDepo, simdi: float, izliyor: bool) -> dict:
    """Müdahale ekranının verisi: son komutlar ve fabrikanın son sorduğu an.
    `izliyor`: ekran açık; fabrika bir sonraki raporda sık sormaya başlar."""
    komutlar = [
        ["LRANGE", KOMUT_SON_ANAHTARI, "0", str(KOMUT_GOSTERILEN - 1)],
        ["GET", YOKLAMA_ANAHTARI],
    ]
    if izliyor:
        komutlar.append(_set_komutu(IZLEYEN_ANAHTARI, "1", IZLEYEN_SURESI_SN))
    sonuc = depo.boru_hatti(komutlar)
    son = sonuc[0] if isinstance(sonuc[0], list) else []
    kimlikler = [kimlik for kimlik in son if _komut_kimligi_mi(kimlik)]
    kayitlar = depo.al_coklu([KOMUT_KAYIT_ONEKI + k for k in kimlikler]) if kimlikler else []
    yoklama = sonuc[1] if isinstance(sonuc[1], str) and _rakam_mi(sonuc[1]) else None
    return {
        "komutlar": [
            komut_gorunumu(kayit, simdi)
            for kayit in map(_json_sozluk, kayitlar)
            if kayit is not None
        ],
        "son_yoklama": _iso(int(yoklama)) if yoklama else None,
        "yoklama_yasi_sn": max(0, round(simdi - int(yoklama))) if yoklama else None,
    }


def komut_olustur(depo: UpstashDepo | BellekDepo, veri: dict, istek: dict, simdi: float) -> dict:
    """Panodan gelen isteği doğrular ve kuyruğa koyar. `veri` pano_verisi'dir:
    seçilen mesaj ve kanal fabrikanın son raporunda olmalı."""
    if veri["baglanti"] != "canli":
        raise PanoHatasi(
            409,
            "fabrika_bagli_degil",
            "Fabrika programından şu an haber gelmiyor; komut gönderilemez.",
        )
    mudahale = _sozluk(_sozluk(veri.get("rapor")).get("mudahale"))
    if mudahale.get("acik") is not True:
        raise PanoHatasi(
            409,
            "mudahale_kapali",
            "Fabrika programında uzaktan müdahale kapalı. Açmak için fabrikadaki "
            "bilgisayarda Ayarlar, Uzak izleme panosu, Uzaktan müdahale'yi seçin.",
        )
    tur = _secim(istek.get("tur"), KOMUT_TURLERI)
    if not tur:
        raise PanoHatasi(400, "tur", "Bilinmeyen müdahale.")
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
    yuk: dict = {"id": secrets.token_hex(8), "tur": tur, "kanal_id": kanal_id}
    if tur == "anons":
        mesajlar = {m["id"]: m for m in mudahale.get("mesajlar", []) if isinstance(m, dict)}
        mesaj_id = _kimlik(istek.get("mesaj_id"))
        if mesaj_id not in mesajlar:
            raise PanoHatasi(400, "mesaj", "Bu anons mesajı fabrikada yok; sayfayı yenileyin.")
        yuk["mesaj_id"] = mesaj_id
        ozet = f"Anons: “{mesajlar[mesaj_id]['metin']}” · {yer}"
    else:
        ozet = f"Hoparlör denemesi · {yer}"
    if depo.say(KOMUT_SAYAC_ANAHTARI, KOMUT_SINIR_PENCERESI_SN) > KOMUT_SINIRI:
        raise PanoHatasi(
            429,
            "cok_sik",
            f"Kısa sürede çok fazla komut gönderildi. {KOMUT_SINIR_PENCERESI_SN // 60} dakika "
            "sonra yeniden deneyin.",
        )
    yuk["son_gecerlilik"] = int(simdi) + KOMUT_GECERLILIK_SN
    kayit = {
        "id": yuk["id"],
        "tur": tur,
        "ozet": ozet,
        "olusturuldu": int(simdi),
        "son_gecerlilik": yuk["son_gecerlilik"],
        "durum": "bekliyor",
        "mesaj": "",
        "guncellendi": int(simdi),
    }
    depo.boru_hatti(
        [
            _set_komutu(KOMUT_KAYIT_ONEKI + yuk["id"], _kayit_metni(kayit), KOMUT_SAKLAMA_SN),
            ["RPUSH", KOMUT_SIRA_ANAHTARI, _kayit_metni(yuk)],
            ["EXPIRE", KOMUT_SIRA_ANAHTARI, str(KOMUT_SAKLAMA_SN)],
            ["LPUSH", KOMUT_SON_ANAHTARI, yuk["id"]],
            ["LTRIM", KOMUT_SON_ANAHTARI, "0", str(KOMUT_SON_SAYISI - 1)],
            ["EXPIRE", KOMUT_SON_ANAHTARI, str(KOMUT_SAKLAMA_SN)],
            _set_komutu(KOMUT_ISARET_ANAHTARI, "1", KOMUT_GECERLILIK_SN),
            _set_komutu(IZLEYEN_ANAHTARI, "1", IZLEYEN_SURESI_SN),
        ]
    )
    return komut_gorunumu(kayit, simdi)


def sonuclari_yaz(depo: UpstashDepo | BellekDepo, ham: object, simdi: float) -> None:
    """Fabrikanın bildirdiği sonuçlar. Yalnız bekleyen ya da iletilmiş komutun
    sonucu yazılır; bitmiş bir komut yeniden açılmaz."""
    sonuclar: dict[str, tuple[str, str]] = {}
    for oge in _liste(ham, 10):
        if not isinstance(oge, dict) or not _komut_kimligi_mi(oge.get("id")):
            continue
        durum = _secim(oge.get("durum"), ("yapildi", "hata"))
        if durum:
            sonuclar[oge["id"]] = (durum, _metin(oge.get("mesaj"), 300))
    if not sonuclar:
        return
    kayitlar = depo.al_coklu([KOMUT_KAYIT_ONEKI + kimlik for kimlik in sonuclar])
    yazilacak = []
    for (kimlik, (durum, mesaj)), ham_kayit in zip(sonuclar.items(), kayitlar, strict=True):
        kayit = _json_sozluk(ham_kayit)
        if kayit is None or kayit.get("durum") not in ("bekliyor", "iletildi"):
            continue
        kayit.update(durum=durum, mesaj=mesaj, guncellendi=int(simdi))
        yazilacak.append(
            _set_komutu(KOMUT_KAYIT_ONEKI + kimlik, _kayit_metni(kayit), KOMUT_SAKLAMA_SN)
        )
    if yazilacak:
        depo.boru_hatti(yazilacak)


def _komut_yuku(ham: object) -> dict | None:
    yuk = _json_sozluk(ham)
    if yuk is None or not _komut_kimligi_mi(yuk.get("id")):
        return None
    tur = _secim(yuk.get("tur"), KOMUT_TURLERI)
    son = yuk.get("son_gecerlilik")
    if not tur or isinstance(son, bool) or not isinstance(son, int):
        return None
    temiz = {"id": yuk["id"], "tur": tur, "kanal_id": _kimlik(yuk.get("kanal_id"))}
    if tur == "anons":
        temiz["mesaj_id"] = _kimlik(yuk.get("mesaj_id"))
    return {**temiz, "son_gecerlilik": son}


def komutlari_teslim_et(depo: UpstashDepo | BellekDepo, simdi: float) -> tuple[list[dict], bool]:
    """Kuyruktan en çok YOKLAMA_TOPLU komutu alır (alınan komut kuyruktan
    çıkar: fabrika yeniden başlasa bile aynı anons ikinci kez çalmaz).
    Döner: (fabrikaya gidecek komutlar, sık sormaya devam etsin mi)."""
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
    teslim, yazilacak = [], []
    for yuk, ham_kayit in zip(yukler, kayitlar, strict=True):
        kayit = _json_sozluk(ham_kayit)
        if kayit is None or kayit.get("durum") != "bekliyor":
            continue  # kaydı olmayan komut yürütülmez
        if simdi >= yuk["son_gecerlilik"]:
            kayit.update(durum="suresi_doldu", mesaj=SURESI_DOLDU_METNI)
        else:
            kayit["durum"] = "iletildi"
            teslim.append({**yuk, "kalan_sn": int(yuk["son_gecerlilik"] - simdi)})
        kayit["guncellendi"] = int(simdi)
        yazilacak.append(
            _set_komutu(KOMUT_KAYIT_ONEKI + yuk["id"], _kayit_metni(kayit), KOMUT_SAKLAMA_SN)
        )
    if yazilacak:
        depo.boru_hatti(yazilacak)
    return teslim, hizli


# -------------------------------------------------------------------- oturum


def _oturum_anahtari(ayar: Ayar) -> bytes:
    """Çerez imzasının anahtarı şifreden VE rapor anahtarından türer: ele geçen
    bir çerezle şifre çevrimdışı denenemez, şifre değişince bütün oturumlar düşer."""
    return hashlib.sha256(
        f"dalsan-pano-oturum|{ayar.pano_sifresi}|{ayar.rapor_anahtari}".encode()
    ).digest()


def cerez_uret(ayar: Ayar, simdi: float) -> str:
    bitis = str(int(simdi) + OTURUM_SURESI_SN)
    imza = hmac.new(_oturum_anahtari(ayar), bitis.encode(), hashlib.sha256).hexdigest()
    return f"{bitis}.{imza}"


def cerez_gecerli_mi(ayar: Ayar, deger: str, simdi: float) -> bool:
    bitis, _, imza = deger.partition(".")
    if not _rakam_mi(bitis) or int(bitis) <= simdi:
        return False
    beklenen = hmac.new(_oturum_anahtari(ayar), bitis.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(beklenen.encode(), imza.encode("utf-8", "replace"))


def cerez_basligi(deger: str, sure_sn: int) -> str:
    return f"{CEREZ_ADI}={deger}; Max-Age={sure_sn}; Path=/; HttpOnly; Secure; SameSite=Strict"


def _adres_anahtari(adres: str) -> str:
    """Kilit sayacının anahtarı. IP adresi kişisel veridir: depoya kendisi
    değil, geri çevrilemeyen özeti yazılır (ve 5 dakika sonra silinir)."""
    return GIRIS_ADRES_ONEKI + hashlib.sha256(adres.encode()).hexdigest()[:24]


def giris_dene(
    depo: UpstashDepo | BellekDepo, ayar: Ayar, adres: str, sifre: str, simdi: float
) -> None:
    """Şifre doğruysa döner; yanlışsa ya da kilitliyse PanoHatasi."""
    adres_anahtari = _adres_anahtari(adres)
    adres_sayisi, genel_sayisi = depo.al_coklu([adres_anahtari, GIRIS_GENEL_ANAHTARI])
    if int(adres_sayisi or 0) >= KILIT_DENEME:
        raise PanoHatasi(
            429,
            "kilitli",
            f"Bu adresten çok fazla yanlış deneme yapıldı. {KILIT_SURESI_SN // 60} dakika "
            "sonra yeniden deneyin.",
        )
    if int(genel_sayisi or 0) >= GENEL_KILIT_DENEME:
        raise PanoHatasi(
            429,
            "genel_kilit",
            "Kısa sürede çok fazla yanlış deneme geldi; giriş bir süre kapalı. "
            f"{GENEL_KILIT_SURESI_SN // 60} dakika sonra yeniden deneyin.",
        )
    dogru = hmac.compare_digest(
        hashlib.sha256(sifre.encode("utf-8")).digest(),
        hashlib.sha256(ayar.pano_sifresi.encode("utf-8")).digest(),
    )
    if not dogru:
        depo.say(adres_anahtari, KILIT_SURESI_SN)
        depo.say(GIRIS_GENEL_ANAHTARI, GENEL_KILIT_SURESI_SN)
        raise PanoHatasi(401, "sifre_yanlis", "Şifre yanlış.")
    if adres_sayisi:
        depo.sil(adres_anahtari)


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
    komutları alır. İstek de cevap da RAPOR_ANAHTARI ile imzalıdır."""
    ayar, ham, simdi = _fabrika_istegi(istek, KOMUT_EN_BUYUK_BAYT)
    if not isinstance(ham, dict) or ham.get("surum") != RAPOR_SURUMU:
        raise PanoHatasi(400, "bicim", "Komut isteğinin biçimi tanınmadı.")
    istek.yanit_anahtari = ayar.rapor_anahtari
    depo = depo_al(ayar)
    sonuclari_yaz(depo, ham.get("sonuclar"), simdi)
    komutlar, hizli = komutlari_teslim_et(depo, simdi)
    return 200, {"tamam": True, "komutlar": komutlar, "hizli": hizli}, None


def giris(istek: Isleyici) -> tuple[int, dict, str | None]:
    """POST /api/giris - {"sifre": "..."} doğruysa oturum çerezi verir."""
    ayar = ayar_oku()
    kurulum_tamam_mi(ayar)
    sifre = istek.json_govdesi(GIRIS_EN_BUYUK_BAYT).get("sifre")
    if not isinstance(sifre, str) or not sifre:
        raise PanoHatasi(400, "sifre_bos", "Şifreyi yazın.")
    simdi = time.time()
    giris_dene(depo_al(ayar), ayar, istek.istemci_adresi(), sifre, simdi)
    return 200, {"tamam": True}, cerez_basligi(cerez_uret(ayar, simdi), OTURUM_SURESI_SN)


def cikis(istek: Isleyici) -> tuple[int, dict, str | None]:
    """POST /api/cikis - oturum çerezini siler."""
    return 200, {"tamam": True}, cerez_basligi("", 0)


def _oturumlu(istek: Isleyici) -> tuple[Ayar, float]:
    ayar = ayar_oku()
    kurulum_tamam_mi(ayar)
    simdi = time.time()
    if not cerez_gecerli_mi(ayar, istek.cerez_al(CEREZ_ADI), simdi):
        raise PanoHatasi(401, "giris_gerekli", "Panoyu görmek için giriş yapın.")
    return ayar, simdi


def durum(istek: Isleyici) -> tuple[int, dict, str | None]:
    """GET /api/durum - panonun verisi; oturum ister. `?mudahale=1`: Müdahale
    ekranı açık; son komutlar da gelir ve fabrika sık sormaya başlar.
    `?kare=1`: Kameralar ekranı açık; kameraların son görüntüsünün zamanı da
    gelir ve fabrika anlık görüntü göndermeye başlar."""
    ayar, simdi = _oturumlu(istek)
    depo = depo_al(ayar)
    veri = pano_verisi(depo, ayar, simdi)
    if istek.sorgu("mudahale") == "1":
        veri["mudahale"] = mudahale_verisi(depo, simdi, izliyor=True)
    if istek.sorgu("kare") == "1":
        veri["kareler"] = kare_zamanlari(depo, veri.get("rapor"))
    return 200, veri, None


def mudahale(istek: Isleyici) -> tuple[int, dict, str | None]:
    """POST /api/mudahale - {"tur": "anons", "mesaj_id": 3, "kanal_id": null}
    ya da {"tur": "ses_dene", "kanal_id": 2}; oturum ister."""
    ayar, simdi = _oturumlu(istek)
    istek.koken_dogrula()
    govde = istek.json_govdesi(KOMUT_EN_BUYUK_BAYT)
    depo = depo_al(ayar)
    komut = komut_olustur(depo, pano_verisi(depo, ayar, simdi), govde, simdi)
    return 200, {"tamam": True, "komut": komut}, None


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
    ayar, _ = _oturumlu(istek)
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
