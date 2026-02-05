import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Header, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError
from starlette.requests import Request

# MongoDB imports
try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
    MONGO_AVAILABLE = True
except ImportError:
    MONGO_AVAILABLE = False
    logger.warning("MongoDB libraries not installed. Install pymongo and motor for database storage.")

try:
    # Loads .env from repo root (parent of backend/) for local dev.
    from dotenv import load_dotenv  # type: ignore

    # Try repo root .env first, then backend/.env
    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(repo_root / ".env")
    load_dotenv(repo_root / "backend" / ".env")
except Exception:
    # Optional dependency; backend can still run with exported env vars.
    pass


"""
Hackathon: Public REST API for Honeypot evaluation.

- Platform sends POST to our endpoint with sessionId, message (sender, text, timestamp), conversationHistory, metadata.
- We return ONLY: {"status": "success", "reply": "<agent reply>"}.
- When we decide enough intel is extracted, we MUST POST to hackathon callback URL with the required payload.

Env: GROQ_*, BASE_MODEL, FT_*, CALLBACK_URL (defaults to hackathon URL), HONEYPOT_API_KEY (x-api-key check).
MongoDB: MONGODB_URI (optional, defaults to mongodb://localhost:27017), MONGODB_DB_NAME (defaults to honeypot_db).
"""

_REPO_ROOT = Path(__file__).resolve().parent.parent

# ========== MongoDB Connection ==========
_mongo_client: Optional[Any] = None
_mongo_db: Optional[Any] = None

def _init_mongodb():
    """Initialize MongoDB connection. Reads MONGODB_URI from .env file."""
    global _mongo_client, _mongo_db
    
    if not MONGO_AVAILABLE:
        logger.warning("MongoDB not available - using in-memory storage only")
        return False
    
    # Read from environment (loaded from .env file by dotenv)
    mongo_uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017").strip()
    db_name = os.environ.get("MONGODB_DB_NAME", "honeypot_db").strip()
    
    # Log connection attempt (without exposing credentials)
    if mongo_uri and mongo_uri != "mongodb://localhost:27017":
        logger.info(f"Connecting to MongoDB: {db_name} (URI from .env)")
    else:
        logger.info(f"Using default MongoDB: {db_name} (localhost)")
    
    try:
        _mongo_client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=5000)
        _mongo_db = _mongo_client[db_name]
        # Test connection
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_mongo_client.admin.command('ping'))
        logger.info(f"✅ MongoDB connected successfully: {db_name}")
        return True
    except (ConnectionFailure, ServerSelectionTimeoutError, Exception) as e:
        logger.warning(f"MongoDB connection failed: {e}. Using in-memory storage only.")
        _mongo_client = None
        _mongo_db = None
        return False

# Initialize MongoDB on import
_mongodb_available = _init_mongodb()


def _load_prompt(name: str) -> str:
    path = _REPO_ROOT / "prompts" / name
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


# Honeypot: engagement persona only; NO defensive/safety replies.
# Enhanced prompt that works like fine-tuned model
HONEYPOT_SYSTEM_PROMPT = _load_prompt("enhanced_honeypot_prompt.txt") or _load_prompt("honeypot_system_prompt.txt") or (
    "You are Aman, a real Indian user. Output ONLY JSON: "
    '{"label":"SCAM|NOT_SCAM|UNCERTAIN","confidence":0-1,"reply":"<your message>"}. '
    "Reply must be confused, curious, cooperative; never say contact bank or refuse. Extract details by asking (UPI again, link, bank). "
    "Use full conversation history to maintain continuity. Reference previous messages naturally."
)
INTEL_EXTRACTION_PROMPT = _load_prompt("intel_extraction_prompt.txt") or (
    "Extract from conversation. Output ONLY JSON: "
    '{"upi_ids":[],"links":[],"bank_accounts":[],"phone_numbers":[],"tactics":[]}.'
)

CLASSIFIER_SYSTEM_PROMPT = HONEYPOT_SYSTEM_PROMPT


class ModelOutput(BaseModel):
    label: str
    confidence: float
    reply: str
    raw: str


# ---------- Hackathon contract: request/response ----------
# Hackathon docs: timestamp is "Epoch time format in ms" (number); we accept number or string.
class IncomingMessage(BaseModel):
    sender: str = Field(..., description="e.g. scammer")
    text: str = Field(..., min_length=1, max_length=8000)
    timestamp: Optional[Union[int, float, str]] = Field(None, description="Epoch time in ms (number or string)")


class ConversationHistoryEntry(BaseModel):
    """One turn in conversationHistory; platform may send sender/text or role/content."""
    sender: Optional[str] = None
    text: Optional[str] = None
    role: Optional[str] = None
    content: Optional[str] = None
    timestamp: Optional[Union[int, float, str]] = None


class HackathonRequest(BaseModel):
    """Exact contract: camelCase from platform."""
    sessionId: str = Field(..., min_length=1, alias="sessionId")
    message: IncomingMessage = Field(..., alias="message")
    conversationHistory: Optional[List[ConversationHistoryEntry]] = Field(None, alias="conversationHistory")
    metadata: Optional[Dict[str, Any]] = Field(None, alias="metadata")

    class Config:
        populate_by_name = True


