"""Uzak izleme panosunun ortak çekirdeği.

Vercel'de `api/` altındaki her `.py` dosyası ayrı bir adrestir (`api/rapor.py`
-> `/api/rapor`). Alt çizgiyle başlayan bu dosya adres değildir; onların ortak
parçasıdır. Yalnız Python'un standart kütüphanesi kullanılır: kurulacak paket,
derleme adımı ya da güncellenecek bağımlılık yoktur.

Akış:

    fabrika programı --(imzalı JSON, 30 sn'de bir)--> /api/rapor --> Redis
    tarayıcı --(şifreyle giriş, oturum çerezi)--> /api/durum <-- Redis

Görüntü bu siteye HİÇ gelmez: rapor yalnız durum, sayı ve olay başlığı taşır
(README.md "Siteye ne gelir, ne gelmez"). Ayarlar Vercel'in Environment
Variables ekranından okunur.
"""

from __future__ import annotations

import hashlib
import hmac
import http.cookies
import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
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


class UpstashDepo:
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

    def al_coklu(self, anahtarlar: list[str]) -> list[str | None]:
        sonuc = self.komut("MGET", *anahtarlar)
        if not isinstance(sonuc, list):
            raise DepoHatasi(f"MGET liste döndürmedi: {sonuc!r:.200}")
        return [deger if isinstance(deger, str) else None for deger in sonuc]

    def yaz_coklu(self, kayitlar: list[tuple[str, str, int | None]]) -> None:
        komutlar = []
        for anahtar, deger, sure_sn in kayitlar:
            komut = ["SET", anahtar, deger]
            if sure_sn:
                komut += ["EX", str(sure_sn)]
            komutlar.append(komut)
        self.boru_hatti(komutlar)

    def say(self, anahtar: str, sure_sn: int) -> int:
        """Sayacı bir artırır. Sayaç yoksa `sure_sn` sonra silinmek üzere kurulur;
        varsa süresi uzamaz (pencere ilk denemeden başlar)."""
        sonuc = self.boru_hatti(
            [["SET", anahtar, "0", "EX", str(sure_sn), "NX"], ["INCR", anahtar]]
        )
        return int(sonuc[1])

    def sil(self, anahtar: str) -> None:
        self.komut("DEL", anahtar)


class BellekDepo:
    """Bellekte duran depo. Yalnız testler ve yerel deneme (yerel_sunucu.py)
    içindir: Vercel'de her istek ayrı bir süreçte çalışabilir, bellek paylaşılmaz."""

    def __init__(self, saat: Callable[[], float] = time.time) -> None:
        self.saat = saat
        self._veri: dict[str, tuple[str, float | None]] = {}
        self._kilit = threading.Lock()

    def _gecerli(self, anahtar: str) -> str | None:
        kayit = self._veri.get(anahtar)
        if kayit is None:
            return None
        deger, bitis = kayit
        if bitis is not None and bitis <= self.saat():
            del self._veri[anahtar]
            return None
        return deger

    def al_coklu(self, anahtarlar: list[str]) -> list[str | None]:
        with self._kilit:
            return [self._gecerli(anahtar) for anahtar in anahtarlar]

    def yaz_coklu(self, kayitlar: list[tuple[str, str, int | None]]) -> None:
        with self._kilit:
            for anahtar, deger, sure_sn in kayitlar:
                self._veri[anahtar] = (deger, self.saat() + sure_sn if sure_sn else None)

    def say(self, anahtar: str, sure_sn: int) -> int:
        with self._kilit:
            mevcut = self._gecerli(anahtar)
            if mevcut is None:
                self._veri[anahtar] = ("1", self.saat() + sure_sn)
                return 1
            yeni = int(mevcut) + 1
            self._veri[anahtar] = (str(yeni), self._veri[anahtar][1])
            return yeni

    def sil(self, anahtar: str) -> None:
        with self._kilit:
            self._veri.pop(anahtar, None)


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


