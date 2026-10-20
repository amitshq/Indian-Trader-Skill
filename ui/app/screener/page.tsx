"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API ?? "http://localhost:8000/api";

export default function Screener() {
  const [rules, setRules] = useState("");
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    fetch(`${API}/screen/example-rules`).then((r) => r.json()).then((j) => setRules(JSON.stringify(j, null, 2))).catch(() => setErr("API not reachable"));
  }, []);

  const run = async () => {
    setErr("");
    let spec;
    try { spec = JSON.parse(rules); } catch { return setErr("Rules are not valid JSON"); }
    const r = await fetch(`${API}/screen`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ spec }) });
    const j = await r.json();
    if (!r.ok) return setErr(j.detail ?? "error");
    setRes(j);
  };

  const card = { background: "#171a21", borderRadius: 8, padding: 16, marginBottom: 16 } as const;
  return (
    <main style={{ maxWidth: 900, margin: "0 auto", padding: 24 }}>
      <p><a href="/" style={{ color: "#8ab4f8" }}>← Dashboard</a></p>
      <h1>Screener</h1>
      <div style={card}>
        <textarea value={rules} onChange={(e) => setRules(e.target.value)} rows={16}
          style={{ width: "100%", fontFamily: "monospace", background: "#0f1115", color: "#e6e6e6" }} />
        <button onClick={run}>Run screen</button>
        {err && <span style={{ color: "#e07a5f", marginLeft: 12 }}>{err}</span>}
      </div>
      {res && (
        <div style={card}>
          {res.sample_data && <p style={{ color: "#e9c46a" }}>⚠ Using SYNTHETIC SAMPLE data ({res.source}). Set FUNDAMENTALS_PATH to real data.</p>}
          <h3>Pass ({res.passed.length})</h3>
          {res.passed.map((p: any) => (
            <div key={p.ticker} style={{ marginBottom: 8 }}>
              <b>{p.ticker}</b> {p.name} — score {p.score ?? "-"}
              <ul style={{ margin: "4px 0" }}>{p.passes.map((w: string) => <li key={w}>{w}</li>)}</ul>
            </div>
          ))}
          <h3>Fail ({res.failed.length})</h3>
          {res.failed.map((f: any) => <div key={f.ticker}><b>{f.ticker}</b> — {f.fails.join("; ")}</div>)}
          <p style={{ opacity: 0.7 }}>{res.note}</p>
        </div>
      )}
    </main>
  );
}