class HackathonResponse(BaseModel):
    """Exact contract: only status and reply."""
    status: str = Field(..., description="Must be 'success'")
    reply: str = Field(..., description="Human-like reply from agent")


def _client():
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:
        raise RuntimeError("Missing dependency `openai`. Install requirements.txt.") from e

    base_url = os.environ.get("GROQ_BASE_URL", "").strip()
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not base_url or not api_key:
        raise RuntimeError("Set GROQ_BASE_URL and GROQ_API_KEY env vars.")
    return OpenAI(base_url=base_url, api_key=api_key)


# FINE-TUNED MODEL CODE COMMENTED OUT - Using base model with enhanced prompt instead
# def _ft_client():
#     """Client for fine-tuned model: uses FT_BASE_URL if set, else same as Groq (base)."""
#     try:
#         from openai import OpenAI  # type: ignore
#     except Exception as e:
#         raise RuntimeError("Missing dependency `openai`. Install requirements.txt.") from e
# 
#     ft_base = os.environ.get("FT_BASE_URL", "").strip()
#     if ft_base:
#         api_key = os.environ.get("FT_API_KEY", "").strip() or "local"
#         return OpenAI(base_url=ft_base.rstrip("/"), api_key=api_key)
#     return _client()

# Always use base client (Groq API)
def _ft_client():
    """Always returns base client - fine-tuned model disabled."""
    return _client()


def _build_conversation_messages(
    conversation_history: List[Dict[str, str]], 
    current_message: str,
    system_prompt: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Build proper chat history with system/user/assistant roles for multi-turn conversations.
    This ensures the model sees full conversation context and can continue naturally.
    """
    prompt = system_prompt or CLASSIFIER_SYSTEM_PROMPT
    messages = [{"role": "system", "content": prompt}]
    
    # Add full conversation history with proper roles
    for msg in conversation_history:
        role = msg.get("role", "user")
        content = msg.get("content", "").strip()
        if not content:
            continue
        
        # Map internal roles to OpenAI chat format
        if role == "scammer":
            messages.append({"role": "user", "content": content})
        elif role == "agent":
            messages.append({"role": "assistant", "content": content})
        else:
            messages.append({"role": role, "content": content})
    
    # Add current message
    messages.append({"role": "user", "content": current_message})
    
    return messages


def _parse_model_output(raw: str, strict: bool = True) -> ModelOutput:
    """Parse raw model text into ModelOutput. If strict, raise 502 on parse/label errors."""
    try:
        parsed: Any = json.loads(raw)
    except Exception:
        if strict:
            raise HTTPException(status_code=502, detail=f"Model did not return valid JSON. raw={raw[:200]}")
        return ModelOutput(
            label="UNCERTAIN",
            confidence=0.5,
            reply=raw[:500] if raw else "(no output)",
            raw=raw,
        )

    # FT/model may return a JSON string or non-dict (e.g. "hello") -> treat as raw text
    if not isinstance(parsed, dict):
        if strict:
            raise HTTPException(status_code=502, detail=f"Model did not return a JSON object. raw={raw[:200]}")
        return ModelOutput(
            label="UNCERTAIN",
            confidence=0.5,
            reply=(raw[:500] if raw else "(no output)"),
            raw=raw,
        )

    label = str(parsed.get("label", "")).strip()
    if not label and parsed.get("is_scam") is not None:
        label = "SCAM" if parsed.get("is_scam") else "NOT_SCAM"
    confidence = float(parsed.get("confidence", 0.0))
    reply = str(parsed.get("reply", "")).strip() or (raw[:300] if raw else "")
    if label not in ("SCAM", "NOT_SCAM", "UNCERTAIN"):
        if strict:
            raise HTTPException(status_code=502, detail=f"Bad label from model: {label}")
        label = "UNCERTAIN"
    return ModelOutput(label=label, confidence=confidence, reply=reply, raw=raw)


def _call_model(
    model: str, 
    conversation_history: List[Dict[str, str]],
    current_message: str,
    use_ft_client: bool = False,  # Ignored now - always uses base model
    max_tokens: int = 512,
    system_prompt: Optional[str] = None,
    use_rag: bool = True  # Enable RAG by default
) -> ModelOutput:
    """
    Call base model with full conversation history, enhanced prompt, and RAG.
    Fine-tuned model disabled - using enhanced prompt + RAG instead.
    """
    # Always use base client (fine-tuned model disabled)
    client = _client()
    
    # Use RAG-enhanced messages if enabled
    if use_rag:
        messages = _build_rag_enhanced_messages(conversation_history, current_message, system_prompt)
    else:
        messages = _build_conversation_messages(conversation_history, current_message, system_prompt)
    
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.3,  # Slight temperature for more natural responses
        max_tokens=max_tokens,
        stop=None,  # Let model decide when to stop naturally
    )
    raw = (resp.choices[0].message.content or "").strip()
    
    # Log for debugging
    logger.debug(f"Model response (first 200 chars): {raw[:200]}")
    
    # Use strict=False for base model to handle parsing errors gracefully
    return _parse_model_output(raw, strict=False)


def _call_llm(system_prompt: str, user_content: str, use_ft_client: bool = True, max_tokens: int = 512) -> str:
    """Single LLM call with given system and user content. Returns raw content."""
    # Always use base model - fine-tuned model disabled
    model = os.environ.get("BASE_MODEL", "").strip()
    if not model:
        raise RuntimeError("Set BASE_MODEL env var.")
    # Always use base client
    client = _client()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


# ---------- Session store (in-memory fallback; keyed by session_id) ----------
_session_store: Dict[str, Dict[str, Any]] = {}


async def _save_to_mongodb(collection: str, document: Dict[str, Any]) -> bool:
    """Save document to MongoDB. Returns True if successful."""
    if not _mongodb_available or not _mongo_db:
        logger.debug(f"MongoDB not available, skipping save to {collection}")
        return False
    
    try:
        result = await _mongo_db[collection].insert_one(document)
        if result.inserted_id:
            logger.info(f"✅ MongoDB: Inserted into {collection}, _id: {result.inserted_id}")
            return True
        else:
            logger.warning(f"⚠️ MongoDB: Insert returned no _id for {collection}")
            return False
    except Exception as e:
        logger.error(f"❌ MongoDB save error to {collection}: {e}", exc_info=True)
        return False


async def _get_from_mongodb(collection: str, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get document from MongoDB. Returns None if not found or error."""
    if not _mongodb_available or not _mongo_db:
        return None
    
    try:
        result = await _mongo_db[collection].find_one(query)
        if result and "_id" in result:
            result["_id"] = str(result["_id"])  # Convert ObjectId to string
        return result
    except Exception as e:
        logger.error(f"MongoDB get error: {e}")
        return None


async def _update_mongodb(collection: str, query: Dict[str, Any], update: Dict[str, Any]) -> bool:
    """Update document in MongoDB. Returns True if successful."""
    if not _mongodb_available or not _mongo_db:
        return False
    
    try:
        result = await _mongo_db[collection].update_one(query, {"$set": update})
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"MongoDB update error: {e}")
        return False


