"""Mongo connection + base document helpers."""
import os
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _coerce_objid(v: Any) -> str:
    if isinstance(v, ObjectId):
        return str(v)
    return v


PyObjectId = Annotated[str, BeforeValidator(_coerce_objid)]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude_none=True)
        if "_id" in data and data["_id"] is None:
            data.pop("_id")
        return data

    @classmethod
    def from_mongo(cls, doc: dict | None):
        if not doc:
            return None
        return cls.model_validate(doc)


_client: AsyncIOMotorClient | None = None
_db: Any = None


def get_db():
    """Return the singleton Mongo database handle, initialising on first call."""
    global _client, _db
    if _db is None:
        _client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        _db = _client[os.environ["DB_NAME"]]
    assert _db is not None  # narrow type for static analyzers
    return _db


def close_db():
    global _client
    if _client is not None:
        _client.close()
