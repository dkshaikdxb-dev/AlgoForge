#!/usr/bin/env python3
"""One-off admin promotion CLI.

Usage:
    python /app/backend/scripts/promote_admin.py <email>

Connects to Mongo using the same env vars as the backend and sets
users.role='admin' for the given email. Idempotent.
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


async def main(email: str) -> int:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    res = await db.users.update_one({"email": email.lower()}, {"$set": {"role": "admin"}})
    if res.matched_count == 0:
        print(f"[!] No user with email {email}")
        client.close()
        return 1
    print(f"[✓] Promoted {email} to admin (modified={res.modified_count})")
    client.close()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1])))
