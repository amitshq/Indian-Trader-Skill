"use client";
import { useCallback, useEffect, useState } from "react";
import { api, card, err, inr, post, td, th, warn } from "./lib";

type Order = { id: number; symbol: string; side: string; qty: number; status: string; fill_price: number | null; reason: string };

export default function Dashboard() {
  const [market, setMarket] = useState<any>(null);
  const [pf, setPf] = useState<any>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [form, setForm] = useState({ symbol: "RELIANCE", side: "BUY", qty: 1 });
  const [preview, setPreview] = useState<any>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setMarket(await api("/market/status"));
      setPf(await api("/portfolio"));
      setOrders(await api("/orders"));
      setError("");
    } catch (e: any) { setError(`API not reachable: ${e.message}`); }
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);

  const submit = async () => {
    try { setPreview(await post("/orders", form)); load(); } catch (e: any) { setError(e.message); }
  };
  const act = async (id: number, what: "approve" | "reject") => {
    try { await post(`/orders/${id}/${what}`, {}); setPreview(null); load(); } catch (e: any) { setError(e.message); }
  };

  const pending = orders.filter((o) => o.status === "PENDING");
  const st = market?.status;
  const stColor = st === "open" ? "#52b788" : st === "pre_open" || st === "special_session" ? "#e9c46a" : "#e07a5f";

  return (
    <main style={{ maxWidth: 940, margin: "0 auto", padding: 24 }}>
      <h1 style={{ marginTop: 0 }}>Dashboard</h1>
      {error && <p style={err}>{error}</p>}
      <div style={card}>
        Market: <b style={{ color: stColor }}>{st ?? "…"}</b>
        {st === "special_session" && " (special-hours day, e.g. Muhurat: timings are announced by the exchange)"} · Next open: {market?.next_open ?? "-"} (IST)
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Portfolio</h3>
        Cash {inr(pf?.cash)} · Holdings {inr(pf?.holdings_value)}
        <table style={{ width: "100%", marginTop: 8 }}>
          <thead><tr><th style={th}>Symbol</th><th style={th}>Qty</th><th style={th}>Avg</th><th style={th}>LTP</th><th style={th}>P&amp;L</th></tr></thead>
          <tbody>{pf?.positions?.map((p: any) => (
            <tr key={p.symbol}><td style={td}>{p.symbol}</td><td style={td}>{p.qty}</td><td style={td}>{inr(p.avg_price)}</td><td style={td}>{inr(p.ltp)}</td><td style={td}>{inr(p.pnl)}</td></tr>
          ))}</tbody>
        </table>
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Order ticket (delivery, NSE)</h3>
        <input aria-label="symbol" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value.toUpperCase() })} />{" "}
        <select aria-label="side" value={form.side} onChange={(e) => setForm({ ...form, side: e.target.value })}><option>BUY</option><option>SELL</option></select>{" "}
        <input aria-label="quantity" type="number" min={1} value={form.qty} onChange={(e) => setForm({ ...form, qty: parseInt(e.target.value || "0", 10) })} style={{ width: 70 }} />{" "}
        <button onClick={submit}>Check &amp; queue</button>
        {preview?.risk && (
          <div style={{ marginTop: 8 }}>
            Risk gate: <b style={{ color: preview.risk.verdict === "PASS" ? "#52b788" : "#e07a5f" }}>{preview.risk.verdict}</b>
            {preview.estimated_charges && <> · estimated charges {inr(preview.estimated_charges.total)} on {inr(preview.estimated_charges.turnover)}</>}
            {preview.risk.reasons.map((r: string) => <div key={r} style={err}>✕ {r}</div>)}
            {preview.risk.warnings.map((r: string) => <div key={r} style={warn}>! {r}</div>)}
          </div>
        )}
        {preview?.order?.status === "REJECTED" && <p style={err}>{preview.order.reason}</p>}
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Approval queue</h3>
        {pending.length === 0 && <p>No pending orders.</p>}
        {pending.map((o) => (
          <div key={o.id} style={{ marginBottom: 6 }}>#{o.id} {o.side} {o.qty} {o.symbol}{" "}
            <button onClick={() => act(o.id, "approve")}>Approve (paper)</button>{" "}
            <button onClick={() => act(o.id, "reject")}>Reject</button></div>
        ))}
      </div>

      <div style={card}>
        <h3 style={{ marginTop: 0 }}>Order book</h3>
        {orders.map((o) => (
          <div key={o.id} style={o.status === "BLOCKED" ? err : undefined}>#{o.id} {o.side} {o.qty} {o.symbol} — {o.status}{o.fill_price ? ` @ ${inr(o.fill_price)}` : ""} {o.reason}</div>
        ))}
      </div>
    </main>
  );
}
