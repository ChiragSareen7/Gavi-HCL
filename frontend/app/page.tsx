"use client";

import React, { useMemo, useState } from "react";

type HackathonResp = { status: string; reply: string };

export default function Page() {
  const [sessionId, setSessionId] = useState("test-session-1");
  const [messageText, setMessageText] = useState(
    "KYC pending. Your bank account will be blocked in 2 hours. Click http://sbi-kyc-help.in to update."
  );
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resp, setResp] = useState<HackathonResp | null>(null);

  const apiBase = useMemo(() => {
    return process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
  }, []);

  async function sendMessage() {
    setLoading(true);
    setError(null);
    setResp(null);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (apiKey.trim()) headers["x-api-key"] = apiKey.trim();
      const r = await fetch(`${apiBase}/v1/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          sessionId: sessionId.trim() || "test-session-1",
          message: { sender: "scammer", text: messageText.trim(), timestamp: new Date().toISOString() },
          conversationHistory: null,
          metadata: {},
        }),
      });
      if (!r.ok) {
        const text = await r.text();
        let msg = text || `HTTP ${r.status}`;
        try {
          const j = JSON.parse(text) as { detail?: string };
          if (j?.detail) msg = j.detail;
        } catch {
          /* */
        }
        throw new Error(msg);
      }
      const j = (await r.json()) as HackathonResp;
      setResp(j);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={{ fontFamily: "ui-sans-serif, system-ui", padding: 24, maxWidth: 700, margin: "0 auto" }}>
      <h2 style={{ marginBottom: 8 }}>Honeypot API — local test</h2>
      <p style={{ marginTop: 0, color: "#555" }}>
        Calls <code>POST {apiBase}/v1/chat</code> (hackathon contract). Not used in evaluation.
      </p>

      <div style={{ marginBottom: 12 }}>
        <label style={{ fontWeight: 600, display: "block", marginBottom: 4 }}>Session ID</label>
        <input
          type="text"
          value={sessionId}
          onChange={(e) => setSessionId(e.target.value)}
          style={{ width: "100%", padding: 8, borderRadius: 8, border: "1px solid #ddd" }}
        />
      </div>
      <div style={{ marginBottom: 12 }}>
        <label style={{ fontWeight: 600, display: "block", marginBottom: 4 }}>x-api-key (if backend requires)</label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="Leave empty if HONEYPOT_API_KEY not set"
          style={{ width: "100%", padding: 8, borderRadius: 8, border: "1px solid #ddd" }}
        />
      </div>
      <div style={{ marginBottom: 12 }}>
        <label style={{ fontWeight: 600, display: "block", marginBottom: 4 }}>Message (scammer text)</label>
        <textarea
          value={messageText}
          onChange={(e) => setMessageText(e.target.value)}
          rows={4}
          style={{ width: "100%", padding: 12, borderRadius: 10, border: "1px solid #ddd" }}
        />
      </div>

      <button
        onClick={sendMessage}
        disabled={loading || !messageText.trim()}
        style={{
          padding: "10px 14px",
          borderRadius: 10,
          border: "1px solid #111",
          background: loading ? "#eee" : "#111",
          color: loading ? "#333" : "#fff",
          cursor: loading ? "not-allowed" : "pointer",
        }}
      >
        {loading ? "Sending..." : "Send"}
      </button>
      {error ? <span style={{ marginLeft: 12, color: "#b00020" }}>{error}</span> : null}

      {resp ? (
        <div style={{ marginTop: 18, padding: 14, background: "#f5f5f5", borderRadius: 10 }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Response: status = {resp.status}</div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Reply</div>
          <div style={{ whiteSpace: "pre-wrap" }}>{resp.reply}</div>
        </div>
      ) : null}
    </main>
  );
}
