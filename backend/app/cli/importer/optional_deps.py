try:
    from bson import ObjectId
    from pymongo import MongoClient
except Exception:  # pragma: no cover - optional dependency for mongo sync
    MongoClient = None
    ObjectId = None

__all__ = ["MongoClient", "ObjectId"]
