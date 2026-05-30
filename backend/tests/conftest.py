"""Pytest config: load backend .env before any test module is collected.

Why: several broker adapters and the encryption helpers initialize Fernet at
module import time. Without ENCRYPTION_KEY, MONGO_URL, and friends set in
os.environ before `import brokers`, those imports raise ValueError ("Fernet
key must be 32 url-safe base64-encoded bytes") and the entire test module
fails to collect.

Solution: load /app/backend/.env into os.environ *at conftest import time*
(pytest evaluates conftest.py before collecting test_*.py files in the
same directory), and add the backend root to sys.path so test files can
`import brokers`, `import auth_csrf`, etc.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Make backend modules importable from tests.
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Load /app/backend/.env into os.environ. We parse manually rather than rely
# on python-dotenv so this file has no runtime deps.
ENV_PATH = BACKEND_ROOT / ".env"
if ENV_PATH.exists():
    with ENV_PATH.open() as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Don't clobber values already set by the surrounding shell/CI.
            os.environ.setdefault(key, value)

# Tests use anyio-style async fixtures; pytest-asyncio is sufficient. The
# default loop policy works on Linux, no override required.
