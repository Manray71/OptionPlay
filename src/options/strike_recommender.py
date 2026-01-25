# Re-export from original location for backwards compatibility
import sys
from pathlib import Path

_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from strike_recommender import *
