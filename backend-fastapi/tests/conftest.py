"""
conftest.py — pytest config (load .env, set HERMES_HOME stub jika perlu)
"""
import os
import sys
from pathlib import Path

# Set HERMES_HOME to /tmp so any profile-aware code uses temp
os.environ.setdefault("HERMES_HOME", "/tmp/tkm-test-home")
os.environ.setdefault("TZ", "UTC")

# Add backend-fastapi to path
BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND))
