from __future__ import annotations

import sys
import pathlib

# Ensure project root is importable when running pytest from any working directory.
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

