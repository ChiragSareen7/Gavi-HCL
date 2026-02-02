import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.requests import Request

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
"""

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_prompt(name: str) -> str:
    path = _REPO_ROOT / "prompts" / name
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


# Honeypot: engagement persona only; NO defensive/safety replies.
HONEYPOT_SYSTEM_PROMPT = _load_prompt("honeypot_system_prompt.txt") or (
    "You are Aman, a real Indian user. Output ONLY JSON: "
    '{"label":"SCAM|NOT_SCAM|UNCERTAIN","confidence":0-1,"reply":"<your message>"}. '
    "Reply must be confused, curious, cooperative; never say contact bank or refuse. Extract details by asking (UPI again, link, bank)."
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
class IncomingMessage(BaseModel):
    sender: str = Field(..., description="e.g. scammer")
    text: str = Field(..., min_length=1, max_length=8000)
    timestamp: Optional[str] = Field(None, description="ISO time")


class ConversationHistoryEntry(BaseModel):
    """One turn in conversationHistory; platform may send sender/text or role/content."""
    sender: Optional[str] = None
    text: Optional[str] = None
    role: Optional[str] = None
    content: Optional[str] = None
    timestamp: Optional[str] = None


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


def _ft_client():
    """Client for fine-tuned model: uses FT_BASE_URL if set, else same as Groq (base)."""
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:
        raise RuntimeError("Missing dependency `openai`. Install requirements.txt.") from e

    ft_base = os.environ.get("FT_BASE_URL", "").strip()
    if ft_base:
        api_key = os.environ.get("FT_API_KEY", "").strip() or "local"
        return OpenAI(base_url=ft_base.rstrip("/"), api_key=api_key)
    return _client()


def _messages(text: str, context: Optional[str], system_prompt: Optional[str] = None) -> List[Dict[str, str]]:
    prompt = system_prompt or CLASSIFIER_SYSTEM_PROMPT
    if context:
        user_content = f"(Context)\n{context}\n\n(Latest message)\n{text}"
    else:
        user_content = text
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_content},
    ]


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


def _call_model(model: str, text: str, context: Optional[str], use_ft_client: bool = False) -> ModelOutput:
    client = _ft_client() if use_ft_client else _client()
    resp = client.chat.completions.create(
        model=model,
        messages=_messages(text, context),
        temperature=0.0,
        max_tokens=256,
    )
    raw = (resp.choices[0].message.content or "").strip()
    return _parse_model_output(raw, strict=not use_ft_client)


def _call_llm(system_prompt: str, user_content: str, use_ft_client: bool = True, max_tokens: int = 512) -> str:
    """Single LLM call with given system and user content. Returns raw content."""
    model = os.environ.get("FT_MODEL", "").strip() or os.environ.get("BASE_MODEL", "").strip()
    if not model:
        raise RuntimeError("Set FT_MODEL or BASE_MODEL.")
    client = _ft_client() if use_ft_client else _client()
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


# ---------- Session store (in-memory; keyed by session_id) ----------
_session_store: Dict[str, Dict[str, Any]] = {}


def _get_session(session_id: str) -> Dict[str, Any]:
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
    if not messages:
        return ""
    lines = []
    for m in messages:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if role == "scammer":
            lines.append(f"Scammer: {content}")
        else:
            lines.append(f"Aman: {content}")
    return "\n".join(lines)


def _extract_intel_from_convo(convo_text: str) -> Dict[str, List[str]]:
    """Use LLM to extract structured intel from full conversation."""
    if not convo_text.strip():
        return {"upi_ids": [], "links": [], "bank_accounts": [], "phone_numbers": [], "tactics": []}
    user_content = f"Conversation:\n{convo_text}\n\nExtract intelligence. Output ONLY the JSON object."
    raw = _call_llm(INTEL_EXTRACTION_PROMPT, user_content, use_ft_client=True, max_tokens=512)
    try:
        parsed = json.loads(raw)
        return {
            "upi_ids": list(parsed.get("upi_ids", []) or []),
            "links": list(parsed.get("links", []) or []),
            "bank_accounts": list(parsed.get("bank_accounts", []) or []),
            "phone_numbers": list(parsed.get("phone_numbers", []) or []),
            "tactics": list(parsed.get("tactics", []) or []),
        }
    except Exception:
        return {"upi_ids": [], "links": [], "bank_accounts": [], "phone_numbers": [], "tactics": []}


def _intel_count(intel: Dict[str, List[str]]) -> int:
    return sum(len(v) for v in intel.values() if isinstance(v, list))


def _should_stop(session: Dict[str, Any], max_turns: int = 10, min_intel_items: int = 2) -> bool:
    """Stop when enough intel collected or max turns reached."""
    if session["turn_count"] >= max_turns:
        return True
    count = _intel_count(session["extracted_intel"])
    if count >= min_intel_items:
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
def health() -> Dict[str, str]:
    return {"status": "ok"}


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
def v1_chat(
    req: HackathonRequest,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> HackathonResponse:
    """
    Hackathon evaluation API. One message per request.
    Request: sessionId, message { sender, text, timestamp }, conversationHistory, metadata.
    Response: ONLY { "status": "success", "reply": "<agent reply>" }.
    When enough intel is extracted, we POST to hackathon callback URL (mandatory for scoring).
    """
    _require_api_key(x_api_key)
    session_id = req.sessionId
    message_text = (req.message.text or "").strip()
    if not message_text:
        raise HTTPException(status_code=400, detail="message.text is required.")
    session = _get_session(session_id)
    if req.conversationHistory is not None:
        session["messages"] = _normalize_history(req.conversationHistory)
    context = _conversation_context(session["messages"])
    try:
        out = _call_model(
            os.environ.get("FT_MODEL", "").strip() or os.environ.get("BASE_MODEL", "").strip(),
            message_text,
            context or None,
            use_ft_client=True,
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"LLM error: {type(e).__name__}: {str(e)[:200]}",
        ) from e
    scam_detected = (out.label == "SCAM") or (out.label == "UNCERTAIN" and out.confidence >= 0.5)
    session["scam_detected"] = session["scam_detected"] or scam_detected
    session["messages"].append({"role": "scammer", "content": message_text})
    session["messages"].append({"role": "agent", "content": out.reply})
    session["turn_count"] = len([m for m in session["messages"] if m.get("role") == "agent"])
    full_convo = _conversation_context(session["messages"])
    session["extracted_intel"] = _extract_intel_from_convo(full_convo)
    ended = _should_stop(session)
    if ended:
        _send_callback(session_id, session, out.reply)
    return HackathonResponse(status="success", reply=out.reply)


