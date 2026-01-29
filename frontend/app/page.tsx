"use client";

import React, { useMemo, useState } from "react";

type ModelOut = {
  label: "SCAM" | "NOT_SCAM" | "UNCERTAIN";
  confidence: number;
  reply: string;
  raw: string;
};

type CompareResp = {
  base: ModelOut;
  finetuned: ModelOut;
  confidence_delta: number;
  decision_delta: string;
};

export default function Page() {
  const [text, setText] = useState(
    "KYC pending. Your bank account will be blocked in 2 hours. Click http://sbi-kyc-help.in to update."
  );
  const [context, setContext] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resp, setResp] = useState<CompareResp | null>(null);

  const apiBase = useMemo(() => {
    return process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
  }, []);

  async function runCompare() {
    setLoading(true);
    setError(null);
    setResp(null);
    try {
      const r = await fetch(`${apiBase}/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, context: context.trim() || null }),
      });
      if (!r.ok) {
        const msg = await r.text();
        throw new Error(msg || `HTTP ${r.status}`);
      }
      const j = (await r.json()) as CompareResp;
      setResp(j);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={{ fontFamily: "ui-sans-serif, system-ui", padding: 24, maxWidth: 1100, margin: "0 auto" }}>
      <h2 style={{ marginBottom: 8 }}>Scam Classifier Compare (Base vs Fine-tuned)</h2>
      <p style={{ marginTop: 0, color: "#555" }}>
        Sends text to backend <code>{apiBase}</code> and renders both model JSON outputs.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 16 }}>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Incoming message</div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={6}
            style={{ width: "100%", padding: 12, borderRadius: 10, border: "1px solid #ddd" }}
          />
        </div>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Optional context (prior turns)</div>
          <textarea
            value={context}
            onChange={(e) => setContext(e.target.value)}
            rows={6}
            placeholder="(Conversation so far)\nScammer: ...\nAman: ..."
            style={{ width: "100%", padding: 12, borderRadius: 10, border: "1px solid #ddd" }}
          />
        </div>
      </div>

      <div style={{ marginTop: 12, display: "flex", gap: 12, alignItems: "center" }}>
        <button
          onClick={runCompare}
          disabled={loading || !text.trim()}
          style={{
            padding: "10px 14px",
            borderRadius: 10,
            border: "1px solid #111",
            background: loading ? "#eee" : "#111",
            color: loading ? "#333" : "#fff",
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Running..." : "Compare"}
        </button>
        {error ? <span style={{ color: "#b00020" }}>{error}</span> : null}
      </div>

      {resp ? (
        <div style={{ marginTop: 18 }}>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", color: "#333" }}>
            <div>
              <strong>Decision delta:</strong> {resp.decision_delta}
            </div>
            <div>
              <strong>Confidence delta:</strong> {resp.confidence_delta.toFixed(3)}
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 12 }}>
            <Card title="Base model" out={resp.base} />
            <Card title="Fine-tuned model" out={resp.finetuned} />
          </div>
        </div>
      ) : null}
    </main>
  );
}

function Card({ title, out }: { title: string; out: ModelOut }) {
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 12, padding: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div style={{ fontWeight: 700 }}>{title}</div>
        <div style={{ fontSize: 13, color: "#555" }}>
          <span style={{ marginRight: 10 }}>
            <strong>label</strong>: {out.label}
          </span>
          <span>
            <strong>conf</strong>: {out.confidence.toFixed(3)}
          </span>
        </div>
      </div>

      <div style={{ marginTop: 10 }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>Reply (Aman)</div>
        <div style={{ whiteSpace: "pre-wrap", background: "#fafafa", border: "1px solid #eee", padding: 10, borderRadius: 10 }}>
          {out.reply}
        </div>
      </div>

      <div style={{ marginTop: 10 }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>Raw JSON</div>
        <pre style={{ margin: 0, fontSize: 12, overflowX: "auto", background: "#0b1020", color: "#e8ecff", padding: 10, borderRadius: 10 }}>
          {out.raw}
        </pre>
      </div>
    </div>
  );
}


