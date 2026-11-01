"""GET /api/bekci - "sistemden haber yok" dış alarmı (docs/20 §3).

Oturum istemez: Vercel Cron `Authorization: Bearer <CRON_SECRET>` ile, dış
izleme servisi aynı başlıkla `BEKCI_ANAHTARI` ile çağırır. Bayat hedef varsa
503 döner. Vercel bu dosyadaki `handler` sınıfını çalıştırır; işin kendisi
`_pano.py`'dedir.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pano import Isleyici, bekci_calistir  # noqa: E402


class handler(Isleyici):  # noqa: N801 - Vercel bu adı arar
    def do_GET(self):  # noqa: N802
        self.calistir(bekci_calistir)