def _get_session(session_id: str) -> Dict[str, Any]:
    """Get session from memory (MongoDB is async, so we use sync in-memory for now)."""
    if session_id not in _session_store:
        _session_store[session_id] = {
            "messages": [],
            "turn_count": 0,
            "scam_detected": False,
            "extracted_intel": {
                "upi_ids": [],
                "links": [],
                "bank_accounts": [],
                "phone_numbers": [],
                "tactics": [],
            },
        }
    return _session_store[session_id]


def _conversation_context(messages: List[Dict[str, str]]) -> str:
    """
    Convert messages to readable text format for logging/debugging.
    Note: This is NOT used for model input - we use _build_conversation_messages instead.
    """
    if not messages:
        return ""
    lines = []
    for m in messages:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if role == "scammer":
            lines.append(f"Scammer: {content}")
        elif role == "agent":
            lines.append(f"Aman: {content}")
        else:
            lines.append(f"{role.capitalize()}: {content}")
    return "\n".join(lines)


# ========== RAG (Retrieval Augmented Generation) Implementation ==========
# Simple in-memory knowledge base for scam patterns and responses
_RAG_KNOWLEDGE_BASE = [
    {
        "pattern": "KYC pending account freeze",
        "keywords": ["kyc", "pending", "freeze", "block", "account"],
        "response_template": "Account freeze? I don't understand. Which company? My UPI is not working, bank details bhej do.",
        "intel_to_extract": ["upi_ids", "links", "bank_accounts"],
        "extraction_strategy": "Show confusion. Ask which company, mention UPI not working, request bank details. Keep it short."
    },
    {
        "pattern": "lottery prize processing fee",
        "keywords": ["lottery", "prize", "processing fee", "lakh", "crore", "won"],
        "response_template": "Lottery? I don't remember entering. Which company? My UPI is not working, bank details bhej do.",
        "intel_to_extract": ["upi_ids", "phone_numbers", "bank_accounts"],
        "extraction_strategy": "Show confusion. Ask which company, mention UPI not working, request bank details. Keep it short."
    },
    {
        "pattern": "parcel customs duty",
        "keywords": ["parcel", "customs", "duty", "courier", "stuck"],
        "response_template": "Parcel stuck? I need it. My UPI is not working, bank details bhej do. Tracking number bhi chahiye.",
        "intel_to_extract": ["upi_ids", "bank_accounts", "phone_numbers"],
        "extraction_strategy": "Show confusion. Mention UPI not working, ask for bank details and tracking. Keep it short and natural."
    },
    {
        "pattern": "refund payment request",
        "keywords": ["refund", "payment", "upi", "transfer", "money"],
        "response_template": "Refund? I don't remember. Which company? My UPI is not working, bank details bhej do.",
        "intel_to_extract": ["upi_ids", "bank_accounts", "ifsc_codes", "phone_numbers"],
        "extraction_strategy": "Show confusion. Ask which company, mention UPI not working, request bank details. Keep it short."
    },
    {
        "pattern": "electricity bill overdue",
        "keywords": ["bill", "overdue", "electricity", "power", "last date"],
        "response_template": "Bill overdue? Which company? My UPI is not working, bank details bhej do.",
        "intel_to_extract": ["links", "upi_ids", "bank_accounts"],
        "extraction_strategy": "Show confusion. Ask which company, mention UPI not working, request bank details. Keep it short."
    },
    {
        "pattern": "IT support remote access",
        "keywords": ["IT", "support", "license", "expired", "anydesk", "teamviewer"],
        "response_template": "License expired? I don't understand. Which company? Where are you working from? Email aur phone bhej do.",
        "intel_to_extract": ["phone_numbers", "emails", "bank_accounts"],
        "extraction_strategy": "Show confusion. Ask which company and where they're from, request email and phone. Keep it short."
    },
    {
        "pattern": "police cyber cell penalty",
        "keywords": ["police", "cyber", "penalty", "case", "legal"],
        "response_template": "Police case? I don't understand. Which station? My UPI is not working, bank details bhej do.",
        "intel_to_extract": ["bank_accounts", "ifsc_codes", "phone_numbers"],
        "extraction_strategy": "Show confusion. Ask which station, mention UPI not working, request bank details. Keep it short."
    },
    {
        "pattern": "crypto investment",
        "keywords": ["crypto", "investment", "guaranteed", "monthly", "deposit"],
        "response_template": "Crypto investment? Which company? Where are you from? My UPI is not working, bank details bhej do.",
        "intel_to_extract": ["links", "upi_ids", "bank_accounts", "phone_numbers"],
        "extraction_strategy": "Show confusion. Ask which company and where they're from, mention UPI not working, request bank details. Keep it short."
    }
]


