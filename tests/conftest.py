"""Testler api/_pano.py'yi Vercel'deki gibi `_pano` adıyla içe aktarır."""

import sys
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KOK / "api"))
sys.path.insert(0, str(KOK))
