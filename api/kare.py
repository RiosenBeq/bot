"""/api/kare - kameraların anlık görüntüsü (yalnız Kameralar ekranı açıkken).

POST: fabrika programı gönderir (imzalı). GET ?kamera=<id>: pano gösterir (oturum).
Vercel bu dosyadaki `handler` sınıfını çalıştırır; işin kendisi `_pano.py`'dedir.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pano import Isleyici, kare_al, kare_ver  # noqa: E402


class handler(Isleyici):  # noqa: N801 - Vercel bu adı arar
    def do_GET(self):  # noqa: N802
        self.calistir(kare_ver)

    def do_POST(self):  # noqa: N802
        self.calistir(kare_al)