def _rag_retrieve_context(message_text: str, conversation_history: List[Dict[str, str]]) -> str:
    """
    RAG: Retrieve relevant context from knowledge base based on message content.
    Returns context string to enhance the prompt.
    """
    message_lower = message_text.lower()
    context_parts = []
    
    # Find matching patterns
    for kb_entry in _RAG_KNOWLEDGE_BASE:
        keyword_matches = sum(1 for kw in kb_entry["keywords"] if kw in message_lower)
        if keyword_matches >= 2:  # At least 2 keywords match
            context_parts.append(f"Pattern: {kb_entry['pattern']}")
            context_parts.append(f"Strategy: {kb_entry.get('extraction_strategy', kb_entry['response_template'])}")
            context_parts.append(f"Suggested response: {kb_entry['response_template']}")
            context_parts.append(f"Extract these details: {', '.join(kb_entry['intel_to_extract'])}")
            context_parts.append(f"CRITICAL: Keep response SHORT (1 sentence max, sometimes 2). Sound CONFUSED and needing HELP. Don't be overly emotional. Mention UPI not working, ask for bank details. Ask which company/where they're from. Make it natural, not fake.")
    
    # Add conversation context if available
    if conversation_history:
        recent_messages = conversation_history[-4:]  # Last 4 messages
        recent_context = _conversation_context(recent_messages)
        if recent_context:
            context_parts.append(f"Recent conversation:\n{recent_context}")
    
    return "\n".join(context_parts) if context_parts else ""


