# Deploying for the Hackathon

For the hackathon you only need to submit:

- **Headers:** `x-api-key` (the value you set as `HONEYPOT_API_KEY` on the server)
- **Honeypot API Endpoint URL:** The public URL of your deployed backend (e.g. `https://your-app.railway.app` or `https://your-app.onrender.com`)

No GitHub repo is required for submission.

---

## 1. Where do I get the Honeypot API Endpoint URL?

**You get it by deploying the backend.** Deploy the `backend/` app to any host that runs Python (e.g. Railway, Render, Fly.io). The root URL of that deployment is your **Honeypot API Endpoint URL**.

- Example: If you deploy to Railway and your app is at `https://gavi-honeypot.railway.app`, then:
  - **Honeypot API Endpoint URL** = `https://gavi-honeypot.railway.app`
  - Evaluators will call `POST https://gavi-honeypot.railway.app/v1/chat` with the `x-api-key` header.

---

## 2. Where do I get the x-api-key?

**You choose it.** Set it as the environment variable `HONEYPOT_API_KEY` on your deployed backend. The value you set is the key you give to the hackathon (e.g. in the “Enter x-api-key” field).

- If `HONEYPOT_API_KEY` is **set** on the server: every request to `POST /v1/chat` must include header `X-API-Key: <that value>` or the server returns 401.
- If `HONEYPOT_API_KEY` is **not set**: the API allows requests without the header (useful for local testing).

**Example:** Set `HONEYPOT_API_KEY=my-secret-key-123` on the server, then submit `my-secret-key-123` as the x-api-key in the hackathon form.

---

## 3. Deploy the backend (e.g. Railway or Render)

### Option A: Railway

1. Sign up at [railway.app](https://railway.app).
2. New Project → Deploy from GitHub (or “Empty” and connect repo later).
3. Set **Root Directory** to `backend` (so Railway runs the `backend/` folder).
4. Add a **Start Command** (if needed): `uvicorn app:app --host 0.0.0.0 --port $PORT`. Railway will auto-detect if `backend/requirements.txt` exists.
5. In **Variables**, set:
   - `GROQ_BASE_URL` = `https://api.groq.com/openai/v1`
   - `GROQ_API_KEY` = your Groq API key
   - `BASE_MODEL` = `llama-3.3-70b-versatile` (or another Groq model ID)
   - `HONEYPOT_API_KEY` = the secret key you will submit as x-api-key (required for evaluation)
   - (Optional) `CALLBACK_URL` = override callback URL; default is `https://hackathon.guvi.in/api/updateHoneyPotFinalResult`
6. Deploy. Your **Honeypot API Endpoint URL** is the generated URL (e.g. `https://xxx.railway.app`).

### Option B: Render

1. Sign up at [render.com](https://render.com).
2. New → Web Service → Connect your repo.
3. **Root Directory:** `backend`
4. **Build Command:** `pip install -r requirements.txt` (uses `backend/requirements.txt`).
5. **Start Command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
6. In **Environment**, add the same variables as above (`GROQ_BASE_URL`, `GROQ_API_KEY`, `BASE_MODEL`, `HONEYPOT_API_KEY`; optional `CALLBACK_URL`).
7. Deploy. Your **Honeypot API Endpoint URL** is the service URL (e.g. `https://your-app.onrender.com`).

---

## 4. Submitting to the hackathon

- **Honeypot API Endpoint URL:** paste your deployed backend URL (no path, no `/v1/chat`).
- **x-api-key:** paste the exact value of `HONEYPOT_API_KEY` you set on the server.

Evaluators will send `POST <your-url>/v1/chat` with header `X-API-Key: <your key>`.

---

## 5. If I deploy and then change the code, is that okay?

Yes. After you change the code:

1. Push to GitHub (if the host is connected to the repo), or
2. Trigger a redeploy / push again so the host rebuilds.

The host will run the new code. Your **Honeypot API Endpoint URL** and **x-api-key** stay the same unless you change the env vars or the service URL.

---

## 6. Checklist before pushing to GitHub

- [ ] No `.env` or `backend/.env` in the repo (they are in `.gitignore`; do not force-add them).
- [ ] No real API keys in any file (only placeholders in `backend/env.example`).
- [ ] Rotate any keys that were ever committed or shared (e.g. Groq key) and update them in your deployed env vars.
