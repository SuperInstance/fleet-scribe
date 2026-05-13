"""conftest.py — shared pytest fixtures."""

import sys
from pathlib import Path

# Ensure fleet_scribe is importable
sys.path.insert(0, str(Path(__file__).parent.parent))