def _build_rag_enhanced_messages(
    conversation_history: List[Dict[str, str]], 
    current_message: str,
    system_prompt: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Build messages with RAG context enhancement.
    """
    prompt = system_prompt or HONEYPOT_SYSTEM_PROMPT
    
    # Retrieve RAG context
    rag_context = _rag_retrieve_context(current_message, conversation_history)
    
    messages = [{"role": "system", "content": prompt}]
    
    # Add RAG context if available
    if rag_context:
        messages.append({
            "role": "user", 
            "content": f"Context from knowledge base:\n{rag_context}\n\nUse this context to inform your response."
        })
        messages.append({
            "role": "assistant",
            "content": "Understood. I'll use this context to respond appropriately."
        })
    
    # Add full conversation history
    for msg in conversation_history:
        role = msg.get("role", "user")
        content = msg.get("content", "").strip()
        if not content:
            continue
        
        if role == "scammer":
            messages.append({"role": "user", "content": content})
        elif role == "agent":
            messages.append({"role": "assistant", "content": content})
        else:
            messages.append({"role": role, "content": content})
    
    # Add current message
    messages.append({"role": "user", "content": current_message})
    
    return messages


def _extract_intel_from_convo(
    conversation_history: List[Dict[str, str]], 
    previous_intel: Optional[Dict[str, List[str]]] = None
) -> Dict[str, List[str]]:
    """
    Incrementally extract intelligence from conversation.
    Merges with previous extractions to avoid losing data.
    """
    if not conversation_history:
        return previous_intel or {"upi_ids": [], "links": [], "bank_accounts": [], "phone_numbers": [], "tactics": []}
    
    # Convert to text for extraction prompt
    convo_text = _conversation_context(conversation_history)
    if not convo_text.strip():
        return previous_intel or {"upi_ids": [], "links": [], "bank_accounts": [], "phone_numbers": [], "tactics": []}
    
    user_content = f"Conversation:\n{convo_text}\n\nExtract intelligence. Output ONLY the JSON object."
    raw = _call_llm(INTEL_EXTRACTION_PROMPT, user_content, use_ft_client=True, max_tokens=512)
    
    try:
        parsed = json.loads(raw)
        new_intel = {
            "upi_ids": list(parsed.get("upi_ids", []) or []),
            "links": list(parsed.get("links", []) or []),
            "bank_accounts": list(parsed.get("bank_accounts", []) or []),
            "phone_numbers": list(parsed.get("phone_numbers", []) or []),
            "tactics": list(parsed.get("tactics", []) or []),
        }
        
        # Merge with previous intelligence (deduplicate)
        if previous_intel:
            for key in new_intel:
                existing = set(previous_intel.get(key, []))
                new_items = set(new_intel[key])
                merged = list(existing | new_items)  # Union
                new_intel[key] = merged
        
        return new_intel
    except Exception as e:
        logger.warning(f"Intel extraction failed: {e}, using previous intel")
        return previous_intel or {"upi_ids": [], "links": [], "bank_accounts": [], "phone_numbers": [], "tactics": []}


def _intel_count(intel: Dict[str, List[str]]) -> int:
    return sum(len(v) for v in intel.values() if isinstance(v, list))


def _should_stop(session: Dict[str, Any], max_turns: int = 100, min_intel_items: int = 20) -> bool:
    """
    Stop when enough intel collected or max turns reached.
    Updated to allow continuous conversations for testing.
    
    Set AUTO_END_CONVERSATION=false in env to disable auto-ending entirely.
    """
    # Check if auto-ending is disabled (for testing/continuous conversations)
    auto_end = os.environ.get("AUTO_END_CONVERSATION", "true").lower() not in ("false", "0", "no")
    if not auto_end:
        logger.debug("Auto-ending disabled - conversation continues indefinitely")
        return False
    
    # Get configurable limits from env vars (for flexibility)
    max_turns_env = os.environ.get("MAX_CONVERSATION_TURNS", "")
    if max_turns_env:
        try:
            max_turns = int(max_turns_env)
        except ValueError:
            pass  # Use default
    
    min_intel_env = os.environ.get("MIN_INTEL_ITEMS", "")
    if min_intel_env:
        try:
            min_intel_items = int(min_intel_env)
        except ValueError:
            pass  # Use default
    
    # Only stop if we've reached a very high threshold (allows continuous conversation)
    if session["turn_count"] >= max_turns:
        logger.info(f"Stopping: max turns reached ({session['turn_count']} >= {max_turns})")
        return True
    count = _intel_count(session["extracted_intel"])
    if count >= min_intel_items:
        logger.info(f"Stopping: enough intel extracted ({count} >= {min_intel_items})")
        return True
    return False


# Mandatory callback URL for hackathon scoring (override via CALLBACK_URL env if needed).
HACKATHON_CALLBACK_URL = "https://hackathon.guvi.in/api/updateHoneyPotFinalResult"


def _agent_notes(session: Dict[str, Any]) -> str:
    """Short summary of scam behavior for callback agentNotes."""
    intel = session.get("extracted_intel", {})
    parts = []
    for k, v in (intel or {}).items():
        if v and isinstance(v, list):
            parts.append(f"{k}: {', '.join(str(x) for x in v[:5])}")
    return "; ".join(parts) if parts else "Conversation ended."


def _send_callback(session_id: str, session: Dict[str, Any], reply: str) -> bool:
    """POST to hackathon callback URL with exact payload format. Returns True if sent."""
    url = (os.environ.get("CALLBACK_URL", "").strip() or HACKATHON_CALLBACK_URL)
    intel = session.get("extracted_intel", {}) or {}
    payload_obj = {
        "sessionId": session_id,
        "scamDetected": session.get("scam_detected", False),
        "totalMessagesExchanged": session.get("turn_count", 0),
        "extractedIntelligence": {
            "bankAccounts": list(intel.get("bank_accounts", []) or []),
            "upiIds": list(intel.get("upi_ids", []) or []),
            "phishingLinks": list(intel.get("links", []) or []),
            "phoneNumbers": list(intel.get("phone_numbers", []) or []),
            "suspiciousKeywords": list(intel.get("tactics", []) or []),
        },
        "agentNotes": _agent_notes(session),
    }
    try:
        import urllib.request
        payload = json.dumps(payload_obj).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


app = FastAPI()


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Better error messages for 422 validation errors."""
    errors = []
    for error in exc.errors():
        field = " -> ".join(str(x) for x in error.get("loc", []))
        msg = error.get("msg", "Validation error")
        error_type = error.get("type", "unknown")
        errors.append(f"{field}: {msg} (type: {error_type})")
    
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Validation error. Check your request format.",
            "errors": errors,
            "expected_format": {
                "sessionId": "string (required)",
                "message": {
                    "sender": "string (required, e.g. 'scammer')",
                    "text": "string (required, min 1 char, max 8000 chars)",
                    "timestamp": "number or string (optional, epoch ms e.g. 1770005528731)"
                },
                "conversationHistory": "array (optional)",
                "metadata": "object (optional)"
            }
        }
    )


# Allow the Next.js dev server (localhost:3000) to call the API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# So the browser shows the real error instead of "blocked by CORS" when backend returns 4xx/5xx.
CORS_ORIGINS = {"http://localhost:3000", "http://127.0.0.1:3000"}