def rapor_temizle(ham: object) -> dict:
    """Gelen raporu bilinen alanlara indirger.

    Fabrika programı imzayla doğrulanmış olsa da depoya yalnız bilinen,
    tipi denetlenmiş, kısaltılmış alanlar yazılır: bilinmeyen bir alan
    (ileride biri kazayla fotoğraf eklese bile) bu siteye girmez.
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
            _olay(oge) for oge in _liste(ham.get("son_olaylar"), 50) if isinstance(oge, dict)
        ],
    }


def rapor_kaydet(depo: UpstashDepo | BellekDepo, rapor: dict, simdi: float) -> None:
    kayit = json.dumps({"rapor": rapor}, ensure_ascii=False, separators=(",", ":"))
    depo.yaz_coklu(
        [
            (DURUM_ANAHTARI, kayit, DURUM_SAKLAMA_SN),
            (SON_RAPOR_ANAHTARI, str(int(simdi)), None),
        ]
    )


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds")


def pano_verisi(depo: UpstashDepo | BellekDepo, ayar: Ayar, simdi: float) -> dict:
    """Panonun gösterdiği her şey; bağlantının durumu burada hesaplanır.

    baglanti: "hic" (hiç rapor gelmedi) · "canli" · "yok" (rapor kesildi)
    · "kapandi" (fabrika programı kapatılırken son raporu gönderdi).
    """
    ham_durum, ham_son = depo.al_coklu([DURUM_ANAHTARI, SON_RAPOR_ANAHTARI])
    rapor = None
    if ham_durum:
        try:
            rapor = _sozluk(json.loads(ham_durum)).get("rapor")
        except ValueError:
            rapor = None
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


class Isleyici(BaseHTTPRequestHandler):
    """`api/*.py` dosyalarındaki `handler` sınıflarının ortak tabanı.

    Her adres yalnız kendi yöntemini (`do_POST` gibi) tanımlar; öbür yöntemler
    405 alır.
    """

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
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(veri)

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

    def istemci_adresi(self) -> str:
        """Vercel, istemcinin gerçek adresini X-Real-IP / X-Forwarded-For'a
        kendisi yazar (istemcinin yazdığını ezer)."""
        adres = self.headers.get("X-Real-IP") or ""
        if not adres:
            adres = (self.headers.get("X-Forwarded-For") or "").split(",")[0]
        return adres.strip() or self.client_address[0]

    def calistir(self, islem: Callable[[Isleyici], tuple[int, dict, str | None]]) -> None:
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
        self.yanit(kod, govde, cerez)


# ------------------------------------------------------------------ adresler


def rapor_al(istek: Isleyici) -> tuple[int, dict, str | None]:
    """POST /api/rapor - fabrika programının imzalı durum raporu."""
    ayar = ayar_oku()
    if len(ayar.rapor_anahtari) < ANAHTAR_EN_AZ:
        raise PanoHatasi(
            503,
            "kurulum_eksik",
            f"Sitede RAPOR_ANAHTARI tanımlı değil ya da {ANAHTAR_EN_AZ} karakterden kısa.",
        )
    govde = istek.govde_oku(RAPOR_EN_BUYUK_BAYT)
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
        raise PanoHatasi(400, "json", "Rapor JSON değil.") from None
    rapor = rapor_temizle(ham)
    if DEPO is None and not (ayar.redis_adresi and ayar.redis_jetonu):
        raise PanoHatasi(503, "kurulum_eksik", "Sitede Upstash Redis bağlı değil.")
    rapor_kaydet(depo_al(ayar), rapor, simdi)
    return 200, {"tamam": True, "alindi": _iso(simdi)}, None


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


def durum(istek: Isleyici) -> tuple[int, dict, str | None]:
    """GET /api/durum - panonun verisi; oturum ister."""
    ayar = ayar_oku()
    kurulum_tamam_mi(ayar)
    simdi = time.time()
    if not cerez_gecerli_mi(ayar, istek.cerez_al(CEREZ_ADI), simdi):
        raise PanoHatasi(401, "giris_gerekli", "Panoyu görmek için giriş yapın.")
    return 200, pano_verisi(depo_al(ayar), ayar, simdi), None
