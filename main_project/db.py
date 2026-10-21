import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URL = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME   = os.getenv("MONGODB_DB_NAME", "org_assistant")

_client: AsyncIOMotorClient = None

def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(MONGO_URL)
    return _client

def get_db():
    return get_client()[DB_NAME]

def conversations_collection():
    return get_db()["conversations"]

def users_collection():
    return get_db()["users"]

def otps_collection():
    return get_db()["otps"]

async def ensure_indexes():
    db = get_db()

    # Conversations — fast lookup by user + thread
    await db["conversations"].create_index([("user_id", 1), ("thread_id", 1)], unique=True)
    await db["conversations"].create_index([("user_id", 1), ("updated_at", -1)])

    # Users — unique email and employeeId
    await db["users"].create_index("email", unique=True)
    await db["users"].create_index("employeeId", unique=True)

    # OTPs — auto-expire after 10 minutes
    await db["otps"].create_index("createdAt", expireAfterSeconds=600)
    await db["otps"].create_index("email")

def close_client():
    global _client
    if _client:
        _client.close()
        _client = None