def _cors_headers(request: Request) -> dict:
    origin = request.headers.get("origin") or "http://localhost:3000"
    if origin not in CORS_ORIGINS:
        origin = "http://localhost:3000"
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=_cors_headers(request),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {str(exc)[:400]}"},
        headers=_cors_headers(request),
    )


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Health check endpoint with MongoDB status."""
    mongo_status = "connected" if _mongodb_available else "not_available"
    
    # Test MongoDB connection
    mongo_test = False
    if _mongodb_available and _mongo_client:
        try:
            await _mongo_client.admin.command('ping')
            mongo_test = True
        except Exception as e:
            logger.warning(f"MongoDB ping failed: {e}")
    
    return {
        "status": "ok",
        "mongodb": mongo_status,
        "mongodb_available": _mongodb_available,
        "mongodb_connected": mongo_test,
        "database": _mongo_db.name if _mongo_db else None
    }


@app.get("/debug/session/{session_id}")
def get_session_debug(session_id: str) -> Dict[str, Any]:
    """
    Debug endpoint to get session data including extracted intelligence.
    Useful for testing and demos.
    """
    session = _get_session(session_id)
    
    return {
        "session_id": session_id,
        "turn_count": session.get("turn_count", 0),
        "scam_detected": session.get("scam_detected", False),
        "extracted_intelligence": session.get("extracted_intel", {}),
        "conversation_history": session.get("messages", []),
        "intel_count": _intel_count(session.get("extracted_intel", {})),
    }


@app.get("/debug/mongodb/stats")
async def get_mongodb_stats() -> Dict[str, Any]:
    """Debug endpoint to check MongoDB collections and counts."""
    if not _mongodb_available or not _mongo_db:
        return {
            "mongodb_available": False,
            "message": "MongoDB not connected"
        }
    
    try:
        collections = await _mongo_db.list_collection_names()
        stats = {}
        for coll_name in collections:
            count = await _mongo_db[coll_name].count_documents({})
            stats[coll_name] = count
        
        return {
            "mongodb_available": True,
            "database": _mongo_db.name,
            "collections": stats,
            "total_collections": len(collections)
        }
    except Exception as e:
        return {
            "mongodb_available": True,
            "error": str(e)
        }


@app.get("/debug/mongodb/session/{session_id}")
async def get_mongodb_session(session_id: str) -> Dict[str, Any]:
    """Debug endpoint to get session data from MongoDB."""
    if not _mongodb_available or not _mongo_db:
        return {
            "mongodb_available": False,
            "message": "MongoDB not connected"
        }
    
    try:
        session = await _get_from_mongodb("sessions", {"session_id": session_id})
        if not session:
            return {
                "found": False,
                "session_id": session_id,
                "message": "Session not found in MongoDB"
            }
        
        # Get related data
        requests = list(await _mongo_db["requests"].find({"session_id": session_id}).to_list(length=100))
        responses = list(await _mongo_db["responses"].find({"session_id": session_id}).to_list(length=100))
        messages = list(await _mongo_db["messages"].find({"session_id": session_id}).sort("timestamp", 1).to_list(length=100))
        
        # Convert ObjectIds to strings
        for doc in requests + responses + messages:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
        
        return {
            "found": True,
            "session": session,
            "requests_count": len(requests),
            "responses_count": len(responses),
            "messages_count": len(messages),
            "requests": requests[:5],  # First 5
            "responses": responses[:5],
            "messages": messages[:10]
        }
    except Exception as e:
        return {
            "error": str(e)
        }


def _require_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> None:
    """If HONEYPOT_API_KEY is set, require X-API-Key header to match. Otherwise allow (local dev)."""
    expected = os.environ.get("HONEYPOT_API_KEY", "").strip()
    if not expected:
        return
    if not x_api_key or x_api_key.strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header.")


def _normalize_history(entries: Optional[List[ConversationHistoryEntry]]) -> List[Dict[str, str]]:
    """Convert platform conversationHistory to internal [{role, content}]."""
    if not entries:
        return []
    out = []
    for t in entries:
        content = (t.text or t.content or "").strip()
        if not content:
            continue
        role = (t.sender or t.role or "scammer").lower()
        if role in ("scammer", "user"):
            out.append({"role": "scammer", "content": content})
        else:
            out.append({"role": "agent", "content": content})
    return out


@app.post("/v1/chat", response_model=HackathonResponse)
async def v1_chat(
    req: HackathonRequest,
    background_tasks: BackgroundTasks,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> HackathonResponse:
    """
    Hackathon evaluation API. One message per request.
    Request: sessionId, message { sender, text, timestamp }, conversationHistory, metadata.
    Response: ONLY { "status": "success", "reply": "<agent reply>" }.
    When enough intel is extracted, we POST to hackathon callback URL (mandatory for scoring).
    
    FIXED: Now properly handles multi-turn conversations with full history.
    All data is stored in MongoDB for persistence.
    """
    _require_api_key(x_api_key)
    session_id = req.sessionId
    message_text = (req.message.text or "").strip()
    if not message_text:
        raise HTTPException(status_code=400, detail="message.text is required.")
    
    # Store incoming request to MongoDB (background task)
    request_doc = {
        "session_id": session_id,
        "timestamp": datetime.utcnow().isoformat(),
        "request": {
            "sessionId": req.sessionId,
            "message": {
                "sender": req.message.sender,
                "text": req.message.text,
                "timestamp": req.message.timestamp,
            },
            "conversationHistory": [dict(h) for h in (req.conversationHistory or [])],
            "metadata": req.metadata or {},
        },
        "api_key_provided": x_api_key is not None,
    }
    
    # Store request to MongoDB (with logging)
    async def save_request():
        try:
            result = await _save_to_mongodb("requests", request_doc)
            if result:
                logger.info(f"✅ MongoDB: Saved request for session {session_id}")
            else:
                logger.warning(f"⚠️ MongoDB: Failed to save request for session {session_id} (MongoDB not available)")
        except Exception as e:
            logger.error(f"❌ MongoDB request save error: {e}", exc_info=True)
    
    background_tasks.add_task(save_request)
    
    session = _get_session(session_id)
    
    # Update session messages from platform's conversationHistory if provided
    if req.conversationHistory is not None:
        normalized = _normalize_history(req.conversationHistory)
        # Merge with existing session messages (platform may send partial history)
        if normalized:
            session["messages"] = normalized
    
    # Get current conversation history (without current message)
    conversation_history = session["messages"].copy()
    
    # PHASE 1: Classification (if first message or not yet detected)
    # Using base model with enhanced prompt + RAG
    base_model = os.environ.get("BASE_MODEL", "").strip()
    if not base_model:
        raise HTTPException(status_code=500, detail="BASE_MODEL env var not set.")
    
    if not session["scam_detected"]:
        try:
            # Quick classification on first message (with RAG)
            classify_out = _call_model(
                base_model,
                [],  # No history for first classification
                message_text,
                use_ft_client=False,  # Always use base model
                max_tokens=256,
                system_prompt=CLASSIFIER_SYSTEM_PROMPT,
                use_rag=True,  # Enable RAG for classification
            )
            scam_detected = (classify_out.label == "SCAM") or (classify_out.label == "UNCERTAIN" and classify_out.confidence >= 0.5)
            session["scam_detected"] = scam_detected
            logger.info(f"Classification: {classify_out.label} (confidence: {classify_out.confidence})")
        except Exception as e:
            logger.warning(f"Classification failed: {e}, assuming uncertain")
            session["scam_detected"] = False
    
    # PHASE 2: Agent Engagement (if scam detected, or continue conversation)
    # Use full conversation history + RAG for natural multi-turn behavior
    try:
        out = _call_model(
            base_model,  # Always use base model
            conversation_history,  # Full history for context
            message_text,  # Current message
            use_ft_client=False,  # Always use base model
            max_tokens=80,  # Keep responses very short (1 sentence, max 2) - like real texting
            system_prompt=HONEYPOT_SYSTEM_PROMPT,
            use_rag=True,  # Enable RAG for engagement
        )
        logger.info(f"Model reply length: {len(out.reply)} chars")
    except Exception as e:
        logger.error(f"LLM error: {type(e).__name__}: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail=f"LLM error: {type(e).__name__}: {str(e)[:200]}",
        ) from e
    
    # Update session with new messages
    session["messages"].append({"role": "scammer", "content": message_text})
    session["messages"].append({"role": "agent", "content": out.reply})
    session["turn_count"] = len([m for m in session["messages"] if m.get("role") == "agent"])
    
    # PHASE 3: Incremental Intelligence Extraction
    # Extract from full conversation, merge with previous
    session["extracted_intel"] = _extract_intel_from_convo(
        session["messages"],
        session.get("extracted_intel")
    )
    
    # Store response and conversation data to MongoDB (background tasks)
    response_doc = {
        "session_id": session_id,
        "timestamp": datetime.utcnow().isoformat(),
        "response": {
            "status": "success",
            "reply": out.reply,
        },
        "model_output": {
            "label": out.label,
            "confidence": out.confidence,
        },
        "session_state": {
            "turn_count": session["turn_count"],
            "scam_detected": session["scam_detected"],
            "extracted_intel": session["extracted_intel"],
        },
    }
    # Store response to MongoDB
    async def save_response():
        try:
            result = await _save_to_mongodb("responses", response_doc)
            if result:
                logger.info(f"✅ MongoDB: Saved response for session {session_id}")
            else:
                logger.warning(f"⚠️ MongoDB: Failed to save response for session {session_id}")
        except Exception as e:
            logger.error(f"❌ MongoDB response save error: {e}", exc_info=True)
    
    background_tasks.add_task(save_response)
    
    # Store full conversation messages
    message_doc = {
        "session_id": session_id,
        "timestamp": datetime.utcnow().isoformat(),
        "message": {
            "role": "scammer",
            "content": message_text,
            "sender": req.message.sender,
            "original_timestamp": req.message.timestamp,
        },
    }
    
    async def save_scammer_message():
        try:
            result = await _save_to_mongodb("messages", message_doc)
            if result:
                logger.info(f"✅ MongoDB: Saved scammer message for session {session_id}")
            else:
                logger.warning(f"⚠️ MongoDB: Failed to save scammer message for session {session_id}")
        except Exception as e:
            logger.error(f"❌ MongoDB message save error: {e}", exc_info=True)
    
    background_tasks.add_task(save_scammer_message)
    
    agent_message_doc = {
        "session_id": session_id,
        "timestamp": datetime.utcnow().isoformat(),
        "message": {
            "role": "agent",
            "content": out.reply,
        },
        "model_info": {
            "label": out.label,
            "confidence": out.confidence,
        },
    }
    
    async def save_agent_message():
        try:
            result = await _save_to_mongodb("messages", agent_message_doc)
            if result:
                logger.info(f"✅ MongoDB: Saved agent message for session {session_id}")
            else:
                logger.warning(f"⚠️ MongoDB: Failed to save agent message for session {session_id}")
        except Exception as e:
            logger.error(f"❌ MongoDB agent message save error: {e}", exc_info=True)
    
    background_tasks.add_task(save_agent_message)
    
    # Store/update session in MongoDB
    session_doc = {
        "session_id": session_id,
        "updated_at": datetime.utcnow().isoformat(),
        "turn_count": session["turn_count"],
        "scam_detected": session["scam_detected"],
        "extracted_intel": session["extracted_intel"],
        "conversation_history": session["messages"],
        "metadata": req.metadata or {},
    }
    
    async def update_session():
        try:
            existing = await _get_from_mongodb("sessions", {"session_id": session_id})
            if existing:
                result = await _update_mongodb("sessions", {"session_id": session_id}, session_doc)
                if result:
                    logger.info(f"✅ MongoDB: Updated session {session_id}")
                else:
                    logger.warning(f"⚠️ MongoDB: Failed to update session {session_id}")
            else:
                session_doc["created_at"] = datetime.utcnow().isoformat()
                result = await _save_to_mongodb("sessions", session_doc)
                if result:
                    logger.info(f"✅ MongoDB: Created new session {session_id}")
                else:
                    logger.warning(f"⚠️ MongoDB: Failed to create session {session_id}")
        except Exception as e:
            logger.error(f"❌ MongoDB session update error: {e}", exc_info=True)
    
    background_tasks.add_task(update_session)
    
    # PHASE 4: Check if conversation should end
    # Note: For testing, we allow longer conversations. Only stop if truly necessary.
    ended = _should_stop(session)
    if ended:
        logger.info(f"Conversation ending. Intel items: {_intel_count(session['extracted_intel'])}, Turns: {session['turn_count']}")
        _send_callback(session_id, session, out.reply)
        
        # Store conversation end event
        end_doc = {
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
            "event": "conversation_ended",
            "final_state": {
                "turn_count": session["turn_count"],
                "extracted_intel": session["extracted_intel"],
                "intel_count": _intel_count(session["extracted_intel"]),
            },
        }
        async def save_end_event():
            try:
                result = await _save_to_mongodb("events", end_doc)
                if result:
                    logger.info(f"✅ MongoDB: Saved conversation end event for session {session_id}")
                else:
                    logger.warning(f"⚠️ MongoDB: Failed to save end event for session {session_id}")
            except Exception as e:
                logger.error(f"❌ MongoDB event save error: {e}", exc_info=True)
        
        background_tasks.add_task(save_end_event)
    else:
        # Log progress for debugging
        logger.debug(f"Conversation continues. Intel: {_intel_count(session['extracted_intel'])}, Turns: {session['turn_count']}")
    
    return HackathonResponse(status="success", reply=out.reply)


class CompareRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)


class CompareResponse(BaseModel):
    base: ModelOutput
    finetuned: ModelOutput
    decision_delta: str


@app.post("/compare", response_model=CompareResponse)
def compare(req: CompareRequest) -> CompareResponse:
    """
    Dev endpoint: compare base model vs fine-tuned model on the same text.
    Returns both outputs and a decision_delta string (e.g., "same" or "NOT_SCAM -> SCAM").
    """
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required.")

    base_model = os.environ.get("BASE_MODEL", "").strip()
    ft_model = os.environ.get("FT_MODEL", "").strip() or base_model

    if not base_model:
        raise HTTPException(status_code=500, detail="BASE_MODEL env var not set.")

    # FINE-TUNED MODEL COMPARISON DISABLED - Compare base model with/without RAG instead
    try:
        base_out = _call_model(base_model, [], text, use_ft_client=False, use_rag=False)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Base model error: {type(e).__name__}: {str(e)[:200]}",
        ) from e

    try:
        # Compare with RAG-enabled version
        rag_out = _call_model(base_model, [], text, use_ft_client=False, use_rag=True)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"RAG model error: {type(e).__name__}: {str(e)[:200]}",
        ) from e

    # Compute decision_delta
    if base_out.label == rag_out.label:
        decision_delta = "same"
    else:
        decision_delta = f"{base_out.label} -> {rag_out.label}"

    # Return base and RAG-enhanced (instead of fine-tuned)
    return CompareResponse(base=base_out, finetuned=rag_out, decision_delta=decision_delta)


