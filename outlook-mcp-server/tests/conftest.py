"""Pytest configuration."""

import sys
from pathlib import Path

# Ensure src layout on path when running without editable install
_root = Path(__file__).resolve().parents[1]
_src = _root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))
