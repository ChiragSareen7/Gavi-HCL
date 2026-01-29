## Backend (FastAPI)

### Env vars
- `GROQ_BASE_URL`: Groq OpenAI-compatible base URL
- `GROQ_API_KEY`: API key (do not commit)
- `BASE_MODEL`: base model name (e.g., a LLaMA/Mistral instruct)
- `FT_MODEL`: fine-tuned model name (or the served adapter endpoint name)

### Local .env
Create `backend/.env` (not committed) based on `backend/env.example`.

### Run

```bash
uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

### Endpoints
- `GET /health`
- `POST /compare`

Request:
```json
{ "text": "…", "context": "optional prior context" }
```

Response:
```json
{
  "base": {"label":"…","confidence":0.0,"reply":"…","raw":"…"},
  "finetuned": {"label":"…","confidence":0.0,"reply":"…","raw":"…"},
  "confidence_delta": 0.0,
  "decision_delta": "same|NOT_SCAM -> SCAM|..."
}
```


