"""POST /api/cikis - oturum çerezini siler.

Vercel bu dosyadaki `handler` sınıfını çalıştırır; işin kendisi `_pano.py`'dedir.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pano import Isleyici, cikis  # noqa: E402


class handler(Isleyici):  # noqa: N801 - Vercel bu adı arar
    def do_POST(self):  # noqa: N802
        self.calistir(cikis)
