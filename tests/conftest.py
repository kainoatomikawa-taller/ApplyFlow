"""Shared pytest configuration.

Ensures the project root is importable so `src.*` resolves during tests.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
