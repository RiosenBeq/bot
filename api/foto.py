"""/api/foto - ihlallerin kanıt fotoğrafı.

POST: fabrika programı gönderir (imzalı). GET ?olay=<id>: pano gösterir (oturum).
Vercel bu dosyadaki `handler` sınıfını çalıştırır; işin kendisi `_pano.py`'dedir.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pano import Isleyici, foto_al, foto_ver  # noqa: E402


class handler(Isleyici):  # noqa: N801 - Vercel bu adı arar
    def do_GET(self):  # noqa: N802
        self.calistir(foto_ver)

    def do_POST(self):  # noqa: N802
        self.calistir(foto_al)
