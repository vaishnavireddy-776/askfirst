from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import os
from dotenv import load_dotenv
from datetime import datetime

from database import get_db, init_db, Thread, Message
# At the very top of main.py, after imports
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
load_dotenv()

app = FastAPI(title="AI Chat API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class ThreadCreate(BaseModel):
    title: Optional[str] = "New Thread"

class ThreadUpdate(BaseModel):
    title: str

class ThreadOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class MessageOut(BaseModel):
    id: int
    thread_id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True

class ChatRequest(BaseModel):
    thread_id: int
    message: str


# ── LLM Helper ────────────────────────────────────────────────────────────────

def get_llm_response(messages: list) -> str:
    """
    Calls the configured LLM provider.
    Set LLM_PROVIDER in .env to: openai | gemini | groq
    """
    provider = os.getenv("LLM_PROVIDER", "groq").lower()

    if provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=messages,
        )
        return response.choices[0].message.content

    elif provider == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))
        # Gemini needs a different message format
        history = []
        system_msg = None
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            elif m["role"] == "user":
                history.append({"role": "user", "parts": [m["content"]]})
            elif m["role"] == "assistant":
                history.append({"role": "model", "parts": [m["content"]]})
        chat = model.start_chat(history=history[:-1] if history else [])
        last_user = history[-1]["parts"][0] if history else ""
        if system_msg:
            last_user = f"[System: {system_msg}]\n\n{last_user}"
        response = chat.send_message(last_user)
        return response.text

    elif provider == "groq":
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        response = client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            messages=messages,
        )
        return response.choices[0].message.content

    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}. Use openai, gemini, or groq.")

def build_messages_with_memory(thread_id: int, new_message: str, db: Session) -> list:
    """Build message history with limit to prevent token overflow"""
    all_messages = (
        db.query(Message)
        .order_by(Message.created_at.asc())
        .limit(40)                    # ← Important limit
        .all()
    )
    system_prompt = (
        "You are a helpful AI assistant. "
        "You have memory of all past conversations across all chat threads."
    )
    chat_messages = [{"role": "system", "content": system_prompt}]
    for msg in all_messages:
        chat_messages.append({"role": msg.role, "content": msg.content})
    chat_messages.append({"role": "user", "content": new_message})
    return chat_messages


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    init_db()


# ── Thread Endpoints ──────────────────────────────────────────────────────────

@app.get("/threads", response_model=List[ThreadOut])
def list_threads(db: Session = Depends(get_db)):
    return db.query(Thread).order_by(Thread.updated_at.desc()).all()


@app.post("/threads", response_model=ThreadOut)
def create_thread(body: ThreadCreate, db: Session = Depends(get_db)):
    thread = Thread(title=body.title)
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


@app.patch("/threads/{thread_id}", response_model=ThreadOut)
def rename_thread(thread_id: int, body: ThreadUpdate, db: Session = Depends(get_db)):
    thread = db.query(Thread).filter(Thread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    thread.title = body.title
    db.commit()
    db.refresh(thread)
    return thread


@app.delete("/threads/{thread_id}")
def delete_thread(thread_id: int, db: Session = Depends(get_db)):
    thread = db.query(Thread).filter(Thread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    db.delete(thread)
    db.commit()
    return {"detail": "Thread deleted"}


# ── Message Endpoints ─────────────────────────────────────────────────────────

@app.get("/threads/{thread_id}/messages", response_model=List[MessageOut])
def get_messages(thread_id: int, db: Session = Depends(get_db)):
    thread = db.query(Thread).filter(Thread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return (
        db.query(Message)
        .filter(Message.thread_id == thread_id)
        .order_by(Message.created_at.asc())
        .all()
    )


@app.post("/chat", response_model=MessageOut)
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    thread = db.query(Thread).filter(Thread.id == body.thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    try:
        llm_messages = build_messages_with_memory(body.thread_id, body.message, db)
        reply_text = get_llm_response(llm_messages)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {str(e)}")

    # Save messages
    try:
        user_msg = Message(thread_id=body.thread_id, role="user", content=body.message)
        db.add(user_msg)

        # Auto-title first message
        existing_count = db.query(Message).filter(Message.thread_id == body.thread_id).count()
        if existing_count == 0 and thread.title == "New Thread":
            thread.title = body.message[:50] + ("…" if len(body.message) > 50 else "")

        assistant_msg = Message(thread_id=body.thread_id, role="assistant", content=reply_text)
        db.add(assistant_msg)

        thread.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(assistant_msg)
        return assistant_msg

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/health")
def health():
    return {"status": "ok"}