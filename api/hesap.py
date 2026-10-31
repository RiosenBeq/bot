"""/api/hesap - hesaplar ve işlem kaydı (siteden yönetim, docs/19 §3.4).

GET: kullanıcı listesi ve işlem kaydı (yönetici). POST {"eylem", ...}: kendi
şifresini değiştirme (herkes) ve hesap yönetimi (yönetici). Vercel bu dosyadaki
`handler` sınıfını çalıştırır; işin kendisi `_pano.py`'dedir.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pano import Isleyici, hesap_getir, hesap_islem  # noqa: E402


class handler(Isleyici):  # noqa: N801 - Vercel bu adı arar
    def do_GET(self):  # noqa: N802
        self.calistir(hesap_getir)

    def do_POST(self):  # noqa: N802
        self.calistir(hesap_islem)
