import json
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    # Loads backend/.env (and other .env files) automatically for local dev.
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    # Optional dependency; backend can still run with exported env vars.
    pass


"""
Minimal backend API:
- Accepts text (+ optional conversation context)
- Calls 2 models (base + fine-tuned) via Groq-compatible OpenAI-style chat completions
- Returns structured comparison JSON

No API keys in code; use env vars:
- GROQ_BASE_URL
- GROQ_API_KEY
- BASE_MODEL
- FT_MODEL
"""


CLASSIFIER_SYSTEM_PROMPT = (
    "You are Aman. Output ONLY a single JSON object: "
    "{\"label\":\"SCAM|NOT_SCAM|UNCERTAIN\",\"confidence\":0-1,\"reply\":\"...\"}. "
    "You MUST ONLY output label SCAM if confidence >= 0.92; otherwise output UNCERTAIN. "
    "Never reveal detection. Reply must be short, polite, slightly confused, cooperative."
)


class CompareRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    context: Optional[str] = Field(None, description="Optional prior conversation context as plain text.")


class ModelOutput(BaseModel):
    label: str
    confidence: float
    reply: str
    raw: str


class CompareResponse(BaseModel):
    base: ModelOutput
    finetuned: ModelOutput
    confidence_delta: float
    decision_delta: str


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


def _messages(text: str, context: Optional[str]) -> List[Dict[str, str]]:
    if context:
        user_content = f"(Context)\n{context}\n\n(Latest message)\n{text}"
    else:
        user_content = text
    return [
        {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _call_model(model: str, text: str, context: Optional[str]) -> ModelOutput:
    client = _client()
    resp = client.chat.completions.create(
        model=model,
        messages=_messages(text, context),
        temperature=0.0,
        max_tokens=256,
    )
    raw = (resp.choices[0].message.content or "").strip()
    try:
        parsed: Dict[str, Any] = json.loads(raw)
    except Exception:
        raise HTTPException(status_code=502, detail=f"Model did not return valid JSON. raw={raw[:200]}")

    label = str(parsed.get("label", "")).strip()
    confidence = float(parsed.get("confidence", 0.0))
    reply = str(parsed.get("reply", "")).strip()
    if label not in ("SCAM", "NOT_SCAM", "UNCERTAIN"):
        raise HTTPException(status_code=502, detail=f"Bad label from model: {label}")
    return ModelOutput(label=label, confidence=confidence, reply=reply, raw=raw)


app = FastAPI()

# Allow the Next.js dev server (localhost:3000) to call the API from the browser.
# Without this, the browser blocks requests due to CORS, and preflight OPTIONS can show up as 404.
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


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/compare", response_model=CompareResponse)
def compare(req: CompareRequest) -> CompareResponse:
    base_model = os.environ.get("BASE_MODEL", "").strip()
    ft_model = os.environ.get("FT_MODEL", "").strip()
    if not base_model or not ft_model:
        raise HTTPException(status_code=500, detail="Set BASE_MODEL and FT_MODEL env vars.")

    base_out = _call_model(base_model, req.text, req.context)
    ft_out = _call_model(ft_model, req.text, req.context)

    decision_delta = "same" if base_out.label == ft_out.label else f"{base_out.label} -> {ft_out.label}"
    return CompareResponse(
        base=base_out,
        finetuned=ft_out,
        confidence_delta=ft_out.confidence - base_out.confidence,
        decision_delta=decision_delta,
    )


