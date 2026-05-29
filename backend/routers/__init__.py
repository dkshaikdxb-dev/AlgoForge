"""Per-domain API routers for AlgoForge.

Each router exposes a single FastAPI APIRouter, mounted under /api by server.py.
Shared dependencies (auth, db, ai_service, market_data) are imported at module load.
"""
