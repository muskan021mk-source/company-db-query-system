import os
import asyncio
import traceback
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from agent import ask_agent_async
from db import conversations_collection, ensure_indexes, close_client
from auth import get_current_user_id, get_current_user, _check_employee_in_pg
from auth_routes import router as auth_router

app = FastAPI(title="Company DB Query System")

# ─── Global exception handler ─────────────────────────────────────────────────
# Reshapes FastAPI's {"detail": "..."} to {"detail": "...", "message": "..."}
# so both the backend standard AND the frontend's error.response.data.message
# check work without changing either side.
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail":  exc.detail,
            "message": exc.detail,   # frontend reads this key
            "success": False,
        },
    )

app.include_router(auth_router)

# ─── CORS ─────────────────────────────────────────────────────────────────────
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# ─── Startup / Shutdown ───────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    await ensure_indexes()

@app.on_event("shutdown")
async def on_shutdown():
    close_client()

# ─── Active requests tracker ──────────────────────────────────────────────────
_active_requests: Dict[str, asyncio.Task] = {}

# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/")
def health_check():
    return {"status": "API is running"}

# ─── Chat ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str
    thread_id: str

class StopRequest(BaseModel):
    thread_id: str


def _resolve_actor(current_user: dict, fallback_id: str) -> dict:
    """
    Identity recorded in the audit log for this chat request.

    Looks the person up in the company Postgres database by their verified
    email, so the audit row gets the real users.id (an integer, e.g. 56) and
    their real name. If the lookup fails, the chat still works: the id is
    None (audit_log.actor_id is an integer column) and the name falls back to
    whatever Mongo has, with the Mongo id kept visible for traceability.
    """
    email = (current_user or {}).get("email")
    try:
        pg_user = _check_employee_in_pg(email) if email else None
    except Exception:
        traceback.print_exc()
        pg_user = None

    mongo_emp = str((current_user or {}).get("employeeId") or "").strip()
    if pg_user and pg_user.get("id") is not None and mongo_emp == str(pg_user["id"]):
        return {"id": pg_user["id"], "name": pg_user.get("name") or email}

    display = (current_user or {}).get("name") or email or "unknown"
    return {"id": None, "name": f"{display} [{fallback_id}]"}


@app.post("/chat")
async def chat(
    req: ChatRequest,
    user_id: str = Depends(get_current_user_id),
    current_user: dict = Depends(get_current_user),
):
    if not req.thread_id or not req.thread_id.strip():
        raise HTTPException(status_code=400, detail="thread_id is required")

    # Blocking psycopg2 call, so keep it off the event loop.
    actor = await asyncio.to_thread(_resolve_actor, current_user, user_id)
    if actor["id"] is None:
        raise HTTPException(
            status_code=403,
            detail="Your employee account could not be verified. Please log in again or contact your administrator.",
        )

    # Scope the thread to this employee so nobody can join another person's conversation.
    scoped_thread = f"emp{actor['id']}:{req.thread_id.strip()}"

    task = asyncio.create_task(
        ask_agent_async(
            req.question,
            thread_id=scoped_thread,
            debug=True,
            user=actor,
        )
    )
    _active_requests[scoped_thread] = task

    try:
        result = await task
        return {
            "answer":        result["answer"],
            "visualization": result["structured"],
        }
    except asyncio.CancelledError:
        return {"answer": "Stopped.", "visualization": None, "stopped": True}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Something went wrong processing that request. Please try again.")
    finally:
        if _active_requests.get(scoped_thread) is task:
            _active_requests.pop(scoped_thread, None)


@app.post("/chat/stop")
async def stop_chat(req: StopRequest, current_user: dict = Depends(get_current_user)):
    actor = await asyncio.to_thread(_resolve_actor, current_user, "")
    if actor["id"] is None:
        return {"stopped": False, "detail": "No in-flight request for this thread_id."}
    task = _active_requests.get(f"emp{actor['id']}:{req.thread_id.strip()}")
    if task is None or task.done():
        return {"stopped": False, "detail": "No in-flight request for this thread_id."}
    task.cancel()
    return {"stopped": True}

# ─── Conversations ────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)

class MessageIn(BaseModel):
    role: str
    text: str
    visualization: Optional[dict] = None
    isError: Optional[bool] = None
    isStopped: Optional[bool] = None

class ConversationCreate(BaseModel):
    thread_id: str
    title: str = "New chat"

class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    messages: Optional[List[MessageIn]] = None

def _serialize(doc: dict) -> dict:
    return {
        "id":         str(doc["_id"]),
        "thread_id":  doc["thread_id"],
        "title":      doc["title"],
        "messages":   doc.get("messages", []),
        "created_at": doc["created_at"].isoformat(),
        "updated_at": doc["updated_at"].isoformat(),
    }

@app.get("/conversations")
async def list_conversations(user_id: str = Depends(get_current_user_id)):
    coll = conversations_collection()
    cursor = coll.find({"user_id": user_id}, {"messages": 0}).sort("updated_at", -1)
    out = []
    async for doc in cursor:
        out.append({
            "id":         str(doc["_id"]),
            "thread_id":  doc["thread_id"],
            "title":      doc["title"],
            "created_at": doc["created_at"].isoformat(),
            "updated_at": doc["updated_at"].isoformat(),
        })
    return out

@app.get("/conversations/{thread_id}")
async def get_conversation(thread_id: str, user_id: str = Depends(get_current_user_id)):
    coll = conversations_collection()
    doc = await coll.find_one({"user_id": user_id, "thread_id": thread_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return _serialize(doc)

@app.post("/conversations")
async def create_conversation(body: ConversationCreate, user_id: str = Depends(get_current_user_id)):
    coll = conversations_collection()
    existing = await coll.find_one({"user_id": user_id, "thread_id": body.thread_id})
    if existing:
        return _serialize(existing)

    now = _now()
    doc = {
        "user_id":    user_id,
        "thread_id":  body.thread_id,
        "title":      body.title,
        "messages":   [],
        "created_at": now,
        "updated_at": now,
    }
    result = await coll.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize(doc)

@app.patch("/conversations/{thread_id}")
async def update_conversation(
    thread_id: str,
    body: ConversationUpdate,
    user_id: str = Depends(get_current_user_id),
):
    coll = conversations_collection()
    update_fields: dict = {"updated_at": _now()}
    if body.title is not None:
        update_fields["title"] = body.title
    if body.messages is not None:
        update_fields["messages"] = [m.model_dump() for m in body.messages]

    result = await coll.find_one_and_update(
        {"user_id": user_id, "thread_id": thread_id},
        {"$set": update_fields},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return _serialize(result)

@app.delete("/conversations/{thread_id}")
async def delete_conversation(thread_id: str, user_id: str = Depends(get_current_user_id)):
    coll = conversations_collection()
    result = await coll.delete_one({"user_id": user_id, "thread_id": thread_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"deleted": True}

@app.delete("/conversations")
async def delete_all_conversations(user_id: str = Depends(get_current_user_id)):
    coll = conversations_collection()
    result = await coll.delete_many({"user_id": user_id})
    return {"deleted_count": result.deleted_count}

