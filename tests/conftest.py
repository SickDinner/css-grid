from pathlib import Path
import sys

# Ensure repository root (where punkkidoom.py lives) is importable during pytest runs.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
